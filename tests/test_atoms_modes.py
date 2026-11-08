"""Spec 0.3 combination modes: unfolding, layer-0 costs, and derived recursion."""

from types import SimpleNamespace

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.boundary import Boundary
from opulse.atoms.combinators import (
    check_combinator,
    combinator_defn,
    counter_atoms,
    fix_atoms,
    fix_spec,
    list_atoms,
    memoized_spec,
    standard_combinators,
    turns_atoms,
    turns_spec,
    twice_via_repeat_spec,
)
from opulse.atoms.library import Library, VerifyRequest
from opulse.atoms.objects import object_atoms
from opulse.atoms.spec import (
    CombinatorSpec,
    Contract,
    Definition,
    Edge,
    ObjectSpec,
    OperationSpec,
)
from opulse.atoms.values import Bottom, Card, Ok
from opulse.atoms.verify import unfold_equivalent_calls
from opulse.atoms.world import WorldDecl


def scope(*specs, atoms=()):
    return kernel.DictScope(atoms=[*counter_atoms(), *list_atoms(), *fix_atoms(),
                                   *turns_atoms(), *atoms],
                            defns=[combinator_defn(spec) for spec in specs])


def equivalent(name, args, environment):
    direct = kernel.call(name, args, environment)
    expanded = kernel.evaluate(kernel.inline(n.Call(name, tuple(n.Lit(arg) for arg in args)),
                                             environment), scope=environment)
    assert (direct.outcome, direct.steps) == (expanded.outcome, expanded.steps)
    traced = kernel.call(name, args, environment, trace=True)
    assert unfold_equivalent_calls(traced.trace, [Boundary.unfold_all(), Boundary.unfold_none(),
                                                    Boundary(open_names=frozenset({name}))]).ok
    return direct


@settings(deadline=None)
@given(st.integers(min_value=0, max_value=10), st.integers(min_value=0, max_value=10))
def test_fix_stabilizes_and_charges_all_probes(start, height):
    spec = fix_spec()
    environment = scope(spec, atoms=[kernel.Atom("grow", 1, lambda value: min(value + 1, 3)
                                     if value < 3 else value)])
    run = equivalent("fix", (kernel.FnRef("grow"), start, height), environment)
    assert run.outcome == (Ok(max(start, 3)) if height > max(3 - start, 0)
                           else Bottom("not_stable"))
    if height == 0:
        assert run.steps == 1


def test_fix_reachability_and_shortest_path_relaxation():
    edges = ((0, 1), (1, 2), (2, 3))
    reach = kernel.Atom("reach", 1, lambda known: tuple(sorted(set(known) |
        {right for left, right in edges if left in known})))
    relax = kernel.Atom("relax", 1, lambda distances: tuple(min((distances[index],
        *(distances[left] + 1 for left, right in edges if right == index)))
        for index in range(4)))
    environment = scope(fix_spec(), atoms=[reach, relax])
    assert equivalent("fix", (kernel.FnRef("reach"), (0,), 4), environment).outcome == Ok((0, 1, 2, 3))
    assert equivalent("fix", (kernel.FnRef("relax"), (0, 99, 99, 99), 4),
                      environment).outcome == Ok((0, 1, 2, 3))


def test_memo_recursion_is_result_and_charged_cost_preserving():
    recursive = n.Rec("fib", ("index",), n.Case((
        (n.Test(n.Call("comb_le", (n.Var("index"), n.Lit(1)))), n.Var("index")),),
        n.Call("sum", (n.Call("fib", (n.Call("comb_dec", (n.Var("index"),)),)),
                       n.Call("fib", (n.Call("comb_sub", (n.Var("index"), n.Lit(2))),))))),
        (n.Var("x"),), n.Var("index"))
    plain = CombinatorSpec("fib_plain", ("x",), (), recursive)
    memo = memoized_spec(plain)
    environment = scope(plain, memo, atoms=[kernel.Atom("sum", 2, lambda left, right: left + right)])
    for index in range(7):
        actual = equivalent(memo.name, (index,), environment)
        expected = equivalent(plain.name, (index,), environment)
        assert (actual.outcome, actual.steps) == (expected.outcome, expected.steps)
        if hasattr(actual, "work"):
            assert actual.work <= actual.steps


