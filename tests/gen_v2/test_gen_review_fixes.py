"""Regression tests for code review 1 of opulse.gen_v2 (out/gen_review/review1.md)."""

from dataclasses import replace

import pytest
from test_gen_admit import X0, _op, _state

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.library import VerifyRequest
from opulse.gen_v2 import fast
from opulse.gen_v2.admit import admit, domain_request
from opulse.gen_v2.base import Entry, Rejection, Sort
from opulse.gen_v2.codec import (
    decode_checkpoint_value,
    decode_value,
    encode_checkpoint_value,
    encode_value,
)
from opulse.gen_v2.run import load, save

SQUARE_PLUS_ONE = n.Call("add", (n.Call("mul", (X0, X0)), n.Lit(1)))


def test_given_combinator_json_lists_remain_parseable_and_frozen():
    from opulse.gen_v2.library import GenLibrary
    from opulse.gen_v2.worlds import hidden

    world = hidden.gen_world()
    library = GenLibrary(hidden.world.decl(), world.atoms, world.dialect, world.extra_scope)
    assert library.get("bind").kind == "combinator"
    with pytest.raises(TypeError, match="immutable"):
        library.world.combinators["library"][0]["body"]["params"].append("extra")


def test_generated_operation_claims_no_independent_reference():  # review 1 #3
    state = _state()
    entry = admit(state, _op("f1", ("int",), "int", SQUARE_PLUS_ONE, 1))
    evidence = state.library.get(entry.name).evidence
    assert evidence.checks == ("unfold_equivalence",)
    assert evidence.scope["reference"].startswith("none")


def test_exhaustive_claim_must_cover_the_full_probe_domain():  # review 1 #2
    state = _state()
    candidate = _op("f1", ("int",), "int", SQUARE_PLUS_ONE, 1)
    candidate.request = VerifyRequest("exhaustive", ((0,), (1,), (2,)), {"domain": "all integers -3..8", "size": 3})
    result = admit(state, candidate)
    assert isinstance(result, Rejection) and "certified finite" in result.reason


def test_extra_atoms_cannot_replace_existing_names_and_refusal_keeps_state():  # review 1 #5, #7
    state = _state()
    admit(state, _op("f1", ("int",), "int", SQUARE_PLUS_ONE, 1))
    with pytest.raises(ValueError):
        state.library.add_atoms((kernel.Atom("add", 2, lambda a, b: a - b),))
    candidate = _op("f2", ("int",), "int", n.Call("add", (X0, n.Lit(3))), 1)
    candidate.new_sorts = [Sort("int", (999,))]
    result = admit(state, candidate)
    assert isinstance(result, Rejection) and "already taken" in result.reason
    assert state.sorts["int"].values[0] == -3
    assert kernel.call("f1", (2,), state.library.scope()).outcome.value == 5


def test_review4_7_duplicate_new_atoms_are_atomically_rejected():
    state = _state()
    with pytest.raises(ValueError, match="duplicate extra atom"):
        state.library.add_atoms((kernel.Atom("probe", 1, abs), kernel.Atom("probe", 1, abs)))
    assert state.library.scope().resolve("probe") is None


def test_world_changed_in_place_resets_evidence():  # review 1 #6
    state = _state()
    admit(state, _op("f1", ("int",), "int", SQUARE_PLUS_ONE, 1))
    with pytest.raises(TypeError, match="immutable"):
        state.library.world.constants["foo"] = 123
    assert state.library.get("f1").status == "promoted"


def test_fast_evaluation_rejects_unknown_dialects():  # review 1 #9
    with pytest.raises(ValueError):
        fast.deep(fast.evaluate, n.Lit(1), {}, kernel.DictScope(), 10, "typo")


def test_published_keep_flag_needs_the_importer():  # review 1 #10
    state = _state()
    candidate = _op("f1", ("int",), "int", n.Call("neg", (n.Call("neg", (X0,)),)), 1)
    candidate.meta["legacy_keep"] = True
    assert isinstance(admit(state, candidate), Rejection)
    again = _op("f2", ("int",), "int", n.Call("neg", (n.Call("neg", (X0,)),)), 1)
    again.meta["legacy_keep"] = True
    with pytest.raises(TypeError):
        admit(state, again, keep_published=True)
    assert isinstance(admit(state, again), Rejection)


