"""Checks for the immutable task data and its deterministic source."""

import json
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest
from atoms_mul.tasks import generate, reference

TASK_DIR = Path(__file__).resolve().parents[1] / "tasks"
BANNED = ("mul", "multipl", "times", "product", "twice", "double", "triple", "*", "\u00d7", "\u00b7")
ALLOWED_AML = {"op", "Nat", "add", "sub", "succ", "pred", "is_zero", "eq", "lt", "mul"}


@pytest.fixture(scope="module", params=(1, 2))
def frozen(request):
    stage = request.param
    return json.loads((TASK_DIR / f"stage{stage}.json").read_text(encoding="utf-8"))


def test_frozen_bytes_match_generator_and_cli(tmp_path):
    env = dict(os.environ, PYTHONPATH=str(TASK_DIR.parent) + os.pathsep + os.environ.get("PYTHONPATH", ""))
    subprocess.run(
        [sys.executable, "-m", "atoms_mul.tasks.generate", "--out", str(tmp_path)],
        check=True,
        env=env,
    )
    for stage, seed in ((1, 11), (2, 22)):
        name = f"stage{stage}.json"
        assert (tmp_path / name).read_bytes() == (TASK_DIR / name).read_bytes()
        assert json.loads((tmp_path / name).read_text(encoding="utf-8")) == generate.generate(stage)
        assert generate.generate(stage)["seed"] == seed


def test_family_counts_ids_and_stage(frozen):
    stage = frozen["stage"]
    assert frozen["generator_version"] == stage + 1
    expected = ({"constant_scale": 8, "variable_scale": 8, "compound": 8} if stage == 1
                else {"dot": 16})
    assert Counter(task["family"] for task in frozen["tasks"]) == expected
    assert [task["id"] for task in frozen["tasks"]] == [
        f"s{stage}_t{number:02d}" for number in range(1, sum(expected.values()) + 1)
    ]
    assert all(task["stage"] == stage for task in frozen["tasks"])


def test_statements_and_aml_signatures(frozen):
    for task in frozen["tasks"]:
        statement = task["statement"]
        assert not any(word in statement.lower() for word in BANNED), task["id"]
        signature = f"solve({', '.join(task['params'])})"
        assert task["solve_signature"] == signature
        assert statement.endswith(f"Define {signature}.")
        aml = task["reference_aml"]
        typed = ", ".join(f"{param}: Nat" for param in task["params"])
        assert aml.startswith(f"op solve({typed}) -> Nat = ")
        names = re.findall(r"[A-Za-z_][A-Za-z_0-9]*", aml)
        assert set(names) <= ALLOWED_AML | {"solve", *task["params"]}
        assert len(task["params"]) == len(set(task["params"]))


def test_answers_and_examples(frozen):
    for task in frozen["tasks"]:
        public = task["public_examples"]
        hidden = task["hidden_tests"]
        assert len(public) == 3
        assert len(hidden) == 12
        assert len({tuple(example["args"]) for example in public + hidden}) == 15
        if task["family"] == "variable_scale":
            assert {0, 1} <= {example["args"][0] for example in hidden}
        for example in public + hidden:
            args = example["args"]
            assert len(args) == len(task["params"])
            assert all(type(value) is int and 0 <= value <= 10**6 for value in args)
            assert example["expected"] == reference.expected(task, args)
            assert 0 <= example["expected"] <= 10**6
            assert max(args, default=0) <= 400


def test_templates_have_distinct_constant_counts_and_dot_sizes():
    stage1 = generate.generate(1)["tasks"]
    assert len(set(reference.CONSTANT_COUNTS)) == 8
    assert all(3 <= count <= 12 for count in reference.CONSTANT_COUNTS)
    for task, count in zip(stage1[:8], reference.CONSTANT_COUNTS):
        assert f"mul({count}, x)" in task["reference_aml"]
    stage2 = generate.generate(2)["tasks"]
    assert set(reference.DOT_SIZES) == {2, 3, 4}
    assert Counter(reference.DOT_SIZES) == {2: 6, 3: 5, 4: 5}
    for index, task in enumerate(stage2):
        size = reference.DOT_SIZES[index]
        assert len(task["params"]) == 2 * size
        assert task["reference_aml"].count("mul(") == size
