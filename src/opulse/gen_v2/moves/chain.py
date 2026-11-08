"""Target a verified object, operation, combinator, observation path."""

from __future__ import annotations

from dataclasses import dataclass
from random import Random

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.spec import ObjectSpec
from opulse.gen_v2.base import Signature
from opulse.gen_v2.moves import combinator, observation, operation
from opulse.gen_v2.moves import object as objects
from opulse.gen_v2.tasks_bridge import four_kinds_path


def _tags(state, obj):
    spec = state.library.get(obj.name).spec
    if spec.form != "compose" or spec.sealed:
        return ()
    return tuple(tag for tag, fields in (spec.tags or {}).items()
                 if isinstance(fields, (list, tuple)) and
                 all(sort in state.sorts and sort != state.world.truth_sort and
                     not state.sorts[sort].sealed
                     for _, sort in fields))[:3]


def _sources(state):
    if not state.world.probes or not state.world.truth_states:
        return []
    cached = getattr(state, "_chain_sources", None)
    if cached is not None and (cached or
                               getattr(state, "_chain_sources_at", -1) == len(state.entries)):
        return cached
    originals = observation._sources(state)
    sources = observation._derived_sources(state, Random(0), originals)
    sources = [source for source in sources if source[1] != state.world.truth_sort and
               source[1] in state.sorts and source[3] and
               not (n.references(source[2]) & state.entries.keys()) and
               (partition := observation._source_partition(state, source)) and
               None not in partition and len(set(partition)) > 1]
    state._chain_sources = sources
    state._chain_sources_at = len(state.entries)
    return sources


def _objects(state):
    return [entry for entry in state.entries.values() if entry.kind == "object" and
            entry.name in state.sorts and len(_tags(state, entry)) == 3]


def _operations(state, obj):
    return [entry for entry in state.entries.values() if entry.kind == "operation" and
            entry.signature == Signature((obj.name,), "bool") and
            any(ref == obj.name or ref.startswith(obj.name + ".")
                for ref in n.references(state.library.get(entry.name).body))]


def _combinators(state, op):
    return [entry for entry in state.entries.values() if entry.kind == "combinator" and
            entry.signature and entry.signature.inputs == op.signature.inputs and
            entry.signature.output == op.signature.output and
            entry.signature.op_inputs == (op.signature, op.signature) and
            len(state.library.get(entry.name).spec.op_params) == 2 and
            any(op.name in family for family in entry.meta.get("slot_families", {}).values())]


def _observed(state, op, comb):
    return any(entry.kind == "observation" and
               ({op.name, comb.name} & n.references(state.library.get(entry.name).body))
               for entry in state.entries.values())


def _object(state, rng):
    choices = _sources(state)
    if not choices:
        return None
    source = rng.choice([item for item in choices if item[1] != "bool"] or choices)
    sort = source[1]
    name = state.names.fresh("object")
    spec = ObjectSpec(name, "compose", tags={tag: [("value", sort)]
                                            for tag in ("left", "right", "middle")})
    values = objects._values(spec, state)
    body = n.Call(f"{name}.left", (objects._witness(state, sort),))
    return objects._candidate(state, spec, "chain.extend", body, values)


def _operation(state, obj):
    name = obj.name
    first, second, _ = _tags(state, obj)
    value = n.Var("x0")
    body = n.Case(((n.Test(n.Call(f"{name}.is_{first}", (value,))),
                    n.Call(f"{name}.is_{first}", (value,))),),
                  n.Call(f"{name}.is_{second}", (value,)))
    return operation._candidate(state, "chain.extend", (name,), "bool", body)


