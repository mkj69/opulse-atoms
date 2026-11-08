"""Regressions for the real Git model and oracle."""

from dataclasses import replace
from pathlib import Path

import pytest

from opulse.worlds_real.git import Repository
from opulse.worlds_real.git.oracle import Scenario, check_case
from opulse.worlds_real.git.showcase import showcases, verify_showcase


@pytest.fixture
def checked_library():
    from opulse.worlds_real.git.world import DEFINITIONS, build_library

    library = build_library()
    for definition in DEFINITIONS:
        library.write(definition)
        assert library.check(definition.name).status == "checked"
    return library


def test_refinement_dependencies_declare_their_validators(checked_library):
    assert checked_library.get("Edit").depends_on == ("valid_edit",)
    assert checked_library.get("MergeReview").depends_on == ("valid_result", "classify_atom")


def test_oracle_uses_system_temporary_directory(monkeypatch):
    from opulse.worlds_real.git import oracle

    original = oracle.tempfile.TemporaryDirectory

    def checked_directory(*args, **kwargs):
        if kwargs.get("prefix") == "opulse-git-oracle-":
            assert Path(kwargs["dir"]).is_absolute()
            assert not Path(kwargs["dir"]).is_relative_to(Path(__file__).resolve().parents[3])
        return original(*args, **kwargs)

    monkeypatch.setattr(oracle.tempfile, "TemporaryDirectory", checked_directory)
    check_case(Scenario({"a": "zero\n"}, ({"a": "one\n"},), ({"a": "topic\n"},)))


def test_oracle_ignores_tmpdir_inside_source_tree(monkeypatch):
    from opulse.worlds_real.git import oracle

    monkeypatch.setattr(oracle.tempfile, "gettempdir", lambda: str(Path(__file__).resolve().parents[3]))
    assert oracle._temp_root() == Path("/tmp")


def test_rebase_status_after_prior_commit():
    check_case(Scenario({"a": "zero\n", "b": "zero\n"},
                        ({"a": "main\n", "b": "zero\n"},),
                        ({"a": "zero\n", "b": "topic\n"}, {"b": "topic\n"})),
               rebase_sequence=True)


def test_first_parent_log_after_merge():
    repo = Repository()
    repo.add("base", (), {"a": "zero\n"})
    repo.add("main", ("base",), {"a": "main\n"})
    repo.add("topic", ("base",), {"a": "zero\n", "b": "topic\n"})
    repo.add("merge", ("main", "topic"), {"a": "main\n", "b": "topic\n"})
    assert repo.log("merge") == ("merge", "main", "base")
    check_case(Scenario({"a": "zero\n"}, ({"a": "main\n"},),
                        ({"a": "zero\n", "b": "topic\n"},)))


@pytest.mark.parametrize("path", ["\u00e9.txt", "tab\tname.txt", "quote\"name.txt"])
def test_oracle_handles_quoted_git_paths(path):
    check_case(Scenario({path: "zero\n"}, ({path: "main\n"},), ({path: "topic\n"},)))


def test_reject_file_directory_collision():
    with pytest.raises(ValueError, match="invalid regular text tree"):
        Repository().add("bad", (), {"a": "file\n", "a/b": "child\n"})


@pytest.mark.parametrize("path", ["a//b", "a/./b", "."])
def test_reject_noncanonical_git_paths(path):
    with pytest.raises(ValueError, match="invalid regular text tree"):
        Repository().add("bad", (), {path: "file\n"})


@pytest.mark.parametrize("path", ["", "/absolute", "../escape", ".git/index", "bad\nname",
                                  "a//b", "a/./b", "."])
def test_git_edit_refinement_rejects_invalid_path(checked_library, path):
    from opulse.atoms.values import Bottom
    from opulse.worlds_real.git import Patch

    library = checked_library
    sample = ((Patch(path, None, "text\n"),),)
    library.make_callable("Edit", sample)
    assert isinstance(library.run("Edit.make", sample[0]).outcome, Bottom)


@pytest.mark.parametrize("before, after", [("not terminated", "valid\n"),
                                                  ("valid\n", "not terminated"),
                                                  (None, "binary\x00file")])
