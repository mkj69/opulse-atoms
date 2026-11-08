"""Finite-scope proposals for translations between generator object sorts.

Generator-side records are proposals; admitted bridges use core BridgeSpec and
verification. No claim is made outside the recorded source domain.
"""

from __future__ import annotations

import itertools
import json
from dataclasses import dataclass, replace

from opulse.atoms import kernel, nodes
from opulse.atoms.values import Bottom, Ok, Unknown, value_equal
from opulse.gen_v2 import fast
from opulse.gen_v2.codec import encode_value


class BridgeRefuted(ValueError):
    """A bridge has an ill-typed map, a counterexample, or no checked interface."""


class BridgeUnknown(ValueError):
    """A bridge cannot be verified within the world fuel limit."""


@dataclass(frozen=True)
class BridgeRecord:
    name: str
    source: tuple[str, str]
    target: tuple[str, str]
    map: nodes.Node
    domain: tuple[object, ...]
    interface: tuple[tuple[str, str], ...]
    evidence: dict
    layer: int
    depends_on: tuple[str, ...]
    forget_failure_reasons: bool = False
    abstraction: object | None = None
    kind: str = "bridge"

    @property
    def closed(self) -> bool:
        return self.evidence.get("closed", False)

    def notation(self) -> str:
        flags = "  forget_failure_reasons" if self.forget_failure_reasons else ""
        return f"bridge ~{self.name}: {self.source[1]} -> {self.target[1]}  L{self.layer}{flags}"

    def application(self, argument: str = "x") -> str:
        return f"~{self.name}({argument})"


def _same_value(left, right):
    def comparable(value):
        if type(value) in (bool, int, str):
            return True
        if isinstance(value, (tuple, list)):
            return all(comparable(item) for item in value)
        from opulse.atoms.values import Card
        if isinstance(value, Card):
            return all(comparable(item) for item in value.fields)
        return type(value).__eq__ is not object.__eq__

    if not comparable(left) or not comparable(right):
        raise BridgeRefuted("no sound value comparator; declare an abstraction")
    return value_equal(left, right)


def _probe_matches(left, right):
    try:
        return _same_value(left, right)
    except BridgeRefuted:
        return False


def _source_scope(state_a, state_b, mapping):
    scope = state_a.library.scope()
    if state_b is state_a:
        return scope
    target_scope = state_b.library.scope()
    combined = kernel.DictScope(scope.atoms, scope.defns)
    for name in nodes.references(mapping):
        if scope.resolve(name) is None:
            atom = target_scope.resolve(name)
            if atom is None:
                raise BridgeRefuted(f"unknown mapping operation: {name}")
            if isinstance(atom, kernel.Atom):
                combined.atoms[name] = atom
            else:
                if any(scope.resolve(dep) is not None for dep in nodes.references(atom.body)):
                    raise BridgeRefuted(f"ambiguous target constructor: {name}")
                combined.defns[name] = atom
    return combined


def _run(node, env, state, scope):
    try:
        result = fast.evaluate(node, env, scope, state.world.fuel, state.world.dialect).outcome
    except (TypeError, ValueError, KeyError, IndexError, AttributeError) as error:
        raise BridgeRefuted(f"host rejects the values: {type(error).__name__}: {error}") from error
    if isinstance(result, Unknown):
        raise BridgeUnknown(f"resource exhausted: {result.resource}")
    return result


def _translate(value, bridge, state_a, scope):
    outcome = _run(bridge.map, {"x": value}, state_a, scope)
    if not isinstance(outcome, Ok):
        raise BridgeRefuted(f"map undefined on declared domain: {value!r}")
    return outcome.value


