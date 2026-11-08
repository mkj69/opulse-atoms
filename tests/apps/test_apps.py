"""App API and adapters; providers let the tests run before tasks_v2 merges."""

import json
import sys
import types
from itertools import islice

import pytest

from opulse.apps import (
    Curriculum,
    Episode,
    episode,
    grade,
    ladder,
    make,
    register_world,
)
from opulse.apps.adapters import (
    LmEvalTask,
    compute_score,
    export_hf,
    export_lmeval,
    export_openai_jsonl,
    export_parquet,
    verl_row,
)
from opulse.apps.diagnostics import report


def fixture_tasks():
    return list(islice(make("bits", angle="compute", seed=2), 3))


def test_legacy_task_stream_and_grading():
    rows = fixture_tasks()
    assert rows == fixture_tasks()
    assert all(row["prompt"].isascii() for row in rows)
    for row in rows:
        answer = row["_grading"]["task"]["answer"]
        assert grade(json.loads(json.dumps(row)), str(answer))["correct"]
        assert not grade(row, "Answer: unparseable")["correct"]
    with pytest.raises(ValueError, match="level"):
        make("integer", level=6)
    with pytest.raises(ValueError, match="open_kinds"):
        make("integer", open_kinds=[])
    with pytest.raises(ValueError, match="modality"):
        make("integer", modality="video")


def test_legacy_ladder_depth():
    depths = [next(make("integer", level=level, angle="compute"))["metadata"]["layer_depth"]
              for level in range(1, 6)]
    assert depths == sorted(depths)


def test_v2_provider_when_available(tmp_path):
    pytest.importorskip("opulse.tasks_v2.angles.operation")
    for level in range(1, 6):
        task = next(make("integer", level=level, angle="compute", seed=11))
        expected = task["_grading"]["task"]["reference"]["outcome"]
        assert grade(json.loads(json.dumps(task)), "Answer: " + json.dumps(expected))["correct"]
        assert task["metadata"]["boundary"]["depth"] == level - 1
    for angle in ("compute", "invert", "decide", "describe", "induce", "create"):
        task = next(make("integer", angle=angle))
        assert task["prompt"].isascii()
        output = export_openai_jsonl([task], tmp_path / "answers.jsonl")
        reference = json.loads(output.read_text().splitlines()[0])["messages"][1]["content"]
        assert grade(task, reference)["correct"]


def test_episode_and_provider():
    def provider(world, level, kinds, angle, kind, modality, seed, index):
        return ({"id": f"mock/{seed}/{index}", "prompt": "Ask or submit", "answer_shape": "value",
                 "metadata": {"world": world, "level": level, "kind": kind, "angle": angle,
                              "boundary": {}, "modality": modality, "tags": {}}},
                lambda answer: {"correct": answer == 2, "reason": "checked"})

    register_world("mock", provider)
    task = next(make("mock", level=3, open_kinds={"observation"}, kind="observation", angle="compute"))
    assert grade(task, 2) == {"reward": 1.0, "correct": True, "reason": "checked"}
    episode = Episode(task, lambda action, turn: ("hint" if action == "query" else "done",
                                                    0 if action == "query" else 1, action != "query", {}))
    assert episode.reset() == "Ask or submit"
    assert episode.step("query") == ("hint", 0.0, False, {})
    assert episode.step("submit") == ("done", 1.0, True, {})
    with pytest.raises(RuntimeError):
        episode.step("again")


def test_robot_episode():
    task = next(make("action", angle="compute"))
    env = episode(task, max_turns=3)
    first = env.reset(seed=7)
    assert first
    observation, reward, done, info = env.step("front_wall")
    assert observation in ("True", "False")
    assert (reward, done, info["reason"]) == (0.0, False, "step")
    expected = json.dumps(task["_grading"]["task"]["answer"])
    assert env.step("submit " + expected)[1:4] == (0.0, True, {"reason": "goal_not_reached"})
    assert env.reset(seed=7) == first


def test_hidden_information_transition():
    task = {"id": "secret", "prompt": "Guess a hidden bit"}
    hidden = {"bit": 0}

    def reset(seed):
        hidden["bit"] = seed % 2
        return "Choose QUERY or SUBMIT 0/1"

    def transition(action, _turn):
        if action == "QUERY":
            return f"bit={hidden['bit']}", 0, False, {}
        return "Done", float(action == f"SUBMIT {hidden['bit']}"), True, {}

    env = episode(task, transition=transition, reset_hook=reset, max_turns=2)
    assert env.reset(seed=1) == "Choose QUERY or SUBMIT 0/1"
    assert env.step("QUERY") == ("bit=1", 0.0, False, {})
    assert env.step("SUBMIT 1") == ("Done", 1.0, True, {})


