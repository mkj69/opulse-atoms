"""Combinator templates and operations that apply admitted combinators."""

from __future__ import annotations

import itertools
import random
from dataclasses import dataclass

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.spec import CombinatorSpec, Edge, OperationSpec
from opulse.atoms.values import Card, Ok, truth, value_equal
from opulse.gen_v2 import fast, vocab
from opulse.gen_v2.base import Candidate, GenState, Signature
from opulse.gen_v2.kinds.combinators import definition as _definition
from opulse.gen_v2.kinds.combinators import family_request


def _value_sorts(state, with_predicate=False):
    return [sort for sort in state.sorts
            if len(state.callables("operation", inputs=(sort,), output=sort)) >= 2
            and len(vocab.steps(state, sort)) >= 2
            and (not with_predicate or
                 len(state.callables("operation", inputs=(sort,), output="bool")) >= 2
                 and len(vocab.deciders(state, sort)) >= 2)]


def _family(state, inputs, output, rng, minimum=2):
    names = state.callables("operation", inputs=inputs, output=output)
    if len(names) < minimum:
        return ()
    given = [name for name in names if name not in state.entries]
    invented = [name for name in names if name in state.entries and
                state.entries[name].kind == "operation" and
                state.entries[name].steps_mean < 20 and state.entries[name].steps_max < 80]
    rng.shuffle(given)
    invented.sort(key=lambda name: (-state.layer(name), state.entries[name].steps_mean))
    return tuple((given[:2] + invented[:2] + given[2:3])[:3])


def _slots(state, slot_sigs, rng):
    families = {}
    by_signature = {}
    for slot, signature in slot_sigs.items():
        key = (signature.inputs, signature.output)
        if key not in by_signature:
            by_signature[key] = _family(state, signature.inputs, signature.output, rng)
        family = by_signature[key]
        if not family:
            return None
        families[slot] = family
    return families


def _combinator(state, rng, move, body, params, slot_sigs, inputs, output, meta=None):
    families = _slots(state, slot_sigs, rng)
    if families is None:
        return None
    if len(set(itertools.chain.from_iterable(families.values()))) < 3:
        return None
    family = tuple(dict.fromkeys(itertools.chain.from_iterable(families.values())))
    request = family_request(state, inputs, family)
    if request is None:
        return None
    name = state.names.fresh("combinator")
    slots = tuple(slot_sigs)
    spec = CombinatorSpec(name, params, slots, body)
    signature = Signature(inputs, output, tuple(slot_sigs[slot] for slot in slots))
    return Candidate(_definition(state, "combinator", name, spec, body, slots), signature,
                     move, request=request, meta={"slot_families": families, **(meta or {})})


def _decorate(body, rng, state, sort="int", input_name="x"):
    invented = [name for name in state.callables("operation", output=sort)
                if name in state.entries and state.entries[name].kind == "operation" and
                state.entries[name].move != "mode.memo" and
                state.signature(name) is not None and
                state.signature(name).inputs in
                ((sort,), (sort, sort)) and
                state.entries[name].steps_mean < 48 and state.entries[name].steps_max < 120]
    invented.sort(key=lambda name: (-state.layer(name), state.entries[name].steps_mean))
    variants = vocab.steps(state, sort)
    if invented:
        name = rng.choice(invented[:min(6, len(invented))])
        args = (body,) if state.signature(name).inputs == (sort,) else (body, n.Var(input_name))
        body = n.Call(name, args)
    elif variants and rng.randrange(3):
        body = n.Call(rng.choice(variants), (body,))
    predicates = [name for name in vocab.deciders(state, sort)
                  if name in state.entries and state.entries[name].steps_mean < 24 and
                  state.entries[name].steps_max < 80]
    predicates.sort(key=lambda name: state.layer(name), reverse=True)
    if (predicates and variants and "Case" in state.world.decl.opened_nodes()
            and rng.randrange(2)):
        body = n.Case(((n.Test(n.Call(rng.choice(predicates[:min(4, len(predicates))]),
                                               (n.Var(input_name),))),
                         n.Call(rng.choice(variants), (body,))),), body)
    return body


