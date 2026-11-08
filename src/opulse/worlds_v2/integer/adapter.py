"""Type-check exceptions for integer's polymorphic storage and direct observations."""

from opulse.atoms.check import check_definition
from opulse.atoms.library import PipelineError


def check_local(library, name):
    """Use the core checker for cards without polymorphic or observation exceptions."""
    if name not in {"mul", "whole", "cf_step", "convergents", "bounded_convergent"}:
        library.check(name)
        return library
    definition = library.get(name)
    problems = check_definition(definition, library.world,
                                lambda reference: library.definitions.get(reference) or library.scope().resolve(reference))
    polymorphic = ("eq ", "ne ", "pair ", "first ", "second ", "cons ",
                   "append ", "head ", "count ", "denominator ")
    problems = [problem for problem in problems if not (
        " argument " in problem and ("expected unknown" in problem or "got unknown" in problem or
                                      problem.startswith(polymorphic)))]
    if problems:
        raise PipelineError([name + ": " + problem for problem in problems])
    library._advance(name, "checked")
    return library
