"""Independent end-to-end Git oracle and reproducible case generation."""

from __future__ import annotations

import random
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .model import MergeResult, Repository, merge, rebase_history, replay, status


@dataclass(frozen=True)
class Scenario:
    base: dict[str, str]
    main: tuple[dict[str, str], ...]
    topic: tuple[dict[str, str], ...]


def generate(seed: int, level: int | None = None) -> Scenario:
    """Seeded regular-file cases, including overlap, disjoint hunks and sequences."""
    rng = random.Random(seed)
    level = level or 1 + seed % 5
    if level not in range(1, 6):
        raise ValueError("level must be 1..5")
    base = {"a.txt": "".join(f"line-{number}-{rng.randrange(10000)}\n" for number in range(16))}
    if level >= 3:
        base["b.txt"] = "".join(f"record-{number}\n" for number in range(12))

    def edit(files: dict[str, str], path: str, position: int, kind: str, serial: int) -> dict[str, str]:
        changed = dict(files)
        lines = changed[path].splitlines(keepends=True)
        token = f"branch-{serial}-{seed}-{rng.randrange(100000)}\n"
        if kind == "insert":
            lines.insert(position, token)
        elif kind == "delete":
            del lines[position]
        else:
            lines[position] = token
        changed[path] = "".join(lines)
        return changed

    kinds = ("replace", "insert", "delete")
    kind = rng.choice(kinds)
    position = rng.randrange(3, 12)
    left = edit(base, "a.txt", position, kind, 1)
    if level == 1:
        right = edit(base, "a.txt", position + 9 if position < 7 else 0, "replace", 2)
    elif level == 2:
        right = edit(base, "a.txt", position, kind, 2)
    elif level == 3:
        right = edit(base, "b.txt", rng.randrange(2, 9), "replace", 2)
    else:
        right = edit(base, "a.txt", position + rng.choice((-2, -1, 0, 1, 2)),
                     rng.choice(kinds), 2)
    main, topic = [left], [right]
    if level >= 4:
        main.append(edit(main[-1], "b.txt" if "b.txt" in base else "a.txt", 1, "replace", 3))
        topic.append(edit(topic[-1], "b.txt" if "b.txt" in base else "a.txt", 9, "replace", 4))
        if seed % 17 == 0:
            topic[-1].pop("b.txt")
    if level == 5:
        main.append(edit(main[-1], "a.txt", 14, "replace", 5))
        topic.append(edit(topic[-1], "a.txt", 0, "replace", 6))
        if seed % 19 == 0:
            main[-1]["new.txt"] = f"left-{seed}\n"
            topic[-1]["new.txt"] = f"right-{seed}\n"
    return Scenario(base, tuple(main), tuple(topic))


def _git(directory: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(["git", "-C", str(directory), *args], capture_output=True,
                            text=True, check=False)
    if check and result.returncode:
        raise AssertionError(f"git {' '.join(args)}: {result.stderr}")
    return result


def _write_tree(directory: Path, files: dict[str, str]) -> None:
    for path in set(_paths(_git(directory, "ls-files", "-z").stdout)) - files.keys():
        (directory / path).unlink()
    for path, text in files.items():
        target = directory / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline="")
    _git(directory, "add", "-A")


def _snapshot(directory: Path) -> dict[str, str]:
    return {path: (directory / path).read_text(encoding="utf-8")
            for path in _paths(_git(directory, "ls-files", "--cached", "-z").stdout)
            if (directory / path).is_file()}


def _paths(output: str) -> tuple[str, ...]:
    return tuple(path for path in output.split("\0") if path)


def _head_tree(directory: Path) -> dict[str, str]:
    return {path: _git(directory, "show", f"HEAD:{path}").stdout
            for path in _paths(_git(directory, "ls-tree", "-r", "--name-only", "-z", "HEAD").stdout)}


def _temp_root() -> Path:
    source = Path(__file__).resolve().parents[4]
    directory = Path(tempfile.gettempdir()).resolve()
    if directory.is_relative_to(source):
        directory = Path("/tmp") if not Path("/tmp").is_relative_to(source) else Path("/var/tmp")
    if directory.is_relative_to(source):
        raise ValueError("system temporary directory must be outside the source tree")
    return directory