def chain(state, rng):
    if any(isinstance(value, Card) for sort in state.sorts.values()
           for value in sort.values[:1]):
        card_candidate = card_measure(state, rng)
        if card_candidate is not None:
            return card_candidate
    sorts = _value_sorts(state)
    if not sorts:
        return None
    sort = rng.choice(sorts)
    source = n.Var("x")
    first = n.Call("f", (source,))
    binary = len(state.callables("operation", inputs=(sort, sort), output=sort)) >= 2
    body = n.Call("g", (first,)) if not binary or rng.randrange(2) else n.Call("g", (first, source))
    if len(body.args) == 2:
        second = Signature((sort, sort), sort)
    else:
        second = Signature((sort,), sort)
    if rng.randrange(2):
        body = n.Call("f", (body,))
    return _combinator(state, rng, "comb.chain", _decorate(body, rng, state, sort),
                       ("f", "g", "x"), {"f": Signature((sort,), sort), "g": second}, (sort,), sort)


def repeat(state, rng):
    sorts = _value_sorts(state)
    if not sorts:
        return None
    sort = rng.choice(sorts)
    count = rng.randint(2, 3)
    body = n.Var("x")
    for _ in range(count):
        body = n.Call("f", (body,))
    return _combinator(state, rng, "comb.repeat", _decorate(body, rng, state, sort),
                       ("f", "x"), {"f": Signature((sort,), sort)}, (sort,), sort,
                       {"count": count})


def weave(state, rng):
    signatures = {}
    for name in state.callables("operation"):
        signature = state.signature(name)
        if (signature and 2 <= len(signature.inputs) <= 3 and
                signature.output in signature.inputs):
            signatures.setdefault((signature.inputs, signature.output), []).append(name)
    options = [key for key, names in signatures.items() if len(names) >= 3 and
               all(sort in state.sorts and state.sorts[sort].values for sort in key[0])]
    if not options:
        return None
    inputs, output = rng.choice(options)
    params = tuple(f"x{index}" for index in range(len(inputs)))
    args = tuple(n.Var(param) for param in params)
    first = n.Call("f", args)
    position = inputs.index(output)
    next_args = tuple(first if index == position else arg for index, arg in enumerate(args))
    body = n.Call("g", next_args)
    if rng.randrange(2):
        body = n.Call("f", tuple(body if index == position else arg
                                 for index, arg in enumerate(args)))
    signature = Signature(inputs, output)
    return _combinator(state, rng, "comb.weave", body, ("f", "g", *params),
                       {"f": signature, "g": signature}, inputs, output)


def card_measure(state, rng):
    if "Case" not in state.world.decl.opened_nodes():
        return None
    options = []
    for source, pairs in state.world.measures.items():
        sort = state.sorts.get(source)
        if sort is None or not any(isinstance(value, Card) for value in sort.values):
            continue
        for _, measure in pairs:
            if state.signature(measure) != Signature((source,), "int"):
                continue
            for projected in state.sorts:
                projections = state.callables("operation", inputs=(source,), output=projected)
                comparisons = state.callables("operation", inputs=(projected, projected),
                                               output="bool")
                if len(projections) >= 2 and comparisons:
                    options.append((source, projected, measure, projections, comparisons))
    if not options:
        return None
    source, projected, measure, projections, comparisons = rng.choice(options)
    reference = rng.choice(projections[:2])
    comparison = rng.choice(comparisons[:3])
    offset = rng.randint(1, 4)
    value = n.Var("x")
    length = n.Call(measure, (value,))
    first = n.Call("combine", (length, n.Lit(offset)))
    second = n.Call("combine", (length, n.Lit(-offset)))
    if rng.randrange(2):
        first, second = second, first
    test = n.Call(comparison, (n.Call("project", (value,)), n.Call(reference, (value,))))
    body = n.Case(((n.Test(test), first),), second)
    earlier = [entry for entry in state.entries.values()
               if entry.move == "comb.card_measure" and entry.signature and
               entry.signature.inputs == (source,) and entry.signature.output == "int" and
               entry.signature.op_inputs == (Signature((source,), projected),
                                             Signature(("int", "int"), "int")) and
               entry.steps_max < 100]
    if earlier and rng.randrange(3):
        earlier.sort(key=lambda entry: entry.layer, reverse=True)
        previous = earlier[0]
        reused = n.Call(previous.name, (n.Var("project"), n.Var("combine"), value))
        body = n.Call("combine", (body, reused))
    return _combinator(state, rng, "comb.card_measure", body,
                       ("project", "combine", "x"),
                       {"project": Signature((source,), projected),
                        "combine": Signature(("int", "int"), "int")},
                       (source,), "int")