@pytest.mark.skipif(not hasattr(kernel.Run, "work"), reason="kernel Run.work is not available yet")
def test_memo_work_never_exceeds_charged_steps():
    plain = next(item for item in standard_combinators() if item.name == "fold")
    memo = memoized_spec(plain)
    environment = scope(memo, atoms=[kernel.Atom("add", 2, lambda left, right: left + right)])
    run = kernel.call(memo.name, (kernel.FnRef("add"), 0, (1, 2, 3)), environment)
    assert run.work <= run.steps


def test_turns_order_all_orders_and_private_observations():
    def observation(index):
        return kernel.Atom(f"observe{index}", 1, lambda state, index=index: state[index])

    atoms = [observation(index) for index in range(2)] + [
        kernel.Atom(f"choose{index}", 1, lambda seen: seen + 1) for index in range(2)] + [
        kernel.Atom("apply", 3, lambda move, index, state: tuple(
            value + (move if position == index else 0)
            for position, value in enumerate(state)))]
    environment = scope(turns_spec(2), atoms=atoms)
    refs = (*tuple(kernel.FnRef(f"{name}{index}") for index in range(2)
                   for name in ("observe", "choose")), kernel.FnRef("apply"))
    assert equivalent("turns", (*refs, (0, 0), 3), environment).outcome == Ok((3, 1))
    assert equivalent("turns", (*refs, (0, 0), (1, 1, 0)), environment).outcome == Ok((1, 3))
    assert equivalent("turns", (*refs, (0, 0), ("all", 2)), environment).outcome == Ok(
        ((0, 0), (1, 0), (0, 1), (3, 0), (1, 1), (0, 3)))
    assert equivalent("turns", (*refs, (0, 0), (3,)), environment).outcome == Bottom("invalid_schedule")


def test_hidden_agent_receives_only_its_declared_probe():
    moves = []

    def choose0(observation):
        move = observation + 1
        moves.append(move)
        return move

    atoms = [kernel.Atom("observe0", 1, lambda state: state[0]),
             kernel.Atom("observe1", 1, lambda state: state[1]),
             kernel.Atom("choose0", 1, choose0),
             kernel.Atom("choose1", 1, lambda observed: observed + 1),
             kernel.Atom("apply", 3, lambda move, index, state:
                         (move, state[1]) if index == 0 else (state[0], move))]
    environment = scope(turns_spec(2), atoms=atoms)
    refs = (*tuple(kernel.FnRef(f"{name}{index}") for index in range(2)
                   for name in ("observe", "choose")), kernel.FnRef("apply"))
    for secret in (7, 900):
        assert equivalent("turns", (*refs, (2, secret), (0,)), environment).outcome == Ok((3, secret))
    assert moves and set(moves) == {3}


@pytest.mark.parametrize("argument", [n.Var("state"),
    n.Call("observe1", (n.Var("state"),)),
    n.Call("observe0", (n.Var("queue"),))])
def test_turns_rejects_policy_access_to_other_information(argument):
    spec = turns_spec(2)
    def replace_call(node):
        if isinstance(node, n.Call) and node.fn == "choose0":
            return n.Call("choose0", (argument,))
        if isinstance(node, n.Call):
            return n.Call(node.fn, tuple(replace_call(arg) for arg in node.args))
        if isinstance(node, n.Case):
            return n.Case(tuple((condition, replace_call(body)) for condition, body in node.arms),
                          replace_call(node.default) if node.default else None)
        if isinstance(node, n.Rec):
            return n.Rec(node.fn, node.params, replace_call(node.body),
                         tuple(replace_call(arg) for arg in node.args), node.measure)
        if isinstance(node, n.Let):
            return n.Let(node.name, replace_call(node.value), replace_call(node.body))
        return node
    body = replace_call(spec.body)
    bad = Definition("turns", "combinator", "invented", 1,
                     tuple(sorted(n.references(body) - set(spec.op_params))),
                     CombinatorSpec(spec.name, spec.params, spec.op_params, body), body)
    assert any("choose0 must receive only its own observation" in problem
               for problem in check_combinator(bad, SimpleNamespace(definitions={})))


def test_combinators_forward_operations_and_verify_bounded_family():
    triple = CombinatorSpec("quadruple", ("f", "x"), ("f",),
                            n.Call("twice", (n.Var("f"), n.Call("twice", (n.Var("f"), n.Var("x"))))))
    environment = scope(*standard_combinators(), triple,
                        atoms=[kernel.Atom("plus_one", 1, lambda value: value + 1)])
    assert equivalent("quadruple", (kernel.FnRef("plus_one"), 2), environment).outcome == Ok(6)
    assert not check_combinator(Definition("quadruple", "combinator", "invented", 2,
                                           ("twice",), triple, triple.body),
                                SimpleNamespace(scope=lambda: environment))
    assert equivalent("twice", (kernel.FnRef("plus_one"), 2), environment).outcome == Ok(4)