def _metadata(bridge, state_a, state_b):
    source_sort = state_a.sorts[bridge.source[1]]
    target_sort = state_b.sorts[bridge.target[1]]
    dependencies = set(nodes.references(bridge.map))
    owners = ((source_sort.defined_by, state_a), (target_sort.defined_by, state_b))
    for owner, _ in owners:
        if owner is not None:
            dependencies.add(owner)
    source_ops = {source_op for source_op, _ in bridge.interface}
    target_ops = {target_op for _, target_op in bridge.interface}
    dependencies.update(source_ops)
    dependencies.update(target_ops)
    if any(state_a.signature(name) is None for name in source_ops):
        raise BridgeRefuted("unknown source interface operation")
    if any(state_b.signature(name) is None for name in target_ops):
        raise BridgeRefuted("unknown target interface operation")
    scope_a = state_a.library.scope()
    scope_b = state_b.library.scope()
    map_layers = []
    for name in nodes.references(bridge.map):
        if scope_a.resolve(name) is not None:
            map_layers.append(state_a.layer(name))
        elif scope_b.resolve(name) is not None:
            map_layers.append(state_b.layer(name))
        else:
            raise BridgeRefuted(f"unknown mapping operation: {name}")
    layers = (map_layers + [state.layer(owner) for owner, state in owners if owner is not None] +
              [state_a.layer(name) for name in source_ops] +
              [state_b.layer(name) for name in target_ops])
    return tuple(sorted(dependencies)), 1 + max(layers, default=0)


def check(bridge: BridgeRecord, state_a, state_b=None) -> dict:
    """Verify the entire declared domain; raise on the first counterexample or Unknown.

    The commuting claim covers only declared domain input tuples whose source
    output remains in the domain. A composed use must re-check membership unless
    closed is true. Failure reasons agree unless explicitly forgotten by the record.
    """
    state_b = state_a if state_b is None else state_b
    if bridge.abstraction is not None:
        raise BridgeRefuted("unchecked bridge abstraction")
    if bridge.source[0] != state_a.world.name or bridge.target[0] != state_b.world.name:
        raise BridgeRefuted("world mismatch")
    if not bridge.domain or not bridge.interface:
        raise BridgeRefuted("empty domain or interface")
    if any(not any(_same_value(value, probe) for probe in state_a.sorts[bridge.source[1]].values)
           for value in bridge.domain):
        raise BridgeRefuted("domain is not a subset of the source probes")
    dependencies, layer = _metadata(bridge, state_a, state_b)
    if bridge.depends_on != dependencies:
        raise BridgeRefuted("bridge dependencies do not match its map and interface")
    if bridge.layer != layer:
        raise BridgeRefuted("bridge layer does not match its dependencies")
    if state_a.sorts[bridge.source[1]].sealed and any(
            name not in state_a.sorts[bridge.source[1]].interface
            for name in nodes.references(bridge.map)):
        raise BridgeRefuted("map reads a sealed representation")
    scope_a = state_a.library.scope()
    scope_b = state_b.library.scope()
    scope_map = _source_scope(state_a, state_b, bridge.map)
    translated = []
    target_probes = state_b.sorts[bridge.target[1]].values
    for value in bridge.domain:
        mapped = _translate(value, bridge, state_a, scope_map)
        if not any(_same_value(mapped, probe) for probe in target_probes):
            raise BridgeRefuted(f"map result outside target probes: {mapped!r}")
        translated.append(mapped)

    checks = 0
    closed = True
    for source_op, target_op in bridge.interface:
        source_sig, target_sig = state_a.signature(source_op), state_b.signature(target_op)
        translates_output = (source_sig is not None and target_sig is not None and
                             source_sig.output == bridge.source[1] and
                             target_sig.output == bridge.target[1])
        if (source_sig is None or target_sig is None or
                not 1 <= len(source_sig.inputs) <= 2 or
                source_sig.inputs != (bridge.source[1],) * len(source_sig.inputs) or
                target_sig.inputs != (bridge.target[1],) * len(source_sig.inputs) or
                not translates_output and source_sig.output != target_sig.output):
            raise BridgeRefuted(f"incompatible interface pair: {source_op}, {target_op}")
        successes = 0
        for indexes in itertools.product(range(len(bridge.domain)), repeat=len(source_sig.inputs)):
            source_args = tuple(bridge.domain[index] for index in indexes)
            target_args = tuple(translated[index] for index in indexes)
            source_out = _run(nodes.Call(source_op, tuple(nodes.Lit(arg) for arg in source_args)),
                              {}, state_a, scope_a)
            target_out = _run(nodes.Call(target_op, tuple(nodes.Lit(arg) for arg in target_args)),
                              {}, state_b, scope_b)
            if isinstance(source_out, Bottom) or isinstance(target_out, Bottom):
                if not isinstance(source_out, Bottom) or not isinstance(target_out, Bottom):
                    raise BridgeRefuted(f"counterexample {source_op}/{target_op}: {source_args!r}")
                if not bridge.forget_failure_reasons and source_out.reason != target_out.reason:
                    raise BridgeRefuted(f"failure reason mismatch {source_op}/{target_op}: {source_args!r}")
            elif translates_output:
                if not isinstance(source_out, Ok) or not isinstance(target_out, Ok):
                    raise BridgeRefuted(f"counterexample {source_op}/{target_op}: {source_args!r}")
                if not any(_same_value(source_out.value, value) for value in bridge.domain):
                    closed = False
                    continue
                mapped_out = _run(bridge.map, {"x": source_out.value}, state_a, scope_map)
                if not isinstance(mapped_out, Ok) or not _same_value(mapped_out.value, target_out.value):
                    raise BridgeRefuted(f"counterexample {source_op}/{target_op}: {source_args!r}")
                successes += 1
            elif not isinstance(source_out, Ok) or not isinstance(target_out, Ok) or not _same_value(
                    source_out.value, target_out.value):
                raise BridgeRefuted(f"counterexample {source_op}/{target_op}: {source_args!r}")
            else:
                successes += 1
            checks += 1
        if successes == 0:
            raise BridgeRefuted(f"no checked pairs for {source_op}/{target_op}")
    return {"method": "bounded", "scope": {
        "domain": [encode_value(value) for value in bridge.domain],
        "size": len(bridge.domain), "checks": checks}, "seed": bridge.evidence.get("seed"),
            "closed": closed, "forget_failure_reasons": bridge.forget_failure_reasons,
            "abstraction": None}


