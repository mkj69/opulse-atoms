"""Generator-side template families and content-addressed instance provenance.

Core TemplateSpec cannot verify these dynamic generator patterns as a portable
family: their builders discover world-specific probes and operations. A checked
family remains a side record. Its digest is part of each instance's spec,
content hash and dependency hash, but the core boundary cannot open it as a
definition until the core supports these dynamic family builders.
"""

from __future__ import annotations

import copy
import hashlib
import itertools
import json
import weakref
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from itertools import product

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.library import VerifyRequest
from opulse.atoms.spec import (
    CombinatorSpec,
    Edge,
    ObjectSpec,
    OperationSpec,
    TemplateSpec,
    content_hash,
)
from opulse.atoms.values import Bottom, Card, Ok, truth, value_equal
from opulse.gen_v2 import fast, vocab
from opulse.gen_v2.admit import admit, domain_request
from opulse.gen_v2.base import Candidate, Entry, Rejection, Signature
from opulse.gen_v2.codec import decode_value, encode_value
from opulse.gen_v2.moves.combinator import _definition
from opulse.gen_v2.moves.object import _candidate as object_candidate
from opulse.gen_v2.moves.observation import _candidate as observation_candidate
from opulse.gen_v2.moves.observation import _sources


def _encode_argument(value):
    return encode_value(value) if isinstance(value, (Card, kernel.FnRef)) else value


def _decode_argument(value):
    return decode_value(value) if isinstance(value, dict) and "t" in value else value


@dataclass
class TemplateRecord:
    name: str
    pattern: str
    kind: str
    parameters: tuple[str, ...]
    value_parameters: tuple[str, ...]
    body: Callable
    family: tuple[tuple, ...]
    evidence: dict
    instances: list[str] = field(default_factory=list)

    def core_spec(self) -> TemplateSpec:
        """The core's portable family schema; evidence stays on the checked family."""
        parameters = tuple(tuple(parameter.split(":", 1)) for parameter in
                           (*self.parameters, *self.value_parameters))
        return TemplateSpec(self.name, parameters, self.kind,
                            {"pattern": self.pattern, "produces": self.kind,
                             "family": [[_encode_argument(value) for value in arguments]
                                        for arguments in self.family]})

    def to_dict(self):
        """Immutable, JSON-safe identity of this checked template."""
        return {"name": self.name, "pattern": self.pattern, "kind": self.kind,
                "parameters": list(self.parameters), "value_parameters": list(self.value_parameters),
                "family": [[_encode_argument(value) for value in arguments]
                           for arguments in self.family], "evidence": self.evidence}

    @property
    def digest(self):
        payload = json.dumps(self.to_dict(), sort_keys=True, default=repr).encode("ascii")
        return hashlib.sha256(payload).hexdigest()

    def checkpoint_dict(self):
        return {**self.to_dict(), "id": self.name, "digest": self.digest,
                "instances": list(self.instances), "spec": self.core_spec().to_dict()}


_CATALOGUES: dict[int, tuple[weakref.ReferenceType, dict[str, TemplateRecord]]] = {}
_PATTERNS = {"Quot": ("object", ("T:sort", "canon:T->T"), ()),
             "Interval": ("object", ("T:sort", "lt:T,T->bool"), ("lo:T", "hi:T")),
             "Lift": ("operation", ("T:record", "f:S->S"), ()),
             "Iterate": ("combinator", ("T:sort",), ("n:int",)),
             "Count": ("observation", ("probe:observation",), ())}


def templates_for(state) -> dict[str, TemplateRecord]:
    """Return the accepted templates for one live state (never a global world catalogue)."""
    key = id(state)
    existing = _CATALOGUES.get(key)
    if existing is not None and existing[0]() is state:
        count = getattr(state, "_template_synced_count", 0)
        if count != len(state.entries):
            for entry in itertools.islice(state.entries.values(), count, None):
                identity = entry.meta.get("template")
                template = existing[1].get(identity.get("name") if isinstance(identity, dict) else identity)
                if template is not None and entry.name not in template.instances:
                    template.instances.append(entry.name)
            state._template_synced_count = len(state.entries)
        return existing[1]
    catalog: dict[str, TemplateRecord] = {}
    for entry in state.entries.values():
        data = entry.meta.get("template_record")
        if data is None:
            continue
        name = data["name"]
        if name not in catalog:
            pattern = data["pattern"]
            catalog[name] = TemplateRecord(name, pattern, data["kind"],
                                           tuple(data["parameters"]), tuple(data["value_parameters"]),
                                           lambda current, arguments, pattern=pattern, family=data["family"]:
                                           _build(current, pattern, arguments, family),
                                           tuple(tuple(_decode_argument(value) for value in item)
                                                 for item in data["family"]), data["evidence"])
            state.names.taken.add(name)
        catalog[name].instances.append(entry.name)

    def release(reference):
        if _CATALOGUES.get(key, (None,))[0] is reference:
            _CATALOGUES.pop(key, None)

    _CATALOGUES[key] = (weakref.ref(state, release), catalog)
    state._template_synced_count = len(state.entries)
    return catalog


