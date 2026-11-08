"""Public catalogue secrecy and deterministic private grading (spec section 12)."""

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from opulse.tasks_v2.challenge_grade import (
    build_grading,
    grade_entry,
    grading_path,
    verify_grading,
)
from tools.tasks_v2_challenge import _canonical as canonical_question
from tools.tasks_v2_challenge import _digest, _retired

ROOT = Path(__file__).resolve().parents[2]


def test_retired_manifest_contains_only_hashes_and_metadata():
    retired = json.loads((ROOT / 'tools/challenge_v2_retired.json').read_text())
    assert set(retired) == {'schema', 'note', 'question_sha256', 'prompt_sha256', 'world_question_sha256'}
    assert retired['schema'] == 'opulse.challenge_retired/1'
    assert isinstance(retired['note'], str) and retired['note']
    for key in ('question_sha256', 'prompt_sha256', 'world_question_sha256'):
        assert retired[key]
        assert all(re.fullmatch(r'[0-9a-f]{64}', value) for value in retired[key])


def test_current_questions_and_prompts_are_not_retired(challenge_grading):
    retired = json.loads((ROOT / 'tools/challenge_v2_retired.json').read_text())
    questions = set(retired['question_sha256'])
    prompts = set(retired['prompt_sha256'])
    world_questions = set(retired['world_question_sha256'])
    public = json.loads((ROOT / 'docs/assets/data/challenge/v2.json').read_text())
    entries = [entry for ladder in public['ladders'].values() for entry in ladder]
    entries.extend(public['paths']['six_kinds_one_world']['steps'])
    assert {entry['id'] for entry in entries} == set(challenge_grading)
    for entry in entries:
        assert _digest(entry['prompt']) not in prompts, entry['id']
        record = challenge_grading[entry['id']]
        if 'task' in record:
            task = record['task']
            assert task['prompt']['en'] == entry['prompt']
            signature = [task['world'], task['angle'], task['kind'], task['question']]
            assert _digest(canonical_question(signature)) not in questions, entry['id']
            # Same question under another angle or kind is retired too.
            assert _digest(canonical_question([task['world'], task['question']])) not in world_questions, entry['id']


def test_retirement_filter_checks_question_and_prompt_independently():
    from opulse.tasks_v2.angles import operation

    task = next(iter(operation.generate('integer', 'compute', 104729, index)
                     for index in range(24)))
    question_hash = _digest(canonical_question([task.world, task.angle, task.kind, task.question]))
    prompt_hash = _digest(task.prompt['en'])
    world_question_hash = _digest(canonical_question([task.world, task.question]))
    assert _retired(task, ({question_hash}, set(), set()))
    assert _retired(task, (set(), {prompt_hash}, set()))
    assert _retired(task, (set(), set(), {world_question_hash}))
    assert not _retired(task, (set(), set(), set()))


def _tracked(*directories):
    result = subprocess.check_output(["git", "ls-files", "--", *directories], cwd=ROOT, text=True)
    return [ROOT / name for name in result.splitlines()]


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"))


def _answer_fragments(value):
    if isinstance(value, (dict, list)):
        is_simple_values = isinstance(value, list) and all(
            isinstance(item, dict) and item.keys() <= {"t", "v", "tag", "f", "sort"} for item in value)
        if not is_simple_values and (not isinstance(value, dict) or
                                     not value.keys() <= {"t", "v", "tag", "f", "sort"}):
            yield _canonical(value)
        values = (value[key] for key in value if key not in {"t", "tag", "sort"}) if isinstance(value, dict) else value
        for item in values:
            yield from _answer_fragments(item)
    elif isinstance(value, str) and len(value) > 12 and not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", value):
        yield _canonical(value)
        yield value


CHALLENGE_MARKERS = ("challenge_grading", "challenge_v2", "six_kinds_one_world", "grade_entry", "path-v")
# A comparison of a grading reference with a literal, e.g. grading[step]['reference'] == {...} or [..]['v'] for ...] == [1, 2].
# A reference passed on as a call argument (followed by "," or ")") is not itself compared.
REFERENCE_LITERAL = re.compile(
    r"\[['\"]reference['\"]\](?:\[[^\]]*\])*(?!\s*[),])[^#\n]*==\s*(\[|\{|-?\d|['\"]|True\b|False\b)")
SELF = Path(__file__).resolve().relative_to(ROOT).as_posix()  # this checker quotes the patterns it rejects