def test_library_verifies_combinator_modes_with_recorded_scope():
    specs = (fix_spec(), turns_spec(2))
    primitives = [*counter_atoms(), *list_atoms(), *fix_atoms(), *turns_atoms(),
                  kernel.Atom("grow", 1, lambda value: min(value + 1, 2)),
                  kernel.Atom("look0", 1, lambda value: value),
                  kernel.Atom("look1", 1, lambda value: value),
                  kernel.Atom("pick0", 1, lambda seen: 1),
                  kernel.Atom("pick1", 1, lambda seen: -1),
                  kernel.Atom("step_world", 3, lambda move, index, state: state + move)]
    declarations = tuple(OperationSpec(atom.name, "transform",
                          tuple(Edge("int") if atom.name in ("turns_schedule", "turns_orders")
                                and index == 1 or atom.name == "comb_equal" and index == 1
                                else Edge("unknown") for index in range(atom.arity)),
                          Edge("int" if atom.name == "list_length" else "unknown"), atom.name)
                         for atom in primitives)
    world = WorldDecl("modes", 1, "atoms-v2", {}, {}, (), declarations,
                      {"nodes": list(n.NODE_NAMES), "recursion": "measure"}, {}, {})
    library = Library(world, primitives)
    for spec in specs:
        dependencies = tuple(sorted(n.references(spec.body) - set(spec.op_params)))
        definition = Definition(spec.name, "combinator", "invented", 1,
                                dependencies, spec, spec.body)
        library.write(definition)
        library.check(spec.name)
        sample = ((kernel.FnRef("grow"), 0, 3),) if spec.name == "fix" else (
            (kernel.FnRef("look0"), kernel.FnRef("pick0"), kernel.FnRef("look1"),
             kernel.FnRef("pick1"), kernel.FnRef("step_world"), 0, (0, 1)),)
        library.make_callable(spec.name, sample)
        families = ({"step": ("grow",)} if spec.name == "fix" else {
            "observe0": ("look0",), "choose0": ("pick0",),
            "observe1": ("look1",), "choose1": ("pick1",), "apply": ("step_world",)})
        domain = ((0, 3), (2, 1)) if spec.name == "fix" else ((0, (0, 1)), (0, ("all", 1)))
        scope_record = {"domain": "finite counter", "size": len(domain),
                        "op_family": families}
        if spec.name == "fix":
            scope_record["finite_height"] = 3
        verified = library.verify(spec.name, VerifyRequest("bounded", domain,
                                   scope_record, extra={"op_family": families}))
        assert verified.evidence.checks == ("unfold_equivalence",)
        assert library.promote(spec.name, Contract("equivalent to its unfold")).status == "promoted"
        for args in sample:
            assert equivalent(spec.name, args, library.scope()).outcome == library.run(spec.name, args).outcome


def test_library_verifies_memo_and_forwarded_combinators():
    repeat = next(item for item in standard_combinators() if item.name == "repeat")
    twice = twice_via_repeat_spec()
    fold_memo = next(item for item in standard_combinators() if item.name == "fold_memo")
    atoms = [*counter_atoms(), *list_atoms(), kernel.Atom("increment", 1,
              lambda value: value + 1), kernel.Atom("add", 2, lambda left, right: left + right)]
    declarations = (OperationSpec("list_length", "transform", (Edge("unknown"),),
                                  Edge("int"), "list_length"),)
    world = WorldDecl("forwarding", 1, "atoms-v2", {}, {}, (), declarations,
                      {"nodes": list(n.NODE_NAMES), "recursion": "measure"}, {}, {})
    library = Library(world, atoms)
    for spec, layer, family, domain in (
        (repeat, 1, ("increment",), ((0,), (2,))),
        (twice, 2, ("increment",), ((0,), (2,))),
        (fold_memo, 1, ("add",), ((0, (1, 2)), (4, (2, 3))))):
        dependencies = tuple(sorted(n.references(spec.body) - set(spec.op_params)))
        definition = Definition(spec.name, "combinator", "invented", layer,
                                dependencies, spec, spec.body)
        library.write(definition)
        library.check(spec.name)
        sample = tuple(kernel.FnRef(family[0]) if param in spec.op_params else 0
                       if param not in ("items",) else () for param in spec.params)
        library.make_callable(spec.name, (sample,))
        scope_record = {"domain": "bounded ints and lists", "size": len(domain),
                        "op_family": family}
        assert library.verify(spec.name, VerifyRequest("bounded", domain, scope_record,
                              extra={"op_family": family})).evidence.checks == ("unfold_equivalence",)
        assert library.promote(spec.name, Contract("equivalent to its unfold")).status == "promoted"
        assert equivalent(spec.name, sample, library.scope()).outcome == library.run(spec.name, sample).outcome
    assert library.get("twice_via_repeat").depends_on == ("repeat",)