def templates_to_json(state) -> list[dict]:
    """Serialize accepted templates independently of their admitted instances."""
    return [record.checkpoint_dict() for record in templates_for(state).values()]


def templates_from_json(state, data) -> dict[str, TemplateRecord]:
    """Restore a checkpoint catalogue after the entries and names have been loaded.

    Pass None for an older checkpoint without a template catalogue; its instance
    metadata is still supported by templates_for.
    """
    if data is None:
        data = []
    catalogue = templates_for(state)
    restored = {}
    for item in data:
        name = item["name"]
        pattern = item["pattern"]
        if (item.get("id", name) != name or pattern not in _PATTERNS
                or (item["kind"], tuple(item["parameters"]), tuple(item["value_parameters"]))
                != _PATTERNS[pattern] or name in restored
                or name in state.entries or state.library.has_name(name)):
            raise ValueError(f"invalid template id or pattern: {name}")
        family = tuple(tuple(_decode_argument(value) for value in member)
                       for member in item["family"])
        record = TemplateRecord(
            name, pattern, item["kind"], tuple(item["parameters"]),
            tuple(item["value_parameters"]),
            lambda current, arguments, pattern=pattern, family=family:
            _build(current, pattern, arguments, family),
            family, item["evidence"], list(item["instances"]))
        if "spec" in item and TemplateSpec.from_dict(item["spec"]) != record.core_spec():
            raise ValueError(f"invalid template core spec: {name}")
        if record.digest != item["digest"] or len(set(record.instances)) != len(record.instances):
            raise ValueError(f"invalid template digest or instances: {name}")
        for instance_name in record.instances:
            entry = state.entries.get(instance_name)
            identity = entry.meta.get("template") if entry is not None else None
            if (not isinstance(identity, dict) or identity.get("name") != name
                    or identity.get("digest") != record.digest
                    or entry.meta.get("template_id", name) != name):
                raise ValueError(f"invalid template instance: {instance_name}")
            validate_instance(state, record, entry)
        restored[name] = record
    for entry in state.entries.values():
        if entry.meta.get("template") and not any(entry.name in record.instances
                                                    for record in restored.values()):
            raise ValueError(f"unlisted template instance: {entry.name}")
    catalogue.clear()
    catalogue.update(restored)
    state.names.taken.update(restored)
    state._template_synced_count = len(state.entries)
    return catalogue


def template_export_payload(state) -> dict:
    """Exportable ASCII declarations and counts alongside the regular atom payload."""
    records = templates_for(state).values()
    items = [{**record.checkpoint_dict(), "spec": record.core_spec().to_dict(),
              "ascii": template_notation(record)}
             for record in records]
    links = {name: {"id": record.name, "digest": record.digest}
             for record in templates_for(state).values() for name in record.instances}
    return {"templates": items,
            "template_instance_links": links,
            "template_counts": {"total": len(items), "per_kind": {
                kind: sum(item["kind"] == kind for item in items)
                for kind in ("object", "operation", "combinator", "observation")}}}


def template_summary_md(state) -> str:
    """Standalone template section to append to the generator summary."""
    payload = template_export_payload(state)
    counts = payload["template_counts"]
    return "\n".join(["## Templates", f"- total: {counts['total']}",
                      *(f"- {kind}: {count}" for kind, count in counts["per_kind"].items()),
                      *(f"- `{item['ascii']}` ({len(item['instances'])} instances)"
                        for item in payload["templates"])])


