"""Proposals for memo recursion, finite fixpoints, and turn-taking."""

from __future__ import annotations

import itertools
import random
from dataclasses import dataclass, fields, is_dataclass, replace

from opulse.atoms import combinators as core_combinators
from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.library import VerifyRequest
from opulse.atoms.spec import CombinatorSpec, Edge, OperationSpec
from opulse.atoms.values import Ok
from opulse.gen_v2 import fast, vocab
from opulse.gen_v2.admit import admit
from opulse.gen_v2.base import Candidate, Entry, Signature
from opulse.gen_v2.kinds.combinators import definition as _definition
from opulse.gen_v2.kinds.combinators import family_request


def _operation(state, move, body, inputs, output, meta=None):
    name = state.names.fresh("operation")
    spec = OperationSpec(name, "transform" if len(inputs) == 1 else "combine",
                         tuple(Edge(sort) for sort in inputs), Edge(output),
                         "Apply a finite, measured combination of operations.",
                         extra={"input_names": [f"arg{index}" for index in range(len(inputs))]})
    signature = Signature(inputs, output)
    return Candidate(_definition(state, "operation", name, spec, body), signature, move,
                     meta=meta or {})


def _combinator(state, move, body, params, slots, inputs, output, families, meta=None):
    if not families or any(len(families.get(slot, ())) < 2 for slot in slots):
        return None
    if len(set(itertools.chain.from_iterable(families.values()))) < 3:
        return None
    family = list(dict.fromkeys(row[0] for row in itertools.chain.from_iterable(families.values())))
    request = family_request(state, inputs, family)
    if request is None:
        return None
    name = state.names.fresh("combinator")
    spec = CombinatorSpec(name, params, slots, body)
    slot_sigs = tuple(Signature(families[slot][0][1], families[slot][0][2]) for slot in slots)
    names = {slot: tuple(row[0] for row in families[slot]) for slot in slots}
    helpers = {row[0]: (row[1], row[2]) for family in families.values() for row in family
               if state.signature(row[0]) is None and row[0] in state.library._extra_atoms}
    return Candidate(_definition(state, "combinator", name, spec, body, slots),
                     Signature(inputs, output, slot_sigs), move, request=request,
                     meta={"slot_families": names, **({"helper_signatures": helpers} if helpers else {}),
                           **(meta or {})})


def _runs(state, name, values):
    scope = state.library.scope()
    return [fast.call(name, (value,), scope, state.world.fuel, state.world.dialect)
            for value in values]


def _fib_parts(state):
    if "int" not in state.sorts or "bool" not in state.sorts:
        return None
    values = tuple(value for value in state.sorts["int"].values if type(value) is int)
    if not all(value in values for value in (0, 1, 2, 3, 4)):
        return None
    less = next(iter(vocab.less(state, "int")), None)
    scope = state.library.scope()

    def result(name, *args):
        run = fast.call(name, args, scope, state.world.fuel, state.world.dialect).outcome
        return run.value if isinstance(run, Ok) else None

    step = next((name for name in vocab.steps(state, "int") if
                 all(result(name, value) == value - 1 for value in (2, 3, 4))), None)
    measure = next((name for name in vocab.int_measures(state, "int") if step and
                    all(type(result(name, value)) is int and
                        0 <= result(name, value - 1) < result(name, value)
                        for value in (2, 3, 4, 5, 6))), None)
    combine = next((name for name in vocab.combiners(state, "int") if
                    all(result(name, left, right) == left + right for left, right in
                        ((1, 1), (1, 2), (2, 3)))), None)
    return (less, measure, step, combine) if all((less, measure, step, combine)) else None


