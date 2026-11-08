"""Shared deterministic episode lifecycle for the AML and machine tracks."""

import random
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class Track:
    library: Callable
    mirror: Callable
    library_enabled: Callable
    visible_fields: tuple[str, ...]
    render_prompt: Callable
    parse: Callable
    syntax_error: type[Exception]
    check: Callable
    grade: Callable
    feedback: Callable
    results: Callable
    name: str | None = None


def run_episode(track, policy, group, episode, tasks_stage1, tasks_stage2, *,
                max_attempts=3, fuel=200_000):
    if max_attempts < 1 or fuel < 0:
        raise ValueError("max_attempts must be positive and fuel nonnegative")
    library = track.library()
    enabled = track.library_enabled(group)
    mirror = track.mirror(group) if enabled else None
    seed = 1000 + episode
    policy.reset(group=group, episode=episode,
                 seed=seed + {"A": 0, "B": 100_000, "C": 200_000}[group])
    rng = random.Random(seed)
    stage1, stage2 = list(tasks_stage1), list(tasks_stage2)
    rng.shuffle(stage1)
    rng.shuffle(stage2)
    records = []
    for stage, tasks in ((1, stage1), (2, stage2)):
        for task in tasks:
            feedback, final_text, valid, correct, program, hidden = [], "", False, False, None, []
            api_error = False
            for attempt in range(1, max_attempts + 1):
                visible = {key: task[key] for key in track.visible_fields}
                prompt = track.render_prompt(group, library, visible, feedback, fuel)
                observation = {"group": group, "episode": episode, "stage": stage,
                               "task_id": task["id"], "attempt": attempt,
                               "library_enabled": enabled, "prompt": prompt,
                               "task": visible, "library": library.listing() if enabled else "",
                               "feedback": list(feedback)}
                if hasattr(policy, "on_prompt"):
                    policy.on_prompt(observation)
                try:
                    final_text = policy.act(observation)
                except Exception:
                    if getattr(policy, "name", None) != "llm":
                        raise
                    api_error, final_text, valid = True, "", False
                    break
                api_error = False
                valid = False
                try:
                    program = track.parse(final_text)
                except track.syntax_error as error:
                    feedback.append(f"Syntax error: {error}")
                    continue
                errors = track.check(program, task, group, library)
                if errors:
                    feedback.append("Check errors: " + "; ".join(errors))
                    continue
                valid = True
                hidden, correct = track.grade(program, task, group, library, fuel)
                if correct:
                    break
                feedback.append(track.feedback(program, task, group, library, fuel)
                                + "; at least one hidden test failed")

            details = track.results(program, valid, hidden, task, group, library, fuel)
            saved = list(program.saves) if valid else []
            core = []
            if saved:
                added = library.add_from_program(program, saved, task["id"])
                core = [{"name": report["name"], "status": report["core_status"],
                         "problems": report["problems"], "evidence": report["evidence"],
                         "contract": report["contract"], "cost": report["cost"]}
                        for report in mirror.mirror([{"definition": entry,
                                                      "mul_equivalent": entry.name in details["mul_equivalent"]}
                                                     for entry in added])]
            record = {"group": group, "episode": episode, "order_seed": seed,
                      "stage": stage, "task_id": task["id"], "family": task["family"],
                      "attempts": attempt, "correct": correct, "final_program": final_text,
                      "defs_written": details["defs_written"], "length": details["length"],
                      "saved": saved, "library_size_after": len(library.names()),
                      "uses_library": details["uses_library"],
                      "library_calls": details["library_calls"],
                      "steps": details["steps"], "boundary_steps": details["boundary_steps"],
                      "mul_equivalent": details["mul_equivalent"], "core_library": core,
                      "check_errors": sum(item.startswith(("Syntax error:", "Check errors:"))
                                          for item in feedback)}
            if track.name is not None:
                record = {"track": track.name, **record}
            if api_error:
                record["api_error"] = True
            records.append(record)
    return records


def uses_library(program, library, entry, calls):
    """Follow local calls from the entry point to a previously saved definition."""
    definitions = {definition.name: definition for definition in program.defs}
    pending, seen = [entry], set()
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        seen.add(name)
        if library.get(name) is not None:
            return True
        if name in definitions:
            pending.extend(calls(definitions[name]))
    return False


def result_counts(hidden, library, is_ok):
    names = library.names()
    all_ok = all(is_ok(result) for result in hidden)
    return (sum(sum(result.calls.get(name, 0) for name in names) for result in hidden),
            sum(result.steps for result in hidden) if all_ok else None,
            sum(result.boundary_steps for result in hidden) if all_ok else None)
