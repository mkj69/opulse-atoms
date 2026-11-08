"""Discoverable moves for checked families of definition templates."""

from __future__ import annotations

from dataclasses import dataclass
from functools import cmp_to_key
from itertools import combinations

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.spec import Edge, ObjectSpec, OperationSpec
from opulse.atoms.values import Card, Ok, truth, value_equal
from opulse.gen_v2 import fast, vocab
from opulse.gen_v2.admit import admit
from opulse.gen_v2.base import Candidate, Entry, Signature
from opulse.gen_v2.moves.combinator import _definition
from opulse.gen_v2.moves.object import _candidate as object_candidate
from opulse.gen_v2.moves.object import _is_base_value
from opulse.gen_v2.moves.observation import _candidate as observation_candidate
from opulse.gen_v2.templates import (
    _count_condition,
    _count_conditions,
    _holds,
    invent_template,
    template_candidate,
    templates_for,
)


def _canonicalizers(state):
    """Find total, idempotent, valid-sort unary operations on finite probe sorts."""
    scope = state.library.scope()
    seen = set()
    for sort in list(state.sorts.values())[:12]:
        if len(sort.values) < 3:
            continue
        for operator in state.callables("operation", inputs=(sort.name,), output=sort.name)[:24]:
            if sort.sealed and operator not in sort.interface:
                continue
            mapped = []
            for value in sort.values:
                result = kernel.call(operator, (value,), scope,
                                     kernel.Limits(fuel=state.world.fuel)).outcome
                if not isinstance(result, Ok) or not _is_base_value(sort.name, result.value):
                    break
                mapped.append(result.value)
            if len(mapped) != len(sort.values):
                continue
            if not all(isinstance(again := kernel.call(operator, (value,), scope,
                    kernel.Limits(fuel=state.world.fuel)).outcome, Ok) and value_equal(again.value, value)
                    for value in mapped):
                continue
            if len({repr(value) for value in mapped}) == len(sort.values):
                continue
            behaviour = (sort.name, tuple(map(repr, mapped)))
            if behaviour in seen:
                continue
            seen.add(behaviour)
            yield (sort.name, operator)


def _synthesize_canonicalizers(state):
    if "operation" not in state.world.open_kinds or not _card_world(state):
        return
    sorts = sorted(list(state.sorts.values())[:12],
                   key=lambda item: (not (item.name == state.world.truth_sort and not item.sealed),
                                     not isinstance(item.values[0], Card)))
    for sort in sorts:
        if sort.sealed or len(sort.values) < 3 or len(repr(sort.values[0])) > 250:
            continue
        tested = getattr(state, "_template_canon_tried", set())
        if sort.name in tested:
            continue
        tested.add(sort.name)
        state._template_canon_tried = tested
        tests = [n.Call(name, (n.Var("x"), n.Lit(value)))
                 for name in vocab.equal(state, sort.name)[:1] for value in sort.values[:4]]
        tests += [n.Call(name, (n.Var("x"),)) for name in vocab.deciders(state, sort.name)[:3]]
        for other in list(state.sorts.values())[:8]:
            if other.name == sort.name:
                continue
            for name in state.callables("operation", inputs=(sort.name, other.name), output="bool")[:2]:
                for value in other.values[:3]:
                    tests.append(n.Call(name, (n.Var("x"), n.Lit(value))))
        for measure in state.callables("operation", inputs=(sort.name,), output="int")[:3]:
            for decider in vocab.deciders(state, "int")[:2]:
                tests.append(n.Call(decider, (n.Call(measure, (n.Var("x"),)),)))
            for equal in vocab.equal(state, "int")[:1]:
                for value in state.sorts["int"].values[:3]:
                    tests.append(n.Call(equal, (n.Call(measure, (n.Var("x"),)), n.Lit(value))))
        for operator in state.callables("operation", output="int"):
            signature = state.signature(operator)
            if signature.inputs != (sort.name, "int"):
                continue
            for decider in vocab.deciders(state, "int")[:2]:
                for index in state.sorts["int"].values[:3]:
                    tests.append(n.Call(decider, (n.Call(operator, (n.Var("x"), n.Lit(index))),)))
        for condition in tests[:20]:
            matches = []
            valid = True
            for value in sort.values:
                result = kernel.evaluate(condition, {"x": value}, state.library.scope(),
                                         kernel.Limits(fuel=state.world.fuel)).outcome
                if not isinstance(result, Ok):
                    valid = False
                    break
                try:
                    matches.append(truth(result.value))
                except TypeError:
                    valid = False
                    break
            if not valid:
                continue
            matches = [value for value, matched in zip(sort.values, matches) if matched]
            if not matches or len(matches) == len(sort.values):
                continue
            replacements = (matches[:3] if len(matches) > 1 else
                            [value for value in sort.values if value not in matches][:3])
            for replacement in replacements:
                if sum(name == sort.name for name, _ in _canonicalizers(state)) >= 3:
                    return
                branch = n.Not(n.Test(condition)) if len(matches) == 1 else n.Test(condition)
                body = n.Case(((branch, n.Lit(replacement)),), n.Var("x"))
                name = state.names.fresh("operation")
                signature = Signature((sort.name,), sort.name)
                spec = OperationSpec(name, "transform", (Edge(sort.name),), Edge(sort.name),
                                     "Canonicalize a tested subset of probe values.",
                                     extra={"input_names": ["x"]})
                admit(state, Candidate(_definition(state, "operation", name, spec, body),
                                       signature, "tmpl.canon"))


