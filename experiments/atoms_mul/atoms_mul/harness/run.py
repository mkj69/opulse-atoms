"""Execute deterministic offline episodes and write reproducible artifacts."""

import argparse
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

from .env import run_episode
from .metrics import summarize
from .policies import POLICIES

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class CheckpointTrack:
    """An external task track sharing the episode checkpoint and LLM lifecycle."""

    run_episode: object
    policies: dict
    task_names: tuple[str, str]
    file_names: tuple[str, ...]
    root: Path
    valid_groups: object
    summarize: object
    world_hashes: dict | None = None


def _json(data):
    return json.dumps(data, sort_keys=True, indent=1, ensure_ascii=False) + "\n"


def _check_config(previous, current):
    for key in ("track", "policy", "max_attempts", "fuel", "model", "hashes"):
        if previous.get(key) != current[key]:
            raise ValueError(f"resume config mismatch: {key}")
    if not set(previous["groups"]) <= set(current["groups"]) or previous["episodes"] > current["episodes"]:
        raise ValueError("resume config mismatch: groups or episodes cannot shrink or change")


def _write_atomic(path, content):
    temporary = path.with_name(path.name + ".tmp")
    try:
        temporary.write_text(content, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _complete_episode(row, tasks):
    """A finished episode has every task result and each attempted prompt once."""
    if not isinstance(row, dict) or not isinstance(row.get("records"), list) or not isinstance(row.get("prompts"), list):
        return False
    expected = {(stage, task["id"]) for stage, stage_tasks in enumerate(tasks, start=1)
                for task in stage_tasks}
    records = row["records"]
    if len(records) != len(expected):
        return False
    required_fields = {"correct", "final_program", "defs_written", "length", "saved",
                       "library_size_after", "uses_library", "library_calls", "steps",
                       "boundary_steps", "mul_equivalent", "core_library", "check_errors"}
    actual = set()
    needed = set()
    for record in records:
        if not isinstance(record, dict) or record.get("group") != row.get("group") or record.get("episode") != row.get("episode"):
            return False
        if not required_fields <= record.keys():
            return False
        key = (record.get("stage"), record.get("task_id"))
        attempts = record.get("attempts")
        if key not in expected or key in actual or type(attempts) is not int or attempts < 1:
            return False
        actual.add(key)
        needed.update((key[0], key[1], attempt) for attempt in range(1, attempts + 1))
    seen = set()
    for prompt in row["prompts"]:
        if not isinstance(prompt, dict) or prompt.get("group") != row.get("group") or prompt.get("episode") != row.get("episode"):
            return False
        key = (prompt.get("stage"), prompt.get("task_id"), prompt.get("attempt"))
        if key not in needed or key in seen or not isinstance(prompt.get("prompt"), str) or not prompt["prompt"]:
            return False
        seen.add(key)
    return seen == needed


def run(*, policy, groups, episodes, run_id, out, max_attempts=3, fuel=200_000,
        allow_api=False, model=None, resume=False, track="aml", extension=None):
    if track not in ("aml", "machine", "kinds"):
        raise ValueError("track must be aml, machine or kinds")
    if track == "kinds":
        if extension is None:
            raise ValueError("kinds track requires an extension")
        run_episode_impl = extension.run_episode
        policies = extension.policies
        task_names = extension.task_names
        file_names = extension.file_names
        root = extension.root
        valid_groups = extension.valid_groups
        summary_impl = extension.summarize
    elif track == "machine":
        from atoms_mul.machine import core_library as machine_core
        from atoms_mul.machine.env import run_episode as machine_episode
        from atoms_mul.machine.policies import POLICIES as machine_policies
        run_episode_impl, policies = machine_episode, machine_policies
        task_names = ("tasks/machine_stage1.json", "tasks/machine_stage2.json")
        file_names = task_names
        root, valid_groups = ROOT, "ABC"
        summary_impl = summarize
    else:
        run_episode_impl, policies = run_episode, POLICIES
        task_names = ("tasks/stage1.json", "tasks/stage2.json")
        file_names = (*task_names, "worlds/A.json", "worlds/B.json", "worlds/C.json")
        root, valid_groups = ROOT, "ABC"
        summary_impl = summarize
    groups = list(groups)
    if not groups or len(set(groups)) != len(groups) or any(group not in valid_groups for group in groups):
        raise ValueError(f"groups must be unique and drawn from {valid_groups}")
    if episodes < 1 or not run_id or Path(run_id).name != run_id or run_id in (".", ".."):
        raise ValueError("episodes must be positive and run_id a directory name")
    paths = {name: root / name for name in file_names}
    tasks = [json.loads(paths[name].read_text(encoding="utf-8"))["tasks"] for name in task_names]
    config = {"track": track, "policy": policy, "groups": groups, "episodes": episodes,
              "max_attempts": max_attempts, "fuel": fuel, "model": model,
              "hashes": {name: hashlib.sha256(path.read_bytes()).hexdigest()
                         for name, path in paths.items()}}
    if track == "machine":
        config["hashes"]["worlds/decl/computer@1.json"] = hashlib.sha256(
            machine_core.DECLARATION.read_bytes()).hexdigest()
        config["hashes"]["worlds/decl/computer_a"] = hashlib.sha256(
            json.dumps(machine_core.load_decl("A").to_dict(), sort_keys=True).encode("utf-8")
        ).hexdigest()
    elif track == "aml":
        from atoms_mul.kernel.core_library import DECLARATIONS

        config["hashes"].update({f"worlds/decl/atoms_mul_{group}.json": hashlib.sha256(
            (DECLARATIONS / f"atoms_mul_{group}.json").read_bytes()).hexdigest()
            for group in "ABC"})
    if track == "kinds":
        config["hashes"].update(extension.world_hashes or {})
    destination = Path(out) / run_id
    if not resume and destination.is_dir() and any(destination.iterdir()):
        raise ValueError(f"run {run_id} exists; use --resume or a new --run-id")
    if policy == "llm":
        from atoms_mul.analysis.llm_policy import DEFAULT_MAX_OUTPUT_TOKENS, LLMPolicy
        actor = LLMPolicy(allow_api=allow_api, model=model,
                          max_output_tokens=DEFAULT_MAX_OUTPUT_TOKENS)
        config["model"] = actor.model
    else:
        actor = policies[policy](*tasks)
    destination.mkdir(parents=True, exist_ok=True)
    # Checkpoint: one line per finished (group, episode), so a long paid run can resume.
    checkpoint = destination / "episodes.jsonl"
    finished = {}
    needs_rewrite = False
    if resume and checkpoint.exists():
        lines = checkpoint.read_bytes().splitlines(keepends=True)
        if not lines or not lines[0].endswith(b"\n"):
            raise ValueError("checkpoint missing config header; cannot safely resume")
        header = json.loads(lines[0])
        if "config" not in header:
            raise ValueError("checkpoint missing config header; cannot safely resume")
        _check_config(header["config"], config)
        for index, line in enumerate(lines[1:], start=1):
            if index == len(lines) - 1 and not line.endswith(b"\n"):
                checkpoint.write_bytes(b"".join(lines[:index]))
                break
            row = json.loads(line)
            if _complete_episode(row, tasks):
                finished[(row["group"], row["episode"])] = row
            else:
                needs_rewrite = True
    elif resume and (destination / "config.json").exists():
        _check_config(json.loads((destination / "config.json").read_text(encoding="utf-8")), config)
        if all((destination / name).exists() for name in
               ("results.jsonl", "prompts.jsonl", "summary.json")):
            results = [json.loads(line) for line in (destination / "results.jsonl").read_text(encoding="utf-8").splitlines()]
            saved_prompts = [json.loads(line) for line in (destination / "prompts.jsonl").read_text(encoding="utf-8").splitlines()]
            for row in results:
                key = (row["group"], row["episode"])
                finished.setdefault(key, {"group": key[0], "episode": key[1], "records": [], "prompts": []})["records"].append(row)
            for row in saved_prompts:
                key = (row["group"], row["episode"])
                if key in finished:
                    finished[key]["prompts"].append(row)
            finished = {key: row for key, row in finished.items() if _complete_episode(row, tasks)}
    if needs_rewrite or not (resume and checkpoint.exists()):
        _write_atomic(checkpoint, json.dumps({"config": config}, sort_keys=True, ensure_ascii=False) + "\n" +
                      "".join(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n"
                              for row in finished.values()))
    records, prompts = [], []
    current = []

    def capture(observation):
        current.append({"track": track, **{key: observation[key] for key in
                        ("group", "stage", "task_id", "attempt", "episode", "prompt")}})

    actor.on_prompt = capture
    for group in groups:
        for episode in range(episodes):
            if (group, episode) not in finished:
                current.clear()
                rows = [{"run_id": run_id, "policy": policy, "track": track, **record}
                        for record in run_episode_impl(actor, group, episode, *tasks,
                                                  max_attempts=max_attempts, fuel=fuel)]
                finished[(group, episode)] = {"group": group, "episode": episode,
                                              "records": rows, "prompts": list(current)}
                with checkpoint.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(finished[(group, episode)], sort_keys=True,
                                            ensure_ascii=False) + "\n")
            records.extend(finished[(group, episode)]["records"])
            prompts.extend(finished[(group, episode)]["prompts"])
    for name, rows in (("results.jsonl", records), ("prompts.jsonl", prompts)):
        _write_atomic(destination / name, "".join(json.dumps(row, sort_keys=True,
                      ensure_ascii=False) + "\n" for row in rows))
    _write_atomic(destination / "config.json", _json(config))
    _write_atomic(destination / "summary.json", _json(summary_impl(records, config)))
    checkpoint.unlink()
    return destination


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--track", choices=("aml", "machine"), default="aml")
    parser.add_argument("--policy", required=True)
    parser.add_argument("--groups", default="A,B,C")
    parser.add_argument("--episodes", type=int, default=2)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--out", type=Path, default=ROOT / "runs")
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--fuel", type=int, default=200_000)
    parser.add_argument("--allow-api", action="store_true")
    parser.add_argument("--model")
    parser.add_argument("--resume", action="store_true",
                        help="reuse finished episodes from runs/<id>/episodes.jsonl")
    args = parser.parse_args(argv)
    if args.track == "machine":
        from atoms_mul.machine.policies import POLICIES as machine_policies
    else:
        machine_policies = POLICIES
    if args.policy != "llm" and args.policy not in machine_policies:
        parser.error("unknown policy for selected track")
    run(policy=args.policy, groups=args.groups.split(","), episodes=args.episodes,
        run_id=args.run_id, out=args.out, max_attempts=args.max_attempts, fuel=args.fuel,
        allow_api=args.allow_api, model=args.model, resume=args.resume, track=args.track)


if __name__ == "__main__":
    main()
