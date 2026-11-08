"""Content identity, world-scoped evidence and immutable promotion (meta spec 3 and 8.I4)."""

from copy import deepcopy
from dataclasses import FrozenInstanceError

import pytest

from opulse.atoms import nodes as n
from opulse.atoms.spec import Contract, Evidence
from opulse.atoms.values import Card
from opulse.meta import code as c
from opulse.meta.identity import Ledger, LedgerError, dependency_hash, edit


def program(value=1):
    return c.make_code("operation", c.sig_op([("int", "bottom")], ("int", "bottom")),
                       ("input",), n.Call("add", (n.Var("input"), n.Lit(value))),
                       lambda name: c.Resolved(digest="add-digest") if name == "add" else None)


def evidence(world="world-A", method="exhaustive", program_code=None):
    return Evidence(method, {"domain": "0..2", "size": 3}, 5 if method == "sampled" else None,
                    ("unfold_equivalence",), world, dependency_hash(program_code or program()))


def test_identity_edit_and_promotion_is_content_addressed():
    ledger = Ledger()
    first = ledger.add(program(), "world-A", "increment")
    original = ledger.record(first, "world-A")
    assert original.status == "callable" and original.evidence == () and original.contract is None
    ledger.attach_evidence(first, "world-A", evidence())
    ledger.promote(first, "world-A", Contract("adds one"))
    promoted = ledger.record(first, "world-A")
    assert promoted.status == "promoted" and promoted.evidence == (evidence(),)
    assert promoted.contract == Contract("adds one")
    promoted.evidence[0].scope["domain"] = "forged"
    assert ledger.record(first, "world-A").evidence[0].scope["domain"] == "0..2"
    promoted = ledger.record(first, "world-A")
    assert ledger.add(program(), "world-A", "renamed") == first
    assert ledger.record(first, "world-A") == promoted
    changed_code = edit(program(), (2, 1, 1), Card("expr", "lit", (2,)))
    assert changed_code == program(2)
    with pytest.raises(FrozenInstanceError):
        promoted.code = changed_code
    changed = ledger.add(changed_code, "world-A")
    assert changed != first
    assert ledger.record(changed, "world-A").evidence == ()
    with pytest.raises(LedgerError, match="exhaustive or bounded"):
        ledger.promote(changed, "world-A", Contract("changed"))
    ledger.bind("increment", changed)
    assert ledger.resolve("increment") == changed
    assert ledger.history == [("increment", first, changed)]
    assert ledger.record(first, "world-A") == promoted
    with pytest.raises(LedgerError, match="immutable"):
        ledger.attach_evidence(first, "world-A", evidence())
    with pytest.raises(LedgerError, match="immutable"):
        ledger.promote(first, "world-A", Contract("different"))
    with pytest.raises(LedgerError, match="immutable"):
        ledger.promote(first, "world-A", promoted.contract)


def test_world_isolation_sampled_refusal_and_pair_evidence():
    ledger = Ledger()
    first = ledger.add(program(), "world-A", "inc")
    second = ledger.add(program(2), "world-A", "other")
    ledger.attach_evidence(first, "world-A", evidence(method="sampled"))
    with pytest.raises(LedgerError, match="exhaustive or bounded"):
        ledger.promote(first, "world-A", Contract("sampled is insufficient"))
    assert ledger.add(program(), "world-B") == first
    assert ledger.record(first, "world-B").evidence == ()
    with pytest.raises(LedgerError, match="exhaustive or bounded"):
        ledger.promote(first, "world-B", Contract("other world"))
    with pytest.raises(LedgerError, match="world hash"):
        ledger.attach_evidence(first, "world-B", evidence())
    with pytest.raises(LedgerError, match="Contract"):
        ledger.promote(first, "world-A", "not a contract")
    ledger.claim_equivalent(first, second, "world-A", evidence(method="bounded"))
    assert ledger.pair_evidence(second, first, "world-A") == (evidence(method="bounded"),)
    assert ledger.record(first, "world-A").evidence == (evidence(method="sampled"),)
    assert ledger.record(second, "world-A").evidence == ()
    assert ledger.pair_evidence(first, second, "world-B") == ()
    with pytest.raises(LedgerError, match="no record"):
        ledger.claim_equivalent(first, second, "world-B", evidence("world-B"))