def test_review4_2_unbounded_probes_are_bounded():
    state = _state()
    request = domain_request(state, _op("f1", ("int",), "int", SQUARE_PLUS_ONE, 1).signature)
    assert request.method == "bounded" and "probe" in request.scope["domain"]
    assert len(request.domain) == 12


def test_review4_2_certified_finite_sort_can_be_exhaustive():
    from opulse.gen_v2.base import Signature

    state = _state()
    state.sorts["bool"].finite = True
    request = domain_request(state, Signature(("bool",), "bool"))
    assert request.method == "exhaustive"
    assert request.domain == ((False,), (True,))


def test_review4_2_direct_library_cannot_spoof_exhaustive_scope():
    state = _state()
    candidate = _op("f1", ("int",), "int", SQUARE_PLUS_ONE, 1)
    library = state.library
    library.write(candidate.defn)
    library.check("f1")
    library.make_callable("f1", ((0,),))
    request = VerifyRequest("exhaustive", tuple((value,) for value in state.sorts["int"].values),
                            {"domain": "all integers", "size": len(state.sorts["int"].values)})
    with pytest.raises(ValueError, match="certified finite"):
        library.verify("f1", request)


def test_review4_3_self_and_aliased_references_are_not_independent():
    state = _state()
    for name, reference in (("f1", "f1"), ("f2", lambda value: value * value + 1)):
        candidate = _op(name, ("int",), "int", SQUARE_PLUS_ONE, 1)
        candidate.request = replace(domain_request(state, candidate.signature), reference=reference)
        result = admit(state, candidate)
        assert isinstance(result, Rejection) and result.stage == "verify"
    given = _op("f3", ("int",), "int", SQUARE_PLUS_ONE, 1)
    given.request = replace(domain_request(state, given.signature), reference="mul")
    assert isinstance(admit(state, given), Rejection)


def test_review4_3_oracle_origin_is_required_for_reference_evidence():
    state = _state()
    candidate = _op("f1", ("int",), "int", SQUARE_PLUS_ONE, 1)
    candidate.request = replace(domain_request(state, candidate.signature),
                                reference=lambda value: value * value + 1,
                                extra={"reference_origin": "oracle"})
    result = admit(state, candidate)
    assert isinstance(result, Entry)
    assert "reference" in state.library.get(result.name).evidence.checks


def test_review4_3_same_body_alias_is_not_an_independent_reference():
    state = _state()
    assert isinstance(admit(state, _op("f1", ("int",), "int", SQUARE_PLUS_ONE, 1)), Entry)
    candidate = _op("f2", ("int",), "int", SQUARE_PLUS_ONE, 1)
    candidate.request = replace(domain_request(state, candidate.signature), reference="f1")
    result = admit(state, candidate)
    assert result.stage == "verify" and "not independent" in result.reason


def test_review4_3_direct_verifier_cannot_record_self_reference():
    state = _state()
    candidate = _op("f1", ("int",), "int", SQUARE_PLUS_ONE, 1)
    library = state.library
    library.write(candidate.defn)
    library.check("f1")
    library.make_callable("f1", ((0,),))
    request = replace(domain_request(state, candidate.signature), reference="f1")
    with pytest.raises(ValueError, match="not independent"):
        library.verify("f1", request)


def test_review4_6_world_is_recursively_immutable():
    state = _state()
    world = state.library.world
    for action in (lambda: world.observation["probes"].append("object"),
                   lambda: world.combinators["nodes"].append("Bad"),
                   lambda: world.constants.update({"changed": 1})):
        with pytest.raises((TypeError, AttributeError)):
            action()


