"""Shared episode helpers and scripted-policy contracts."""

from types import SimpleNamespace

from atoms_mul.harness.episode import result_counts, uses_library
from atoms_mul.harness.prompt_parts import library_section, task_section
from atoms_mul.harness.scripted import FlakyPolicy, ScriptedPolicy
from hypothesis import given
from hypothesis import strategies as st


def test_shared_prompt_sections():
    library = SimpleNamespace(listing=lambda: "saved")
    assert library_section(True, library, "ON", "OFF") == "ON\nLibrary:\nsaved"
    assert library_section(False, library, "ON", "OFF") == "OFF\nLibrary:\nempty"
    assert task_section({"statement": "work"}, "1 -> 2", [], "Answer\n") == (
        "\nTask: work\nPublic examples: 1 -> 2\nPrevious attempt feedback: none\nAnswer\n")
    assert "Previous attempt feedback: first\nsecond\n" in task_section(
        {"statement": "work"}, "1 -> 2", ["first", "second"], "Answer\n")


def test_scripted_policy_and_flaky_retries():
    class Inventor(ScriptedPolicy):
        def act(self, observation):
            return self.tasks[observation["task_id"]]["answer"]

    class Flaky(FlakyPolicy, Inventor):
        def bad_syntax(self, observation):
            return "parse"

        def bad_check(self, observation):
            return "check"

    policy = Flaky([{"id": "first", "answer": "ok"}])
    policy.reset(group="B", episode=0, seed=1000)
    assert policy.group == "B"
    assert [policy.act({"task_id": "first", "attempt": attempt}) for attempt in (1, 2, 3)] == [
        "parse", "check", "ok"]


def test_library_reachability():
    local = SimpleNamespace(name="solve", dependencies=("helper",))
    helper = SimpleNamespace(name="helper", dependencies=("saved",))
    program = SimpleNamespace(defs=(local, helper))
    library = SimpleNamespace(get=lambda name: object() if name == "saved" else None)
    assert uses_library(program, library, "solve", lambda definition: definition.dependencies)
    assert not uses_library(program, library, "unused", lambda definition: definition.dependencies)


@given(st.lists(st.tuples(st.integers(min_value=0, max_value=10),
                          st.integers(min_value=0, max_value=10),
                          st.integers(min_value=0, max_value=10), st.booleans()), max_size=15))
def test_result_counts_preserve_steps_and_library_calls(rows):
    hidden = [SimpleNamespace(calls={"saved": calls}, steps=steps,
                              boundary_steps=boundary, ok=ok)
              for calls, steps, boundary, ok in rows]
    library = SimpleNamespace(names=lambda: ["saved"])
    counts, steps, boundary = result_counts(hidden, library, lambda result: result.ok)
    assert counts == sum(row[0] for row in rows)
    assert steps == (sum(row[1] for row in rows) if all(row[3] for row in rows) else None)
    assert boundary == (sum(row[2] for row in rows) if all(row[3] for row in rows) else None)