def test_git_edit_refinement_rejects_invalid_text(checked_library, before, after):
    from opulse.atoms.values import Bottom
    from opulse.worlds_real.git import Patch

    library = checked_library
    library.make_callable("Edit", ((Patch("a", None, "valid\n"),),))
    assert isinstance(library.run("Edit.make", (Patch("a", before, after),)).outcome, Bottom)


@pytest.mark.parametrize("path, text", [("bad\ud800", "good\n"), ("a", "bad\udfff\n")])
def test_surrogates_refused_by_repository_and_edit(checked_library, path, text):
    from opulse.atoms.values import Bottom
    from opulse.worlds_real.git import Patch

    with pytest.raises(ValueError, match="invalid regular text tree"):
        Repository().add("bad", (), {path: text})
    checked_library.make_callable("Edit", ((Patch("a", None, "good\n"),),))
    assert isinstance(checked_library.run("Edit.make", (Patch(path, None, text),)).outcome, Bottom)


@pytest.mark.parametrize("invalid", [
    lambda MergeResult: MergeResult({"a": "missing LF"}, ()),
    lambda MergeResult: MergeResult({"a": "CRLF\r\n"}, ()),
    lambda MergeResult: MergeResult({"a": "file\n", "a/b": "child\n"}, ()),
    lambda MergeResult: MergeResult({"a": "valid\n"}, ("a", "a")),
    lambda MergeResult: MergeResult({"a": "valid\n"}, ("../escape",)),
])
def test_invalid_merge_results_stay_invalid_after_promotion(checked_library, invalid):
    from opulse.atoms.library import VerifyRequest
    from opulse.atoms.spec import Contract
    from opulse.atoms.values import Bottom
    from opulse.worlds_real.git import MergeResult

    result = invalid(MergeResult)
    library = checked_library
    library.make_callable("MergeReview", ((MergeResult({"a": "valid\n"}, ()),),))
    assert library.run("valid_result", (result,)).outcome.value is False
    assert isinstance(library.run("MergeReview.make", (result,)).outcome, Bottom)
    library.verify("MergeReview", VerifyRequest(
        "bounded", ((result,),), {"domain": "invalid result", "size": 1}))
    library.account("MergeReview")
    library.promote("MergeReview", Contract("valid results remain classified"))
    assert isinstance(library.run("MergeReview.make", (result,)).outcome, Bottom)


def test_merge_result_rejects_surrogate_conflict_path(checked_library):
    from opulse.atoms.values import Bottom
    from opulse.worlds_real.git import MergeResult

    invalid = MergeResult({"a": "valid\n"}, ("a\ud800",))
    library = checked_library
    library.make_callable("MergeReview", ((MergeResult({"a": "valid\n"}, ()),),))
    assert library.run("valid_result", (invalid,)).outcome.value is False
    assert isinstance(library.run("MergeReview.make", (invalid,)).outcome, Bottom)


def test_merge_review_classifies_both_outcomes(checked_library):
    from opulse.worlds_real.git import MergeResult

    library = checked_library
    clean = MergeResult({"a": "valid\n"}, ())
    conflicted = MergeResult({"a": "valid\n"}, ("a",))
    library.make_callable("MergeReview", ((clean,), (conflicted,)))
    for result, kind in ((clean, "clean"), (conflicted, "conflicted")):
        wrapped = library.run("MergeReview.make", (result,)).outcome.value
        assert library.run("MergeReview.base", (wrapped,)).outcome.value.kind == kind
        assert wrapped.fields[0].result == result


@pytest.mark.parametrize("left, right, suffix", [
    ({"a": "file\n"}, {"a/b": "child\n"}, "HEAD"),
    ({"a/b": "child\n"}, {"a": "file\n"}, "topic"),
])
def test_cross_branch_file_directory_conflict_matches_git(left, right, suffix):
    result = check_case(Scenario({"seed": "base\n"},
                                 ({"seed": "base\n", **left},),
                                 ({"seed": "base\n", **right},)))
    assert result.conflicts == (f"a~{suffix}",)
    assert result.files[f"a~{suffix}"] == "file\n"
    assert result.files["a/b"] == "child\n"


