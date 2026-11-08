"""Bind locally checked DFA observation and provenance-sensitive object evidence."""
from dataclasses import replace

from opulse.atoms.spec import Evidence
from opulse.worlds_v2.export_util import bound_evidence


def record(library, name, request, checks, steps):
    definition = library.get(name)
    library._steps[name] = steps
    library._definitions[name] = replace(definition, evidence=bound_evidence(library, name, Evidence(
        request.method, dict(request.scope), request.seed, tuple(checks),
        library.world.world_hash(), library._deps_hash(name), library.content_hash(name)), request.domain))
    return library._advance(name, "verified")