def _combinator(state, rng, op):
    obj = op.signature.inputs[0]
    value = n.Var("x")
    first = n.Call("f", (value,))
    body = n.Case(((n.Test(first), n.Call("g", (value,))),), first)
    signature = Signature((obj,), "bool")
    candidate = combinator._combinator(state, rng, "chain.extend", body,
                                        ("f", "g", "x"), {"f": signature, "g": signature},
                                        (obj,), "bool")
    if candidate is not None and not any(op.name in family for family in
                                         candidate.meta["slot_families"].values()):
        families = {slot: tuple(dict.fromkeys((op.name, *family)))[:3]
                    for slot, family in candidate.meta["slot_families"].items()}
        candidate.meta["slot_families"] = families
        candidate.request = combinator.family_request(state, (obj,),
                                                       tuple(dict.fromkeys(name for family in
                                                                            families.values() for name in family)))
        if candidate.request is None:
            state.names.release(candidate.defn.name)
            return None
    return candidate


def _observation(state, rng, obj, op, comb):
    sources = _sources(state)
    first, second, _ = _tags(state, obj)
    spec_obj = state.library.get(obj.name).spec
    fields = spec_obj.tags[first] + spec_obj.tags[second]
    choices = [source for source in sources if source[1] in {sort for _, sort in fields}]
    if not choices:
        choices = [source for source in sources if source[1] != "bool"] or sources
    predicates = [source for source in sources if source[1] == "bool"]
    if not choices or not predicates:
        return None
    source, predicate = rng.choice(choices), rng.choice(predicates)
    value = source[2]
    condition = n.Test(predicate[2])
    def construct(tag):
        arguments = tuple(value if field_sort == source[1] else objects._witness(state, field_sort)
                          for _, field_sort in spec_obj.tags[tag])
        return n.Call(f"{obj.name}.{tag}", arguments)

    argument = n.Case(((condition, construct(first)),), construct(second))
    spec = state.library.get(comb.name).spec
    plugged = {spec.op_params[0]: op.name,
               spec.op_params[1]: f"{obj.name}.is_{second}"}
    args = tuple(n.Lit(kernel.FnRef(plugged[param])) if param in plugged else argument
                 for param in spec.params)
    body = n.Call(comb.name, args)
    candidate = observation._candidate(state, "chain.extend", body,
                                       source[3] + predicate[3], "bool")
    if observation.observation_check(candidate.defn, state.library):
        state.names.release(candidate.defn.name)
        return None
    return candidate


@dataclass
class ChainMove:
    kind: str
    name: str = "chain.extend"
    bias: float = 0.0
    builds_on_top: bool = True

    def __call__(self, state, rng):
        if self.kind not in state.world.open_kinds or not _sources(state):
            return None
        objects._reclaim_refused_name(state)
        if getattr(state, "_chain_complete", False):
            return None
        objects_ = _objects(state)
        if not objects_:
            if "object" in state.world.open_kinds:
                candidate = _object(state, rng)
                if candidate is not None:
                    state._object_pending_name = (candidate.defn.name, len(state.rejections))
                return candidate
            return None
        partials = []
        for obj in objects_:
            operations = _operations(state, obj)
            if not operations:
                partials.append((1, obj.layer, obj, None, None))
            for op in operations:
                combinators = _combinators(state, op)
                if not combinators:
                    partials.append((2, op.layer, obj, op, None))
                for comb in combinators:
                    partials.append((3, comb.layer, obj, op, comb))
        if any(stage == 3 and _observed(state, op, comb)
               for stage, _, _, op, comb in partials):
            state._chain_complete = four_kinds_path(state) is not None
            if state._chain_complete:
                return None
        choices = [partial for partial in partials if (
            partial[0] == 1 and "operation" in state.world.open_kinds or
            partial[0] == 2 and "combinator" in state.world.open_kinds or
            partial[0] == 3 and not _observed(state, partial[3], partial[4]))]
        if not choices:
            return None
        choices.sort(key=lambda partial: (partial[0], partial[1] if self.bias else 0,
                                          partial[2].layer, partial[2].name), reverse=True)
        stage, _, obj, op, comb = choices[0]
        if stage == 1:
            return _operation(state, obj)
        if stage == 2:
            return _combinator(state, rng, op)
        if not _observed(state, op, comb):
            return _observation(state, rng, obj, op, comb)
        return None


MOVES = [ChainMove("observation")]