def _mappings(state_a, state_b, source, target):
    source_sort = state_a.sorts[source]
    target_sort = state_b.sorts[target]
    mappings = []
    if source == target or any(
            _probe_matches(value, other)
            for value in source_sort.values for other in target_sort.values):
        mappings.append(nodes.Var("x"))
    if source_sort.origin == "invented" and (state_a is state_b or source != target):
        for accessor in sorted(source_sort.accessors):
            if state_a.signature(accessor) and state_a.signature(accessor).output == target:
                mappings.append(nodes.Call(accessor, (nodes.Var("x"),)))
    if state_a is state_b:
        for name in state_a.callables(inputs=(source,), output=target):
            if source_sort.sealed and name not in source_sort.interface:
                continue
            mappings.append(nodes.Call(name, (nodes.Var("x"),)))
    for constructor in sorted(target_sort.constructors):
        sig = state_b.signature(constructor)
        if sig is None or not sig.inputs or len(sig.inputs) > 3:
            continue
        spec = (state_b.library.get(target_sort.defined_by).spec
                if target_sort.defined_by else None)
        members = spec.tags.get(constructor.removeprefix(target + ".")) if spec and spec.tags else None
        field_names = ([field for field, _ in members]
                       if isinstance(members, list) else [])
        accessors = []
        for index, input_sort in enumerate(sig.inputs):
            options = [name for name in sorted(source_sort.accessors)
                       if (state_a.signature(name) is not None and
                           state_a.signature(name).output == input_sort and
                           (not source_sort.sealed or name in source_sort.interface))]
            if not options:
                break
            preferred = f"{source}.{field_names[index]}" if index < len(field_names) else ""
            accessors.append(preferred if preferred in options else options[0])
        if len(accessors) == len(sig.inputs):
            mappings.append(nodes.Call(constructor, tuple(nodes.Call(name, (nodes.Var("x"),))
                                                          for name in accessors)))
    return list(dict.fromkeys(mappings))


def _pairs(state_a, state_b, source, target):
    source_ops = [name for name in state_a.callables() if (sig := state_a.signature(name)) and
                  1 <= len(sig.inputs) <= 2 and sig.inputs == (source,) * len(sig.inputs) and
                  (not state_a.sorts[source].sealed or name in state_a.sorts[source].interface)]
    target_ops = [name for name in state_b.callables() if (sig := state_b.signature(name)) and
                  1 <= len(sig.inputs) <= 2 and sig.inputs == (target,) * len(sig.inputs)]
    for source_op in source_ops:
        source_sig = state_a.signature(source_op)
        for target_op in target_ops:
            target_sig = state_b.signature(target_op)
            if (len(source_sig.inputs) == len(target_sig.inputs) and
                    ((source_sig.output == source and target_sig.output == target) or
                     source_sig.output == target_sig.output)):
                yield source_op, target_op


