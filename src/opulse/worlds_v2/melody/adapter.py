"""Public-probe adapter for derived observations calling invented combinators."""

from opulse.atoms import kernel, nodes
from opulse.atoms.check import all_dependencies
from opulse.atoms.library import PipelineError
from opulse.atoms.spec import Evidence
from opulse.atoms.values import Ok, encode, outcome_equal
from opulse.worlds_v2.export_util import bound_evidence


def run_observation(lib, name, state, trace=False):
    definition = lib.get(name)
    visible = {}
    for probe in definition.spec.reads:
        observed = lib.run(probe, (state,))
        if not isinstance(observed.outcome, Ok):
            return observed
        visible[probe] = observed.outcome.value
    if definition.status == "promoted":
        return lib.run(name, tuple(visible[probe] for probe in definition.spec.reads), trace=trace)
    atoms = [kernel.Atom(probe, 0, lambda value=visible[probe]: value,
                         cost=1, kind="observation") for probe in definition.spec.reads]
    scope = lib.scope()
    scope = kernel.DictScope(atoms={**scope.atoms, **{item.name: item for item in atoms}},
                             defns=scope.defns)
    return kernel.evaluate(definition.body, visible, scope=scope, trace=trace)


def verify(lib, name, request):
    definition = lib.get(name)
    dependencies = nodes.references(definition.body) - set(definition.spec.reads)
    if (dependencies - set(definition.depends_on)
            or any(lib.scope().resolve(dep) is None for dep in all_dependencies(definition))):
        raise PipelineError(f"dependency failure: {name}")
    steps = []
    for history in request.extra["states"]:
        for state in history:
            before = encode(state)
            actual = run_observation(lib, name, state, trace=True)
            expected = request.reference(state)
            if not outcome_equal(actual.outcome, expected if isinstance(expected, (Ok,)) else Ok(expected)):
                raise PipelineError(f"reference counterexample: {name}, {state!r}: {actual.outcome!r} != {expected!r}")
            if encode(state) != before:
                raise PipelineError(f"facts_unchanged failure: {name}, {state!r}")
            steps.append(actual.steps)
        for index, left in enumerate(history):
            for right in history[index + 1:]:
                visible_left = tuple(lib.run(probe, (left,)).outcome for probe in definition.spec.reads)
                visible_right = tuple(lib.run(probe, (right,)).outcome for probe in definition.spec.reads)
                if visible_left == visible_right and run_observation(lib, name, left).outcome != run_observation(lib, name, right).outcome:
                    raise PipelineError("non_interference failure")
    evidence = Evidence(request.method, request.scope, request.seed,
                        ("dependency", "reference", "facts_unchanged", "non_interference"),
                        lib.world.world_hash(), lib._deps_hash(name), lib.content_hash(name))
    lib._steps[name] = steps
    return lib.record_evidence(name, bound_evidence(lib, name, evidence, request.domain))