def test_derived_object_fold_passes_library_pipeline_and_boundaries():
    list_spec = ObjectSpec("List", "compose", tags={"nil": (),
        "cons": (("head", "int"), ("tail", "List"))})
    preliminary = WorldDecl("fold_pipeline", 1, "atoms-v2", {}, {}, (list_spec,), (),
                            {"nodes": list(n.NODE_NAMES), "recursion": "measure"}, {}, {})
    derived = object_atoms(list_spec, Library(preliminary, ()))
    primitives = [item for item in derived if isinstance(item, kernel.Atom)] + [
        kernel.Atom("fold_zero", 0, lambda: 0),
        kernel.Atom("fold_cons", 2, lambda head, rest: head + rest)]
    operations = tuple(OperationSpec(atom.name, "transform",
                       tuple(Edge("unknown") for _ in range(atom.arity)),
                       Edge("int" if atom.name == "List.size" else "unknown"), atom.name)
                       for atom in primitives)
    world = WorldDecl("fold_pipeline", 1, "atoms-v2", {}, {}, (list_spec,), operations,
                      {"nodes": list(n.NODE_NAMES), "recursion": "measure"}, {}, {})
    library = Library(world, primitives)
    fold = next(item for item in derived if isinstance(item, kernel.Defn)
                and item.name == "List.fold")
    spec = CombinatorSpec(fold.name, fold.params, fold.params[:-1], fold.body)
    definition = Definition(spec.name, "combinator", "invented", 1,
                            tuple(sorted(n.references(spec.body) - set(spec.op_params))),
                            spec, spec.body)
    items = Card("List", "cons", (2, Card("List", "cons", (3, Card("List", "nil")))))
    args = (kernel.FnRef("fold_zero"), kernel.FnRef("fold_cons"), items)
    library.write(definition)
    assert library.check(spec.name).status == "checked"
    assert library.make_callable(spec.name, (args,)).status == "callable"
    family = {"on_List_nil": ("fold_zero",), "on_List_cons": ("fold_cons",)}
    domain = ((items,), (Card("List", "nil"),))
    request = VerifyRequest("bounded", domain, {"domain": "two finite lists", "size": len(domain),
                            "op_family": family}, extra={"op_family": family})
    assert library.verify(spec.name, request).evidence.checks == ("unfold_equivalence",)
    assert library.promote(spec.name, Contract("structural fold")).status == "promoted"
    assert equivalent(spec.name, args, library.scope()).outcome == Ok(5)


def test_forwarding_rejects_operation_as_value():
    spec = CombinatorSpec("bad", ("f", "x"), ("f",),
                          n.Call("repeat", (n.Var("x"), n.Var("f"))))
    definition = Definition("bad", "combinator", "invented", 2, ("repeat",), spec, spec.body)
    bad = check_combinator(definition, SimpleNamespace(definitions={}))
    assert any("needs an operation reference" in problem for problem in bad)
    assert any("cannot be stored as data" in problem for problem in bad)


def test_forwarding_accepts_literal_operation_reference():
    spec = CombinatorSpec("literal_repeat", ("x",), (),
                          n.Call("repeat", (n.Lit(kernel.FnRef("increment")), n.Var("x"))))
    definition = Definition(spec.name, "combinator", "invented", 2,
                            ("repeat",), spec, spec.body)
    assert any("increment" in problem for problem in
               check_combinator(definition, SimpleNamespace(definitions={})))
    declared = Definition(spec.name, "combinator", "invented", 2,
                          ("increment", "repeat"), spec, spec.body)
    assert not check_combinator(declared, SimpleNamespace(definitions={}))
    environment = scope(*standard_combinators(), spec,
                        atoms=[kernel.Atom("increment", 1, lambda value: value + 1)])
    assert equivalent(spec.name, (3,), environment).outcome == Ok(5)


