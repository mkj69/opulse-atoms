"""Verify observations that combine public probes with invented operations."""

from copy import deepcopy
from dataclasses import replace

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.check import check_definition
from opulse.atoms.library import PipelineError
from opulse.atoms.spec import Evidence
from opulse.atoms.values import Bottom, Ok, Unknown, outcome_equal
from opulse.worlds_v2.export_util import bound_evidence


def check(library, name):
    definition = library.get(name)
    problems = [problem for problem in check_definition(definition, library.world,
                 library.definitions.get) if ' argument ' not in problem]
    if definition.kind == 'observation':
        probes = library.world.observation['capabilities']['learner']['probes']
        if definition.spec.reads != ('cells',) or 'cells' not in probes:
            problems.append('observation must use only its granted cells probe')
        if any(isinstance(node, n.Var) and node.name != 'arg0' and
               node.name not in {part.name for part in n.walk(definition.body) if isinstance(part, n.Let)} and
               node.name not in {param for part in n.walk(definition.body) if isinstance(part, n.Rec)
                                 for param in part.params}
               for node in n.walk(definition.body)):
            problems.append('observation reads undeclared data')
    if problems:
        raise PipelineError(problems)
    library._advance(name, 'checked')


def make_callable(library, name, args):
    if library.get(name).status != 'checked':
        raise PipelineError('check before making callable')
    definition = library.get(name)
    scope = library.scope().extend([kernel.Defn(name, library._params(definition), definition.body,
                                                definition.kind, definition.layer)])
    result = kernel.call(name, args, scope)
    if isinstance(result.outcome, Unknown):
        raise PipelineError(f'non-terminating sample: {result.outcome!r}')
    library._steps[name] = [result.steps]
    library._advance(name, 'callable')


def verify(library, name, domain, description, reference):
    definition = library.get(name)
    scope = library.scope()
    deps_hash = library._deps_hash(name)
    world_hash = library.world.world_hash()
    steps = []
    for args in domain:
        before = deepcopy(args)
        direct = library.run(name, args)
        unfolded = kernel.evaluate(kernel.inline(n.Call(name, tuple(n.Lit(arg) for arg in args)), scope), scope=scope)
        if (isinstance(direct.outcome, Unknown) or not outcome_equal(direct.outcome, unfolded.outcome)
                or direct.steps != unfolded.steps or args != before):
            raise PipelineError(f'{name}: failed unfold or probe non-interference on {args!r}')
        if reference is not None:
            expected = reference(*args)
            expected = expected if isinstance(expected, (Ok, Bottom)) else Ok(expected)
            if not outcome_equal(direct.outcome, expected):
                raise PipelineError(f'{name}: reference mismatch on {args!r}')
        steps.append(direct.steps)
    if library._deps_hash(name) != deps_hash or library.world.world_hash() != world_hash:
        raise PipelineError(f'{name}: dependencies changed during verification')
    checks = ('dependency', 'facts_unchanged', 'non_interference',
              'unfold_equivalence', 'reference')
    evidence = Evidence('bounded', {'domain': description, 'size': len(domain)},
                        checks=checks, world_hash=world_hash, deps_hash=deps_hash)
    library._steps[name] = steps
    library._definitions[name] = replace(definition, evidence=bound_evidence(library, name, evidence, domain))
    library._advance(name, 'verified')