def _generic_value(fragment):
    """A bare scalar outcome such as {"ok":{"t":"int","v":0}} is common data, not a challenge disclosure.

    So is a refusal verdict "refused at step k" (a small, published answer format of law compute).
    """
    if re.fullmatch(r'"?refused at step \d+"?', fragment):
        return True
    try:
        value = json.loads(fragment)
    except ValueError:
        return False
    if isinstance(value, dict) and set(value) == {"ok"}:
        value = value["ok"]
    return isinstance(value, dict) and set(value) <= {"t", "v", "tag", "f"} and not value.get("f")


def _tracked_texts(roots=("tools", "docs", "tests")):
    """Tracked data and test files. src/ is the generator: its finite vocabularies (template bodies)
    necessarily contain answers, and the literal-comparison check below covers its code."""
    return {str(path.relative_to(ROOT)): path.read_text(encoding="utf-8", errors="replace")
            for path in _tracked(*roots) if path.exists() and path.is_file()}


def _challenge_leaks(grading, tracked, visible_prompts):
    """(identifier, fragment, file) for every challenge answer a tracked file discloses.

    Only challenge answers are searched for, and only answer fragments specific enough to identify one
    (longer than 12 characters, not a bare scalar outcome, not printed in the public prompt). A file
    that handles challenge data (CHALLENGE_MARKERS) must not contain such a fragment at all; any other
    file (for example published gen_v2 data) leaks only if it also names the challenge item, by
    identifier or by question, so values that merely coincide with a challenge answer are not leaks.
    """
    leaks = []
    for identifier, row in grading.items():
        question = _canonical(row["task"]["question"]) if "task" in row else None
        fragments = {fragment for fragment in _answer_fragments(row["reference"])
                     if len(fragment) > 12 and not _generic_value(fragment)
                     and not (question is not None and (fragment.strip('"') in visible_prompts or
                                                        fragment.strip('"') in question))}
        for name, content in tracked.items():
            handles_challenge = any(marker in content for marker in CHALLENGE_MARKERS)
            if not handles_challenge and identifier not in content and (question is None or question not in content):
                continue
            leaks += [(identifier, fragment, name) for fragment in sorted(fragments) if fragment in content]
    return leaks


def test_no_challenge_answers_are_tracked(challenge_grading):
    catalogue = json.loads((ROOT / "docs/assets/data/challenge/v2.json").read_text())
    visible_prompts = "\n".join(entry["prompt"] for ladder in catalogue["ladders"].values()
                                for entry in ladder)
    tracked = _tracked_texts()
    assert "tools/challenge_v2_grading.json" not in tracked
    assert not any(name.startswith("build/") for name in tracked)
    assert not _challenge_leaks(challenge_grading, tracked, visible_prompts)


def test_answer_scan_flags_challenge_answers_not_gen_data(challenge_grading):
    """Integration round 5: common values in unrelated gen_v2 exports are not challenge leaks."""
    identifier, row = next((key, row) for key, row in sorted(challenge_grading.items())
                           if "task" in row and any(len(f) > 12 and not _generic_value(f)
                                                    for f in _answer_fragments(row["reference"])))
    reference = _canonical(row["reference"])
    common = '{"ok":{"t":"int","v":0}}'
    gen_like = {"docs/assets/data/gen_v2/x.json": _canonical({"examples": [json.loads(common), row["reference"]]})}
    assert not _challenge_leaks({identifier: row}, gen_like, "")
    assert not _challenge_leaks({"clock@2/compute/operation/0010": {"reference": json.loads(common)}},
                                {"docs/assets/data/gen_v2/y.json": common}, "")
    record = {"docs/assets/data/gen_v2/z.json": _canonical({"id": identifier, "answer": row["reference"]})}
    assert _challenge_leaks({identifier: row}, record, "")
    test_file = {"tests/tasks_v2/test_x.py": f"grading = load_challenge_grading()\nexpected = {reference}\n"}
    assert _challenge_leaks({identifier: row}, test_file, "")


def test_challenge_code_never_compares_references_with_literals():
    """Files that read challenge grading data assert shape and consistency, never literal answers."""
    offenders = []
    for name, content in _tracked_texts(("tools", "docs", "tests", "src")).items():
        if name == SELF or not name.endswith(".py") or not any(marker in content for marker in CHALLENGE_MARKERS):
            continue
        offenders += [f"{name}:{number}" for number, line in enumerate(content.splitlines(), 1)
                      if REFERENCE_LITERAL.search(line)]
    assert not offenders, offenders


