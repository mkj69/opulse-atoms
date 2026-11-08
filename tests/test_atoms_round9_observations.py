"""Subject sealing and derived-observation verification (spec sections 7 and 18.3)."""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.library import Library, PipelineError, VerifyRequest
from opulse.atoms.observations import check_observation
from opulse.atoms.spec import (
    BridgeSpec,
    CombinatorSpec,
    Definition,
    Edge,
    ObservationSpec,
    OperationSpec,
)
from opulse.atoms.values import Ok
from opulse.atoms.world import WorldDecl


def observation_library():
    operations = (
        OperationSpec("peek", "decide", (Edge("state"),), Edge("int"), "peek"),
        OperationSpec("add", "transform", (Edge("int"), Edge("int")), Edge("int"), "add"),
    )
    combinator = CombinatorSpec("@apply", ("f", "x"), ("f",), n.Call("f", (n.Var("x"),)))
    world = WorldDecl("round9-observations", 1, "atoms-v2", {}, {}, (), operations,
                      {"nodes": list(n.NODE_NAMES), "recursion": "fuel",
                       "library": (combinator.to_dict(),)},
                      {"truth": "state", "probes": [{"name": "peek"}]}, {},
                      open_kinds=("operation", "observation", "bridge"))
    return Library(world, (kernel.Atom("peek", 1, lambda state: state["visible"], kind="observation"),
                           kernel.Atom("add", 2, lambda left, right: left + right)))


def private_observation(name, body, dependencies):
    return Definition(name, "observation", "invented", 2, dependencies,
                      ObservationSpec(name, ("peek",), body), body)


def test_private_subject_cannot_enter_public_observation_at_check_time():
    lib = observation_library()
    public_body = n.Var("value")
    lib.write(Definition("public", "observation", "invented", 1, (),
                         ObservationSpec("public", (), public_body, extra={"inputs": (("value", "int"),)}),
                         public_body))
    lib.check("public")
    lib.make_callable("public", ((1,),))
    leak = private_observation("leak", n.Call("public", (n.Var("s"),)), ("public",))
    lib.write(leak)

    with pytest.raises(PipelineError, match=r"subject s.*public observation public"):
        lib.check("leak")
    assert lib.get("leak").status == "written"


@pytest.mark.parametrize("callee, body, dependencies", (
    ("add", n.Call("add", (n.Var("s"), n.Lit(1))), ("add",)),
    ("@apply", n.Call("@apply", (n.Lit(kernel.FnRef("add")), n.Var("s"))),
     ("@apply", "add")),
    ("translate", n.Call("translate", (n.Var("s"),)), ("translate",)),
))
def test_subject_cannot_enter_operations_combinators_or_bridges(callee, body, dependencies):
    lib = observation_library()
    if callee == "translate":
        spec = BridgeSpec("translate", "int", "int", n.Var("x"))
        lib._definitions[callee] = Definition(callee, "bridge", "invented", 1, (), spec, n.Var("x"))
    definition = private_observation("leak", body, dependencies)
    assert any("subject s may only be passed to probes and observations" in problem
               for problem in check_observation(definition, lib))


@settings(deadline=None, max_examples=12)
@given(st.integers(-20, 20), st.integers(-20, 20), st.integers(1, 20))
def test_pure_operation_observation_verifies_non_interference(visible, first_secret, secret_delta):
    lib = observation_library()
    body = n.Call("add", (n.Call("peek", (n.Var("s"),)), n.Lit(1)))
    lib.write(private_observation("seen_plus_one", body, ("peek", "add")))
    lib.check("seen_plus_one")
    states = ({"visible": visible, "secret": first_secret},
              {"visible": visible, "secret": first_secret + secret_delta})
    lib.make_callable("seen_plus_one", ((states[0],),))
    verified = lib.verify("seen_plus_one", VerifyRequest(
        "bounded", tuple((state,) for state in states), {"domain": "paired hidden states", "size": 2},
        extra={"states": (states,)}))

    assert {"dependency", "non_interference", "facts_unchanged", "unfold_equivalence"} <= set(
        verified.evidence.checks)
    assert verified.evidence.scope["reference"] == "none"
    assert lib.run("seen_plus_one", (states[0],)).outcome == Ok(visible + 1)


def test_leaking_reference_fails_verification(monkeypatch):
    """Pure deterministic operations receive only probe values, so cannot read a hidden field.

    A leaking implementation needs an impure host atom, outside the declared host contract.
    Substitute a hand-built leaking execution agreeing with a leaking reference and check
    that verification still rejects indistinguishable states with different results.
    """
    from opulse.atoms import observations

    lib = observation_library()
    body = n.Call("add", (n.Call("peek", (n.Var("s"),)), n.Lit(1)))
    lib.write(private_observation("seen_plus_one", body, ("peek", "add")))
    lib.check("seen_plus_one")
    states = ({"visible": 3, "secret": 0}, {"visible": 3, "secret": 9})
    lib.make_callable("seen_plus_one", ((states[0],),))
    reference = lambda state: state["secret"]

    def leaking_run(definition, library, history, *, inline=False):
        return [Ok(reference(state)) for state in history], [0 for state in history]

    monkeypatch.setattr(observations, "_run", leaking_run)

    with pytest.raises(PipelineError, match="non_interference: indistinguishable states differ"):
        lib.verify("seen_plus_one", VerifyRequest(
            "bounded", tuple((state,) for state in states), {"domain": "paired hidden states", "size": 2},
            reference=reference, extra={"states": (states,)}))
    assert lib.get("seen_plus_one").status == "callable"