def blend(state, rng):
    if "Case" not in state.world.decl.opened_nodes():
        return None
    signatures = {}
    for name in state.callables("operation", output="bool"):
        signature = state.signature(name)
        if signature and signature.inputs and all(sort in state.sorts for sort in signature.inputs):
            signatures.setdefault(signature.inputs, []).append(name)
    options = [inputs for inputs, names in signatures.items() if len(names) >= 3]
    if not options:
        return None
    inputs = rng.choice(options)
    params = tuple(f"x{index}" for index in range(len(inputs)))
    args = tuple(n.Var(param) for param in params)
    first, second = n.Call("f", args), n.Call("g", args)
    body = n.Case(((n.Test(first), second),), first)
    predicates = [name for name in state.callables("operation", inputs=inputs, output="bool")
                  if name in state.entries and state.entries[name].steps_mean < 30]
    if predicates:
        predicates.sort(key=lambda name: (-state.layer(name), state.entries[name].steps_mean))
        predicate = rng.choice(predicates[:min(5, len(predicates))])
        body = n.Case(((n.Test(n.Call(predicate, args)), body),),
                      n.Call("f" if rng.randrange(2) else "g", args))
    signature = Signature(inputs, "bool")
    return _combinator(state, rng, "comb.blend", body, ("f", "g", *params),
                       {"f": signature, "g": signature}, inputs, "bool")


def guard(state, rng):
    if "Case" not in state.world.decl.opened_nodes():
        return None
    sorts = _value_sorts(state, with_predicate=True)
    if not sorts:
        return None
    sort = rng.choice(sorts)
    value = n.Var("x")
    predicate = n.Call("p", (value,))
    first = n.Call("f", (value,))
    second = n.Call("g", (value,))
    if rng.randrange(2):
        first, second = second, first
    body = n.Case(((n.Test(predicate), first),), second)
    return _combinator(state, rng, "comb.guard", _decorate(body, rng, state, sort),
                       ("p", "f", "g", "x"),
                       {"p": Signature((sort,), "bool"), "f": Signature((sort,), sort),
                        "g": Signature((sort,), sort)}, (sort,), sort)


def _counter(state):
    if "int" not in state.world.measures:
        return None
    step, measure = state.world.measures["int"][0]
    if state.signature(step) != Signature(("int",), "int") or state.signature(measure) != Signature(("int",), "int"):
        return None
    return step, measure


def loop(state, rng):
    if not {"Case", "Rec"} <= state.world.decl.opened_nodes():
        return None
    counter = _counter(state)
    if counter is None:
        return _measured_loop(state, rng, fixed=False)
    step, measure = counter
    sorts = [sort for sort in state.sorts if vocab.steps(state, sort) and vocab.deciders(state, sort)]
    if not sorts:
        return None
    sort = rng.choice(sorts)
    rounds = rng.randint(2, 6)
    value, remaining = n.Var("acc"), n.Var("remaining")
    recurse = n.Call("iterate", (n.Call("f", (value,)), n.Call(step, (remaining,))))
    body = n.Case(((n.Test(n.Call("p", (value,))), recurse),), value)
    rec = n.Rec("iterate", ("acc", "remaining"), body, (n.Var("x"), n.Lit(rounds)),
                n.Call(measure, (remaining,)))
    return _combinator(state, rng, "comb.loop", _decorate(rec, rng, state, sort),
                       ("p", "f", "x"),
                       {"p": Signature((sort,), "bool"), "f": Signature((sort,), sort)},
                       (sort,), sort, {"rounds": rounds})


def search(state, rng):
    if not {"Case", "Rec"} <= state.world.decl.opened_nodes():
        return None
    if "int" not in state.sorts or 0 not in state.sorts["int"].values:
        return _search_measured(state, rng)
    samples = (0, 1, 2)
    def matches(name, arguments, expected):
        for args, value in zip(arguments, expected):
            try:
                outcome = fast.call(name, args, state.library.scope(),
                                    state.world.fuel, state.world.dialect).outcome
            except (ValueError, TypeError, KeyError):
                return False
            if not isinstance(outcome, Ok) or outcome.value != value:
                return False
        return True
    increment = [name for name in vocab.steps(state, "int")
                 if matches(name, ((value,) for value in samples), (1, 2, 3))]
    distance = [name for name in state.callables("operation", inputs=("int", "int"), output="int")
                if matches(name, ((3, value) for value in samples), (3, 2, 1))]
    less = vocab.less(state, "int")
    if not increment or not distance or not less:
        return _search_measured(state, rng)
    advance, difference, order = rng.choice(increment), rng.choice(distance), rng.choice(less)
    index, bound = n.Var("index"), n.Var("bound")
    recurse = n.Call("scan", (n.Call(advance, (index,)),))
    body = n.Case(((n.Test(n.Call("p", (index,))), index),),
                  n.Case(((n.Test(n.Call(order, (index, bound))), recurse),)))
    rec = n.Rec("scan", ("index",), body, (n.Lit(0),), n.Call(difference, (bound, index)))
    guarded = n.Case(((n.Test(n.Call(order, (bound, n.Lit(0)))), n.Case(())),), rec)
    return _combinator(state, rng, "comb.search", guarded, ("p", "bound"),
                       {"p": Signature(("int",), "bool")}, ("int",), "int")