def tree_recursive(state, rng):
    if any(entry.move == "mode.tree_recursive" for entry in state.entries.values()):
        return None
    parts = _fib_parts(state)
    if parts is None or "Rec" not in state.world.decl.opened_nodes():
        return None
    less, measure, step, combine = parts
    value = n.Var("value")
    smaller = n.Call(step, (value,))
    body = n.Case(((n.Test(n.Call(less, (value, n.Lit(2)))), n.Lit(1)),),
                  n.Call(combine, (n.Call("tree", (smaller,)),
                                   n.Call("tree", (n.Call(step, (smaller,)),)))))
    rec = n.Rec("tree", ("value",), body, (n.Var("arg0"),), n.Call(measure, (value,)))
    candidate = _operation(state, "mode.tree_recursive", rec, ("int",), "int")
    values = tuple((value,) for value in state.sorts["int"].values if
                   type(value) is int and -3 <= value <= 6)
    candidate.request = VerifyRequest("bounded", values,
                                      {"domain": "integer probes -3..6", "size": len(values)})
    return candidate


def memo(state, rng):
    originals = [entry for entry in state.entries.values() if entry.kind == "operation" and
                 entry.signature and entry.move != "mode.memo" and entry.steps_max <= 150 and
                 len(state.requests[entry.name].domain) <= 16 and
                 not any(variant.meta.get("memo_of") == entry.name for variant in state.entries.values()
                         if variant.move == "mode.memo") and
                 any(isinstance(node, n.Rec) and sum(isinstance(call, n.Call) and call.fn == node.fn
                     for call in n.walk(node.body)) >= 2 and not node.memo
                     for node in n.walk(state.library.get(entry.name).body))]
    if not originals:
        return None
    original = rng.choice(originals)
    definition = state.library.get(original.name)
    spec = CombinatorSpec("memo_template", tuple(definition.spec.extra.get("input_names") or
                          (f"arg{index}" for index in range(len(original.signature.inputs)))), (),
                          definition.body)
    body = core_combinators.memoized_spec(spec).body
    scope = state.library.scope()
    domain = state.requests[original.name].domain
    plain = [kernel.call(original.name, args, scope, kernel.Limits(fuel=state.world.fuel),
                         dialect=state.world.dialect) for args in domain]
    work = [kernel.evaluate(body, dict(zip(spec.params, args)), scope,
                            kernel.Limits(fuel=state.world.fuel), dialect=state.world.dialect).work
            for args in domain]
    candidate = _operation(state, "mode.memo", body, original.signature.inputs,
                           original.signature.output,
                           {"memo_of": original.name, "plain_steps": [run.steps for run in plain],
                            "memo_work": work})
    candidate.request = state.requests[original.name]
    return candidate


def stable_step(state, rng):
    if "int" not in state.sorts:
        return None
    values = [value for value in state.sorts["int"].values if type(value) is int]
    less = next(iter(vocab.less(state, "int")), None)
    if not less or not all(value in values for value in (0, 1, 2, 3, 4)):
        return None
    available = tuple(bound for bound in (2, 3, 4, 5, 6) if not any(
        entry.move == "mode.stable_step" and entry.meta.get("cap") == bound
        for entry in state.entries.values()))
    if not available:
        return None
    bound = rng.choice(available)
    steps = [name for name in vocab.steps(state, "int") if all(
        isinstance(run.outcome, Ok) and run.outcome.value == value + 1
        for value, run in zip((value for value in values if value < bound),
                              _runs(state, name, (value for value in values if value < bound))))]
    if not steps:
        return None
    value = n.Var("arg0")
    body = n.Case(((n.Test(n.Call(less, (value, n.Lit(bound)))),
                    n.Call(rng.choice(steps), (value,))),), value)
    return _operation(state, "mode.stable_step", body, ("int",), "int", {"cap": bound})


