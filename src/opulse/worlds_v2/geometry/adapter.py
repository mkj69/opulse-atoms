"""Public-point probe adapter for multi-argument geometric observations."""

from copy import deepcopy
from dataclasses import replace

from opulse.atoms import kernel, nodes
from opulse.atoms.library import PipelineError
from opulse.atoms.spec import Evidence
from opulse.atoms.values import Bottom, Ok, outcome_equal
from opulse.worlds_v2.export_util import bound_evidence


def make_callable(library, name, samples):
    definition = library.get(name)
    scope = library.scope().extend((kernel.Defn(name, ("r",), definition.body,
                                             definition.kind, definition.layer),))
    for args in samples:
        result = kernel.call(name, args, scope, dialect=library.dialect)
        if isinstance(result.outcome, kernel.Unknown):
            raise PipelineError(f"observation sample exhausted fuel: {name}")
    return library._advance(name, "callable")


def verify(library, name, request):
    """ADAPTER: core observations only accept one robot-style truth input."""
    if request.scope.get("size") != len(request.domain) or request.method not in ("bounded", "exhaustive"):
        raise PipelineError("invalid geometric observation scope")
    if request.reference is None:
        raise PipelineError("geometric observation requires independent reference")
    definition = library.get(name)
    scope = library.scope()
    for dependency in definition.depends_on:
        target = scope.resolve(dependency)
        if target is None or (dependency in library._definitions and
                               library.get(dependency).status != "promoted"):
            raise PipelineError(f"unverified observation dependency: {dependency}")
    steps = []
    seen_views = {}
    for args in request.domain:
        before = deepcopy(args)
        actual = library.run(name, args)
        expected = request.reference(*args)
        if not isinstance(expected, (Ok, Bottom)):
            expected = Ok(expected)
        if not outcome_equal(actual.outcome, expected):
            raise PipelineError(f"observation reference mismatch at {args!r}: {actual.outcome!r} != {expected!r}")
        if args != before:
            raise PipelineError(f"observation mutated input at {args!r}")
        probe = library.run("points", (args[0],)).outcome
        if probe in seen_views and not outcome_equal(seen_views[probe], actual.outcome):
            raise PipelineError(f"observational non-interference violated at {args!r}")
        seen_views[probe] = actual.outcome
        steps.append(actual.steps)
    evidence = Evidence(request.method, dict(request.scope), request.seed,
                        ("dependency", "facts_unchanged", "non_interference", "reference"),
                        library.world.world_hash(), library._deps_hash(name), library.content_hash(name))
    library._steps[name] = steps
    library._definitions[name] = replace(library.get(name), evidence=bound_evidence(library, name, evidence, request.domain))
    return library._advance(name, "verified")


def verify_heavy_operation(library, name, request):
    """ADAPTER: check all references, but inline the first complete congruence."""
    if request.method != "bounded" or request.scope.get("size") != len(request.domain):
        raise PipelineError("invalid bounded congruence scope")
    scope = library.scope()
    steps = []
    for args in request.domain:
        actual = library.run(name, args)
        expected = request.reference(*args)
        if not outcome_equal(actual.outcome, expected if isinstance(expected, (Ok, Bottom)) else Ok(expected)):
            raise PipelineError(f"congruence reference mismatch at {args!r}")
        steps.append(actual.steps)
    first = request.domain[0]
    inlined = kernel.inline(nodes.Call(name, tuple(nodes.Lit(value) for value in first)), scope)
    comparison = kernel.evaluate(inlined, scope=scope, dialect=library.dialect)
    original = library.run(name, first)
    if not outcome_equal(original.outcome, comparison.outcome) or original.steps != comparison.steps:
        raise PipelineError("congruence kernel unfold mismatch")
    evidence = Evidence("bounded", dict(request.scope), None, ("reference", "unfold_equivalence"),
                        library.world.world_hash(), library._deps_hash(name), library.content_hash(name))
    library._steps[name] = steps
    library._definitions[name] = replace(library.get(name), evidence=bound_evidence(library, name, evidence, request.domain))
    return library._advance(name, "verified")


def verify_region_pair(library, name, request):
    if request.method != "bounded" or request.scope.get("size") != len(request.domain):
        raise PipelineError("invalid region-pair scope")
    steps = []
    for (candidate,) in request.domain:
        if not isinstance(candidate, kernel.Card) or candidate.sort != "RegionPair" or candidate.tag != "shape":
            raise PipelineError("region-pair domain contains a non-pair")
        actual = library.run("RegionPair.shape", candidate.fields)
        if not outcome_equal(actual.outcome, Ok(candidate)):
            raise PipelineError("region-pair constructor lost or accepted invalid fields")
        steps.append(actual.steps)
    evidence = Evidence(request.method, dict(request.scope), request.seed, ("finite_values",),
                        library.world.world_hash(), library._deps_hash(name), library.content_hash(name))
    library._steps[name] = steps
    library._definitions[name] = replace(library.get(name), evidence=bound_evidence(library, name, evidence, request.domain))
    return library._advance(name, "verified")
