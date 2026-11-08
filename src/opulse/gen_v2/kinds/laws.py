"""Run law proposals on their domain and replay with the core law verifier."""

from opulse.atoms.laws import check_law
from opulse.atoms.laws import verify_law as core_verify_law
from opulse.gen_v2 import fast
from opulse.gen_v2.admit import KindHook, register_hook


def run_law(state, candidate, request):
    spec = candidate.defn.spec
    scope = state.library.scope()
    results = []
    for args in request.domain:
        if len(args) != len(spec.vars):
            raise ValueError("law input arity differs from variables")
        run = fast.evaluate(candidate.defn.body, dict(zip((name for name, _ in spec.vars), args)),
                            scope, state.world.fuel, state.world.dialect)
        results.append((args, run.outcome, run.steps))
    return results


def verify_law(state, candidate, request, results):
    result = core_verify_law(candidate.defn, state.library, request)
    return result.checks, result.problems


register_hook("law", KindHook(check_law, run_law, verify_law))