def until_stable(state, rng):
    steps = [entry for entry in state.entries.values() if entry.move == "mode.stable_step"]
    if len(steps) < 2 or "Rec" not in state.world.decl.opened_nodes():
        return None
    equal = next(iter(vocab.equal(state, "int")), None)
    less = next(iter(vocab.less(state, "int")), None)
    scope = state.library.scope()
    subtract = next((name for name in vocab.combiners(state, "int") if all(
        isinstance(run.outcome, Ok) and run.outcome.value == left - right
        for left, right, run in ((left, right, fast.call(name, (left, right), scope,
                                                         state.world.fuel, state.world.dialect))
                                 for left, right in ((5, 2), (3, -1), (4, 4))))), None)
    if not all((equal, less, subtract)):
        return None
    selected = sorted(steps, key=lambda entry: entry.meta["cap"])[:3]
    if len({entry.meta["cap"] for entry in selected}) < 2:
        return None
    if any(entry.move == "mode.until_stable" and
           entry.meta.get("monotone_steps") == [item.name for item in selected]
           for entry in state.entries.values()):
        return None
    bound = max(entry.meta["cap"] for entry in selected)
    def core_calls(node):
        if isinstance(node, n.Call):
            args = tuple(core_calls(arg) for arg in node.args)
            if node.fn == "comb_positive":
                return n.Call(less, (n.Lit(0), *args))
            if node.fn == "comb_dec":
                return n.Call(subtract, (args[0], n.Lit(1)))
            return n.Call(equal if node.fn == "fix_equal" else node.fn, args)
        if isinstance(node, n.Rec):
            return n.Rec(node.fn, node.params, core_calls(node.body),
                         tuple(core_calls(arg) for arg in node.args), core_calls(node.measure))
        if isinstance(node, n.Let):
            return n.Let(node.name, core_calls(node.value), core_calls(node.body))
        if isinstance(node, n.Case):
            return n.Case(tuple((n.Test(core_calls(condition.expr)), core_calls(branch))
                                for condition, branch in node.arms),
                          core_calls(node.default) if node.default is not None else None)
        return node

    rec = n.Let("height", n.Lit(bound + 6), core_calls(core_combinators.fix_spec().body))
    families = {"step": [(entry.name, ("int",), "int") for entry in selected]}
    return _combinator(state, "mode.until_stable", rec, ("step", "x"),
                       ("step",), ("int",), "int", families,
                       {"cap": bound, "monotone_steps": [entry.name for entry in selected]})


def turns(state, rng):
    if not {"Case", "Rec"} <= state.world.decl.opened_nodes():
        return None
    options = []
    for sort in state.sorts.values():
        if not sort.values or sort.name == "bool":
            continue
        observe = state.callables("operation", inputs=(sort.name,), output=sort.name)
        if len(observe) >= 2:
            options.append((sort.name, observe))
    if not options:
        return None
    sort, observe = rng.choice(options)
    scheme = core_combinators.turns_spec(2)
    helpers = core_combinators.turns_atoms() + core_combinators.list_atoms() + [
        atom for atom in core_combinators.counter_atoms() if atom.name == "comb_equal"]
    renames = {atom.name: f"_gen_turns_{atom.name}" for atom in helpers}

    def rename(value):
        if isinstance(value, n.Call):
            return n.Call(renames.get(value.fn, value.fn), tuple(rename(arg) for arg in value.args))
        if is_dataclass(value) and not isinstance(value, (kernel.FnRef,)):
            return replace(value, **{field.name: rename(getattr(value, field.name))
                                     for field in fields(value)})
        if isinstance(value, tuple):
            return tuple(rename(item) for item in value)
        return value

    families = {f"observe{index}": [(name, (sort,), sort) for name in observe[:2]]
                for index in range(2)}
    families.update({f"choose{index}": [(name, (sort,), sort) for name in observe[:2]]
                     for index in range(2)})
    families["apply"] = [(name, (sort, "int", sort), sort)
                         for name in ("_gen_turns_apply_move", "_gen_turns_apply_state")]
    if not set(scheme.op_params) <= set(families):
        return None
    body = n.Let("schedule", n.Lit(2), rename(scheme.body))
    reusable = [entry for entry in state.entries.values() if entry.kind == "operation" and
                entry.signature == Signature((sort,), sort) and entry.steps_max < 60]
    reusable.sort(key=lambda entry: (-entry.layer, entry.steps_mean))
    if reusable and rng.randrange(2):
        body = n.Call(rng.choice(reusable[:5]).name, (body,))
    candidate = _combinator(state, "mode.turns", body, (*scheme.op_params, "state"),
                            scheme.op_params, (sort,), sort, families,
                            {"agents": 2, "schedule": 2})
    # The renamed core helpers are standard-library primitives the library provides itself
    # (GenLibrary: turns_helpers), so they survive checkpoints and are not candidate extras.
    if candidate is not None and not all(state.library.has_name(name) for name in renames.values()):
        return None
    return candidate


