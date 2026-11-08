"""Reference model for Git's line-based, regular-file, two-head merge.

The text merge primitive is Git's public `merge-file` plumbing command, *not*
`git merge`. The graph, tree, base selection, and replay logic are independent
of the merge oracle, which executes `git merge` in an actual repository.
"""

from __future__ import annotations

import subprocess
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Patch:
    path: str
    before: str | None
    after: str | None


@dataclass(frozen=True)
class Commit:
    name: str
    parents: tuple[str, ...]
    tree: tuple[tuple[str, str], ...]

    def files(self) -> dict[str, str]:
        return dict(self.tree)


@dataclass(frozen=True)
class MergeResult:
    files: dict[str, str]
    conflicts: tuple[str, ...]

    @property
    def clean(self) -> bool:
        return not self.conflicts


@dataclass(frozen=True)
class MergeReview:
    kind: str
    result: MergeResult


def classify(result: MergeResult) -> MergeReview:
    return MergeReview("clean" if result.clean else "conflicted", result)


def classify_result(value: MergeResult | MergeReview) -> MergeReview:
    return value if isinstance(value, MergeReview) else classify(value)


@dataclass(frozen=True)
class Review:
    history: tuple[str, ...]
    changes: tuple[Patch, ...]
    unmerged: tuple[str, ...]


@dataclass(frozen=True)
class RebaseHistory:
    result: MergeResult
    applied: tuple[str, ...]
    skipped: tuple[str, ...]


class Repository:
    def __init__(self) -> None:
        self.commits: dict[str, Commit] = {}

    def add(self, name: str, parents: tuple[str, ...], files: Mapping[str, str]) -> Commit:
        if name in self.commits or any(parent not in self.commits for parent in parents):
            raise ValueError("duplicate commit or unknown parent")
        if not valid_tree(files):
            raise ValueError("invalid regular text tree")
        commit = Commit(name, parents, tuple(sorted(files.items())))
        self.commits[name] = commit
        return commit

    def ancestors(self, name: str) -> set[str]:
        seen: set[str] = set()
        pending = [name]
        while pending:
            current = pending.pop()
            if current not in seen:
                seen.add(current)
                pending.extend(self.commits[current].parents)
        return seen

    def merge_base(self, left: str, right: str) -> str:
        common = self.ancestors(left) & self.ancestors(right)
        maximal = [name for name in common if not any(
            name != other and name in self.ancestors(other) for other in common)]
        if len(maximal) != 1:
            raise ValueError("this world requires exactly one best merge base")
        return maximal[0]

    def diff(self, before: str, after: str) -> tuple[Patch, ...]:
        old, new = self.commits[before].files(), self.commits[after].files()
        return tuple(Patch(path, old.get(path), new.get(path))
                     for path in sorted(old.keys() | new.keys()) if old.get(path) != new.get(path))

    def log(self, head: str) -> tuple[str, ...]:
        history = []
        while True:
            history.append(head)
            parents = self.commits[head].parents
            if not parents:
                return tuple(history)
            head = parents[0]


def valid_path(path: str) -> bool:
    return (isinstance(path, str) and bool(path) and not path.startswith("/")
            and bool(Path(path).parts) and Path(path).as_posix() == path
            and ".git" not in Path(path).parts and ".." not in Path(path).parts
            and "\n" not in path and "\x00" not in path and _utf8(path))


def _utf8(value: str) -> bool:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def valid_text(text: str | None) -> bool:
    return text is None or (isinstance(text, str) and "\x00" not in text and "\r" not in text
                            and (not text or text.endswith("\n")) and _utf8(text))


def valid_tree(files: object) -> bool:
    return (isinstance(files, Mapping)
            and all(valid_path(path) and isinstance(text, str) and valid_text(text)
                    for path, text in files.items())
            and not any("/".join(path.split("/")[:index]) in files
                        for path in files for index in range(1, len(path.split("/")))))


def valid_result(value: object) -> bool:
    if isinstance(value, MergeReview):
        return (isinstance(value.result, MergeResult) and valid_result(value.result)
                and value.kind == ("clean" if value.result.clean else "conflicted"))
    return (isinstance(value, MergeResult) and valid_tree(value.files)
            and isinstance(value.conflicts, tuple)
            and all(valid_path(path) and path in value.files for path in value.conflicts)
            and len(value.conflicts) == len(set(value.conflicts)))


def apply_edit(tree: Mapping[str, str], edit: Patch) -> dict[str, str]:
    if tree.get(edit.path) != edit.before:
        raise ValueError("stale edit preimage")
    updated = dict(tree)
    if edit.after is None:
        updated.pop(edit.path, None)
    else:
        updated[edit.path] = edit.after
    return updated


def commit_series(tree: Mapping[str, str], edits: tuple[Patch, ...]) -> dict[str, str]:
    current = dict(tree)
    for edit in edits:
        current = apply_edit(current, edit)
    return current


def changed_paths(before: Mapping[str, str], after: Mapping[str, str]) -> tuple[str, ...]:
    return tuple(sorted(path for path in before.keys() | after.keys()
                        if before.get(path) != after.get(path)))