def propose(state_a, state_b=None, max_bridges=50, seed=0) -> list[BridgeRecord]:
    """Find finite-scope bridges, ordered by commuting interface size.

    Source and target operation names are never assumed to have the same spelling.
    Each accepted pair is independently checked; only pairs that commute on the
    full chosen domain are included. The seed is recorded, not used for sampling.
    """
    if max_bridges < 0:
        raise ValueError("max_bridges must be nonnegative")
    if max_bridges == 0:
        return []
    state_b = state_a if state_b is None else state_b
    records = []
    for source in sorted(state_a.sorts):
        if state_a is state_b and state_a.sorts[source].origin != "invented":
            continue
        for target in sorted(state_b.sorts):
            if state_a is state_b and source == target:
                continue
            pairs = list(_pairs(state_a, state_b, source, target))
            if not pairs:
                continue
            for mapping in _mappings(state_a, state_b, source, target):
                map_dependencies = tuple(sorted(nodes.references(mapping)))
                if state_a is not state_b and any(
                        state_a.library.scope().resolve(dep) is not None and
                        state_b.library.scope().resolve(dep) is not None
                        for dep in map_dependencies):
                    continue
                domain = []
                provisional = BridgeRecord("", (state_a.world.name, source),
                                           (state_b.world.name, target), mapping, (), (),
                                           {"seed": seed}, 0, ())
                try:
                    scope = _source_scope(state_a, state_b, mapping)
                    for value in state_a.sorts[source].values[:16]:
                        result = _run(mapping, {"x": value}, state_a, scope)
                        if isinstance(result, Ok) and any(
                                _probe_matches(result.value, probe)
                                for probe in state_b.sorts[target].values):
                            domain.append(value)
                except (BridgeRefuted, BridgeUnknown, TypeError, ValueError, KeyError):
                    continue
                if len(domain) < 2:
                    continue
                for size in dict.fromkeys((len(domain), min(8, len(domain)),
                                           min(4, len(domain)), 2)):
                    trial_domain = replace(provisional, domain=tuple(domain[:size]))
                    accepted = []
                    for pair in pairs:
                        trial = replace(trial_domain, interface=(pair,))
                        dependencies, layer = _metadata(trial, state_a, state_b)
                        trial = replace(trial, depends_on=dependencies, layer=layer)
                        try:
                            check(trial, state_a, state_b)
                        except (BridgeRefuted, BridgeUnknown, TypeError, ValueError, KeyError):
                            continue
                        accepted.append(pair)
                    if accepted:
                        record = replace(trial_domain, interface=tuple(accepted))
                        dependencies, layer = _metadata(record, state_a, state_b)
                        record = replace(record, depends_on=dependencies, layer=layer)
                        records.append(replace(record, evidence=check(record, state_a, state_b)))
                        break
    records.sort(key=lambda record: (-len(record.interface), -len(record.domain),
                                     record.source, record.target, repr(record.map)))
    return [replace(record, name=f"b{index}") for index, record in
            enumerate(records[:max_bridges], start=1)]


def admit_proposed(state, max_bridges=50, seed=0, target_state=None):
    """Admit checked diagrams into the source catalogue, optionally attaching a target world."""
    from opulse.gen_v2.admit import admit
    from opulse.gen_v2.base import Entry
    from opulse.gen_v2.moves.bridge import candidate

    if "bridge" not in state.world.open_kinds:
        return []
    entries = []
    for bridge in propose(state, target_state, max_bridges=max_bridges, seed=seed):
        proposal = candidate(state, bridge, target_state)
        if proposal is not None:
            result = admit(state, proposal)
            if isinstance(result, Entry):
                entries.append(result)
    return entries


def to_json(bridges: list[BridgeRecord]) -> str:
    """Export the checked records as ASCII-only, versioned JSON text."""
    return json.dumps({"schema": "opulse.gen_v2.bridge/1", "bridges": [
        {"name": bridge.name, "source": list(bridge.source), "target": list(bridge.target),
         "map": nodes.to_json(bridge.map), "domain": [encode_value(value) for value in bridge.domain],
         "interface": [list(pair) for pair in bridge.interface], "evidence": bridge.evidence,
         "layer": bridge.layer, "depends_on": list(bridge.depends_on), "closed": bridge.closed,
         "forget_failure_reasons": bridge.forget_failure_reasons,
         "abstraction": None,
         "notation": bridge.notation()}
        for bridge in bridges]}, sort_keys=True, ensure_ascii=True)