def test_review4_6_export_rechecks_the_original_world_hash(tmp_path):
    from opulse.gen_v2.export import export

    state = _state()
    assert isinstance(admit(state, _op("f1", ("int",), "int", SQUARE_PLUS_ONE, 1)), Entry)
    state.world.decl.constants["changed"] = 1
    with pytest.raises(ValueError, match="world declaration changed"):
        export(state, tmp_path / "bad.json")


def test_review4_10_published_metadata_is_not_a_keep_token():
    state = _state()
    candidate = _op("f1", ("int",), "int", n.Call("neg", (n.Call("neg", (X0,)),)), 1)
    candidate.meta.update(legacy_keep=True, legacy={"func_id": "f1"})
    assert isinstance(admit(state, candidate, _import_token=object()), Rejection)


def test_review4_14_memo_tag_does_not_bypass_duplicates():
    state = _state()
    assert isinstance(admit(state, _op("f1", ("int",), "int", SQUARE_PLUS_ONE, 1)), Entry)
    second = _op("f2", ("int",), "int", SQUARE_PLUS_ONE, 1)
    second.meta["memo_of"] = "f1"
    assert admit(state, second).stage == "duplicate"


def test_review4_14_only_matching_memo_recursion_bypasses_duplicate():
    state = _state()
    variable = n.Var("k")
    previous = n.Call("dec", (variable,))
    plain = n.Rec("loop", ("k",), n.Case(((n.Test(n.Call("is_pos", (variable,))),
                                          n.Call("add", (n.Call("loop", (previous,)),
                                                         n.Call("loop", (previous,))))),), n.Lit(1)),
                  (n.Call("absv", (X0,)),), n.Call("absv", (variable,)))
    assert isinstance(admit(state, _op("f1", ("int",), "int", plain, 1)), Entry)
    memo = _op("f2", ("int",), "int", replace(plain, memo=True), 1)
    memo.meta["memo_of"] = "f1"
    assert isinstance(admit(state, memo), Entry)
    mismatched = _op("f3", ("int",), "int", plain, 1)
    mismatched.meta["memo_of"] = "f2"
    assert admit(state, mismatched).stage == "duplicate"
    repeated = _op("f4", ("int",), "int", replace(plain, memo=True), 1)
    repeated.meta["memo_of"] = "f1"
    assert admit(state, repeated).stage == "duplicate"


def test_review4_14_memo_without_work_savings_is_duplicate():
    state = _state()
    variable = n.Var("k")
    plain = n.Rec("loop", ("k",), n.Case(((n.Test(n.Call("is_pos", (variable,))),
                                          n.Call("add", (n.Call("loop", (n.Call("dec", (variable,)),)),
                                                         variable))),), n.Lit(0)),
                  (n.Call("absv", (X0,)),), n.Call("absv", (variable,)))
    assert isinstance(admit(state, _op("f1", ("int",), "int", plain, 1)), Entry)
    memo = _op("f2", ("int",), "int", replace(plain, memo=True), 1)
    memo.meta["memo_of"] = "f1"
    assert admit(state, memo).stage == "duplicate"


def test_memo_admission_reuses_candidate_runs_instead_of_evaluating_both_bodies(monkeypatch):
    state = _state()
    variable = n.Var("k")
    previous = n.Call("dec", (variable,))
    plain = n.Rec("loop", ("k",), n.Case(((n.Test(n.Call("is_pos", (variable,))),
                                          n.Call("add", (n.Call("loop", (previous,)),
                                                         n.Call("loop", (previous,))))),), n.Lit(1)),
                  (n.Call("absv", (X0,)),), n.Call("absv", (variable,)))
    assert isinstance(admit(state, _op("f1", ("int",), "int", plain, 1)), Entry)
    candidate = _op("f2", ("int",), "int", replace(plain, memo=True), 1)
    candidate.meta["memo_of"] = "f1"
    calls = []
    evaluate = kernel.evaluate

    def counted(node, *args, **kwargs):
        if isinstance(node, n.Rec):
            calls.append(node.memo)
        return evaluate(node, *args, **kwargs)

    monkeypatch.setattr(kernel, "evaluate", counted)
    assert isinstance(fast.deep(admit, state, candidate), Entry)
    assert calls == [False] * len(state.requests["f1"].domain)


