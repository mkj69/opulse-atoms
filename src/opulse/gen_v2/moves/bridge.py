"""Create record-backed bridge candidates from checked commuting diagrams."""

from dataclasses import dataclass

from opulse.atoms import kernel, nodes
from opulse.atoms.bridges import bridge_defn
from opulse.atoms.library import VerifyRequest
from opulse.atoms.spec import BridgeSpec, Definition
from opulse.atoms.values import Card, Ok, truth
from opulse.gen_v2 import bridges, vocab
from opulse.gen_v2.base import Candidate


def _domain_predicate(state, sort, domain):
    if tuple(domain) == tuple(state.sorts[sort].values):
        return None

    def condition(value, expression, value_sort):
        if isinstance(value, Card):
            fields = state.library.get(value.sort).spec.tags.get(value.tag) if value.sort in state.library.definitions else None
            if not isinstance(fields, list) or len(fields) != len(value.fields):
                return None
            tester = f"{value.sort}.is_{value.tag}"
            if state.library.scope().resolve(tester) is None:
                return None
            checks = [nodes.Test(nodes.Call(tester, (expression,)))]
            for (field, field_sort), member in zip(fields, value.fields):
                part = condition(member, nodes.Call(f"{value.sort}.{field}", (expression,)), field_sort)
                if part is None:
                    return None
                checks.append(part)
            result = checks[0]
            for part in checks[1:]:
                result = nodes.And(result, part)
            return result
        for equal in vocab.equal(state, value_sort):
            return nodes.Test(nodes.Call(equal, (expression, nodes.Lit(value))))
        if value_sort == "int":
            probes = tuple(dict.fromkeys((*state.sorts[value_sort].values, *range(-8, 9))))
            scope = state.library.scope()
            unary = state.callables("operation", inputs=(value_sort,), output=value_sort)
            binary = state.callables("operation", inputs=(value_sort, value_sort), output=value_sort)
            deciders = state.callables("operation", inputs=(value_sort,), output="bool")
            for transform in unary:
                transformed = bridges.fast.call(transform, (value,), scope, state.world.fuel,
                                                state.world.dialect).outcome
                if not isinstance(transformed, Ok):
                    continue
                for combine in binary:
                    outputs = [bridges.fast.call(combine, (probe, transformed.value), scope,
                                                 state.world.fuel, state.world.dialect).outcome
                               for probe in probes]
                    if not all(isinstance(output, Ok) for output in outputs):
                        continue
                    for decide in deciders:
                        outcomes = [bridges.fast.call(decide, (output.value,), scope,
                                                      state.world.fuel, state.world.dialect).outcome
                                    for output in outputs]
                        if all(isinstance(outcome, Ok) and truth(outcome.value) == (probe == value)
                               for probe, outcome in zip(probes, outcomes)):
                            return nodes.Test(nodes.Call(decide, (nodes.Call(combine, (
                                expression, nodes.Call(transform, (nodes.Lit(value),)))),)))
        outside = [probe for probe in state.sorts[value_sort].values if probe != value]
        checks = []
        for operation in state.callables("operation", inputs=(value_sort,), output="bool"):
            evaluated = [bridges.fast.call(operation, (probe,), state.library.scope(),
                                           state.world.fuel, state.world.dialect).outcome
                         for probe in (value, *outside)]
            if not all(isinstance(item, Ok) for item in evaluated):
                continue
            expected = truth(evaluated[0].value)
            eliminated = [probe for probe, item in zip(outside, evaluated[1:])
                          if truth(item.value) != expected]
            if eliminated:
                test = nodes.Test(nodes.Call(operation, (expression,)))
                checks.append(test if expected else nodes.Not(test))
                outside = [probe for probe in outside if probe not in eliminated]
            if not outside:
                result = checks[0]
                for part in checks[1:]:
                    result = nodes.And(result, part)
                return result
        return None

    arms = []
    for value in domain:
        test = condition(value, nodes.Var("x"), sort)
        if test is None:
            return False
        arms.append((test, nodes.Lit(True)))
    return nodes.Case(tuple(arms), nodes.Lit(False))