def check_case(scenario: Scenario, *, replay_sequence: bool = False,
               rebase_sequence: bool = False) -> MergeResult:
    """Compare the model to real Git merge, cherry-pick, or rebase."""
    if replay_sequence and rebase_sequence:
        raise ValueError("choose only one replay mode")
    repo = Repository()
    repo.add("base", (), scenario.base)
    parent = "base"
    for index, tree in enumerate(scenario.main, 1):
        name = f"main-{index}"
        repo.add(name, (parent,), tree)
        parent = name
    main_head = parent
    parent = "base"
    for index, tree in enumerate(scenario.topic, 1):
        name = f"topic-{index}"
        repo.add(name, (parent,), tree)
        parent = name
    topic_head = parent
    expected = merge(repo, main_head, topic_head)
    with tempfile.TemporaryDirectory(prefix="opulse-git-oracle-", dir=_temp_root()) as temporary:
        directory = Path(temporary)
        _git(directory, "init", "-q", "-b", "main")
        _git(directory, "config", "user.name", "Opulse Oracle")
        _git(directory, "config", "user.email", "opulse@example.invalid")
        _git(directory, "config", "core.autocrlf", "false")
        _git(directory, "config", "merge.conflictStyle", "merge")
        _write_tree(directory, scenario.base)
        _git(directory, "commit", "-qm", "base")
        base_hash = _git(directory, "rev-parse", "HEAD").stdout.strip()
        _git(directory, "branch", "topic")
        for index, files in enumerate(scenario.main, 1):
            _write_tree(directory, files)
            _git(directory, "commit", "-qm", f"main-{index}")
        main_hash = _git(directory, "rev-parse", "HEAD").stdout.strip()
        _git(directory, "switch", "-q", "topic")
        topic_hashes: list[str] = []
        for index, files in enumerate(scenario.topic, 1):
            _write_tree(directory, files)
            _git(directory, "commit", "-qm", f"topic-{index}")
            topic_hashes.append(_git(directory, "rev-parse", "HEAD").stdout.strip())
        assert _git(directory, "merge-base", main_hash, "HEAD").stdout.strip() == base_hash
        assert repo.merge_base(main_head, topic_head) == "base"
        assert set(_paths(_git(directory, "diff", "--name-only", "-z", base_hash, "HEAD").stdout)) == {
            patch.path for patch in repo.diff("base", topic_head)}
        assert _git(directory, "log", "--format=%s", "--first-parent").stdout.splitlines() == [
            f"topic-{index}" for index in range(len(scenario.topic), 0, -1)] + ["base"]
        _git(directory, "switch", "-q", "main")
        status_base = repo.commits["base"].files()
        status_ours = repo.commits[main_head].files()
        status_theirs = repo.commits[topic_head].files()
        if rebase_sequence:
            history = rebase_history(repo, main_head, tuple(f"topic-{index}" for index in range(1, len(scenario.topic) + 1)))
            expected = history.result
            result = _git(directory, "rebase", "main", "topic", check=False)
            if expected.conflicts:
                stopped = len(history.applied) + len(history.skipped) + 1
                status_base = repo.commits[f"topic-{stopped - 1}" if stopped > 1 else "base"].files()
                status_ours = _head_tree(directory)
                status_theirs = repo.commits[f"topic-{stopped}"].files()
        elif replay_sequence:
            expected = replay(repo, main_head, tuple(f"topic-{index}" for index in range(1, len(scenario.topic) + 1)))
            for index, commit_hash in enumerate(topic_hashes, 1):
                status_base = repo.commits[repo.commits[f"topic-{index}"].parents[0]].files()
                status_ours = _snapshot(directory)
                status_theirs = repo.commits[f"topic-{index}"].files()
                result = _git(directory, "cherry-pick", "--keep-redundant-commits",
                              commit_hash, check=False)
                if result.returncode:
                    break
        else:
            result = _git(directory, "merge", "--no-edit", "--no-ff", "topic", check=False)
        conflicts = tuple(sorted(_paths(_git(directory, "diff", "--name-only", "--diff-filter=U", "-z").stdout)))
        actual = _snapshot(directory)
        if (replay_sequence or rebase_sequence) and conflicts:
            actual = {path: re.sub(r"(?m)^>>>>>>> [0-9a-f]+ \(topic-[0-9]+\)$",
                                   ">>>>>>> topic", text) for path, text in actual.items()}
        if conflicts != expected.conflicts or actual != expected.files:
            raise AssertionError(f"Git/model mismatch: conflicts {conflicts} != {expected.conflicts}; "
                                 f"worktree {actual!r} != {expected.files!r}; "
                                 f"git: {result.stderr}")
        assert (result.returncode == 0) == expected.clean
        if rebase_sequence and expected.clean:
            actual_log = _git(directory, "log", "--format=%s", "--first-parent").stdout.splitlines()
            base_log = ([f"main-{index}" for index in range(len(scenario.main), 0, -1)]
                        + ["base"])
            assert actual_log == list(reversed(history.applied)) + base_log
        if not rebase_sequence and not replay_sequence and expected.clean:
            repo.add("merged", (main_head, topic_head), expected.files)
            assert _git(directory, "log", "--format=%s", "--first-parent").stdout.splitlines()[1:] == list(
                repo.log("merged")[1:])
        porcelain = _paths(_git(directory, "status", "--porcelain=v1", "-z").stdout)
        assert porcelain == status(status_base, status_ours, status_theirs, expected), (
            porcelain, expected)
    return expected
