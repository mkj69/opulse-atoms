"""Standard combinators and bounded unfold evidence (spec section 6.2)."""

from types import SimpleNamespace

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.combinators import (
    check_combinator,
    combinator_defn,
    counter_atoms,
    instantiate,
    list_atoms,
    memoized_spec,
    repeat_spec,
    repeat_until_spec,
    standard_combinators,
    verify_combinator,
)
from opulse.atoms.spec import CombinatorSpec, Definition
from opulse.atoms.values import Bottom, Ok
from opulse.core.semantics import NAN
from opulse.worlds import action


def test_memoized_spec_reaches_recursion_inside_blocks():
    recursion = n.Rec("local", ("value",), n.Var("value"), (n.Lit(1),), "fuel")
    body = n.Blocks((), "start", (("start", n.Block((), n.Halt(recursion))),))
    spec = CombinatorSpec("sample", (), (), body)
    assert [item.memo for item in n.walk(memoized_spec(spec).body) if isinstance(item, n.Rec)] == [True]


def scope():
    atoms = [*counter_atoms(), *list_atoms(), *(
        kernel.Atom(name, 1, lambda state, name=name: action.apply_atom(name, state))
        for name in (*action.ACTION_RULES, *action.OBS_RULES)),
        kernel.Atom("succ", 1, lambda value: value + 1),
        kernel.Atom("add", 2, lambda left, right: left + right),
        kernel.Atom("is_three", 1, lambda value: value == 3)]
    atoms.extend(kernel.Atom(f"op_{offset}", 1, lambda value, offset=offset: value + offset)
                 for offset in range(5))
    return kernel.DictScope(atoms=atoms, defns=[combinator_defn(spec) for spec in standard_combinators()])


def test_standard_combinators_and_nested_twice():
    lib = scope()
    ref = kernel.FnRef("succ")
    assert kernel.call("twice", (ref, 2), lib).outcome == Ok(4)
    assert kernel.call("seq", (ref, ref, 2), lib).outcome == Ok(4)
    twice_twice = kernel.evaluate(n.Call("twice", (n.Lit(ref), n.Call("twice", (n.Lit(ref), n.Lit(2))))),
                                  scope=lib)
    assert twice_twice.outcome == kernel.evaluate(instantiate(repeat_spec(4), {"f": "succ"}, (2,)), scope=lib).outcome
    assert kernel.call("fold", (kernel.FnRef("add"), 0, (1, 2, 3, 4)), lib).outcome == Ok(10)
    assert kernel.evaluate(instantiate(next(spec for spec in standard_combinators()
                                        if spec.name == "fold"), {"f": "add"}, (0, (1, 2, 3))),
                           scope=lib).outcome == Ok(6)
    assert kernel.call("map", (ref, (1, 2)), lib).outcome == Ok((2, 3))


def test_repeat_until_matches_published_robot_skill():
    for max_rounds in (0, 1, 2, 3):
        spec = repeat_until_spec(max_rounds, dialect="legacy-v1")
        lib = scope().extend([combinator_defn(spec)])
        for state in action._examples_states()[:6]:
            for skill_name in ("turn_left", "turn_right", "forward"):
                skill = action.Skill("trial", 1, "recursion", skill_name, guard="front_wall",
                                     expected=True, bound=max_rounds)
                expected, _ = action.run_skill(skill, state, {skill.name: skill})
                actual = kernel.call("repeat_until", (kernel.FnRef(skill_name),
                                                      kernel.FnRef("front_wall"), state), lib,
                                     dialect="legacy-v1").outcome
                assert isinstance(actual, Bottom) if expected is NAN else actual == Ok(expected)
    assert kernel.call("repeat_until", (kernel.FnRef("turn_left"),
                                        kernel.FnRef("front_wall"), action.initial_state()),
                       scope().extend([combinator_defn(repeat_until_spec(0))])).outcome == Bottom("exhausted")


def test_search_and_bounded_family_verification():
    lib = scope()
    run = kernel.call("search", (kernel.FnRef("is_three"), 5), lib)
    assert run.outcome == Ok(3) and run.steps > 3
    assert kernel.call("search", (kernel.FnRef("is_three"), 0), lib).outcome == Bottom("not_found")
    assert kernel.call("search", (kernel.FnRef("is_three"), 2), lib).outcome == Bottom("not_found")
    spec = next(spec for spec in standard_combinators() if spec.name == "twice")
    defn = Definition("twice", "combinator", "invented", 1, (), spec, spec.body)

    class Library:
        dialect = "atoms-v2"

        def scope(self):
            return lib

    request = SimpleNamespace(method="bounded", extra={"op_family": [f"op_{index}" for index in range(5)]},
                              scope={"domain": "small ints", "size": 4,
                                     "op_family": [f"op_{index}" for index in range(5)]},
                              domain=[(value,) for value in range(4)],
                              reference=lambda ops, inputs: inputs[0] + 2 * int(ops["f"].split("_")[-1]))
    assert verify_combinator(defn, Library(), request).ok
    assert not verify_combinator(defn, Library(), SimpleNamespace(**{**vars(request), "method": "exhaustive"})).ok
    buggy_spec = CombinatorSpec("twice", spec.params, spec.op_params, n.Call("f", (n.Var("x"),)))
    buggy = Definition("twice", "combinator", "invented", 1, (), buggy_spec, buggy_spec.body)
    assert not verify_combinator(buggy, Library(), request).ok
    mismatched_arity = CombinatorSpec("bad_arity", ("f", "x"), ("f",),
                                     n.Call("f", (n.Var("x"), n.Var("x"))))
    assert not verify_combinator(Definition("bad_arity", "combinator", "invented", 1, (),
                                            mismatched_arity, mismatched_arity.body), Library(), request).ok
    assert check_combinator(Definition("bad", "combinator", "invented", 1, (),
                                       CombinatorSpec("bad", ("f",), ("f",), n.Var("f")), n.Var("f")), Library())
