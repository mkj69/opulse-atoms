import pytest

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.spec import Definition, Edge, OperationSpec
from opulse.atoms.values import Ok
from opulse.gen_v2.admit import admit
from opulse.gen_v2.base import Candidate, Entry, GenState, Rejection, Signature
from opulse.gen_v2.library import GenLibrary
from opulse.gen_v2.worlds import toy


def _state(open_kinds=("object", "operation", "combinator", "observation")):
    world = toy.gen_world(open_kinds)
    return GenState(world, GenLibrary(world.decl, world.atoms, world.dialect), dict(world.sorts))


def _op(name, ins, out, body, layer):
    spec = OperationSpec(name, "transform", tuple(Edge(sort) for sort in ins), Edge(out), "generated",
                         extra={"input_names": [f"x{i}" for i in range(len(ins))]})
    defn = Definition(name, "operation", "invented", layer, tuple(sorted(n.references(body))), spec, body)
    return Candidate(defn, Signature(ins, out), "op.test")


X0, X1 = n.Var("x0"), n.Var("x1")


def test_admit_promotes_with_evidence_and_layers():
    state = _state()
    first = admit(state, _op("f1", ("int", "int"), "int", n.Call("add", (n.Call("mul", (X0, X0)), X1)), 1))
    second = admit(state, _op("f2", ("int",), "int", n.Call("f1", (X0, n.Call("inc", (X0,)))), 2))
    assert isinstance(first, Entry) and isinstance(second, Entry)
    record = state.library.get("f2")
    assert record.status == "promoted" and record.evidence.method == "bounded"
    assert state.entries["f1"].reuse == 1


def test_admit_rejects_identity_duplicate_and_closed_kind():
    state = _state()
    assert admit(state, _op("f3", ("int",), "int", n.Call("neg", (n.Call("neg", (X0,)),)), 1)).stage == "degenerate"
    assert "f3" not in state.library.definitions
    assert isinstance(admit(state, _op("f4", ("int",), "int", n.Call("add", (X0, X0)), 1)), Entry)
    duplicate = admit(state, _op("f5", ("int",), "int", n.Call("sub", (n.Call("add", (X0, X0)), n.Lit(0))), 1))
    assert isinstance(duplicate, Rejection) and duplicate.stage == "duplicate"
    closed = _state(("operation",))
    from opulse.atoms.spec import CombinatorSpec

    body = n.Call("f", (n.Call("f", (n.Var("x"),)),))
    comb = Definition("k1", "combinator", "invented", 1, (), CombinatorSpec("k1", ("f", "x"), ("f",), body), body)
    assert admit(closed, Candidate(comb, None, "comb.test")).stage == "closed_kind"


def test_measured_recursion_is_admitted():
    state = _state()
    k = n.Var("k")
    rec = n.Rec("loop", ("k",), n.Case(((n.Test(n.Call("is_pos", (k,))),
                                         n.Call("add", (n.Call("loop", (n.Call("dec", (k,)),)), k))),), n.Lit(0)),
                (n.Call("absv", (X0,)),), n.Call("absv", (k,)))
    entry = admit(state, _op("f6", ("int",), "int", rec, 1))
    assert isinstance(entry, Entry) and entry.steps_max > entry.steps_mean > 0


def test_sealed_sort_inside_is_refused_outside_its_interface():
    from opulse.atoms.spec import ObjectSpec
    from opulse.atoms.values import Card
    from opulse.gen_v2.base import Sort
    from opulse.gen_v2.kinds.objects import object_atoms

    state = _state()
    spec = ObjectSpec("A1", "compose", tags={"pair": [["left", "int"], ["right", "int"]]}, sealed=True,
                      interface=("A1.pair", "A1.left"))
    atoms, signatures = object_atoms(spec, state)
    body = n.Call("A1.pair", (n.Lit(0), n.Lit(1)))
    values = tuple(Card("A1", "pair", (a, b)) for a in range(3) for b in range(3))
    from opulse.atoms.library import VerifyRequest

    request = VerifyRequest("bounded", tuple((value,) for value in values), {"domain": "pairs", "size": len(values)})
    obj = Candidate(Definition("A1", "object", "invented", 1, ("A1.pair",), spec, body), None, "obj.test", request,
                    atoms, [Sort("A1", values, "invented", "A1", ("A1.pair",), ("A1.left", "A1.right"), ("A1.is_pair",),
                                 True, spec.interface)], extra_signatures=signatures)
    assert isinstance(admit(state, obj), Entry)
    inside = _op("f2", ("A1",), "int", n.Call("add", (n.Call("A1.right", (X0,)), n.Lit(1))), 1)
    refused = admit(state, inside)
    assert isinstance(refused, Rejection) and refused.stage == "check" and "sealed" in refused.reason
    from opulse.atoms.library import PipelineError

    with pytest.raises(PipelineError, match="sealed object private name"):
        state.library.run("A1.right", (Card("A1", "pair", (0, 7)),))
    assert kernel.call("A1.right", (Card("A1", "pair", (0, 7)),),
                       state.library.scope()).outcome == Ok(7)
    allowed = _op("f3", ("A1",), "int", n.Call("add", (n.Call("A1.left", (X0,)), n.Lit(1))), 2)
    assert isinstance(admit(state, allowed), Entry)
