"""Cross-check machine programs against the atoms-v2 reference kernel."""

import json
import random

from atoms_mul.machine.compile import compile_sub
from atoms_mul.machine.env import state_for
from atoms_mul.machine.evaluate import run_sub
from atoms_mul.machine.lang import parse_program
from atoms_mul.machine.library import Library
from atoms_mul.machine.tasks import ROOT

from opulse.atoms import kernel as core
from opulse.atoms import nodes
from opulse.atoms.values import Bottom, Ok
from opulse.worlds_v2.computer import reference, runner
from opulse.worlds_v2.computer.machine import State


def compare(program, state, group, library=None, fuel=2000):
    operations = reference.atoms() if group == "A" else runner.atoms()
    last_state = [state]
    atoms = []
    for name, (arity, function, cost) in operations.items():
        def wrapped(*args, function=function):
            value = function(*args)
            if isinstance(value, Ok) and isinstance(value.value, State):
                last_state[0] = value.value
            elif isinstance(value, State):
                last_state[0] = value
            return value
        atoms.append(core.Atom(name, arity, wrapped, cost=cost))
    definitions = ([core.Defn(entry.name, ("s",), nodes.from_json(entry.body))
                    for entry in library._entries.values()] if library else [])
    definitions += [core.Defn(sub.name, ("s",), compile_sub(sub)) for sub in program.defs]
    result = core.call("main", [state], core.DictScope(atoms, definitions), core.Limits(fuel=fuel))
    local = run_sub("main", state, group=group, program=program, library=library, fuel=fuel)
    assert type(local.outcome) is type(result.outcome), (group, program, state, local, result)
    if isinstance(result.outcome, Ok):
        assert local.outcome.value == result.outcome.value, (group, program, state)
        final_state = result.outcome.value
    elif isinstance(result.outcome, Bottom):
        assert local.outcome.reason == result.outcome.reason, (group, program, state)
        final_state = last_state[0]
    else:
        assert local.outcome.resource == result.outcome.resource, (group, program, state)
        final_state = last_state[0]
    assert (local.final_state, local.steps) == (final_state, result.steps), (group, program, state, local, result)


def test_references_and_saved_dry_runs():
    tasks = {task["id"]: task for stage in (1, 2) for task in
             json.loads((ROOT / "tasks" / f"machine_stage{stage}.json").read_text())["tasks"]}
    for task in tasks.values():
        program = parse_program(task["reference_masm"])
        for example in (*task["public_examples"], *task["hidden_tests"]):
            compare(program, state_for(example), "A")
    for policy in ("inventor", "nosave"):
        path = ROOT / "runs" / f"dryrun_machine_{policy}" / "results.jsonl"
        libraries = {}
        for line in path.read_text().splitlines():
            record = json.loads(line)
            if record["group"] not in ("B", "C"):
                continue
            key = (record["group"], record["episode"])
            library = libraries.setdefault(key, Library())
            program = parse_program(record["final_program"])
            task = tasks[record["task_id"]]
            for example in (*task["public_examples"], *task["hidden_tests"]):
                compare(program, state_for(example), record["group"], library)
            if record["saved"]:
                library.add_from_program(program, record["saved"], record["task_id"])


def test_seeded_random_loops():
    rng = random.Random(28101)
    for _ in range(100):
        count = rng.randrange(256)
        text = ("sub main:\n  set r2, " + str(count) + "\nLOOP:\n  jz r2, DONE\n"
                "  add r0, r1\n  dec r2\n  jmp LOOP\nDONE:\n  halt\nend")
        compare(parse_program(text), State((0, rng.randrange(256), 0, 0)), "B", fuel=2000)
    compare(parse_program(text), State((0, 200, 0, 0)), "B", fuel=9)
