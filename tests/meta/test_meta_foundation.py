"""Foundation checks for opulse.meta.code and the vn/1 reference (docs/spec/atoms-meta.md)."""

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.values import Card
from opulse.meta import code as C
from opulse.meta.vn import reference as R


def _atoms(*names):
    return lambda name: C.Resolved(digest="d-" + name) if name in names else None


def test_code_round_trip_and_alpha_invariance():
    body_a = n.Let("t", n.Call("add", (n.Var("a"), n.Lit(1))), n.Call("add", (n.Var("t"), n.Var("b"))))
    body_b = n.Let("q", n.Call("add", (n.Var("x"), n.Lit(1))), n.Call("add", (n.Var("q"), n.Var("y"))))
    sig = C.sig_op([("int", "bottom"), ("int", "bottom")], ("int", "bottom"))
    a = C.make_code("operation", sig, ("a", "b"), body_a, _atoms("add"))
    b = C.make_code("operation", sig, ("x", "y"), body_b, _atoms("add"))
    assert a == b and C.code_hash(a) == C.code_hash(b)
    assert C.is_canonical(a)
    decoded = C.decode(a)
    assert decoded.main.params == ("x0", "x1")
    run = kernel.call(decoded.main.name, (3, 4), kernel.DictScope(
        [kernel.Atom("add", 2, lambda x, y: x + y)], [decoded.main]))
    assert run.outcome.value == 8 and run.steps == 2


def test_modified_body_changes_hash_and_deps_are_merkle():
    sig1 = C.sig_op([("int", "bottom")], ("int", "bottom"))
    inc = C.make_code("operation", sig1, ("x",), n.Call("add", (n.Var("x"), n.Lit(1))), _atoms("add"))
    inc2 = C.make_code("operation", sig1, ("x",), n.Call("add", (n.Var("x"), n.Lit(2))), _atoms("add"))
    assert C.code_hash(inc) != C.code_hash(inc2)

    def resolver(dep):
        return lambda name: C.Resolved(code=dep) if name == "inc" else _atoms("add")(name)

    twice1 = C.make_code("operation", sig1, ("x",), n.Call("inc", (n.Call("inc", (n.Var("x"),)),)), resolver(inc))
    twice2 = C.make_code("operation", sig1, ("x",), n.Call("inc", (n.Call("inc", (n.Var("x"),)),)), resolver(inc2))
    assert C.code_hash(twice1) != C.code_hash(twice2)
    assert C.decode(twice1).main.body.fn == "#" + C.code_hash(inc)
    assert C.canonicalize(twice1) == twice1


def test_rec_and_blocks_canonical_names():
    rec = n.Rec("loop", ("i", "acc"), n.Case(((n.Test(n.Call("is_zero", (n.Var("i"),))), n.Var("acc")),),
                                             n.Call("loop", (n.Call("dec", (n.Var("i"),)), n.Var("acc")))),
                (n.Var("p"), n.Lit(0)), "fuel")
    code = C.make_code("operation", C.sig_op([("int", "bottom")], ("int", "bottom")), ("p",), rec,
                       _atoms("is_zero", "dec"))
    node = C.decode(code).main.body
    assert node.fn == "r0" and node.params == ("v0", "v1")
    blocks = n.Blocks((("k", n.Var("p")),), "top", (
        ("done", n.Block((), n.Halt(n.Var("k")))),
        ("top", n.Block((("k", n.Call("dec", (n.Var("k"),))),),
                        n.CondJump(n.Test(n.Call("is_zero", (n.Var("k"),))), "done", "top")))))
    code = C.make_code("operation", C.sig_op([("int", "bottom")], ("int", "bottom")), ("p",), blocks,
                       _atoms("is_zero", "dec"))
    node = C.decode(code).main.body
    assert node.entry == "l0" and [label for label, _ in node.blocks] == ["l1", "l0"]


def test_unbound_name_and_bad_card_rejected():
    import pytest

    with pytest.raises(C.CodeError):
        C.make_code("operation", C.sig_op([], ("int", "bottom")), (), n.Call("nope", ()), _atoms())
    with pytest.raises(C.CodeError):
        C.decode_node(Card("expr", "call", ("f",)))


def test_vn_reference_self_modifying_sum():
    # ADD reads a byte of its own code, then the program patches the ADD operand (address 3)
    prog = [1, 0, 4, 12, 3, 15, 2, 3, 8, 1, 3, 3, 2, 15, 0, 0]
    s = R.load(prog, 16)
    status, final, steps = R.run(s, 100)
    assert status == "ok" and final.mem[3] == 13 and steps == 8
    assert R.run(R.load([9, 0], 16), 5)[0] == "illegal"
    assert R.run(R.load([6, 0], 16), 50) == ("fuel", None, 50)