def status(base: Mapping[str, str], ours: Mapping[str, str], theirs: Mapping[str, str],
           result: MergeResult) -> tuple[str, ...]:
    """Git porcelain-v1 index/worktree status after a merge attempt."""
    if result.clean:
        return ()
    lines: list[str] = []
    for path in sorted(base.keys() | ours.keys() | result.files.keys()):
        if path in result.conflicts:
            if path.endswith("~HEAD") and path not in ours and path[:-5] in ours:
                code = "AU"
            elif path.endswith("~topic") and path not in theirs and path[:-6] in theirs:
                code = "UA"
            elif path not in base:
                code = "AA"
            elif path not in ours:
                code = "DU"
            elif path not in theirs:
                code = "UD"
            else:
                code = "UU"
        elif ours.get(path) != result.files.get(path):
            code = "A " if path not in ours else "D " if path not in result.files else "M "
        else:
            continue
        lines.append(f"{code} {path}")
    return tuple(lines)


def _merge_text(base: str, ours: str, theirs: str) -> tuple[str, bool]:
    with tempfile.TemporaryDirectory(prefix="opulse-merge-file-") as directory:
        paths = [Path(directory) / name for name in ("ours", "base", "theirs")]
        for path, text in zip(paths, (ours, base, theirs)):
            path.write_text(text, encoding="utf-8", newline="")
        result = subprocess.run(
            ["git", "merge-file", "-p", "-L", "HEAD", "-L", "base", "-L", "topic",
             *(str(path) for path in paths)], capture_output=True, check=False)
        if result.returncode < 0 or result.returncode > 127:
            raise RuntimeError(result.stderr.decode(errors="replace"))
        return result.stdout.decode("utf-8"), result.returncode != 0


def merge_trees(base: Mapping[str, str], ours: Mapping[str, str],
                theirs: Mapping[str, str]) -> MergeResult:
    files: dict[str, str] = {}
    conflicts: list[str] = []
    for path in sorted(base.keys() | ours.keys() | theirs.keys()):
        ancestor, left, right = base.get(path), ours.get(path), theirs.get(path)
        if left == right:
            selected = left
        elif left == ancestor:
            selected = right
        elif right == ancestor:
            selected = left
        elif left is None or right is None or ancestor is None:
            # A modify/delete conflict retains the modified side in the worktree.
            # Add/add invokes Git's text merge with an empty ancestor.
            if ancestor is None and left is not None and right is not None:
                selected, conflicted = _merge_text("", left, right)
                if conflicted:
                    conflicts.append(path)
            else:
                selected = left if left is not None else right
                conflicts.append(path)
        else:
            selected, conflicted = _merge_text(ancestor, left, right)
            if conflicted:
                conflicts.append(path)
        if selected is not None:
            files[path] = selected
    for path in sorted(files, key=lambda item: (item.count("/"), item)):
        if path in files and any(child.startswith(path + "/") for child in files):
            if path in ours:
                suffix = "HEAD"
            else:
                suffix = "topic"
            moved = f"{path}~{suffix}"
            if moved in files:
                raise ValueError("unsupported directory/file conflict destination")
            files[moved] = files.pop(path)
            if path in conflicts:
                conflicts.remove(path)
            conflicts.append(moved)
    return MergeResult(files, tuple(conflicts))


def merge(repo: Repository, ours: str, theirs: str) -> MergeResult:
    base = repo.merge_base(ours, theirs)
    return merge_trees(repo.commits[base].files(), repo.commits[ours].files(),
                       repo.commits[theirs].files())


def three_way(repo: Repository, ours: str, theirs: str) -> MergeResult:
    return merge(repo, ours, theirs)


def replay(repo: Repository, onto: str, commits: tuple[str, ...]) -> MergeResult:
    """Cherry-pick first-parent patches, stopping at the first conflict."""
    current = repo.commits[onto].files()
    for name in commits:
        result = _replay_step(repo, current, name, "replay")
        current = result.files
        if result.conflicts:
            return result
    return MergeResult(current, ())


def cherry_pick(repo: Repository, onto: str, commits: tuple[str, ...]) -> MergeResult:
    return replay(repo, onto, commits)


def rebase(repo: Repository, onto: str, branch: tuple[str, ...]) -> MergeResult:
    return rebase_history(repo, onto, branch).result


def rebase_history(repo: Repository, onto: str, branch: tuple[str, ...]) -> RebaseHistory:
    """Reapply patches; Git rebase omits commits whose result is already present."""
    current = repo.commits[onto].files()
    applied: list[str] = []
    skipped: list[str] = []
    for name in branch:
        result = _replay_step(repo, current, name, "rebase")
        if result.conflicts:
            return RebaseHistory(result, tuple(applied), tuple(skipped))
        if result.files == current:
            skipped.append(name)
        else:
            applied.append(name)
        current = result.files
    return RebaseHistory(MergeResult(current, ()), tuple(applied), tuple(skipped))


def _replay_step(repo: Repository, current: dict[str, str], name: str, mode: str) -> MergeResult:
    commit = repo.commits[name]
    if len(commit.parents) != 1:
        raise ValueError(f"{mode} requires non-merge commits")
    return merge_trees(repo.commits[commit.parents[0]].files(), current, commit.files())


def review(repo: Repository, head: str, result: MergeResult) -> Review:
    old = repo.commits[head].files()
    return Review(repo.log(head), tuple(Patch(path, old.get(path), result.files.get(path))
                                        for path in changed_paths(old, result.files)), result.conflicts)