def test_literal_reference_check_catches_the_round_5_leak():
    # Synthetic values in the shape of the round-5 leak; never real challenge answers.
    leaked = "    assert [grading[s['id']]['reference']['ok']['f'][0]['v'] for s in steps] == [4, 9, 25]"
    assert REFERENCE_LITERAL.search(leaked)
    assert REFERENCE_LITERAL.search("assert grading[x]['reference'] == {'ok': {'t': 'int', 'v': 8}}")
    assert not REFERENCE_LITERAL.search("assert reference == recomputed[step['id']]")
    assert not REFERENCE_LITERAL.search("assert grade_entry(i, grading[i]['reference']) == {'correct': True}")
    assert _generic_value('{"ok":{"t":"int","v":0}}') and not _generic_value('{"ok":{"t":"fraction","tag":"fraction","f":[1,3]}}')


def test_path_answers_are_not_in_tracked_files(challenge_grading):
    """Path references are compared as whole values and as their tuple of scalar parts."""
    tracked = {name: content for name, content in _tracked_texts().items()
               if any(marker in content for marker in CHALLENGE_MARKERS)}
    catalogue = json.loads((ROOT / "docs/assets/data/challenge/v2.json").read_text())
    steps = catalogue["paths"]["six_kinds_one_world"]["steps"]
    for step in steps:
        reference = challenge_grading[step["id"]]["reference"]
        assert _canonical(reference) not in "".join(tracked.values()), step["id"]
    def scalars(value):
        if isinstance(value, dict):
            for key in sorted(value):
                if key not in ("t", "tag"):
                    yield from scalars(value[key])
        elif isinstance(value, list):
            for item in value:
                yield from scalars(item)
        else:
            yield value
    firsts = [next(scalars(challenge_grading[step["id"]]["reference"]), None) for step in steps]
    for width in (2, 3):
        for start in range(len(firsts) - width + 1):
            window = firsts[start:start + width]
            if all(type(item) is int for item in window):
                needle = "[" + ", ".join(map(str, window)) + "]"
                assert not any(needle in content for content in tracked.values()), needle


def test_challenge_questions_are_disjoint_from_frozen_samples(challenge_grading):
    samples = set()
    sample_sources = set()
    for path in _tracked("worlds/tasks"):
        if path.suffix != ".json":
            continue
        records = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(records, list):
            continue
        for task in records:
            if not isinstance(task, dict) or "question" not in task:
                continue
            samples.add((task["world"], task["angle"], task["kind"], _canonical(task["question"])))
            source = task.get("source", {})
            if {"generator", "seed", "index"} <= source.keys():
                sample_sources.add((source["generator"], source["seed"], source["index"]))
    for identifier, row in challenge_grading.items():
        if "task" not in row:
            continue
        task = row["task"]
        signature = (task["world"], task["angle"], task["kind"], _canonical(task["question"]))
        assert signature not in samples, identifier
        source = task["source"]
        if {"generator", "seed", "index"} <= source.keys():
            assert (source["generator"], source["seed"], source["index"]) not in sample_sources, identifier


def test_grading_rebuild_is_byte_identical_and_matches_public_hash(challenge_grading, tmp_path):
    first = grading_path().read_bytes()
    second = build_grading(tmp_path / "second.json")
    assert first == second
    assert verify_grading(first)
    public = json.loads((ROOT / "docs/assets/data/challenge/v2.json").read_text())
    assert public["grading_sha256"] == hashlib.sha256(first).hexdigest()


@settings(max_examples=12)
@given(st.binary(min_size=1, max_size=48))
def test_grading_hash_rejects_any_appended_bytes(challenge_grading, extra):
    data = grading_path().read_bytes()
    assert not verify_grading(data + extra)


def test_missing_key_builds_on_first_grade(challenge_grading, tmp_path, monkeypatch):
    from opulse.tasks_v2 import challenge_grade

    path = tmp_path / "unbuilt/grading.json"
    data = grading_path().read_bytes()
    built = []

    def rebuild(destination):
        built.append(destination)
        destination.parent.mkdir(parents=True)
        destination.write_bytes(data)

    monkeypatch.setattr(challenge_grade, "build_grading", rebuild)
    identifier = next(iter(challenge_grading))
    assert grade_entry(identifier, challenge_grading[identifier]["reference"], path=path) == {"correct": True}
    assert built == [path]
    assert path.read_bytes() == data


def test_cli_build_honors_override(challenge_grading, tmp_path):
    path = tmp_path / "private.json"
    environment = {**os.environ, "OPULSE_CHALLENGE_GRADING": str(path)}
    subprocess.check_call([sys.executable, "-m", "opulse.tasks_v2.challenge_grade", "--build"],
                          cwd=ROOT, env=environment)
    assert json.loads(path.read_text()) == challenge_grading
