"""Local pipeline hooks for typed cards and non-robot observations."""

from copy import deepcopy
from dataclasses import replace

from opulse.atoms import kernel, nodes
from opulse.atoms.check import check_definition
from opulse.atoms.library import PipelineError
from opulse.atoms.spec import Evidence
from opulse.atoms.values import Bottom, Ok, Unknown, outcome_equal
from opulse.worlds_v2.export_util import bound_evidence

from . import hosts


def _checked_problems(library, name):
    definition = library.get(name)
    generated = {reference for reference in nodes.references(definition.body)
                 if reference.startswith(("Event.", "Belief.", "Walk."))} if definition.body is not None else set()
    scope = library.scope()
    problems = check_definition(definition, library.world,
                                lambda reference: library._definitions.get(reference) or scope.resolve(reference))
    return [problem for problem in problems if " argument " not in problem and
            not (problem.startswith("unresolved call: ") and problem[17:] in generated)]


def check_local(library, name):
    definition = library.get(name)
    problems = _checked_problems(library, name)
    if definition.body != definition.spec.body:
        problems.append("observation body differs from declared body")
    granted = {probe["name"] for probe in library.world.observation["probes"]}
    for expression in (item for item in nodes.walk(definition.body) if isinstance(item, nodes.Call)):
        operation = next((item for item in library.world.operations if item.name == expression.fn), None)
        if operation is not None and operation.role == "act":
            problems.append(f"observation invokes action {expression.fn}")
        if expression.fn in granted and expression.fn not in definition.spec.reads:
            problems.append(f"probe {expression.fn} is not granted to the observation")
    if not set(definition.spec.reads) <= granted:
        problems.append("observation reads an undeclared probe")
    if problems:
        raise PipelineError(problems)
    return library._advance(name, "checked")


def check_refs(library, name):
    definition = library.get(name)
    problems = [problem for problem in _checked_problems(library, name)
                if problem != "operation references cannot be stored as data"]
    for item in nodes.walk(definition.body):
        if (isinstance(item, nodes.Lit) and isinstance(item.value, kernel.FnRef)
                and library.scope().resolve(item.value.name) is None):
            problems.append(f"unknown continuation: {item.value.name}")
    if problems:
        raise PipelineError(problems)
    return library._advance(name, "checked")


def check_generic(library, name):
    problems = _checked_problems(library, name)
    if problems:
        raise PipelineError(problems)
    return library._advance(name, "checked")


def make_callable_local(library, name, samples):
    steps = []
    definition = library.get(name)
    scope = library.scope().extend([kernel.Defn(name, library._params(definition), definition.body,
                                                definition.kind, definition.layer)])
    for args in samples:
        result = kernel.call(name, args, scope)
        if isinstance(result.outcome, Unknown):
            raise PipelineError(f"unknown observation outcome: {result.outcome!r}")
        steps.append(result.steps)
    library._steps[name] = steps
    return library._advance(name, "callable")


def verify_general(library, name, request):
    definition = library.get(name)
    if definition.status != "callable" or request.scope["size"] != len(request.domain):
        raise PipelineError("invalid verification scope")
    steps = []
    for args in request.domain:
        before = deepcopy(args)
        result = library.run(name, args)
        expected = request.reference(*args)
        unfolded = kernel.evaluate(kernel.inline(nodes.Call(name, tuple(nodes.Lit(arg) for arg in args)), library.scope()),
                                   scope=library.scope())
        expected_outcome = expected if isinstance(expected, (Ok, Bottom, Unknown)) else Ok(expected)
        if (not outcome_equal(result.outcome, expected_outcome) or
                not outcome_equal(result.outcome, unfolded.outcome) or result.steps != unfolded.steps or args != before):
            raise PipelineError(f"reference/unfold counterexample for {name}: {result.outcome!r}, {expected!r}, {unfolded.outcome!r}")
        if definition.kind == "observation":
            truth = library.run("independent", (kernel.FnRef("roll"), kernel.FnRef("roll"), hosts.FAIR, hosts.FAIR)).outcome
            snapshot = deepcopy(truth)
            repeated = library.run(name, args)
            if (not outcome_equal(result.outcome, repeated.outcome) or result.steps != repeated.steps
                    or not outcome_equal(truth, snapshot) or args != before):
                raise PipelineError(f"observation interference: {name}")
            for dependency in definition.depends_on:
                if dependency in library.definitions and getattr(library.get(dependency).spec, "role", None) == "act":
                    raise PipelineError(f"observation depends on action: {dependency}")
        steps.append(result.steps)
    checks = ("reference", "unfold_equivalence")
    if definition.kind == "observation":
        checks += ("dependency", "facts_unchanged", "non_interference")
    evidence = Evidence(request.method, dict(request.scope), request.seed, checks,
                        library.world.world_hash(), library._deps_hash(name))
    library._steps[name] = steps
    library._definitions[name] = replace(definition, evidence=bound_evidence(library, name, evidence, request.domain))
    return library._advance(name, "verified")
