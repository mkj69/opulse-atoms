"""The experiment kernel and the atoms-v2 reference kernel agree on outcomes and steps."""

import json
import random
from pathlib import Path

import pytest

pytest.importorskip("opulse.atoms.kernel")

from atoms_mul.kernel import (
    Library,
    Ok,
    Unknown,
    check_program,
    evaluate,
    load_world,
    parse_program,
)
from atoms_mul.kernel.core_backend import core_evaluate

ROOT = Path(__file__).resolve().parents[1]
TASKS = [task for stage in (1, 2)
         for task in json.loads((ROOT / "tasks" / f"stage{stage}.json").read_text())["tasks"]]
HELPER = "op rep(n: Nat, x: Nat) -> Nat = if is_zero(n) then 0 else add(x, rep(pred(n), x))\n"


def same(name, args, **kwargs):
    ours = evaluate(name, args, **kwargs)
    theirs, steps = core_evaluate(name, args, **kwargs)
    assert type(ours.outcome) is type(theirs), (name, args, ours.outcome, theirs)
    if isinstance(theirs, Ok):
        assert ours.outcome.value == theirs.value and type(ours.outcome.value) is type(theirs.value)
    if isinstance(theirs, Unknown):
        assert ours.outcome.resource == theirs.resource
    assert ours.steps == steps, (name, args, ours.steps, steps)
    return ours


@pytest.mark.parametrize("group", ["A", "C"])
def test_every_task_agrees(group):
    world = load_world(group)
    for task in TASKS:
        text = task["reference_aml"] if group == "A" else HELPER + task["reference_aml"].replace("mul(", "rep(")
        program = parse_program(text)
        for example in task["public_examples"] + task["hidden_tests"]:
            assert isinstance(same("solve", example["args"], world=world, program=program).outcome, Ok)


def test_library_calls_agree():
    world = load_world("B")
    library = Library()
    library.add_from_program(parse_program(HELPER + "save rep"), ["rep"], "s1")
    program = parse_program("op solve(a: Nat, b: Nat, c: Nat) -> Nat = add(rep(a, b), rep(b, c))")
    for args in ([0, 0, 0], [3, 4, 5], [12, 0, 7], [40, 300, 2]):
        same("solve", args, world=world, program=program, library=library)


def test_failures_and_resources_agree():
    world = load_world("B")
    program = parse_program(
        "op down(n: Nat) -> Nat = if is_zero(n) then 0 else succ(down(pred(n)))\n"
        "op bad(n: Nat) -> Nat = add(pred(n), n)\n"
        "op loop(n: Nat) -> Nat = loop(succ(n))\n"
        "op big(n: Nat) -> Nat = add(n, 999999999)\n")
    for args in ([0], [5], [1500]):
        same("down", args, world=world, program=program)
    same("down", [3000], world=world, program=program)          # Unknown(depth)
    same("down", [1500], world=world, program=program, fuel=700)  # Unknown(fuel)
    same("bad", [0], world=world, program=program)              # Bottom(negative)
    same("loop", [0], world=world, program=program, fuel=5000)
    same("big", [2], world=world, program=program)              # Bottom(overflow)


def _expr(rng, params, names, depth):
    choice = rng.randrange(7 if depth > 0 else 2)
    if choice == 0:
        return rng.choice(params)
    if choice == 1:
        return str(rng.randrange(4))
    if choice == 2:
        return f"if is_zero({_expr(rng, params, names, depth - 1)}) then " \
               f"{_expr(rng, params, names, depth - 1)} else {_expr(rng, params, names, depth - 1)}"
    if choice == 3:
        return f"let t = {_expr(rng, params, names, depth - 1)} in add(t, {_expr(rng, params + ['t'], names, depth - 1)})"
    op, arity = rng.choice([("add", 2), ("sub", 2), ("succ", 1), ("pred", 1)] + names)
    return f"{op}({', '.join(_expr(rng, params, names, depth - 1) for _ in range(arity))})"


def test_random_programs_agree():
    rng = random.Random(20261104)
    world = load_world("C")
    for _ in range(150):
        # f may recurse on a decreasing argument; g calls f.
        f_body = (f"if is_zero(n) then {_expr(rng, ['m'], [], 2)} "
                  f"else {_expr(rng, ['n', 'm'], [], 1)}" if rng.random() < 0.5 else
                  f"if is_zero(n) then {_expr(rng, ['m'], [], 2)} else add(m, f(pred(n), m))")
        text = f"op f(n: Nat, m: Nat) -> Nat = {f_body}\nop g(a: Nat, b: Nat) -> Nat = {_expr(rng, ['a', 'b'], [('f', 2)], 3)}\n"
        program = parse_program(text)
        assert check_program(program, world, None) == []
        for _ in range(4):
            same("g", [rng.randrange(6), rng.randrange(6)], world=world, program=program, fuel=300)