def test_list_fold_sum_length_and_tree_size():
    list_spec = ObjectSpec("List", "compose", tags={"nil": (),
        "cons": (("head", "int"), ("tail", "List"))})
    tree_spec = ObjectSpec("Tree", "compose", tags={"leaf": (("value", "int"),),
        "branch": (("left", "Tree"), ("right", "Tree"))})
    world = WorldDecl("structures", 1, "atoms-v2", {}, {}, (list_spec, tree_spec), (),
                      {"nodes": (), "recursion": "measure"}, {}, {})
    library = Library(world, ())
    items = [*object_atoms(list_spec, library), *object_atoms(tree_spec, library),
             kernel.Atom("zero", 0, lambda: 0),
             kernel.Atom("sum_cons", 2, lambda head, rest: head + rest),
             kernel.Atom("len_cons", 2, lambda head, rest: rest + 1),
             kernel.Atom("leaf", 1, lambda value: 1),
             kernel.Atom("branch", 2, lambda left, right: left + right + 1)]
    environment = kernel.DictScope([item for item in items if isinstance(item, kernel.Atom)],
                                   [item for item in items if isinstance(item, kernel.Defn)])
    list_value = Card("List", "cons", (2, Card("List", "cons", (3, Card("List", "nil")))))
    assert equivalent("List.fold", (kernel.FnRef("zero"), kernel.FnRef("sum_cons"),
                                    list_value), environment).outcome == Ok(5)
    assert equivalent("List.fold", (kernel.FnRef("zero"), kernel.FnRef("len_cons"),
                                    list_value), environment).outcome == Ok(2)
    tree = Card("Tree", "branch", (Card("Tree", "leaf", (4,)), Card("Tree", "leaf", (5,))))
    assert kernel.call("Tree.size", (tree,), environment).outcome == Ok(3)
    assert equivalent("Tree.fold", (kernel.FnRef("leaf"), kernel.FnRef("branch"),
                                    tree), environment).outcome == Ok(3)


def test_repeated_items_fold_recursive_fields_first():
    spec = ObjectSpec("Forest", "compose", tags={"empty": (),
        "many": {"items": "Forest"}})
    world = WorldDecl("forest", 1, "atoms-v2", {}, {}, (spec,), (),
                      {"nodes": (), "recursion": "measure"}, {}, {})
    library = Library(world, ())
    entries = [*object_atoms(spec, library), kernel.Atom("zero", 0, lambda: 0),
               kernel.Atom("sum_children", 1, lambda items: 1 + sum(items))]
    environment = kernel.DictScope([item for item in entries if isinstance(item, kernel.Atom)],
                                   [item for item in entries if isinstance(item, kernel.Defn)])
    forest = Card("Forest", "many", (Card("Forest", "empty"),
                                     Card("Forest", "many", (Card("Forest", "empty"),))))
    assert kernel.call("Forest.size", (forest,), environment).outcome == Ok(4)
    assert equivalent("Forest.fold", (kernel.FnRef("zero"), kernel.FnRef("sum_children"),
                                      forest), environment).outcome == Ok(2)


def test_object_group_folds_and_size_are_kernel_definitions():
    even = ObjectSpec("Even", "compose", tags={"zero": (), "next": (("odd", "Odd"),)},
                      group=("Even", "Odd"))
    odd = ObjectSpec("Odd", "compose", tags={"next": (("even", "Even"),)},
                     group=("Even", "Odd"))
    world = WorldDecl("folds", 1, "atoms-v2", {}, {}, (even, odd), (),
                      {"nodes": (), "recursion": "measure"}, {}, {})
    library = Library(world, ())
    ops = [*object_atoms(even, library), *object_atoms(odd, library),
           kernel.Atom("zero_case", 0, lambda: 0),
           kernel.Atom("even_case", 1, lambda value: value + 1),
           kernel.Atom("odd_case", 1, lambda value: value + 1)]
    environment = kernel.DictScope([item for item in ops if isinstance(item, kernel.Atom)],
                                   [item for item in ops if isinstance(item, kernel.Defn)])
    tree = Card("Even", "next", (Card("Odd", "next", (Card("Even", "zero"),)),))
    assert kernel.call("Even.size", (tree,), environment).outcome == Ok(3)
    assert equivalent("Even.fold", (kernel.FnRef("zero_case"), kernel.FnRef("even_case"),
                                    kernel.FnRef("odd_case"), tree), environment).outcome == Ok(2)