def _count_source(state, probe, scope, truth_state):
    signature = state.signature(probe)
    if probe not in state.entries and signature is not None and len(signature.inputs) != 1:
        return Bottom("probe needs fixed arguments")  # Count reads one-argument probes only
    if probe in state.entries:
        from opulse.gen_v2.kinds.observations import _evaluate

        outcome, _ = _evaluate(state, state.library.get(probe), (truth_state,), scope)
    else:
        outcome = fast.call(probe, (truth_state,), scope, state.world.fuel,
                            state.world.dialect).outcome
    return outcome


def _count_conditions(state, sort):
    value = n.Var("_sample")
    truth_states = state.world.truth_states
    truth_sample = truth_states[0] if truth_states else None

    def safe_literal(fixed):
        return not (getattr(fixed, "sort", None) == state.world.truth_sort or
                    isinstance(truth_sample, (tuple, list, dict)) and
                    isinstance(fixed, type(truth_sample)) and
                    any(value_equal(fixed, item) for item in truth_states))

    if sort == "bool":
        yield value
    for decider in dict.fromkeys((*vocab.deciders(state, sort),
                                  *state.callables("operation", inputs=(sort,), output="bool"))):
        yield n.Call(decider, (value,))
    if sort == "int":
        comparisons = (vocab.equal(state, "int")[:1] or
                       state.callables("operation", inputs=("int", "int"), output="bool")[:8])
        for equal in comparisons:
            for fixed in state.sorts["int"].values[:16]:
                yield n.Call(equal, (value, n.Lit(fixed)))
        return
    for operator in state.callables("operation", inputs=(sort,), output="int")[:4]:
        for condition in _count_conditions(state, "int"):
            yield n.Let("_sample", n.Call(operator, (value,)), condition)
    for other in list(state.sorts.values())[:8]:
        for name in state.callables("operation", inputs=(sort, other.name), output="bool")[:3]:
            for fixed in other.values[:9]:
                if not safe_literal(fixed):
                    continue
                yield n.Call(name, (value, n.Lit(fixed)))
        for name in state.callables("operation", inputs=(sort, other.name), output="int")[:3]:
            for fixed in other.values[:3]:
                if not safe_literal(fixed):
                    continue
                for condition in _count_conditions(state, "int"):
                    yield n.Let("_sample", n.Call(name, (value, n.Lit(fixed))), condition)
        for name in state.callables("operation", inputs=(sort, other.name))[:8]:
            result_sort = state.signature(name).output
            if result_sort not in state.sorts or result_sort in (sort, "int", "bool"):
                continue
            for fixed in other.values[:3]:
                if not safe_literal(fixed):
                    continue
                for projection in state.callables("operation", inputs=(result_sort,), output="int")[:2]:
                    for condition in _count_conditions(state, "int"):
                        yield n.Let("_sample", n.Call(projection, (n.Call(name, (value, n.Lit(fixed))),)),
                                    condition)