def test_curriculum():
    policy = Curriculum("integer", window=2)
    assert ladder("integer", 5)["boundary_depth"] == 4
    policy.observe(1)
    assert policy.observe({"reward": 1}) == 2
    policy.observe(0)
    assert policy.observe(0) == 1
    assert next(policy.make(angle="compute"))["metadata"]["level"] == 1


def test_verl_and_parquet(tmp_path):
    tasks = fixture_tasks()
    row = verl_row(tasks[0])
    assert row["prompt"] == [{"role": "user", "content": tasks[0]["prompt"]}]
    assert compute_score("opulse.apps", str(row["reward_model"]["ground_truth"]), row["reward_model"]["ground_truth"]) == 0
    answer = tasks[0]["_grading"]["task"]["answer"]
    assert compute_score("opulse.apps", str(answer), row["reward_model"]["ground_truth"]) == 1
    pa = pytest.importorskip("pyarrow.parquet")
    output = export_parquet(tasks, tmp_path / "train.parquet")
    assert len(pa.read_table(output).to_pylist()) == len(tasks)


def test_parquet_without_optional_dependency(monkeypatch, tmp_path):
    stored = {}
    arrow = types.ModuleType("pyarrow")
    parquet = types.ModuleType("pyarrow.parquet")

    class FakeTable:
        @staticmethod
        def from_pylist(rows):
            return rows

    arrow.Table = FakeTable
    arrow.parquet = parquet
    parquet.write_table = lambda rows, path: stored.update(rows=rows, path=path)
    monkeypatch.setitem(sys.modules, "pyarrow", arrow)
    monkeypatch.setitem(sys.modules, "pyarrow.parquet", parquet)
    output = export_parquet(fixture_tasks(), tmp_path / "fake.parquet")
    assert stored["path"] == output
    assert len(stored["rows"]) == 3


def test_hf_and_openai(tmp_path):
    tasks = fixture_tasks()
    root = export_hf(tasks, tmp_path / "hf", version="1.2.3")
    assert sum(len((root / f"{split}.jsonl").read_text().splitlines())
               for split in ("train", "validation", "test")) == len(tasks)
    assert "grading_json" in (root / "README.md").read_text()
    out = export_openai_jsonl(tasks, tmp_path / "openai.jsonl")
    messages = json.loads(out.read_text().splitlines()[0])["messages"]
    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert "_grading" not in out.read_text()
    with pytest.raises(ValueError, match="version"):
        export_hf(tasks, tmp_path, version="unversioned")


def test_lmeval(tmp_path):
    tasks = fixture_tasks()
    config = export_lmeval(tasks, tmp_path / "lm")
    assert "!function utils.process_results" in config.read_text()
    hook = LmEvalTask(config.parent / "tasks.jsonl")
    target = tasks[0]["_grading"]["task"]["answer"]
    assert hook.process_results({"id": tasks[0]["id"]}, [str(target)]) == {"accuracy": 1.0}
    pytest.importorskip("datasets")
    assert len(hook.load_dataset()["test"]) == len(tasks)


def test_lmeval_without_optional_dependency(monkeypatch, tmp_path):
    tasks = fixture_tasks()
    config = export_lmeval(tasks, tmp_path)
    fake = types.ModuleType("datasets")
    fake.Dataset = types.SimpleNamespace(from_list=lambda rows: rows)
    monkeypatch.setitem(sys.modules, "datasets", fake)
    rows = LmEvalTask(config.parent / "tasks.jsonl").load_dataset()["test"]
    assert len(rows) == 3
    assert set(rows[0]) == {"id", "prompt", "target"}
    assert "_grading" not in rows[0]


def test_report(tmp_path):
    tasks = fixture_tasks()
    replies = {row["id"]: str(row["_grading"]["task"]["answer"]) for row in tasks}
    replies[tasks[0]["id"]] = "bad"
    outcome = report(tasks, replies, tmp_path / "report")
    assert outcome["accuracy"] == pytest.approx(2 / 3)
    assert outcome["breakdown"]["world"]["bits"]["count"] == 3
    assert (tmp_path / "report" / "accuracy.svg").exists()
    assert "Accuracy" in (tmp_path / "report" / "summary.txt").read_text()