def test_review4_16_vocabulary_changes_with_probe_values():
    from opulse.gen_v2 import vocab

    state = _state()
    assert "is_zero" in vocab.zero_test(state, "int")
    state.sorts["int"].values = (1, 2)
    assert "is_zero" not in vocab.zero_test(state, "int")
    state.sorts["int"].values = (0, 2)
    assert "is_zero" in vocab.zero_test(state, "int")


def test_review4_17_checkpoint_restores_exact_requests(tmp_path):
    state = _state()
    assert isinstance(admit(state, _op("f1", ("int",), "int", SQUARE_PLUS_ONE, 1)), Entry)
    path = tmp_path / "checkpoint.json"
    save(state, path)
    restored = load(state.world, path)
    assert restored.requests["f1"].domain == state.requests["f1"].domain
    assert restored.requests["f1"].scope == state.requests["f1"].scope
    assert restored.requests["f1"].method == "bounded"


def test_review4_18_display_only_host_values_cannot_be_checkpointed(tmp_path):
    from opulse.atoms.values import Card

    for value in (3, (3, Card("bool", "true")), kernel.FnRef("add")):
        assert decode_value(encode_value(value)) == value
    for value in (True, (False, Card("pair", "one", (True,)))):
        assert decode_checkpoint_value(encode_checkpoint_value(value)) == value
    state = _state()
    state.sorts["invented"] = Sort("invented", ({"host": "not reversible"},), origin="invented")
    with pytest.raises(ValueError, match="display-only host"):
        save(state, tmp_path / "bad.json")
    state.sorts.pop("invented")
    entry = admit(state, _op("f1", ("int",), "int", SQUARE_PLUS_ONE, 1))
    assert isinstance(entry, Entry)
    entry.examples.append(((object(),), {"ok": {"t": "int", "v": 1}}, 1))
    with pytest.raises(ValueError, match="display-only host"):
        save(state, tmp_path / "bad_example.json")


def test_review4_19_reasons_name_their_sample_basis():
    from opulse.gen_v2.curate import _why

    state = _state()
    entry = admit(state, _op("f1", ("int",), "int", SQUARE_PLUS_ONE, 1))
    assert isinstance(entry, Entry)
    reason = _why(state, entry)
    assert "direct invented dependents" in reason
    assert f"mean of {len(state.requests['f1'].domain)} verified runs" in reason


def test_review4_11_mutating_atom_is_rejected_without_touching_probe_inputs():
    state = _state()
    state.sorts["int"].values = ([1], [2])

    def mutate(value):
        value.append(9)
        return len(value)

    state.library.add_atoms((kernel.Atom("mutate", 1, mutate),))
    candidate = _op("f1", ("int",), "int", n.Call("mutate", (X0,)), 1)
    result = admit(state, candidate)
    assert result.stage == "callable" and "impure atom mutates its argument" in result.reason
    assert state.sorts["int"].values == ([1], [2])


def test_review4_11_mutating_reference_is_rejected_as_impure():
    state = _state()
    state.library.add_atoms((kernel.Atom("length", 1, len),))
    candidate = _op("f1", ("int",), "int", n.Call("length", (X0,)), 1)

    def reference(value):
        value.append(99)
        return len(value) - 1

    domain = (([1],), ([2, 3],))
    candidate.request = VerifyRequest("bounded", domain, {"domain": "two probe lists", "size": 2},
                                      reference=reference, extra={"reference_origin": "oracle"})
    state.library.write(candidate.defn)
    state.library.check("f1")
    state.library.make_callable("f1", domain)
    with pytest.raises(ValueError, match="impure atom mutates its argument"):
        state.library.verify("f1", candidate.request)
    assert domain == (([1],), ([2, 3],))
    pure = replace(candidate.request, reference=lambda value: len(value))
    verified = state.library.verify("f1", pure)
    assert "reference" in verified.evidence.checks


