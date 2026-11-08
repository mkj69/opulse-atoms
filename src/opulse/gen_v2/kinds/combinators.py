"""Typed operation-family sampling for combinator admission.

The core verifier assumes every operation slot shares one interchangeable family.
This hook also handles heterogeneous slots (a predicate and a transformer) while
checking the same unfolding, outcome, and layer-0 step obligations.
"""

from __future__ import annotations

from itertools import product

from opulse.atoms import kernel, nodes
from opulse.atoms.combinators import instantiate
from opulse.atoms.library import VerifyRequest
from opulse.atoms.spec import Definition
from opulse.atoms.values import Unknown, outcome_equal
from opulse.gen_v2 import fast
from opulse.gen_v2.admit import KindHook, register_hook


def definition(state, kind, name, spec, body, slots=(), *, include_literals=True, fold_layer=True):
    references = nodes.references(body) - set(slots)
    dependencies = tuple(sorted(references | nodes.operation_literals(body) if include_literals else references))

    def layer(reference):
        if fold_layer and reference.endswith(".fold"):
            target = state.library.scope().resolve(reference)
            if isinstance(target, kernel.Defn):
                return target.layer
        return state.layer(reference)

    return Definition(name, kind, "invented", 1 + max(map(layer, dependencies), default=0),
                      dependencies, spec, body)


def family_request(state, inputs, families, limit=8):
    probes = [tuple(state.sorts[sort].values) for sort in inputs]
    if any(not values for values in probes):
        return None
    bound = max((len(values) for values in probes), default=1)
    while bound > 1 and _prefix_size(probes, bound) > limit:
        bound -= 1
    domain = tuple(product(*(values[:bound] for values in probes)))
    if not domain or len(domain) > limit:
        return None
    family = list(dict.fromkeys(families))
    description = f"all value-input probe prefixes through bound {bound}"
    return VerifyRequest("bounded", domain,
                         {"domain": description, "description": description,
                          "size": len(domain), "bound": bound, "op_family": family},
                         extra={"op_family": family})


def _prefix_size(probes, bound):
    size = 1
    for values in probes:
        size *= min(len(values), bound)
    return size


def _assignments(candidate):
    slots = candidate.defn.spec.op_params
    families = candidate.meta["slot_families"]
    for names in product(*(families[slot] for slot in slots)):
        yield dict(zip(slots, names))


def _validate_families(state, candidate, request):
    slots = candidate.defn.spec.op_params
    signatures = candidate.signature.op_inputs if candidate.signature is not None else ()
    families = candidate.meta.get("slot_families", {})
    if len(signatures) != len(slots) or set(families) != set(slots):
        raise ValueError("operation slots do not match the declared signatures")
    helpers = candidate.meta.get("helper_signatures", {})
    for slot, signature in zip(slots, signatures):
        names = families[slot]
        if not names:
            raise ValueError(f"operation family for {slot} is empty")
        for name in names:
            actual = state.signature(name)
            if actual == signature:
                continue
            helper = state.library._extra_atoms.get(name)
            declared = helpers.get(name)
            if (actual is not None or helper is None or
                    not isinstance(helper, kernel.Atom) or helper.arity != len(signature.inputs) or
                    not isinstance(declared, (tuple, list)) or len(declared) != 2 or
                    tuple(declared[0]) != signature.inputs or declared[1] != signature.output):
                raise ValueError(f"operation family for {slot} has an incompatible signature")
    names = tuple(dict.fromkeys(name for slot in slots for name in families[slot]))
    if (not names or set(names) != set(request.scope.get("op_family", ())) or
            set(names) != set(request.extra.get("op_family", ()))):
        raise ValueError("scope must record the exact typed operation family")


def _arguments(spec, assignment, values):
    values = iter(values)
    return tuple(kernel.FnRef(assignment[param]) if param in assignment else next(values)
                 for param in spec.params)


def run(state, candidate, request):
    _validate_families(state, candidate, request)
    definition = candidate.defn
    scope = state.library.scope().extend([kernel.Defn(definition.name, definition.spec.params,
                                                      definition.body, kind="combinator")])
    results = []
    for assignment in _assignments(candidate):
        for values in request.domain:
            arguments = _arguments(definition.spec, assignment, values)
            result = fast.call(definition.name, arguments, scope, state.world.fuel, state.world.dialect)
            results.append((tuple(values), result.outcome, result.steps))
    return results


def verify(state, candidate, request, results):
    try:
        _validate_families(state, candidate, request)
    except ValueError as error:
        return (), [str(error)]
    definition = candidate.defn
    if request.method != "bounded" or request.scope.get("size") != len(request.domain):
        return (), ["combinator needs an exact bounded value domain"]
    probes = [tuple(state.sorts[sort].values) for sort in candidate.signature.inputs]
    bound = request.scope.get("bound")
    if bound is None and candidate.move == "tmpl.instantiate":
        bound = next((size for size in range(1, max(map(len, probes), default=1) + 1)
                      if tuple(product(*(values[:size] for values in probes))) == request.domain), None)
    if (not isinstance(bound, int) or isinstance(bound, bool) or
            not 1 <= bound <= max(map(len, probes), default=1) or
            tuple(product(*(values[:bound] for values in probes))) != request.domain):
        return (), ["bounded domain must be the complete probe-value prefix"]
    families = candidate.meta["slot_families"]
    expected_size = len(request.domain)
    for slot in definition.spec.op_params:
        expected_size *= len(families[slot])
    if len(results) != expected_size:
        return (), ["operation family results do not cover the recorded assignments and inputs"]
    scope = state.library.scope().extend([kernel.Defn(definition.name, definition.spec.params,
                                                      definition.body, kind="combinator")])
    index = 0
    for assignment in _assignments(candidate):
        for values in request.domain:
            actual = results[index][1:]
            index += 1
            unfolded = fast.evaluate(instantiate(definition.spec, assignment, values), {}, scope,
                                     state.world.fuel, state.world.dialect)
            if (isinstance(unfolded.outcome, Unknown) or
                    not outcome_equal(actual[0], unfolded.outcome) or actual[1] != unfolded.steps):
                return (), [f"unfold_equivalence mismatch: {assignment!r}, {values!r}"]
    slots = definition.spec.op_params
    rows = list(product(*(families[slot] for slot in slots)))
    width = len(request.domain)
    for position, slot in enumerate(slots):
        if not any(all(left[other] == right[other] for other in range(len(slots)) if other != position)
                   and left[position] != right[position]
                   and any(not outcome_equal(results[left_index * width + value_index][1],
                                             results[right_index * width + value_index][1])
                           for value_index in range(width))
                   for left_index, left in enumerate(rows) for right_index, right in enumerate(rows)):
            return (), [f"behaviour does not depend on operation slot {slot}"]
    return ("unfold_equivalence",), []


register_hook("combinator", KindHook(run=run, verify=verify))