def candidate(state, bridge, target_state=None):
    target_state = state if target_state is None else target_state
    if bridge.source[0] != state.world.name or bridge.target[0] != target_state.world.name:
        return None
    if "Let" not in state.world.decl.opened_nodes():
        return None
    source = state.sorts[bridge.source[1]]
    if not bridge.domain or any(value not in source.values for value in bridge.domain):
        return None
    predicate = _domain_predicate(state, bridge.source[1], bridge.domain)
    if predicate is False:
        return None
    if any(not (state.library.scope().resolve(name) or target_state.library.scope().resolve(name))
           and name not in state.library._definitions and name not in target_state.library._definitions
           for name in bridge.depends_on):
        return None
    evidence = bridge.evidence
    if evidence.get("scope", {}).get("domain") != [bridges.encode_value(value)
                                                     for value in bridge.domain]:
        try:
            evidence = bridges.check(bridge, state, target_state)
        except (bridges.BridgeRefuted, bridges.BridgeUnknown, TypeError, ValueError, KeyError):
            return None
    cross_world = target_state is not state
    target_id = f"{target_state.world.decl.world}@{target_state.world.decl.version}"
    if cross_world:
        state.library.attach_world(target_id, target_state.library)
    dependencies = tuple(sorted(set(bridge.depends_on) | (nodes.references(predicate)
                                                         if predicate is not None else set())))
    name = state.names.fresh("bridge")
    mapping = bridge.map
    for index, dependency in enumerate(dependencies):
        if dependency not in nodes.references(mapping):
            mapping = nodes.Let(f"bridge_dependency_{index}", nodes.Lit(kernel.FnRef(dependency)), mapping)
    target_hashes = ({operation: target_state.library.content_hash(operation)
                      for _, operation in bridge.interface if operation in target_state.library.definitions}
                     if cross_world else {})
    spec = BridgeSpec(name, bridge.source[1],
                      f"{target_id}:{bridge.target[1]}" if cross_world else bridge.target[1],
                      mapping, predicate, bridge.interface,
                      {"checked_domain": [bridges.encode_value(value) for value in bridge.domain],
                       "closed": evidence["closed"],
                       **({"target_world_hash": target_state.world.decl.world_hash(),
                           "target_dependency_hashes": target_hashes} if cross_world else {})})
    body = bridge_defn(spec).body
    layer = 1 + max((state.layer(dependency) if state.library.scope().resolve(dependency)
                     else target_state.layer(dependency) for dependency in dependencies), default=0)
    definition = Definition(name, "bridge", "invented", layer, dependencies, spec, body)
    request = VerifyRequest("exhaustive" if source.finite and tuple(bridge.domain) == tuple(source.values)
                            else "bounded", tuple((value,) for value in bridge.domain),
                            {"domain": "all source values" if predicate is None and source.finite else "bounded source probe values",
                             "size": len(bridge.domain), "interface": [list(pair) for pair in bridge.interface]},
                            extra={"target_world": target_id} if cross_world else {})
    return Candidate(definition, None, "bridge.commute", request,
                     contract="The listed interface commutes on the recorded source domain.")


@dataclass
class BridgeMove:
    kind: str = "bridge"
    name: str = "bridge.commute"

    def __call__(self, state, rng):
        if not any(sort.origin == "invented" for sort in state.sorts.values()):
            return None
        proposals = bridges.propose(state, max_bridges=8, seed=rng.randrange(1 << 30))
        rng.shuffle(proposals)
        for bridge in proposals:
            if any(entry.kind == "bridge" and
                   (spec := state.library.get(entry.name).spec).source == bridge.source[1] and
                   spec.target == bridge.target[1] and spec.map == bridge.map and
                   spec.interface == bridge.interface and
                   tuple(args[0] for args in state.requests[entry.name].domain) == bridge.domain
                   for entry in state.entries.values()):
                continue
            result = candidate(state, bridge)
            if result is not None:
                return result
        return None


MOVES = [BridgeMove()]
