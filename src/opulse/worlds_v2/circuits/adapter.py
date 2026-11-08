"""World-parametric object and observation verifier support."""
from dataclasses import replace

from opulse.atoms.spec import Evidence
from opulse.worlds_v2.export_util import bound_evidence


def _record(lib, name, request, checks, steps, domain):
    """Record the exact input tuples exercised by a world-specific verifier."""
    definition = lib.get(name)
    evidence = Evidence(request.method, dict(request.scope), request.seed, tuple(checks),
                        lib.world.world_hash(), lib._deps_hash(name))
    lib._steps[name] = steps
    lib._definitions[name] = replace(definition, evidence=bound_evidence(lib, name, evidence, domain))
    return lib._advance(name, "verified")