def fold_of(state, rng):
    if "Rec" not in state.world.decl.opened_nodes():
        return None
    options = []
    for sort in state.sorts.values():
        if sort.origin != "invented" or sort.sealed or not sort.values:
            continue
        spec = state.library.get(sort.name).spec
        if spec.form != "compose" or len(spec.tags) != 2:
            continue
        base = [tag for tag, members in spec.tags.items() if not members]
        recursive = [(tag, members) for tag, members in spec.tags.items()
                     if not isinstance(members, dict) and len(members) == 2 and
                     members[0][1] == "int" and members[1][1] == sort.name]
        if len(base) != 1 or len(recursive) != 1 or not state.library.has_name(f"{sort.name}.fold"):
            continue
        combiners = state.callables("operation", inputs=("int", "int"), output="int")
        if combiners:
            options.append((sort.name, base[0], recursive[0][0], combiners))
    if not options:
        return None
    sort, base_tag, recursive_tag, combiners = rng.choice(options)
    combiner = rng.choice(combiners[:8])
    zeroes = state.callables("operation", inputs=(), output="int")
    if zeroes:
        zero = rng.choice(zeroes)
    else:
        helper = _operation(state, "mode.fold_zero", n.Lit(0), (), "int")
        if not isinstance(admit(state, helper), Entry):
            return None
        zero = helper.defn.name
    parts = (n.Lit(kernel.FnRef(zero)), n.Lit(kernel.FnRef(combiner)), n.Var("arg0"))
    body = n.Let("used_sort", n.Call(sort, ()),
                 n.Let("used_zero", n.Call(zero, ()),
                       n.Let("used_combiner", n.Call(combiner, (n.Lit(1), n.Lit(2))),
                             n.Call(f"{sort}.fold", parts))))
    candidate = _operation(state, "mode.fold_of", body, (sort,), "int",
                           {"sort": sort, "tags": (base_tag, recursive_tag), "combiner": combiner})
    return candidate


def apply(state, rng):
    options = [entry for entry in state.entries.values() if entry.move == "mode.until_stable"]
    if not options:
        return None
    entry = rng.choice(options)
    spec = state.library.get(entry.name).spec
    chosen = [rng.choice(entry.meta["slot_families"][slot]) for slot in spec.op_params]
    values = iter(n.Var(f"arg{index}") for index in range(len(entry.signature.inputs)))
    plugged = iter(chosen)
    call = n.Call(entry.name, tuple(n.Lit(kernel.FnRef(next(plugged))) if param in spec.op_params
                                   else next(values) for param in spec.params))
    return _operation(state, "mode.apply", call, entry.signature.inputs,
                      entry.signature.output, {"combinator": entry.name, "plugged": chosen})


@dataclass(frozen=True)
class ModeMove:
    name: str
    kind: str
    build: object

    def __call__(self, state, rng: random.Random):
        if self.kind not in state.world.open_kinds:
            return None
        return self.build(state, rng)


MOVES = [ModeMove("mode.tree_recursive", "operation", tree_recursive),
         ModeMove("mode.memo", "operation", memo),
         ModeMove("mode.stable_step", "operation", stable_step),
         ModeMove("mode.until_stable", "combinator", until_stable),
         ModeMove("mode.turns", "combinator", turns),
         ModeMove("mode.fold_of", "operation", fold_of),
         ModeMove("mode.apply", "operation", apply)]