def test_round_trip_exact_including_bind_history_and_pairs():
    ledger = Ledger()
    first = ledger.add(program(), "world-A", "inc")
    second = ledger.add(program(2), "world-A")
    ledger.attach_evidence(first, "world-A", evidence(method="bounded"))
    ledger.promote(first, "world-A", Contract("bounded", ("r0",), ("r1",)))
    ledger.add(program(), "world-B")
    ledger.bind("inc", second)
    ledger.claim_equivalent(first, second, "world-A", evidence(method="sampled"))
    data = ledger.to_dict()
    assert data["schema"] == "opulse.ledger/1"
    assert Ledger.from_dict(deepcopy(data)).to_dict() == data
    corrupted = deepcopy(data)
    corrupted["records"][0]["hash"] = "0" * 64
    with pytest.raises(LedgerError, match="record hash"):
        Ledger.from_dict(corrupted)


def test_edit_rejects_invalid_paths_and_keeps_input():
    original = program()
    assert edit(original, (2, 1, 1), Card("expr", "lit", (3,))) == program(3)
    assert original == program()
    for path in ((), (8,), (2, 8), (2, 0, 0)):
        with pytest.raises(LedgerError):
            edit(original, path, Card("expr", "lit", (5,)))
    with pytest.raises(LedgerError, match="binding"):
        Ledger().bind("missing", c.code_hash(program()))


def test_promoted_lookup_feeds_builder_extend():
    from opulse.atoms.spec import Contract, Evidence
    from opulse.meta import code as C
    from opulse.meta.identity import Ledger

    body = C.make_code("operation", C.sig_op([("int", "bottom")], ("int", "bottom")), ("x",),
                       __import__("opulse.atoms.nodes", fromlist=["Var"]).Var("x"), lambda name: None)
    ledger = Ledger()
    digest = ledger.add(body, "w")
    assert ledger.promoted(digest, "w") is None
    evidence = Evidence("exhaustive", {"domain": "0..2", "size": 3}, world_hash="w",
                        deps_hash=ledger.record(digest, "w").deps_hash)
    ledger.attach_evidence(digest, "w", evidence)
    assert ledger.promoted(digest, "w") is None
    ledger.promote(digest, "w", Contract("identity"))
    assert ledger.promoted(digest, "w") == (evidence, Contract("identity"))
    assert ledger.promoted(digest, "other") is None


def test_generator_output_records_its_producer_and_starts_without_evidence():
    from opulse.atoms import nodes as n
    from opulse.meta import code as C
    from opulse.meta.identity import Ledger

    sig = C.sig_op([("int", "bottom")], ("int", "bottom"))
    source = C.make_code("operation", sig, ("x",), n.Call("add", (n.Lit(1), n.Lit(2))),
                         lambda name: C.Resolved(digest="d") if name == "add" else None)
    folded = C.make_code("operation", sig, ("x",), n.Lit(3), lambda name: None)
    ledger = Ledger()
    world = "w"
    generator = "f" * 64
    source_hash = ledger.add(source, world)
    out = ledger.add(folded, world, produced_by=(generator, source_hash))
    record = ledger.record(out, world)
    assert record.produced_by == (generator, source_hash)
    assert record.evidence == () and record.status == "callable"
    assert Ledger.from_dict(ledger.to_dict()).record(out, world) == record


def test_unbound_evidence_is_bound_to_the_record_and_forged_hash_is_refused():
    import pytest

    from opulse.atoms import nodes as n
    from opulse.atoms.spec import Evidence
    from opulse.meta import code as C
    from opulse.meta.identity import Ledger, LedgerError, dependency_hash

    code = C.make_code("operation", C.sig_op([("int", "bottom")], ("int", "bottom")), ("x",), n.Var("x"),
                       lambda name: None)
    ledger = Ledger()
    digest = ledger.add(code, "w")
    with pytest.raises(LedgerError, match="dependency hash"):
        ledger.attach_evidence(digest, "w", Evidence("exhaustive", {"domain": "0..2", "size": 3},
                                                     world_hash="w", deps_hash="forged"))
    ledger.attach_evidence(digest, "w", Evidence("exhaustive", {"domain": "0..2", "size": 3}, world_hash="w"))
    assert ledger.record(digest, "w").evidence[0].deps_hash == dependency_hash(code)
