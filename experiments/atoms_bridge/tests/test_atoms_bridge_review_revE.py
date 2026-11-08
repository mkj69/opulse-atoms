"""Independent reproductions for bridge access, analysis, and run hygiene."""

import json
import re
from pathlib import Path

import pytest
from atoms_bridge.env import LibraryView, _check, _grade
from atoms_bridge.machine import _runtime, parse_program, runtime_names
from atoms_mul.machine.lang import NAME, MasmSyntaxError
from atoms_mul.machine.policies import HELPER


@pytest.mark.parametrize(
    ("reserved_name", "instruction"),
    [("machine_add", "add r0, r1"),
     ("to_byte", "xcall mul r1, r2 -> r0")],
)
def test_checker_rejects_shadowed_runtime_dependencies(reserved_name, instruction):
    program = parse_program(
        f"sub {reserved_name}:\n  set r0, 40\nend\n"
        f"sub main:\n  {instruction}\nend"
    )
    library = LibraryView()
    library.group = "B"
    assert _check(program, {}, "B", library)


def test_every_installed_runtime_name_is_reserved():
    for group in ("B", "C"):
        library = LibraryView()
        library.group = group
        atoms, definitions = _runtime(group)
        installed_names = set(atoms) | set(definitions)
        assert runtime_names(group) == installed_names
        for name in installed_names:
            source = f"sub {name}:\n  halt\nend\nsub main:\n  halt\nend"
            if not NAME.fullmatch(name) or name == "__xcall_mul":
                with pytest.raises(MasmSyntaxError):
                    parse_program(source)
            else:
                assert _check(parse_program(source), {}, group, library), name


def test_frozen_tasks_have_accuracy_ceiling_and_length_primary():
    task_file = (Path(__file__).resolve().parents[2] / "atoms_mul" /
                 "tasks/machine_stage2.json")
    tasks = json.loads(task_file.read_text(encoding="utf-8"))["tasks"]
    solved = 0
    for task in tasks:
        positions = int(re.match(r"For (\d+) positions,", task["statement"]).group(1))
        lines = ["  set r3, 0"]
        for index in range(positions):
            lines.extend((f"  load r1, {16 + index}", f"  load r2, {32 + index}",
                          "  call MUL", "  add r3, r0"))
        lines.extend(("  set r0, 0", "  add r0, r3"))
        program = parse_program(HELPER + "\nsub main:\n" + "\n".join(lines) + "\nend")
        solved += _grade(program, task, "A", LibraryView(), 200_000)[1]
    assert solved == len(tasks)
    from atoms_bridge.summary import analyze

    rows = [{"group": group, "stage": 2, "episode": episode, "task_id": task["id"],
             "correct": True, "length": 20 if group == "A" else 5}
            for group in ("A", "B") for episode in range(40) for task in tasks]
    result = analyze(rows, resamples=20)
    assert result["decision"] == "transfer saves effort"
    assert result["secondary_accuracy_G2_minus_G1"]["difference"] == 0


def test_resume_hashes_shared_runtime_dependencies():
    config_file = Path(__file__).resolve().parents[1] / "runs/dryrun_transfer/config.json"
    config = json.loads(config_file.read_text(encoding="utf-8"))
    assert {"../atoms_mul/atoms_mul/machine/compile.py",
            "../atoms_mul/atoms_mul/harness/episode.py"} <= config["hashes"].keys()
