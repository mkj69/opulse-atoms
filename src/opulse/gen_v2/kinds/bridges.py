"""Run bridge proposals and replay commuting checks with the core verifier."""

from dataclasses import replace

from opulse.atoms.bridges import BridgeContext, check_bridge
from opulse.atoms.bridges import verify_bridge as core_verify_bridge
from opulse.atoms.spec import Edge, OperationSpec
from opulse.gen_v2 import fast
from opulse.gen_v2.admit import KindHook, register_hook


class _TypedSource:
    """Expose generated object-interface output sorts to core bridge verification."""

    def __init__(self, state):
        self.library = state.library
        known = {op.name for op in self.library.world.operations}
        generated = tuple(OperationSpec(name, "transform",
                                        tuple(Edge(sort) for sort in signature.inputs),
                                        Edge(signature.output), "Generated object interface")
                          for name, signature in state.extra_signatures.items()
                          if name not in known and not signature.op_inputs)
        self.world = replace(self.library.world,
                             operations=(*self.library.world.operations, *generated))

    def __getattr__(self, name):
        return getattr(self.library, name)


def typed_request(state, request):
    return replace(request, extra={**request.extra, "bridge_context":
                                   BridgeContext(_TypedSource(state), state.library)})


def run_bridge(state, candidate, request):
    scope = state.library.scope()
    results = []
    for args in request.domain:
        if len(args) != 1:
            raise ValueError("bridge domain must contain unary inputs")
        run = fast.evaluate(candidate.defn.spec.map, {"x": args[0]}, scope,
                            state.world.fuel, state.world.dialect)
        results.append((args, run.outcome, run.steps))
    return results


def verify_bridge(state, candidate, request, results):
    result = core_verify_bridge(candidate.defn, state.library, typed_request(state, request))
    return result.checks, result.problems


register_hook("bridge", KindHook(check_bridge, run_bridge, verify_bridge))