def _count_condition(state, source):
    cache = getattr(state, "_template_count_conditions", None)
    if cache is None:
        cache = {}
        state._template_count_conditions = cache
    if source[0] in cache:
        condition = cache[source[0]]
        return (n.Let("_sample", source[2], condition), condition) if condition else None
    missing = getattr(state, "_template_count_missing", {})
    operation_count = len(state.callables("operation"))
    if missing.get(source[0]) == operation_count:
        return None
    scope = state.library.scope()
    samples = state.world.truth_states
    indices = (tuple(range(len(samples))) if len(samples) <= 32 else
               tuple(dict.fromkeys((0, *(len(samples) * index // 8 for index in range(1, 8)),
                                         len(samples) - 1))))
    observed = [_count_source(state, source[0], scope, samples[index]) for index in indices]
    for condition in _count_conditions(state, source[1]):
        answers = set()
        for outcome in observed:
            if isinstance(outcome, Ok):
                result = fast.evaluate(condition, {"_sample": outcome.value}, scope,
                                       state.world.fuel, state.world.dialect).outcome
                if not isinstance(result, Ok):
                    break
                try:
                    answers.add(truth(result.value))
                except TypeError:
                    break
        if len(answers) == 2:
            cache[source[0]] = condition
            return n.Let("_sample", source[2], condition), condition
    missing[source[0]] = operation_count
    state._template_count_missing = missing
    return None


def _count_request(state, candidate, probes, condition):
    states = state.world.truth_states
    scope = state.library.scope()
    indices = []
    sources = {source[0]: source for source in _sources(state, earlier=True)}
    for probe in dict.fromkeys(probes):
        signal = _count_condition(state, sources[probe]) if probe in sources else None
        predicate = signal[1] if signal is not None else condition
        for index, truth_state in enumerate(states):
            if index in indices:
                continue
            outcome = _count_source(state, probe, scope, truth_state)
            if not isinstance(outcome, Ok):
                continue
            result = fast.evaluate(predicate, {"_sample": outcome.value}, scope,
                                   state.world.fuel, state.world.dialect).outcome
            if isinstance(result, Ok):
                try:
                    matches = truth(result.value)
                except TypeError:
                    continue
                if matches:
                    indices.append(index)
                    break
        if len(indices) >= 3:
            break
    if states and len(indices) < 4 and len(states) - 1 not in indices:
        indices.append(len(states) - 1)
    if not indices:
        return candidate
    length = 3 if sum(len(indices) ** size for size in (1, 2, 3)) <= state.world.max_scope else 2
    domain = tuple(history for size in range(1, length + 1)
                   for history in product((states[index] for index in indices), repeat=size))
    candidate.request = VerifyRequest("bounded", domain,
                                      {"domain": f"all histories of lengths 1..{length} over truth state indices "
                                                 f"{tuple(indices)}", "size": len(domain),
                                       "history_length": length, "history_state_indices": tuple(indices)})
    return candidate


def _build(state, pattern, arguments, family=()):
    if pattern == "Quot":
        sort, canon = arguments
        if sort not in state.sorts or state.signature(canon) != Signature((sort,), sort):
            return None
        base = state.sorts[sort]
        if not base.values or base.sealed and canon not in base.interface:
            return None
        name = state.names.fresh("object")
        spec = ObjectSpec(name, "refine", base=sort, valid=n.Lit(True),
                          canon=n.Call(canon, (n.Var("x"),)))
        values = []
        for value in base.values:
            result = kernel.call(canon, (value,), state.library.scope(),
                                 kernel.Limits(fuel=state.world.fuel)).outcome
            if isinstance(result, Ok):
                card = Card(name, "val", (result.value,))
                if card not in values:
                    values.append(card)
        if not values:
            return None
        source = (n.Call(sort, ()) if base.origin == "invented" and sort in state.library.definitions
                  else n.Lit(base.values[0]))
        candidate = object_candidate(state, spec, "tmpl.instantiate",
                                     n.Call(f"{name}.make", (n.Call(canon, (source,)),)), values)
        candidate.extra_atoms = (*candidate.extra_atoms, kernel.Defn(name, (), candidate.defn.body,
                                                                      kind="object"))
        candidate.request = VerifyRequest("bounded", candidate.request.domain,
                                          {**candidate.request.scope, "family": "finite probe domain"})
        return candidate
    if pattern == "Interval":
        sort, less, lo, hi = arguments
        if (sort not in state.sorts or state.signature(less) != Signature((sort, sort), "bool")
                or lo not in state.sorts[sort].values or hi not in state.sorts[sort].values):
            return None
        name = state.names.fresh("object")
        valid = n.Case(((n.And(n.Not(n.Test(n.Call(less, (n.Var("x"), n.Lit(lo))))),
                               n.Not(n.Test(n.Call(less, (n.Lit(hi), n.Var("x")))))), n.Lit(True)),), n.Lit(False))
        spec = ObjectSpec(name, "refine", base=sort, valid=valid)
        inside = [value for value in state.sorts[sort].values
                  if _holds(state, less, lo, value, equal_ok=True) and _holds(state, less, value, hi, equal_ok=True)]
        if not inside:
            return None
        values = tuple(Card(name, "val", (value,)) for value in inside)
        witness = n.Case(((n.Test(n.Call(less, (n.Lit(lo), n.Lit(hi)))), n.Lit(lo)),),
                         n.Lit(hi))
        candidate = object_candidate(state, spec, "tmpl.instantiate",
                                     n.Call(f"{name}.make", (witness,)), values)
        candidate.extra_atoms = (*candidate.extra_atoms, kernel.Defn(name, (), candidate.defn.body,
                                                                      kind="object"))
        candidate.request = VerifyRequest("bounded", candidate.request.domain,
                                          {**candidate.request.scope, "family": "finite probe domain"})
        return candidate
    if pattern == "Lift":
        sort, operator = arguments
        record = state.library.definitions.get(sort)
        if record is None or record.kind != "object" or record.spec.form != "compose" or len(record.spec.tags) != 1:
            return None
        tag, fields = next(iter(record.spec.tags.items()))
        if not isinstance(fields, list) or len(fields) < 2 or len({part for _, part in fields}) != 1:
            return None
        field_sort = fields[0][1]
        if state.signature(operator) != Signature((field_sort,), field_sort):
            return None
        name = state.names.fresh("operation")
        body = n.Call(f"{sort}.{tag}", tuple(n.Call(operator, (n.Call(f"{sort}.{field}", (n.Var("x"),)),))
                                               for field, _ in fields))
        spec = OperationSpec(name, "transform", (Edge(sort),), Edge(sort),
                             "Lift the operation over each record field.", extra={"input_names": ["x"]})
        request = domain_request(state, Signature((sort,), sort))
        request = VerifyRequest("bounded", request.domain,
                                {"domain": "finite record probe values", "size": len(request.domain)})
        return Candidate(_definition(state, "operation", name, spec, body), Signature((sort,), sort),
                         "tmpl.instantiate", request)
    if pattern == "Iterate":
        sort, count = arguments
        if sort not in state.sorts or not isinstance(count, int) or not 2 <= count <= 5:
            return None
        operators = state.callables("operation", inputs=(sort,), output=sort)
        if len(operators) < 3:
            return None
        name = state.names.fresh("combinator")
        body = n.Var("x")
        for _ in range(count):
            body = n.Call("f", (body,))
        spec = CombinatorSpec(name, ("f", "x"), ("f",), body)
        signature = Signature((sort,), sort, (Signature((sort,), sort),))
        request = domain_request(state, Signature((sort,), sort))
        domain = request.domain[:8]
        family = operators[:3]
        request = VerifyRequest("bounded", domain,
                                {"domain": "template value and operation family", "size": len(domain),
                                 "op_family": family}, extra={"op_family": family})
        return Candidate(_definition(state, "combinator", name, spec, body, ("f",)), signature,
                         "tmpl.instantiate", request, meta={"slot_families": {"f": family}})
    if pattern == "Count":
        (probe,) = arguments
        source = next((item for item in _sources(state, earlier=True) if item[0] == probe), None)
        if source is None or "int" not in state.sorts or 1 not in state.sorts["int"].values:
            return None
        signal = _count_condition(state, source)
        if signal is None:
            return None
        updates = [(operator, increment) for operator in vocab.combiners(state, "int")
                   for increment in state.sorts["int"].values[:12]
                   if all(isinstance(result := fast.call(operator, (item, increment),
                          state.library.scope(), state.world.fuel, state.world.dialect).outcome, Ok)
                          and result.value == item + 1 for item in range(4))
                   and all(isinstance(result := fast.call(operator, (item, 0),
                           state.library.scope(), state.world.fuel, state.world.dialect).outcome, Ok)
                           and result.value == item for item in range(4))]
        if not updates:
            return None
        value, condition = signal
        operator, increment = updates[0]
        step = n.Case(((n.Test(value), n.Call(operator, (n.Var("memory"), n.Lit(increment)))),),
                      n.Var("memory"))
        body = n.Case(((n.Test(value), n.Call(operator, (n.Var("memory"), n.Lit(0)))),),
                      n.Var("memory"))
        candidate = observation_candidate(state, "tmpl.instantiate", body, source[3],
                                          "int", {"init": n.Lit(0), "step": step})
        probes = (probe, *(item[0] for item in family))
        return _count_request(state, candidate, probes, condition)
    raise ValueError(f"unknown template pattern: {pattern}")


def _name(state, kind):
    prefix = {"object": "Q", "operation": "t", "combinator": "@K", "observation": "?C"}[kind]
    catalogue = templates_for(state)
    index = 1
    while f"{prefix}{index}" in catalogue or f"{prefix}{index}" in state.names.taken:
        index += 1
    return f"{prefix}{index}"


def _argument_hash(state, name):
    """Hash invented arguments, resolving generated object members through their owner."""
    def digest(current):
        if current in state.library.definitions:
            definition = state.library.get(current)
            return definition.content_hash({dependency: content_hash({"internal": dependency})
                                            if dependency.startswith(current + ".") else digest(dependency)
                                            for dependency in definition.depends_on})
        owner, separator, _ = current.partition(".")
        if separator and owner in state.library.definitions:
            return content_hash({"member": current, "owner": digest(owner)})
        return content_hash({"given": current, "world": state.world.decl.world_hash()})

    return digest(name)


def template_candidate(state, record, arguments):
    """Build an instance proposal for the ordinary driver admission path."""
    candidate = record.body(state, arguments)
    if candidate is None:
        return None
    display = f"{record.pattern}[{', '.join(map(str, arguments))}]"
    family_index = next((index for index, member in enumerate(record.family)
                         if member == tuple(arguments)), None)
    dependency_hashes = {argument: _argument_hash(state, argument)
                         for argument in arguments if isinstance(argument, str)
                         and argument in state.library.definitions}
    encoded_arguments = [_encode_argument(value) for value in arguments]
    identity = {"id": record.name, "name": record.name, "digest": record.digest, "arguments": encoded_arguments,
                "dependency_hashes": dependency_hashes}
    candidate.defn = replace(candidate.defn, spec=replace(
        candidate.defn.spec, extra={**candidate.defn.spec.extra, "template": identity}))
    if candidate.request is None and candidate.signature is not None:
        candidate.request = domain_request(state, candidate.signature)
    if candidate.request is not None:
        candidate.request = replace(candidate.request, scope={
            **candidate.request.scope, "template_digest": record.digest,
            "template_arguments": encoded_arguments})
    candidate.meta.update({"template": identity, "template_id": record.name,
                           "arguments": tuple(encoded_arguments),
                           "display": display, "template_record": record.to_dict(),
                           "template_digest": record.digest,
                           "template_family_covered": family_index is not None,
                           "template_family_index": family_index,
                           "instance_digest": hashlib.sha256(json.dumps(
                               identity, sort_keys=True, default=repr).encode("ascii")).hexdigest()})
    return candidate


def validate_instance(state, record, entry):
    """Check the expansion and all provenance against the recorded family and library."""
    identity = entry.meta.get("template")
    arguments = identity.get("arguments") if isinstance(identity, dict) else None
    if not isinstance(arguments, (tuple, list)):
        raise TypeError(f"invalid template arguments: {entry.name}")
    arguments = tuple(_decode_argument(value) for value in arguments)
    trial = copy.copy(state)
    trial.names = copy.deepcopy(state.names)
    trial.entries = dict(itertools.takewhile(lambda pair: pair[0] != entry.name,
                                             state.entries.items()))
    proposal = template_candidate(trial, record, arguments)
    if proposal is None:
        raise ValueError(f"template expansion unavailable: {entry.name}")
    expected = proposal.defn
    actual = state.library.get(entry.name)

    def rename(value):
        if isinstance(value, str):
            return (entry.name + value[len(expected.name):]
                    if value == expected.name or value.startswith(expected.name + ".") else value)
        if isinstance(value, dict):
            return {key: rename(item) for key, item in value.items()}
        if isinstance(value, (tuple, list)):
            return type(value)(rename(item) for item in value)
        return value

    expected_data = rename(expected.to_dict())
    expected_data["depends_on"] = sorted(expected_data["depends_on"])
    actual_data = actual.to_dict()
    for key in ("name", "kind", "origin", "layer", "depends_on", "spec", "body"):
        if json.dumps(actual_data[key], sort_keys=True, default=repr) != json.dumps(
                expected_data[key], sort_keys=True, default=repr):
            raise ValueError(f"template expansion differs: {entry.name}: {key}")
    for key in ("template", "template_id", "arguments", "template_record", "template_digest",
                "template_family_covered", "template_family_index", "instance_digest"):
        if json.dumps(entry.meta.get(key), sort_keys=True, default=repr) != json.dumps(
                proposal.meta.get(key), sort_keys=True, default=repr):
            raise ValueError(f"template provenance differs: {entry.name}: {key}")
    if (actual.evidence is None or actual.evidence.content_hash != state.library.content_hash(entry.name)
            or actual.evidence.deps_hash != state.library._deps_hash(entry.name)):
        raise ValueError(f"template evidence differs: {entry.name}")
    if (actual.evidence.scope.get("template_digest") != record.digest
            or actual.evidence.scope.get("template_arguments") != list(proposal.meta["template"]["arguments"])):
        raise ValueError(f"template evidence scope differs: {entry.name}")


def _instance(state, record, arguments):
    candidate = template_candidate(state, record, arguments)
    if candidate is None:
        return Rejection("tmpl.instantiate", record.kind, "check", "invalid template arguments")
    return admit(state, candidate)


def invent_template(state, pattern: str, family, *, name: str | None = None):
    """Accept only if three distinct instances all pass normal admission on a trial state.

    The trial avoids partially admitted families when any member fails. A successful
    family is replayed on the original state, retaining separate bounded evidence.
    """
    if pattern not in _PATTERNS:
        raise ValueError(f"unknown template pattern: {pattern}")
    kind, parameters, values = _PATTERNS[pattern]
    family = tuple(tuple(item) for item in family)
    if kind not in state.world.open_kinds or len(family) < 3 or len(set(map(repr, family))) != len(family):
        return None
    name = name or _name(state, kind)
    if name in templates_for(state) or name in state.names.taken:
        return None
    trial = copy.deepcopy(state)
    record = TemplateRecord(name, pattern, kind, parameters, values,
                            lambda current, arguments: _build(current, pattern, arguments, family), family,
                            {"method": "bounded", "scope": {"family": [
                                [_encode_argument(value) for value in arguments] for arguments in family],
                                "size": len(family)}})
    for arguments in family:
        result = _instance(trial, record, arguments)
        if not isinstance(result, Entry):
            state.rejections.append(Rejection("tmpl.invent", kind, "verify",
                                              f"family member {arguments!r}: {result.stage}: {result.reason}"))
            return None
    for arguments in family:
        entry = _instance(state, record, arguments)
        if not isinstance(entry, Entry):
            raise TypeError("template trial and original state disagree")
        record.instances.append(entry.name)
    templates_for(state)[name] = record
    state.names.taken.add(name)
    return record


def instantiate_template(state, name: str, arguments):
    """Admit an instance with fresh evidence; unknown or invalid arguments are refused."""
    record = templates_for(state).get(name)
    if record is None:
        raise KeyError(name)
    if record.kind not in state.world.open_kinds:
        return Rejection("tmpl.instantiate", record.kind, "closed_kind", "kind closed")
    result = _instance(state, record, tuple(arguments))
    if isinstance(result, Entry) and result.name not in record.instances:
        record.instances.append(result.name)
    return result


def template_notation(record: TemplateRecord) -> str:
    """ASCII headline for the template catalogue."""
    parameters = ", ".join(parameter.replace(":", ": ").replace("->", " -> ")
                          for parameter in (*record.parameters, *record.value_parameters))
    kind = {"object": "obj", "operation": "op", "combinator": "comb", "observation": "obs"}[record.kind]
    return f"{kind} {record.name}[{parameters}] = {record.pattern} template"


def instance_notation(entry: Entry) -> str:
    """ASCII headline of an admitted instance and its expansion link."""
    arguments = ["Int" if arg == "int" else "Bool" if arg == "bool" else str(arg)
                 for arg in entry.meta["arguments"]]
    kind = {"object": "obj", "operation": "op", "combinator": "comb", "observation": "obs"}[entry.kind]
    identity = entry.meta["template"]
    name = identity["name"] if isinstance(identity, dict) else identity
    return f"{kind} {entry.name} = {name}[{', '.join(arguments)}]  L{entry.layer}"


__all__ = [
    "TemplateRecord",
    "instance_notation",
    "instantiate_template",
    "invent_template",
    "template_candidate",
    "template_export_payload",
    "template_notation",
    "template_summary_md",
    "templates_for",
    "templates_from_json",
    "templates_to_json",
]


def _holds(state, less, left, right, equal_ok=False) -> bool:
    """not less(right, left), i.e. left <= right under the world's order (or left < right).
    A host that rejects the values (ill-typed for its order) means: no order holds."""
    try:
        return _holds_unguarded(state, less, left, right, equal_ok)
    except (TypeError, ValueError, KeyError, IndexError, AttributeError):
        return False


def _holds_unguarded(state, less, left, right, equal_ok):
    if equal_ok:
        outcome = kernel.call(less, (right, left), state.library.scope(), kernel.Limits(fuel=state.world.fuel)).outcome
        return isinstance(outcome, Ok) and not truth(outcome.value)
    outcome = kernel.call(less, (left, right), state.library.scope(), kernel.Limits(fuel=state.world.fuel)).outcome
    return isinstance(outcome, Ok) and truth(outcome.value)