def test_review4_15_uncached_calls_reexecute_impure_atoms_and_cache_hits_do_no_work():
    from opulse.gen_v2 import fast

    count = []
    scope = kernel.DictScope((kernel.Atom("bump", 1, lambda value: count.append(value) or len(count)),),
                             (kernel.Defn("f", ("x0",), n.Call("bump", (X0,))),))

    def check():
        assert fast.call("f", (1,), scope, 10).outcome.value == 1
        assert fast.call("f", (1,), scope, 10).outcome.value == 2
        assert count == [1, 1]

    fast.deep(check)


def test_review4_17_missing_request_fails_audit():
    from opulse.gen_v2.audit import audit

    state = _state()
    assert isinstance(admit(state, _op("f1", ("int",), "int", SQUARE_PLUS_ONE, 1)), Entry)
    state.requests.clear()
    report = audit(state)
    assert not report.ok and any("request unavailable" in issue.detail for issue in report.failures)


def test_review4_17_unrestorable_oracle_fails_replay_closed(tmp_path):
    from opulse.gen_v2.audit import audit

    state = _state()
    candidate = _op("f1", ("int",), "int", SQUARE_PLUS_ONE, 1)
    candidate.request = replace(domain_request(state, candidate.signature),
                                reference=lambda value: value * value + 1,
                                extra={"reference_origin": "oracle"})
    assert isinstance(admit(state, candidate), Entry)
    path = tmp_path / "oracle.json"
    save(state, path)
    restored = load(state.world, path)
    report = audit(restored)
    assert not report.ok and not report.skipped
    assert any("reference unavailable" in failure.detail for failure in report.failures)


def test_nested_operation_reference_round_trips_through_json():
    """Core now encodes FnRef inside card values; such a definition is stored and reloaded intact
    (admission stores the codec form, so a reloaded library is identical)."""
    from opulse.atoms.spec import Definition
    from opulse.atoms.values import Card

    body = n.Let("_c", n.Lit(Card("box", "box", (kernel.FnRef("inc"),))), n.Call("inc", (X0,)))
    candidate = _op("f1", ("int",), "int", body, 1)
    again = Definition.from_dict(candidate.defn.to_dict())
    assert again.body == candidate.defn.body



def test_plugged_operations_enter_the_dependency_hash():  # review 5 #31
    state = _state()
    admit(state, _op("f1", ("int",), "int", n.Call("add", (X0, n.Lit(37))), 1))
    body = n.Call("f", (n.Call("f", (n.Var("x"),)),))
    from opulse.atoms.spec import CombinatorSpec, Definition

    comb = Definition("k2", "combinator", "invented", 1, (), CombinatorSpec("k2", ("f", "x"), ("f",), body), body)
    state.library.write(comb)
    use = _op("f3", ("int",), "int", n.Call("k2", (n.Lit(kernel.FnRef("f1")), X0)), 2)
    state.library.write(use.defn)
    assert "f1" in state.library._uses("f3") and "f1" not in use.defn.depends_on
    before = state.library._deps_hash("f3")
    from dataclasses import replace

    state.library._definitions["f1"] = replace(state.library.get("f1"), body=n.Call("add", (X0, n.Lit(38))))
    assert state.library._deps_hash("f3") != before


def test_generated_combinator_application_lists_plugged_operation():
    from opulse.atoms.spec import CombinatorSpec, Definition
    from opulse.gen_v2.moves.operation import _candidate

    state = _state()
    assert isinstance(admit(state, _op("f1", ("int",), "int", SQUARE_PLUS_ONE, 1)), Entry)
    body = n.Call("slot", (n.Call("slot", (n.Var("x"),)),))
    state.library.write(Definition("k2", "combinator", "invented", 1, (),
                                   CombinatorSpec("k2", ("slot", "x"), ("slot",), body), body))
    application = n.Call("k2", (n.Lit(kernel.FnRef("f1")), n.Var("x0")))
    candidate = _candidate(state, "op.plug", ("int",), "int", application)
    assert candidate is not None
    assert candidate.defn.depends_on == ("f1", "k2")
    assert candidate.defn.layer == state.entries["f1"].layer + 1
    assert not candidate.defn.validate()
