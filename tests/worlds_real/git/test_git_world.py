"""Every generated answer is compared against real Git, not another model call."""

import pytest

from opulse.worlds_real.git import (
    LADDER,
    LAYER_ZERO,
    STORY,
    TAGS,
    Patch,
    Repository,
    apply_edit,
    changed_paths,
    classify,
    commit_series,
    rebase,
    review,
)
from opulse.worlds_real.git.oracle import Scenario, check_case, generate
from opulse.worlds_real.git.showcase import showcases, verify_showcase


@pytest.mark.parametrize("seed", range(2000))
def test_real_git_merge(seed):
    check_case(generate(seed))


@pytest.mark.parametrize("seed", range(40))
def test_clean_cherry_pick_sequences(seed):
    scenario = generate(seed * 5 + 3, 3)
    check_case(scenario, replay_sequence=True)


@pytest.mark.parametrize("seed", range(40))
def test_conflicted_cherry_pick_sequences(seed):
    check_case(generate(seed, 2), replay_sequence=True)


@pytest.mark.parametrize("seed", range(40))
def test_rebase_sequences(seed):
    check_case(generate(seed * 5 + 3, 3), rebase_sequence=True)


@pytest.mark.parametrize("seed", range(20))
def test_conflicted_rebase_sequences(seed):
    check_case(generate(seed, 2), rebase_sequence=True)


@pytest.mark.parametrize("seed", range(40))
def test_multi_commit_cherry_pick_sequences(seed):
    check_case(generate(seed, 5), replay_sequence=True)


def test_declaration_and_showcases():
    assert len(STORY) == 10 and len(LADDER) == 5
    assert {item["kind"] for item in STORY} == set(TAGS["open_kinds"])
    assert len({task.angle for task in showcases()}) == 5
    assert all(verify_showcase(task) for task in showcases())
    assert LAYER_ZERO["schema"] == "opulse.world/2"
    assert all(entry["form"] == "given" for entry in LAYER_ZERO["objects"])
    assert LAYER_ZERO["operations"] and LAYER_ZERO["combinators"]["nodes"]
    assert LAYER_ZERO["observation"]["probes"]


def test_graph_and_change_preconditions():
    repo = Repository()
    repo.add("root", (), {"a": "one\n"})
    repo.add("left", ("root",), {"a": "two\n"})
    repo.add("right", ("root",), {"a": "one\n", "b": "three\n"})
    assert repo.merge_base("left", "right") == "root"
    assert repo.diff("root", "left")[0].before == "one\n"
    assert changed_paths(repo.commits["root"].files(), repo.commits["left"].files()) == ("a",)
    assert commit_series({"a": "one\n"}, (Patch("a", "one\n", "two\n"),)) == {"a": "two\n"}
    assert rebase(repo, "left", ("right",)).files == {"a": "two\n", "b": "three\n"}
    assert classify(rebase(repo, "left", ("right",))).kind == "clean"
    assert review(repo, "left", rebase(repo, "left", ("right",))).changes[0].path == "b"
    with pytest.raises(ValueError, match="stale"):
        apply_edit({}, Patch("a", "one\n", "two\n"))
    with pytest.raises(ValueError):
        repo.add("bad", ("missing",), {})


@pytest.mark.parametrize("scenario", [
    Scenario({"seed": "zero\n"}, ({"seed": "zero\n", "added": "ours\n"},),
             ({"seed": "zero\n", "added": "theirs\n"},)),
    Scenario({"seed": "zero\n"}, ({"seed": "change\n"},), ({},)),
    Scenario({"seed": "zero\n"}, ({},), ({"seed": "change\n"},)),
    Scenario({"seed": "zero\n"}, ({"seed": "zero\n", "added": "same\n"},),
             ({"seed": "zero\n", "added": "same\n"},)),
    Scenario({"seed": "zero\n"}, ({"seed": "same\n"},), ({"seed": "same\n"},)),
    Scenario({"seed": "zero\n", "keep": "value\n"}, ({"keep": "value\n"},),
             ({"keep": "value\n"},)),
])
def test_file_lifecycle(scenario):
    check_case(scenario)
