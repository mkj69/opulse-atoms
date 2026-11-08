"""Ledger promotion requires evidence over at least one input (meta spec 3.3)."""

from dataclasses import replace

import pytest

from opulse.atoms.nodes import Lit
from opulse.atoms.spec import Contract, Evidence
from opulse.meta.code import make_code, sig_op
from opulse.meta.identity import Ledger, LedgerError

EMPTY_SCOPES = [{"domain": [], "size": 0}, {"domain": [], "size": 2}, {"domain": "0..2", "size": 0},
                {"domain": "0..2", "size": True}, {"domain": [0], "size": -1}]


def ledger_with_code():
    ledger = Ledger()
    program = make_code("operation", sig_op((), ("int", "bottom")), (), Lit(1), lambda _: None)
    return ledger, ledger.add(program, "w")


@pytest.mark.parametrize("scope", EMPTY_SCOPES)
@pytest.mark.parametrize("method", ["exhaustive", "bounded"])
def test_attach_refuses_empty_promotion_scope(scope, method):
    ledger, digest = ledger_with_code()
    with pytest.raises(LedgerError, match="scope.size > 0"):
        ledger.attach_evidence(digest, "w", Evidence(method, scope, world_hash="w"))
    assert ledger.record(digest, "w").status == "callable" and ledger.record(digest, "w").evidence == ()


def test_promote_rechecks_scope_of_attached_evidence():
    ledger, digest = ledger_with_code()
    ledger.attach_evidence(digest, "w", Evidence("bounded", {"domain": [0], "size": 1}, world_hash="w"))
    original = ledger.record(digest, "w")
    ledger._records[digest, "w"] = replace(original, evidence=(
        replace(original.evidence[0], scope={"domain": [], "size": 0}),))
    with pytest.raises(LedgerError, match="exhaustive or bounded"):
        ledger.promote(digest, "w", Contract("one"))
    assert ledger.record(digest, "w").status == "verified"


@pytest.mark.parametrize("scope", EMPTY_SCOPES)
def test_from_dict_refuses_promoted_record_with_empty_scope(scope):
    ledger, digest = ledger_with_code()
    ledger.attach_evidence(digest, "w", Evidence("bounded", {"domain": [0], "size": 1}, world_hash="w"))
    ledger.promote(digest, "w", Contract("one"))
    payload = ledger.to_dict()
    payload["records"][0]["evidence"][0]["scope"] = scope
    with pytest.raises(LedgerError, match="invalid record status or promotion"):
        Ledger.from_dict(payload)


def test_nonempty_scope_promotes_and_round_trips():
    ledger, digest = ledger_with_code()
    ledger.attach_evidence(digest, "w", Evidence("exhaustive", {"domain": "0..2", "size": 3}, world_hash="w"))
    ledger.promote(digest, "w", Contract("one"))
    assert Ledger.from_dict(ledger.to_dict()).record(digest, "w") == ledger.record(digest, "w")


def test_sampled_evidence_never_promotes():
    ledger, digest = ledger_with_code()
    ledger.attach_evidence(digest, "w", Evidence("sampled", {"domain": [], "size": 0}, seed=0, world_hash="w"))
    with pytest.raises(LedgerError, match="exhaustive or bounded"):
        ledger.promote(digest, "w", Contract("not proved"))
