"""Observation moves over granted probes and verified earlier observations."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from itertools import product
from math import gcd, isqrt, prod

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.library import VerifyRequest
from opulse.atoms.spec import Definition, ObservationSpec
from opulse.atoms.values import Ok
from opulse.gen_v2 import fast, vocab
from opulse.gen_v2.base import Candidate, Signature
from opulse.gen_v2.kinds.combinators import definition as make_definition
from opulse.gen_v2.kinds.observations import (
    _evaluate,
    _holds_truth_state,
    _is_truth,
    _probe_args,
    _read_arguments,
)
from opulse.gen_v2.kinds.observations import check as observation_check


def _varies(state, name, fixed=()):
    cache = getattr(state, "_observation_source_variation", None)
    if cache is None:
        cache = {}
        state._observation_source_variation = cache
    key = (name, repr(fixed))
    if key not in cache:
        scope = state.library.scope()
        states = state.world.truth_states
        indices = range(len(states)) if len(states) <= 32 else tuple(dict.fromkeys(
            (0, len(states) - 1, len(states) // 2, *(index * len(states) // 32 for index in range(32)))))
        seen = set()
        for index in indices:
            outcome = fast.call(name, (deepcopy(states[index]), *fixed), scope, state.world.fuel,
                                state.world.dialect).outcome
            if isinstance(outcome, Ok):
                seen.add(repr(outcome.value))
        cache[key] = len(seen) > 1
    return cache[key]


def _sources(state, output=None, earlier=False, include_memory=False):
    sources = [(name, state.signature(name).output, n.Var(name), (name,))
               for name in state.world.probes if state.signature(name) is not None and
               len(state.signature(name).inputs) == 1 and _varies(state, name)]
    for name in state.world.probes:
        signature = state.signature(name)
        if signature is None or len(signature.inputs) < 2:
            continue
        default = _probe_args(state, name, state.library.scope())
        if _varies(state, name, default):
            sources.append((name, signature.output, n.Var(name), (name,)))
        resolved = state.library.resolve(name)
        if resolved is None or not hasattr(resolved, "spec") or any(
                edge.sort == "unknown" for edge in resolved.spec.inputs[1:]):
            continue
        if any(sort not in state.sorts for sort in signature.inputs[1:]):
            continue
        domains = [tuple({repr(value): value for value in (
            *state.sorts[sort].values[:8],
            *state.sorts[sort].values[8::max(1, len(state.sorts[sort].values) // 8)],
            *state.sorts[sort].values[-1:])}.values())
                   for sort in signature.inputs[1:]]
        total = prod(map(len, domains))
        if total > 32:
            stride = isqrt(total) + 1
            while gcd(stride, total) != 1:
                stride += 1
            combinations = []
            for index in range(32):
                position = index * stride % total
                fixed = []
                for domain in reversed(domains):
                    position, offset = divmod(position, len(domain))
                    fixed.append(domain[offset])
                combinations.append(tuple(reversed(fixed)))
        else:
            combinations = product(*domains)
        for fixed in combinations:
            if not _varies(state, name, fixed):
                continue
            body = n.Call(name, (n.Var("__truth"), *(n.Lit(value) for value in fixed)))
            sources.append((name, signature.output, body, (name,)))
    if earlier:
        for entry in state.entries.values():
            if entry.kind != "observation" or entry.meta.get("memory") and not include_memory:
                continue
            sources.append((entry.name, entry.signature.output, n.Call(entry.name),
                            tuple(state.library.get(entry.name).spec.reads)))
    return [item for item in sources if output is None or item[1] == output]


def _usable(state, signature):
    return (signature is not None and 0 < len(signature.inputs) <= 4 and
            not any(sort not in state.sorts for sort in signature.inputs) and
            (state.world.truth_sort not in signature.inputs and
             signature.output != state.world.truth_sort or
             state.world.truth_sort in {state.signature(probe).output for probe in state.world.probes}))


def _literal_sources(state, sources):
    return sources + [("", sort.name, n.Lit(value), ())
                      for sort in state.sorts.values() if sort.name != state.world.truth_sort
                      for value in sort.values[:3 if sort.name in ("int", "bool") else 8]
                      if not _is_truth(value, state.world.truth_sort) and
                      not _holds_truth_state(value, state.world.truth_states)]


def _derived_sources(state, rng, sources):
    available = {source[1] for source in sources if source[3]}
    derived = []
    literals = _literal_sources(state, [])
    act_names = {op.name for op in state.world.decl.operations if op.role == "act"}
    names = sorted(state.callables("operation"))
    rng.shuffle(names)
    given = [name for name in names if name not in state.entries]
    invented = [name for name in names if name in state.entries]
    invented.sort(key=state.layer, reverse=True)
    names = given + invented
    given_limit = 16
    invented_limit = 12
    given_count = invented_count = 0
    for name in names:
        if name in state.entries and invented_count >= invented_limit:
            continue
        if name not in state.entries and given_count >= given_limit:
            continue
        signature = state.signature(name)
        if (name in state.world.probes or name in act_names or not _usable(state, signature) or
                not 1 <= len(signature.inputs) <= 2 or
                not any(sort in available for sort in signature.inputs)):
            continue
        options = [sources if sort in available else literals for sort in signature.inputs]
        if any(not any(source[1] == sort for source in group)
               for sort, group in zip(signature.inputs, options)):
            continue
        arguments = [rng.choice([source for source in group if source[1] == sort])
                     for sort, group in zip(signature.inputs, options)]
        if not any(source[3] for source in arguments):
            continue
        derived.append((name, signature.output,
                        n.Call(name, tuple(source[2] for source in arguments)),
                        tuple(read for source in arguments for read in source[3])))
        if name in state.entries:
            invented_count += 1
        else:
            given_count += 1
        if given_count >= given_limit and invented_count >= invented_limit:
            break
    return sources + derived


def _choose_source(state, rng, sources, sort):
    choices = [source for source in sources if source[1] == sort]
    deep = [source for source in choices if source[0] in state.entries]
    if deep and rng.random() < 0.65:
        highest = max(state.layer(source[0]) for source in deep)
        choices = [source for source in deep if state.layer(source[0]) >= highest - 3]
    return rng.choice(choices)


def _source_partition(state, source):
    cache = getattr(state, "_observation_partitions", None)
    if cache is None:
        cache = {}
        state._observation_partitions = cache
    key = (repr(source[2]), source[3])
    if key not in cache:
        name = "__observation_sample"
        spec = ObservationSpec(name, tuple(sorted(set(source[3]))), source[2], None)
        defn = Definition(name, "observation", "invented", 1, (), spec, source[2])
        scope = state.library.scope()
        arguments = _read_arguments(state, defn, scope)
        states = state.world.truth_states
        indices = range(len(states)) if len(states) <= 32 else tuple(
            dict.fromkeys((0, len(states) - 1, *(index * len(states) // 32 for index in range(32)))))
        cache[key] = tuple(repr(outcome.value) if isinstance(outcome, Ok) else None
                           for index in indices
                           for outcome, _ in (_evaluate(state, defn, (deepcopy(states[index]),),
                                                        scope, arguments=arguments),))
    return cache[key]


def _operations(state, sources, *, output=None):
    available = {source[1] for source in sources}
    actual = {source[1] for source in sources if source[3]}
    roles = {op.name: op.role for op in state.world.decl.operations}
    names = sorted(state.callables("operation"))
    return [(name, state.signature(name)) for name in names
            if name not in state.world.probes and roles.get(name) != "act" and
            _usable(state, state.signature(name)) and
            any(sort in actual for sort in state.signature(name).inputs) and
            set(state.signature(name).inputs) <= available and
            (output is None or state.signature(name).output == output)]


def _apply(state, rng, sources, name, signature, move):
    arguments = [_choose_source(state, rng, sources, sort) for sort in signature.inputs]
    if not any(item[3] for item in arguments):
        position = rng.choice([index for index, sort in enumerate(signature.inputs)
                               if any(source[1] == sort and source[3] for source in sources)])
        arguments[position] = rng.choice([source for source in sources
                                          if source[1] == signature.inputs[position] and source[3]])
    return _candidate(state, move, n.Call(name, tuple(item[2] for item in arguments)),
                      tuple(read for item in arguments for read in item[3]), signature.output)


def _choose_operation(state, rng, operations):
    invented = [(name, signature) for name, signature in operations if name in state.entries]
    return rng.choice(invented if invented and rng.random() < 0.7 else operations)


def _bounded_combiners(state, sort):
    if sort != "int":
        return []
    cache = getattr(state, "_observation_combiners", None)
    if cache is not None:
        return cache
    values = state.sorts[sort].values
    sample = tuple(dict.fromkeys((values[0], values[len(values) // 2], values[-1])))
    bound = max(8, max(abs(value) for value in sample) * 2)
    candidates = []
    for name in sorted(vocab.combiners(state, sort)):
        if name in state.entries:
            continue
        if all(isinstance((result := fast.call(name, (left, right), state.library.scope(),
                                               state.world.fuel, state.world.dialect)).outcome, Ok) and
               type(result.outcome.value) is int and abs(result.outcome.value) <= bound
               for left in sample for right in sample):
            candidates.append(name)
    state._observation_combiners = candidates
    return candidates


def _candidate(state, move, body, reads, output, memory=None):
    name = state.names.fresh("observation")
    if memory and n.references(memory["step"]) - n.references(body):
        body = n.Case(((n.Always(), body),), memory["step"])
    spec = ObservationSpec(name, tuple(sorted(set(reads))), body, memory)
    defn = make_definition(state, "observation", name, spec, body,
                           include_literals=False, fold_layer=False)
    request = None
    if memory:
        states = state.world.truth_states
        indices = tuple(dict.fromkeys((0, len(states) // 2, len(states) // 16, len(states) - 1)))
        max_length = 3 if sum(len(indices) ** length for length in range(1, 4)) <= state.world.max_scope else 2
        histories = tuple(history for length in range(1, 4)
                          if length <= max_length
                          for history in product(*(tuple(states[index] for index in indices),) * length))
        request = VerifyRequest("bounded", histories,
                                {"domain": (f"bounded: all histories of lengths 1..{max_length} over explicitly "
                                            f"enumerated truth state indices {indices} (restricted to these states)"),
                                 "size": len(histories), "history_length": max_length,
                                 "history_state_indices": indices})
    observed_sort = state.world.truth_sort or state.signature(state.world.probes[0]).inputs[0]
    if request is None and observed_sort == "Any":
        truths = state.world.truth_states[:state.world.max_scope]
        request = VerifyRequest("bounded", tuple((truth,) for truth in truths),
                                {"domain": "bounded: explicitly enumerated observation truth states",
                                 "size": len(truths)})
    return Candidate(defn, Signature((observed_sort,), output), move,
                     request=request, meta={"memory": bool(memory)})


def _promising_memory(state, candidate):
    histories = candidate.request.domain
    selected = (histories[0], histories[len(histories) // 4],
                histories[len(histories) // 2], histories[-1])
    try:
        return any(isinstance(_evaluate(state, candidate.defn, deepcopy(history),
                                        state.library.scope())[0], Ok) for history in selected)
    except (ValueError, TypeError, KeyError, RecursionError, IndexError, AttributeError):
        return False


@dataclass(frozen=True)
class _Move:
    name: str
    kind: str = "observation"

    @property
    def builds_on_top(self):
        return self.name in ("obs.compose", "obs.via_ops", "obs.threshold")

    def __call__(self, state, rng):
        if not state.world.probes or not state.world.truth_states:
            return None
        builders = {"obs.derive": _derive, "obs.compose": _compose,
                    "obs.memory": _memory, "obs.via_ops": _via_ops,
                    "obs.threshold": _threshold}
        for _ in range(10):
            candidate = builders[self.name](state, rng)
            if candidate is None:
                continue
            if (n.node_kinds(candidate.defn.body) <= state.world.decl.opened_nodes() and
                    not observation_check(candidate.defn, state.library) and
                    (not candidate.defn.spec.memory or _promising_memory(state, candidate))):
                return candidate
        return None


def _record_sources(state, sources, rng):
    available = {sort for _, sort, _, _ in sources}
    records = []
    for sort in state.sorts.values():
        if sort.origin != "invented" or sort.sealed:
            continue
        for constructor in sort.constructors:
            signature = state.signature(constructor)
            if (not _usable(state, signature) or
                    not set(signature.inputs) <= available):
                continue
            arguments = [_choose_source(state, rng, sources, field)
                         for field in signature.inputs]
            records.append((constructor, sort.name,
                            n.Call(constructor, tuple(arg[2] for arg in arguments)),
                            tuple(read for arg in arguments for read in arg[3])))
    return records


def _via_ops(state, rng, sources=None, move="obs.via_ops", primitive=False):
    sources = sources if sources is not None else _sources(state, earlier=True)
    if not sources:
        return None
    sources = _literal_sources(state, _derived_sources(state, rng, sources))
    sources = sources + _record_sources(state, sources, rng)
    choices = [("operation", name, signature) for name, signature in _operations(state, sources)
               if not primitive or signature.output in ("int", "bool")]
    for entry in state.entries.values():
        if entry.kind != "combinator" or entry.signature is None:
            continue
        signature = entry.signature
        if (len(signature.op_inputs) == 1 and len(signature.inputs) <= 2 and
                (not primitive or signature.output in ("int", "bool")) and
                set(signature.inputs) <= {source[1] for source in sources} and
                any(name not in state.world.probes and state.signature(name) == signature.op_inputs[0]
                    for name in sorted(state.callables("operation")))):
            choices.append(("combinator", entry.name, signature))
    for sort in state.sorts.values():
        if sort.origin != "invented" or sort.sealed:
            continue
        for constructor in sort.constructors:
            signature = state.signature(constructor)
            if (signature and signature.inputs and
                    set(signature.inputs) <= {source[1] for source in sources} and
                    (not primitive or any(state.signature(accessor) and
                                          state.signature(accessor).output in ("int", "bool")
                                          for accessor in sort.accessors))):
                choices.append(("object", constructor, signature))
    if not choices:
        return None
    objects = [choice for choice in choices if choice[0] == "object"]
    cross = [choice for choice in choices if choice[1] in state.entries or
             choice[0] == "object"]
    chosen = objects if objects and not primitive and rng.random() < 0.3 else (
        cross if cross and rng.random() < 0.8 else choices)
    if rng.random() < 0.55:
        best = max(state.layer(name) if name in state.entries else 0 for _, name, _ in chosen)
        chosen = [choice for choice in chosen
                  if (state.layer(choice[1]) if choice[1] in state.entries else 0) >= best - 3]
    kind, name, signature = rng.choice(chosen)
    arguments = [_choose_source(state, rng, sources, sort) for sort in signature.inputs]
    if not any(source[3] for source in arguments):
        positions = [index for index, sort in enumerate(signature.inputs)
                     if any(source[1] == sort and source[3] for source in sources)]
        if not positions:
            return None
        position = rng.choice(positions)
        arguments[position] = rng.choice([source for source in sources
                                          if source[1] == signature.inputs[position] and source[3]])
    reads = tuple(probe for source in arguments for probe in source[3])
    values = tuple(source[2] for source in arguments)
    if kind == "combinator":
        operations = [name for name in sorted(state.callables("operation"))
                      if name not in state.world.probes and state.signature(name) == signature.op_inputs[0]]
        operation = rng.choice(operations)
        values = (n.Lit(kernel.FnRef(operation)), *values)
    body = n.Call(name, values)
    if kind == "object" and (primitive or rng.random() < 0.5):
        accessors = [accessor for accessor in state.sorts[signature.output].accessors
                     if state.signature(accessor) is not None and
                     (not primitive or state.signature(accessor).output in ("int", "bool"))]
        if accessors:
            accessor = rng.choice(accessors)
            body = n.Call(accessor, (body,))
            signature = state.signature(accessor)
    return _candidate(state, move, body, reads, signature.output)


def _project(state, rng, move, earlier=False):
    sources = _sources(state, earlier=earlier)
    if not sources:
        return None
    roles = {op.name: op.role for op in state.world.decl.operations}
    options = [(source, name, signature) for source in sources
               for name in sorted(state.callables("operation"))
               if (signature := state.signature(name)) is not None and
               name not in state.world.probes and roles.get(name) != "act" and
               2 <= len(signature.inputs) <= 3 and signature.inputs[0] == source[1] and
               signature.output != state.world.truth_sort and
               all(sort in state.sorts and state.sorts[sort].values
                   for sort in signature.inputs[1:])]
    if earlier:
        previous = [option for option in options if option[0][0] in state.entries]
        if previous and rng.random() < 0.9:
            recursive = [option for option in previous if option[2].output == option[0][1]]
            options = recursive if recursive and rng.random() < 0.9 else previous
            highest = max(state.layer(option[0][0]) for option in options)
            options = [option for option in options
                       if state.layer(option[0][0]) >= highest - 1]
    if not options:
        return None

    def used_literals(expression):
        seen = set()
        pending = [expression]
        visited = set()
        while pending:
            for part in n.walk(pending.pop()):
                if isinstance(part, n.Lit) and isinstance(part.value, str):
                    seen.add(part.value)
                if (isinstance(part, n.Call) and part.fn in state.entries and
                        state.entries[part.fn].kind == "observation" and part.fn not in visited):
                    visited.add(part.fn)
                    pending.append(state.library.get(part.fn).body)
        return seen

    for _ in range(8):
        source, name, signature = rng.choice(options)
        fixed = []
        for index, sort in enumerate(signature.inputs[1:]):
            values = state.sorts[sort].values
            if index == 0 and signature.output == source[1]:
                used = used_literals(source[2])
                unused = [value for value in values if isinstance(value, str) and value not in used]
                if unused:
                    values = unused
            fixed.append(n.Lit(rng.choice(values)))
        expression = n.Call(name, (source[2], *fixed))
        result = (name, signature.output, expression, source[3])
        if len(set(_source_partition(state, result))) > 1:
            return _candidate(state, move, expression, source[3], signature.output)
    return None


def _derive(state, rng):
    if state.world.truth_sort == "Any" and rng.random() < 0.2:
        fixed = [source for source in _sources(state)
                 if isinstance(source[2], n.Call) and source[0] in state.world.probes]
        if fixed:
            source = rng.choice(fixed)
            return _candidate(state, "obs.derive", source[2], source[3], source[1])
    if state.world.truth_sort == "Any" and rng.random() < 0.7:
        projected = _project(state, rng, "obs.derive")
        if projected is not None:
            return projected
    sources = _sources(state, earlier=rng.random() < 0.4)
    if not sources:
        return None
    if rng.random() < 0.6:
        cross = _via_ops(state, rng, sources, "obs.derive")
        if cross is not None:
            return cross
    sources = _literal_sources(state, sources)
    operations = _operations(state, sources)
    if operations and rng.random() < 0.8:
        name, signature = _choose_operation(state, rng, operations)
        return _apply(state, rng, sources, name, signature, "obs.derive")
    bools = [source for source in sources if source[1] == "bool"]
    if bools:
        first, second = rng.choice(bools), rng.choice(bools)
        condition = rng.choice((n.And(n.Test(first[2]), n.Test(second[2])),
                                n.Or(n.Test(first[2]), n.Test(second[2])),
                                n.Not(n.Test(first[2]))))
        return _candidate(state, "obs.derive", n.Case(((condition, n.Lit(True)),), n.Lit(False)),
                          first[3] + second[3], "bool")
    return None


def _compose(state, rng):
    if state.world.truth_sort == "Any" and rng.random() < 0.7:
        projected = _project(state, rng, "obs.compose", earlier=True)
        if projected is not None:
            return projected
    sources = _sources(state, earlier=True)
    previous = [source for source in sources if source[0] in state.entries]
    if not previous:
        return None
    if rng.random() < 0.3:
        combined = _join(state, rng)
        if combined is not None:
            return combined
    if rng.random() < 0.2:
        cross = _via_ops(state, rng, sources, "obs.compose")
        if cross is not None and any(ref in state.entries and state.entries[ref].kind == "observation"
                                     for ref in cross.defn.depends_on):
            return cross
    deep = sorted(previous, key=lambda source: state.layer(source[0]), reverse=True)
    first = rng.choice(deep[:max(1, len(deep) // 10)] if rng.random() < 0.9 else previous)
    sources = _literal_sources(state, sources)
    operations = [(name, signature) for name, signature in _operations(state, sources)
                  if first[1] in signature.inputs]
    if operations:
        name, signature = _choose_operation(state, rng, operations)
        arguments = [first if sort == first[1] and (index == 0 or first[1] not in signature.inputs[:index])
                     else _choose_source(state, rng, sources, sort)
                     for index, sort in enumerate(signature.inputs)]
        return _candidate(state, "obs.compose", n.Call(name, tuple(item[2] for item in arguments)),
                          tuple(read for item in arguments for read in item[3]), signature.output)
    if first[1] == "bool":
        others = [source for source in sources if source[1] == "bool"]
        second = rng.choice(others)
        condition = n.Or(n.Test(first[2]), n.Test(second[2]))
        return _candidate(state, "obs.compose", n.Case(((condition, n.Lit(True)),), n.Lit(False)),
                          first[3] + second[3], "bool")
    return None


def _join(state, rng):
    sources = [source for source in _sources(state, earlier=True)
               if source[3] and source[1] != state.world.truth_sort]
    if len(sources) < 2:
        return None
    deep = [source for source in sources if source[0] in state.entries]
    if not deep:
        return None
    first = rng.choice(sorted(deep, key=lambda source: state.layer(source[0]), reverse=True)
                       [:max(1, len(deep) // 5)])
    first_values = _source_partition(state, first)
    if len(set(first_values)) <= 1 or len(set(first_values)) == len(first_values):
        return None
    rng.shuffle(sources)
    for second in sources[:20]:
        if second[2] == first[2] or second[1] != first[1]:
            continue
        second_values = _source_partition(state, second)
        if len(set(second_values)) == len(second_values):
            continue
        if len(set(zip(first_values, second_values))) <= max(
                len(set(first_values)), len(set(second_values))):
            continue
        if first[1] == "bool":
            if "int" in state.sorts:
                body = n.Case(((n.Test(first[2]), n.Case(
                    ((n.Test(second[2]), n.Lit(3)),), n.Lit(2))),
                    (n.Test(second[2]), n.Lit(1))), n.Lit(0))
                output = "int"
            else:
                condition = rng.choice((n.And(n.Test(first[2]), n.Test(second[2])),
                                        n.Or(n.Test(first[2]), n.Test(second[2]))))
                body = n.Case(((condition, n.Lit(True)),), n.Lit(False))
                output = "bool"
        elif first[1] == "int":
            operators = sorted(vocab.combiners(state, "int"))
            if not operators:
                continue
            body = n.Call(rng.choice(operators), (first[2], second[2]))
            output = "int"
        else:
            available = _literal_sources(state, sources)
            operations = [(name, signature) for name, signature in _operations(state, available)
                          if signature.inputs.count(first[1]) >= 2]
            if not operations:
                continue
            name, signature = _choose_operation(state, rng, operations)
            arguments = []
            for sort in signature.inputs:
                if sort == first[1] and first not in arguments:
                    arguments.append(first)
                elif sort == first[1] and second not in arguments:
                    arguments.append(second)
                else:
                    arguments.append(_choose_source(state, rng, available, sort))
            body = n.Call(name, tuple(source[2] for source in arguments))
            output = signature.output
        reads = (tuple(read for source in arguments for read in source[3])
                 if first[1] not in ("bool", "int") else first[3] + second[3])
        return _candidate(state, "obs.compose", body, reads, output)
    return None


def _threshold(state, rng):
    sources = _sources(state, earlier=True)
    if rng.random() < 0.7:
        derived = [source for source in _derived_sources(state, rng, sources)[len(sources):]
                   if source[1] == "int" and source[3]]
        if derived:
            sources = derived
    sources = [source for source in sources if source[1] != state.world.truth_sort and
               state.sorts.get(source[1]) and
               state.sorts[source[1]].values and
               (vocab.less(state, source[1]) or vocab.equal(state, source[1]))]
    if not sources:
        return None
    source = rng.choice(sources)
    values = state.sorts[source[1]].values
    if source[1] == "int" and rng.random() < 0.8:
        observed = sorted({int(value) for value in _source_partition(state, source)
                           if value is not None and value.lstrip("-").isdigit()})
        if observed:
            values = tuple(dict.fromkeys((*observed, *(value + 1 for value in observed))))
    value = rng.choice(values)
    operator = rng.choice(sorted(vocab.less(state, source[1]) + vocab.equal(state, source[1])))
    body = n.Call(operator, (source[2], n.Lit(value)))
    return _candidate(state, "obs.threshold", body, source[3], "bool")


def _memory(state, rng):
    sources = [source for source in _sources(state, earlier=True, include_memory=True)
               if source[1] != state.world.truth_sort and
               state.sorts.get(source[1]) and
               state.sorts[source[1]].values]
    if not sources or rng.random() < 0.7:
        derived = _via_ops(state, rng, primitive=True)
        if (derived and derived.signature.output in state.sorts and
                derived.signature.output != state.world.truth_sort and
                (not sources or any(ref in state.entries and state.entries[ref].kind != "observation"
                                    or "." in ref for ref in derived.defn.depends_on))):
            sources = [(derived.defn.name, derived.signature.output, derived.defn.body,
                        derived.defn.spec.reads)]
    if not sources:
        return None
    previous = [source for source in sources if source[0] in state.entries]
    if previous and rng.random() < 0.7:
        deep = sorted(previous, key=lambda item: state.layer(item[0]), reverse=True)
        source = rng.choice(deep[:max(1, len(deep) // 8)])
    else:
        source = rng.choice(sources)
    value = source[2]
    if source[1] == "bool":
        counters = [name for name in sorted(vocab.steps(state, "int"))
                    if name not in state.entries and state.signature(name) and
                    state.signature(name).inputs == ("int",)
                    and state.signature(name).output == "int" and
                    isinstance((sample := fast.call(name, (0,), state.library.scope(),
                                                    state.world.fuel, state.world.dialect)).outcome, Ok)
                    and sample.outcome.value != 0] if "int" in state.sorts else []
        if counters and 0 in state.sorts["int"].values and rng.random() < 0.65:
            increment = n.Call(rng.choice(counters), (n.Var("memory"),))
            if rng.random() < 0.3:
                increment = n.Call(rng.choice(counters), (increment,))
            condition = n.Test(value) if rng.random() < 0.5 else n.Not(n.Test(value))
            step = n.Case(((condition, increment),), n.Var("memory"))
            init = n.Lit(0)
            output = "int"
        else:
            condition = rng.choice((n.Or(n.Test(n.Var("memory")), n.Test(value)),
                                    n.And(n.Test(n.Var("memory")), n.Test(value)),
                                    n.And(n.Test(n.Var("memory")), n.Not(n.Test(value)))))
            step = n.Case(((condition, n.Lit(True)),), n.Lit(False))
            init = n.Lit(False)
            output = "bool"
    else:
        values = state.sorts[source[1]].values
        init = n.Lit(0 if source[1] == "int" and 0 in values else values[0])
        deciders = sorted(vocab.deciders(state, source[1]))
        combiners = _bounded_combiners(state, source[1])
        if combiners and rng.random() < 0.65:
            step = n.Call(rng.choice(combiners), (n.Var("memory"), value))
        elif deciders:
            decider = rng.choice(deciders)
            step = n.Case(((n.Test(n.Call(decider, (value,))), value),), n.Var("memory"))
        else:
            step = value
        output = source[1]
    return _candidate(state, "obs.memory", n.Let("observed", value, step),
                      source[3], output,
                      {"init": init, "step": step})


MOVES = [_Move(name) for name in ("obs.derive", "obs.compose", "obs.memory", "obs.threshold",
                                "obs.via_ops")]