def _ordered(state, sort, operator):
    values = sort.values[:12]

    def compare(left, right):
        if _holds(state, operator, left, right):
            return -1
        if _holds(state, operator, right, left):
            return 1
        return 0

    return sorted(values, key=cmp_to_key(compare))


def _card_order(state, sort):
    if not isinstance(sort.values[0], Card):
        return []
    less = vocab.less(state, "int") if "int" in state.sorts else []
    equal = vocab.equal(state, "int") if "int" in state.sorts else []
    if not less or not equal:
        return []
    scope = state.library.scope()
    projections = []
    for name in state.callables("operation", inputs=(sort.name,), output="int")[:6]:
        outcomes = [fast.call(name, (value,), scope, state.world.fuel, state.world.dialect).outcome
                    for value in sort.values]
        if all(isinstance(result, Ok) and type(result.value) is int for result in outcomes):
            projections.append((name, tuple(result.value for result in outcomes)))
    selected = next(((first,) for first in projections if len(set(first[1])) == len(sort.values)), None)
    if selected is None:
        selected = next(((first, second) for first in projections for second in projections
                         if first != second and len(set(zip(first[1], second[1]))) == len(sort.values)), None)
    if not selected:
        return []
    left = n.Var("left")
    right = n.Var("right")
    body = n.Lit(False)
    for name, _ in reversed(selected):
        lhs = n.Call(name, (left,))
        rhs = n.Call(name, (right,))
        body = n.Case(((n.Test(n.Call(less[0], (lhs, rhs))), n.Lit(True)),
                       (n.Test(n.Call(equal[0], (lhs, rhs))), body)), n.Lit(False))
    operator = state.names.fresh("operation")
    spec = OperationSpec(operator, "decide", (Edge(sort.name), Edge(sort.name)), Edge("bool"),
                         "Order observable coordinates lexicographically.",
                         extra={"input_names": ["left", "right"]})
    entry = admit(state, Candidate(_definition(state, "operation", operator, spec, body),
                                   Signature((sort.name, sort.name), "bool"), "tmpl.order"))
    return [entry.name] if isinstance(entry, Entry) else []


def _interval_families(state):
    for sort in list(state.sorts.values())[:12]:
        if sort.sealed or len(sort.values) < 5 or len(repr(sort.values[0])) > 250:
            continue
        operators = vocab.less(state, sort.name)
        if not operators and "operation" in state.world.open_kinds:
            attempted = getattr(state, "_template_order_attempted", set())
            if sort.name not in attempted:
                attempted.add(sort.name)
                state._template_order_attempted = attempted
                operators = _card_order(state, sort)
        for operator in operators[:1]:
            values = _ordered(state, sort, operator)
            yield [(sort.name, operator, values[index], values[index + 2]) for index in range(3)]