def test_git_edit_refinement_rejects_no_op(checked_library):
    from opulse.atoms.values import Bottom
    from opulse.worlds_real.git import Patch

    library = checked_library
    library.make_callable("Edit", ((Patch("a", None, "valid\n"),),))
    assert isinstance(library.run("Edit.make", (Patch("a", "same\n", "same\n"),)).outcome, Bottom)


def test_induce_grades_task_evidence():
    task = next(task for task in showcases() if task.angle == "Induce")
    assert verify_showcase(task)
    labels, held_out = task.evidence
    wrong = ((labels[0][0], not labels[0][1]),) + labels[1:]
    assert not verify_showcase(replace(task, evidence=(wrong, held_out)))


def test_induce_grades_supplied_held_out_cases():
    task = next(task for task in showcases() if task.angle == "Induce")
    labels, held_out = task.evidence
    opposite = next(case for case, clean in labels if clean != task.answer[0])
    assert not verify_showcase(replace(task, evidence=(labels, (opposite, *held_out[1:]))))


def test_loadable_world_declaration():
    from opulse.atoms.spec import Definition
    from opulse.atoms.world import WorldDecl
    from opulse.worlds_real.git.world import DEFINITIONS, WORLD

    world = WorldDecl.from_dict(WORLD)
    assert world.world == "real_git_merge"
    assert world.world_hash() == WorldDecl.from_dict(world.to_dict()).world_hash()
    assert len(DEFINITIONS) == 10
    assert {definition.kind for definition in DEFINITIONS} == set(world.open_kinds)
    assert all(Definition.from_dict(definition.to_dict()) == definition for definition in DEFINITIONS)


def test_git_definition_check_unfold_verify_and_promote(checked_library):
    from opulse.atoms.library import VerifyRequest, checked_scope
    from opulse.atoms.spec import Contract
    from opulse.worlds_real.git import Patch, apply_edit

    library = checked_library
    cases = (({"a": "old\n"}, Patch("a", "old\n", "new\n")),
             ({"a": "old\n"}, Patch("b", None, "new\n")))
    library.make_callable("Edit", ((cases[0][1],),))
    library.make_callable("apply_edit", cases)
    assert all(library.run("apply_edit", args).outcome.value == apply_edit(*args) for args in cases)
    request = VerifyRequest("bounded", cases, {"domain": "bounded to two text edits", "size": 2},
                            reference=apply_edit)
    verified = library.verify("apply_edit", request)
    assert "unfold_equivalence" in verified.evidence.checks
    library.account("apply_edit")
    promoted = library.promote("apply_edit", Contract("guarded edit matches Git tree replacement"))
    assert promoted.status == "promoted"
    assert all(promoted.evidence.scope[key] == value for key, value in request.scope.items())
    assert promoted.evidence.scope["checked"] == {**checked_scope(cases), "by": "library"}
    assert set(promoted.evidence.scope["checked"]) == {"bounds", "by", "sha256", "size"}
    assert all(library.run("apply_edit", args).outcome.value == apply_edit(*args) for args in cases)


def test_object_refinement_verifies_and_promotes(checked_library):
    from opulse.atoms.library import VerifyRequest
    from opulse.atoms.spec import Contract
    from opulse.worlds_real.git import Patch

    library = checked_library
    samples = ((Patch("a", None, "new\n"),),)
    library.make_callable("Edit", samples)
    verified = library.verify("Edit", VerifyRequest("bounded", samples, {"domain": "bounded one edit", "size": 1}))
    assert "canon_idempotent" in verified.evidence.checks
    assert library.promote("Edit", Contract("valid path and canonical edit")).status == "promoted"


def test_observation_verifies_without_changing_truth(checked_library):
    from opulse.atoms.library import VerifyRequest
    from opulse.atoms.spec import Contract
    from opulse.worlds_real.git import MergeResult

    library = checked_library
    result = MergeResult({"a": "main\n"}, ("a",))
    samples = ((result,),)
    library.make_callable("unmerged", samples)
    verified = library.verify("unmerged", VerifyRequest(
        "bounded", samples, {"domain": "bounded one merge", "size": 1}, reference=lambda state: state.conflicts))
    assert "facts_unchanged" in verified.evidence.checks
    assert library.promote("unmerged", Contract("returns unresolved paths, preserves the tree")).status == "promoted"
    assert result.files == {"a": "main\n"}