def fixpoint(state, rng):
    if not {"Case", "Rec"} <= state.world.decl.opened_nodes():
        return None
    counter = _counter(state)
    if counter is None:
        return _measured_loop(state, rng, fixed=True)
    sorts = [sort for sort in state.sorts if vocab.steps(state, sort) and vocab.equal(state, sort)]
    if not sorts:
        return None
    sort = rng.choice(sorts)
    equality = rng.choice(vocab.equal(state, sort))
    step, measure = counter
    value, remaining = n.Var("acc"), n.Var("remaining")
    next_value = n.Call("f", (value,))
    body = n.Let("next_value", next_value,
                 n.Case(((n.Test(n.Call(equality, (value, n.Var("next_value")))), value),),
                        n.Call("converge", (n.Var("next_value"), n.Call(step, (remaining,))))))
    rec = n.Rec("converge", ("acc", "remaining"), body,
                (n.Var("x"), n.Lit(rng.randint(2, 6))), n.Call(measure, (remaining,)))
    return _combinator(state, rng, "comb.fixpoint", _decorate(rec, rng, state, sort), ("f", "x"),
                       {"f": Signature((sort,), sort)}, (sort,), sort)


def _measured_loop(state, rng, fixed):
    options = [(sort, step, measure) for sort, pairs in state.world.measures.items()
               if sort in state.sorts and len(vocab.steps(state, sort)) >= 2
               and len(vocab.equal(state, sort) if fixed else vocab.deciders(state, sort)) >= (1 if fixed else 2)
               for step, measure in pairs]
    if not options:
        return None
    sort, step, measure = rng.choice(options)
    tester = _base_tester(state, state.sorts[sort], measure)
    if tester is None:
        return None
    value, remaining = n.Var("acc"), n.Var("remaining")
    recurse = n.Call("iterate", (n.Call("f", (value,)), n.Call(step, (remaining,))))
    if fixed:
        equality = rng.choice(vocab.equal(state, sort))
        body = n.Let("next_value", n.Call("f", (value,)),
                     n.Case(((n.Test(n.Call(equality, (value, n.Var("next_value")))), value),),
                            n.Call("iterate", (n.Var("next_value"), n.Call(step, (remaining,))))))
    else:
        body = n.Case(((n.Test(n.Call("p", (value,))), recurse),), value)
    body = n.Case(((n.Test(n.Call(tester, (remaining,))), value),), body)
    rec = n.Rec("iterate", ("acc", "remaining"), body, (n.Var("x"), n.Var("x")),
                n.Call(measure, (remaining,)))
    slots = {"f": Signature((sort,), sort)}
    if not fixed:
        slots = {"p": Signature((sort,), "bool"), **slots}
    return _combinator(state, rng, "comb.fixpoint" if fixed else "comb.loop", rec,
                       ("f", "x") if fixed else ("p", "f", "x"), slots,
                       (sort,), sort)