def _ensure_lift_record(state):
    if ("object" not in state.world.open_kinds or not _card_world(state) or
            getattr(state, "_template_record_tried", False)):
        return
    # Given object operations are registered with kind "object" but carry an OperationSpec.
    if any(definition.kind == "object" and getattr(definition.spec, "form", None) == "compose" and
           len(definition.spec.tags) == 1 and any(isinstance(fields, list) and len(fields) >= 2 and
           len({part for _, part in fields}) == 1 and
           len(_lift_operators(state, fields[0][1])) >= 3
           for fields in definition.spec.tags.values()) for definition in state.library.definitions.values()):
        state._template_record_tried = True
        return
    for sort in state.sorts.values():
        if sort.sealed or len(sort.values) < 3 or len(repr(sort.values[0])) > 150:
            continue
        if len(_lift_operators(state, sort.name)) < 3:
            continue
        state._template_record_tried = True
        name = state.names.fresh("object")
        spec = ObjectSpec(name, "compose", tags={"pair": [["left", sort.name], ["right", sort.name]]})
        samples = tuple(dict.fromkeys((sort.values[0], sort.values[len(sort.values) // 2],
                                       sort.values[-1])))
        values = tuple(Card(name, "pair", (left, right))
                       for left in samples for right in samples)
        witness = n.Call(f"{name}.pair", (n.Lit(samples[0]), n.Lit(samples[1])))
        if isinstance(admit(state, object_candidate(state, spec, "tmpl.record", witness, values)), Entry):
            return


def _lift_operators(state, sort):
    scope = state.library.scope()
    values = state.sorts[sort].values
    sample = tuple(dict.fromkeys((values[0], values[len(values) // 2], values[-1])))
    cache = getattr(state, "_template_lift_operators", {})
    for name in state.callables("operation", inputs=(sort,), output=sort):
        if (sort, name) not in cache:
            results = [fast.call(name, (value,), scope, state.world.fuel,
                                 state.world.dialect).outcome for value in sample]
            cache[sort, name] = (all(isinstance(result, Ok) and
                                     _is_base_value(sort, result.value) for result in results) and
                                 len({repr(result.value) for result in results}) >= 2 and
                                 any(not value_equal(value, result.value)
                                     for value, result in zip(sample, results)))
    state._template_lift_operators = cache
    return [name for name in state.callables("operation", inputs=(sort,), output=sort)
            if cache[sort, name]]


def _card_world(state):
    return any(sort.origin == "given" and sort.values and isinstance(sort.values[0], Card)
               for sort in state.sorts.values())


def _ensure_count_probes(state):
    if (not state.world.probes or not state.world.truth_states or "int" not in state.sorts or
            not vocab.combiners(state, "int") or getattr(state, "_template_count_seeded", False)):
        return
    from opulse.gen_v2.moves.observation import _sources

    sources = _sources(state, earlier=True)
    if len({source[0] for source in sources if _count_condition(state, source) is not None}) >= 3:
        state._template_count_seeded = True
        return
    source = next((item for item in sources if item[0] in state.world.probes and
                   len(state.signature(item[0]).inputs) == 1), None)
    if source is None or (baseline := _count_condition(state, source)) is None:
        return
    scope = state.library.scope()
    states = state.world.truth_states
    samples = (tuple(range(len(states))) if len(states) <= 32 else
               tuple(dict.fromkeys((0, *(len(states) * index // 8 for index in range(1, 8)),
                                         len(states) - 1))))
    observed = [fast.call(source[0], (states[index],), scope, state.world.fuel,
                          state.world.dialect).outcome for index in samples]
    created = 0
    for condition in _count_conditions(state, source[1]):
        if created >= 2:
            break
        if condition == baseline[1]:
            continue
        answers = [fast.evaluate(condition, {"_sample": outcome.value}, scope, state.world.fuel,
                                 state.world.dialect).outcome for outcome in observed if isinstance(outcome, Ok)]
        if len(answers) != len(observed) or not all(isinstance(answer, Ok) for answer in answers):
            continue
        try:
            if len({truth(answer.value) for answer in answers}) != 2:
                continue
        except TypeError:
            continue
        body = n.Let("_sample", source[2], condition)
        candidate = observation_candidate(state, "tmpl.probe", body, source[3], "bool")
        if isinstance(admit(state, candidate), Entry):
            created += 1
    state._template_count_seeded = True


def _families(state, kind=None):
    if "object" in state.world.open_kinds and kind in (None, "object"):
        canonical = list(_canonicalizers(state))
        if not any(isinstance(state.sorts[sort].values[0], Card) for sort, _ in canonical) or len(canonical) < 3:
            _synthesize_canonicalizers(state)
            canonical = list(_canonicalizers(state))
        canonical.sort(key=lambda item: not isinstance(state.sorts[item[0]].values[0], Card))
        if len(canonical) >= 3:
            yield "Quot", canonical[:3]
        for family in _interval_families(state):
            yield "Interval", family
    if "combinator" in state.world.open_kinds and kind in (None, "combinator"):
        for sort in state.sorts:
            if len(state.callables("operation", inputs=(sort,), output=sort)) >= 3:
                yield "Iterate", [(sort, count) for count in (2, 3, 4)]
                break
    if "observation" in state.world.open_kinds and state.world.truth_states and kind in (None, "observation"):
        from opulse.gen_v2.moves.observation import _sources

        probes = [source[0] for source in _sources(state, earlier=True)
                  if _count_condition(state, source) is not None]
        if len(set(probes)) >= 3 and "int" in state.sorts and vocab.combiners(state, "int"):
            for family in list(combinations(dict.fromkeys(probes[:12]), 3))[:32]:
                yield "Count", [(probe,) for probe in family]
    if "operation" in state.world.open_kinds and kind in (None, "operation"):
        offered = 0
        for sort in state.sorts.values():
            if sort.origin != "invented":
                continue
            definition = state.library.definitions.get(sort.name)
            if definition is None or definition.spec.form != "compose" or len(definition.spec.tags) != 1:
                continue
            fields = next(iter(definition.spec.tags.values()))
            if not isinstance(fields, list) or len(fields) < 2 or len({part for _, part in fields}) != 1:
                continue
            field_sort = fields[0][1]
            operators = _lift_operators(state, field_sort)
            if len(operators) >= 3:
                variants = [tuple(operators[index:index + 3]) for index in range(min(3, len(operators) - 2))]
                variants.append(tuple(operators[-3:]))
                for family in dict.fromkeys(variants):
                    yield "Lift", [(sort.name, operator) for operator in family]
                    offered += 1
                    if offered >= 12:
                        return


@dataclass(frozen=True)
class TemplateMove:
    name: str
    kind: str

    def __call__(self, state, rng):
        if self.kind not in state.world.open_kinds:
            return
        if self.name == "tmpl.invent":
            if self.kind == "operation":
                _ensure_lift_record(state)
            if self.kind == "observation":
                _ensure_count_probes(state)
            attempted = getattr(state, "_template_families_attempted", set())
            families = [(pattern, family) for pattern, family in _families(state, self.kind)
                        if {"Quot": "object", "Interval": "object", "Lift": "operation",
                            "Count": "observation", "Iterate": "combinator"}[pattern] == self.kind
                        and not any(record.pattern == pattern for record in templates_for(state).values())
                        and (pattern, repr(family)) not in attempted]
            if families:
                pattern, family = rng.choice(families)
                attempted.add((pattern, repr(family)))
                state._template_families_attempted = attempted
                invent_template(state, pattern, family)
            return
        records = [record for record in templates_for(state).values() if record.kind == self.kind]
        if not records:
            return
        record = rng.choice(records)
        if record.pattern == "Quot":
            choices = [pair for pair in _canonicalizers(state) if pair not in record.family]
        elif record.pattern == "Interval":
            sort, operator, _, _ = record.family[0]
            values = _ordered(state, state.sorts[sort], operator)
            choices = [(sort, operator, values[index], values[index + 2])
                       for index in range(len(values) - 2) if
                       (sort, operator, values[index], values[index + 2]) not in record.family]
        elif record.pattern == "Iterate":
            choices = [(record.family[0][0], count) for count in (5,) if
                       (record.family[0][0], count) not in record.family]
        elif record.pattern == "Lift":
            sort = record.family[0][0]
            field_sort = state.signature(record.family[0][1]).inputs[0]
            choices = [(sort, name) for name in _lift_operators(state, field_sort)
                       if (sort, name) not in record.family]
        else:
            from opulse.gen_v2.moves.observation import _sources
            choices = [(item[0],) for item in _sources(state, earlier=True)
                       if _count_condition(state, item) is not None
                       and (item[0],) not in record.family]
        if choices:
            return template_candidate(state, record, rng.choice(choices))


MOVES = [TemplateMove(name, kind) for kind in ("object", "operation", "combinator", "observation")
         for name in ("tmpl.invent", "tmpl.instantiate")]
