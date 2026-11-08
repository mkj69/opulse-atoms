"""Public-list observation verification where the core expects robot truth states."""
from dataclasses import replace

from opulse.atoms import kernel, nodes
from opulse.atoms.library import PipelineError
from opulse.atoms.spec import Evidence
from opulse.atoms.values import Bottom, Ok, outcome_equal
from opulse.worlds_v2.export_util import bound_evidence


def record(lib, name, request, checks, steps):
    definition = lib.get(name)
    lib._steps[name] = steps
    lib._definitions[name] = replace(definition, evidence=bound_evidence(lib, name, Evidence(
        request.method, dict(request.scope), request.seed, tuple(checks),
        lib.world.world_hash(), lib._deps_hash(name)), request.domain))
    return lib._advance(name, "verified")


def _unfold(lib, name, args, result):
    unfolded = kernel.evaluate(kernel.inline(nodes.Call(name, tuple(nodes.Lit(arg) for arg in args)),
                                             lib.scope()), scope=lib.scope())
    return outcome_equal(result.outcome, unfolded.outcome) and result.steps == unfolded.steps


def _reference_result(actual, expected):
    return outcome_equal(actual.outcome, expected if isinstance(expected, Bottom) else Ok(expected))


def verify_public_observation(lib, name, request, reference):
    """Public lists fully determine the immutable observation's truth."""
    if lib.get(name).status != "callable" or request.scope["size"] != len(request.domain):
        raise PipelineError("invalid observation scope")
    steps = []
    for args in request.domain:
        before = tuple(args)
        actual = lib.run(name, args)
        if (not _reference_result(actual, reference(name, args)) or not _unfold(lib, name, args, actual)
                or before != args):
            raise PipelineError(f"observation reference/unfold failure: {name} {args!r}")
        steps.append(actual.steps)
    return record(lib, name, request, ("dependency", "facts_unchanged", "non_interference",
                                        "reference", "unfold_equivalence"), steps)