def compose(state, rng):
    originals = [entry for entry in state.entries.values() if entry.kind == "combinator" and
                 entry.signature and entry.signature.inputs and
                 (entry.signature.output in entry.signature.inputs or
                  entry.signature.output == "bool" and "Case" in state.world.decl.opened_nodes() and
                  any(slot.inputs == entry.signature.inputs and slot.output == "bool"
                      for slot in entry.signature.op_inputs)) and
                 len(entry.signature.inputs) <= 3 and entry.steps_mean < 35 and entry.steps_max < 90]
    if not originals:
        return None
    originals.sort(key=lambda entry: entry.layer, reverse=True)
    original = rng.choice(originals[:min(8, len(originals))])
    old = state.library.get(original.name).spec
    mapping = {slot: f"slot{index}" for index, slot in enumerate(old.op_params)}
    params = tuple(mapping.get(param, param) for param in old.params)
    body = n.Call(original.name, tuple(n.Var(param) for param in params))
    if original.signature.output not in original.signature.inputs:
        choices = [mapping[slot] for slot, signature in zip(old.op_params, original.signature.op_inputs)
                   if signature.inputs == original.signature.inputs and signature.output == "bool"]
        body = n.Case(((n.Test(body), n.Lit(False)),),
                      n.Call(rng.choice(choices), tuple(n.Var(param) for param in params
                                                        if param not in mapping.values())))
        return _combinator(state, rng, "comb.compose", body, params,
                           dict(zip(mapping.values(), original.signature.op_inputs)),
                           original.signature.inputs, original.signature.output,
                           {"derived_from": [original.name]})
    unary = [mapping[slot] for slot, signature in zip(old.op_params, original.signature.op_inputs)
             if signature.inputs == (original.signature.output,) and
             signature.output == original.signature.output]
    if unary:
        body = n.Call(rng.choice(unary), (body,))
    else:
        value_params = [param for param in params if param not in mapping.values()]
        position = original.signature.inputs.index(original.signature.output)
        binary = state.callables("operation", inputs=(original.signature.output,) * 2,
                                 output=original.signature.output)
        if binary:
            body = n.Call(rng.choice(binary[:8]), (body, n.Var(value_params[position])))
        else:
            wrapped = tuple(body if param == value_params[position] else n.Var(param) for param in params)
            body = n.Call(original.name, wrapped)
    if len(original.signature.inputs) == 1:
        value_param = next(param for param in params if param not in mapping.values())
        body = _decorate(body, rng, state, original.signature.output, value_param)
    slot_sigs = dict(zip(mapping.values(), original.signature.op_inputs))
    return _combinator(state, rng, "comb.compose", body, params, slot_sigs,
                       original.signature.inputs, original.signature.output,
                       {"derived_from": [original.name]})


def _base_tester(state, sort, measure):
    cache = getattr(state, "_comb_base_tester_cache", None)
    if cache is None:
        cache = {}
        state._comb_base_tester_cache = cache
    key = sort.name, measure
    if key in cache:
        return cache[key]
    scope = state.library.scope()
    base_size = 1 if sort.origin == "invented" else 0
    for tester in (*sort.testers, *state.world.bases.get(sort.name, ())):
        if state.signature(tester) != Signature((sort.name,), "bool"):
            continue
        try:
            observations = [(kernel.call(tester, (value,), scope).outcome,
                             kernel.call(measure, (value,), scope).outcome)
                            for value in sort.values[:12]]
            if observations and all(isinstance(test, Ok) and isinstance(size, Ok) and
                                    truth(test.value) == (size.value == base_size)
                                    for test, size in observations):
                cache[key] = tester
                return tester
        except (ValueError, TypeError, IndexError, KeyError):
            continue
    cache[key] = None
    return None


def _search_measured(state, rng):
    options = []
    for sort_name, pairs in state.world.measures.items():
        sort = state.sorts.get(sort_name)
        if sort is None or len(state.callables("operation", inputs=(sort_name,), output="bool")) < 2:
            continue
        for step, measure in pairs:
            tester = _base_tester(state, sort, measure)
            if tester:
                options.append((sort_name, step, measure, tester))
    if not options:
        return None
    sort, step, measure, tester = rng.choice(options)
    current = n.Var("current")
    body = n.Case(((n.Test(n.Call("p", (current,))), current),),
                  n.Case(((n.Test(n.Call(tester, (current,))), n.Case(())),),
                         n.Call("scan", (n.Call(step, (current,)),))))
    rec = n.Rec("scan", ("current",), body, (n.Var("bound"),), n.Call(measure, (current,)))
    return _combinator(state, rng, "comb.search", rec, ("p", "bound"),
                       {"p": Signature((sort,), "bool")}, (sort,), sort)