def test_combinator_verifies_and_promotes_with_fixed_family(checked_library):
    from opulse.atoms.kernel import FnRef
    from opulse.atoms.library import VerifyRequest
    from opulse.atoms.spec import Contract

    library = checked_library
    sample = ((FnRef("series_atom"), {"a": "old\n"}, ()),)
    library.make_callable("commit_series", sample)
    verified = library.verify("commit_series", VerifyRequest(
        "bounded", (({"a": "old\n"}, ()),),
        {"domain": "bounded empty series", "size": 1, "op_family": ["series_atom"]},
        extra={"op_family": ("series_atom",)}))
    assert "unfold_equivalence" in verified.evidence.checks
    assert library.promote("commit_series", Contract("applies the supplied step")).status == "promoted"


def test_review_probe_preserves_observed_facts(checked_library):
    from opulse.atoms.library import VerifyRequest
    from opulse.atoms.spec import Contract
    from opulse.worlds_real.git import Patch, Review

    library = checked_library
    state = (("main", "base"), (Patch("a", "old\n", "new\n"),), ())
    samples = ((state,),)
    library.make_callable("review", samples)
    verified = library.verify("review", VerifyRequest(
        "bounded", samples, {"domain": "bounded review snapshot", "size": 1},
        reference=lambda value: Review(*value)))
    assert "facts_unchanged" in verified.evidence.checks
    assert library.promote("review", Contract("summarize without changing facts")).status == "promoted"


def test_every_curriculum_definition_carries_promotion_evidence():
    from opulse.worlds_real.git.world import DEFINITIONS, promote_curriculum

    library = promote_curriculum()
    derived = library.derived_world()
    assert set(derived.scopes()) == {definition.name for definition in DEFINITIONS}
    assert all(library.get(definition.name).status == "promoted" for definition in DEFINITIONS)
    assert all(library.get(definition.name).evidence.world_hash == library.world.world_hash()
               for definition in DEFINITIONS)


def test_rebase_unfolds_the_invented_replay_combinator():
    from opulse.worlds_real.git.world import DEFINITIONS, promote_curriculum

    definition = next(item for item in DEFINITIONS if item.name == "rebase")
    assert "cherry_pick" in definition.depends_on
    assert definition.layer > next(item.layer for item in DEFINITIONS if item.name == "cherry_pick")
    library = promote_curriculum()
    repo = Repository()
    repo.add("base", (), {"a": "old\n"})
    repo.add("main", ("base",), {"a": "new\n"})
    repo.add("topic", ("base",), {"a": "new\n"})
    assert library.run("rebase", (repo, "main", ("topic",))).outcome.value.files == {"a": "new\n"}


def test_worker_log_is_not_at_repository_root():
    assert not (Path(__file__).resolve().parents[3] / "NOTES.md").exists()


def test_curriculum_uses_its_invented_edit_and_pick():
    from opulse.atoms import nodes
    from opulse.atoms.kernel import FnRef
    from opulse.worlds_real.git import Patch
    from opulse.worlds_real.git.world import DEFINITIONS, promote_curriculum

    definitions = {definition.name: definition for definition in DEFINITIONS}
    assert definitions["apply_edit"].spec.inputs[1].sort == "Edit"
    assert "cherry_pick" in definitions["rebase"].depends_on
    assert "pick_atom" in definitions["cherry_pick"].depends_on
    assert nodes.references(definitions["rebase"].body) == {"cherry_pick"}
    library = promote_curriculum()
    edit = Patch("a", "before\n", "after\n")
    assert library.run("apply_edit", ({"a": "before\n"}, edit)).outcome.value == {"a": "after\n"}
    assert library.run("commit_series", (FnRef("apply_edit"), {"a": "before\n"},
                                         (edit,))).outcome.value == {"a": "after\n"}