def fold(state, rng):
    if not {"Case", "Rec"} <= state.world.decl.opened_nodes():
        return None
    sorts = [sort for sort in state.sorts.values() if sort.origin != "invented"]
    for sort in sorts:
        if not sort.testers and not state.world.bases.get(sort.name):
            continue
        for step, measure in state.world.measures.get(sort.name, ()):
            tester = _base_tester(state, sort, measure)
            accessors = sort.accessors or tuple(name for name in state.callables(
                "operation", inputs=(sort.name,)) if name not in (step, measure) and
                state.signature(name).output not in (sort.name, "bool"))
            choices = [(access, accumulator) for access in accessors
                       if state.signature(access) and state.signature(access).inputs == (sort.name,)
                       for accumulator in state.sorts
                       if len(state.callables("operation", inputs=(state.signature(access).output, accumulator),
                                              output=accumulator)) >= 2]
            if not choices:
                continue
            accessor, accumulator = rng.choice(choices)
            if not tester or not accessor or state.signature(step) != Signature((sort.name,), sort.name):
                continue
            items, zero = n.Var("items"), n.Var("zero")
            body = n.Case(((n.Test(n.Call(tester, (items,))), zero),),
                          n.Call("f", (n.Call(accessor, (items,)),
                                       n.Call("fold_items", (n.Call(step, (items,)),)))))
            rec = n.Rec("fold_items", ("items",), body, (n.Var("items"),),
                        n.Call(measure, (items,)))
            candidate = _combinator(state, rng, "comb.fold", _decorate(rec, rng, state, accumulator, "zero"),
                                    ("f", "zero", "items"),
                                    {"f": Signature((state.signature(accessor).output, accumulator), accumulator)},
                                    (accumulator, sort.name), accumulator)
            if candidate is not None:
                return candidate
    return None


def apply(state, rng):
    options = [entry for entry in state.entries.values() if entry.kind == "combinator" and entry.signature
               and entry.move not in ("comb.fixpoint", "comb.search", "comb.loop") and
               entry.steps_mean < 80]
    options.sort(key=lambda entry: entry.layer, reverse=True)
    if len(options) > 12:
        options = options[:12] + rng.sample(options[12:], min(3, len(options) - 12))
    rng.shuffle(options)
    for entry in options:
        signature = entry.signature
        spec = state.library.get(entry.name).spec
        if not signature.inputs or not all(sort in state.sorts for sort in signature.inputs):
            continue
        families = []
        for slot_signature in signature.op_inputs:
            names = state.callables("operation", inputs=slot_signature.inputs, output=slot_signature.output)
            if not names:
                break
            names = [name for name in names if name not in state.entries or
                     state.entries[name].steps_mean < 20]
            names.sort(key=lambda name: state.layer(name), reverse=True)
            families.append(names[:min(12, len(names))])
        if len(families) != len(spec.op_params):
            continue
        if any(not names for names in families):
            continue
        chosen = [rng.choice(names[:min(5, len(names))]) for names in families]
        arguments = iter(n.Var(f"arg{index}") for index in range(len(signature.inputs)))
        plugged = iter(chosen)
        call = n.Call(entry.name, tuple(n.Lit(kernel.FnRef(next(plugged))) if param in spec.op_params
                                     else next(arguments) for param in spec.params))
        body = call
        name = state.names.fresh("operation")
        operation = OperationSpec(name, "transform" if len(signature.inputs) == 1 else "combine",
                                  tuple(Edge(sort) for sort in signature.inputs), Edge(signature.output),
                                  "Apply a verified combinator to the plugged operations.",
                                  extra={"input_names": [f"arg{index}" for index in range(len(signature.inputs))]})
        definition = _definition(state, "operation", name, operation, body)
        if signature.inputs == (signature.output,):
            scope = state.library.scope().extend([kernel.Defn(name, ("arg0",), body)])
            probes = state.sorts[signature.output].values[:8]
            if probes and all(
                    isinstance(result := fast.call(name, (value,), scope, state.world.fuel,
                                                   state.world.dialect).outcome, Ok)
                    and value_equal(result.value, value) for value in probes):
                continue
        return Candidate(definition, Signature(signature.inputs, signature.output), "app.apply",
                         meta={"combinator": entry.name, "plugged": chosen})
    return None


@dataclass(frozen=True)
class _Move:
    name: str
    kind: str
    build: object

    def __call__(self, state: GenState, rng: random.Random):
        if self.kind not in state.world.open_kinds:
            return None
        return self.build(state, rng)


MOVES = [_Move(f"comb.{fn.__name__}", "combinator", fn) for fn in
         (chain, repeat, weave, blend, guard, loop, fold, search, fixpoint, compose)] + [
             _Move("app.apply", "operation", apply)]
