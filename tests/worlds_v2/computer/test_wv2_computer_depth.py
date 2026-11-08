"""Deep byte-machine reference examples, pipeline invariants and export."""

import importlib.util
import json
from pathlib import Path

from opulse.atoms import kernel, nodes
from opulse.atoms.boundary import Boundary
from opulse.atoms.library import Library, atoms_digest
from opulse.atoms.values import Bottom, Card, Ok, outcome_equal
from opulse.atoms.verify import unfold_equivalent
from opulse.atoms.world import WorldDecl
from opulse.notation3.export import notation3_block
from opulse.tasks_v2.decl import load, validate
from opulse.worlds_v2.computer2 import hosts
from opulse.worlds_v2.computer2.export import (
    GRADING,
    OUTPUT,
    build_export,
    example_cases,
    visible,
)
from opulse.worlds_v2.computer2.story import (
    TOWER,
    build_library,
    oracle_multiply,
    vector,
)

REFERENCE = Path(__file__).with_name("design_reference.py")


def design_examples():
    spec = importlib.util.spec_from_file_location("computer_design_reference", REFERENCE)
    module = importlib.util.module_from_spec(spec)
    import sys

    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.examples()


def test_design_reference_is_independent_of_export_metadata():
    assert REFERENCE.is_file()
    assert "META" not in design_examples.__code__.co_names
    assert set(design_examples()) == {"loop", "multiply", "vec", "read", "step", "fold",
                                       "dot", "carry", "wide_type", "wide", "wrap"}


def test_layer_zero_machine_effects_and_domain_failures():
    state = hosts.state((0, 1, 2, 3), {255: 9}, pc=255, z=1)
    assert hosts.fields(hosts.put(state, "A", 0))[2:] == (0, 1)
    assert hosts.out(hosts.add(state, "A", "B")) == 1
    assert hosts.b(hosts.dec(state, "B")) == 0
    assert hosts.c(hosts.load(state, "C", 255)) == 9
    stored = hosts.store(state, 255, "B")
    assert hosts.fields(stored)[1][255] == 1 and hosts.z(stored) == 1 and hosts.pc(stored) == 0
    assert hosts.pc(hosts.branch(state, True, 7)) == 7
    assert hosts.pc(hosts.branch(state, False, 7)) == 0
    assert hosts.snapshot(state) == state and hosts.snapshot(state) is not state
    assert hosts.put(state, "A", 256) == Bottom("invalid_byte")
    assert hosts.load(state, "C", 256) == Bottom("invalid_addr")
    assert hosts.store(state, 256, "D") == Bottom("invalid_addr")


def test_reference_examples_and_full_state():
    oracle = design_examples()
    keys = ("loop", "multiply", "vec", "read", "step", "fold", "dot", "carry", "wide_type", "wide", "wrap")
    library = build_library()
    for name, key in zip(TOWER, keys):
        executable = f"{name}.make" if name in ("Vec", "Wide") else name
        run = library.run(executable, example_cases()[name])
        assert isinstance(run.outcome, Ok), (name, run.outcome)
        assert visible(name, run.outcome.value) == oracle[key], name
    sample = hosts.state((7, 11, 13, 17), {16: 37, 64: 43, 255: 29}, pc=91, z=1)
    assert library.run("mul_into", (sample,)).outcome == Ok(oracle_multiply(sample))
    assert library.run("@seq", (kernel.FnRef("snapshot"), kernel.FnRef("snapshot"), sample)).outcome == Ok(sample)
    assert hosts.put(sample, Card("Reg", "A"), 8) == hosts.put(sample, "A", 8)
    assert library.run("Vec.make", (hosts.vec(224, 32),)).outcome == Bottom("invalid")
    assert library.run("Vec.make", (9,)).outcome == Bottom("invalid")
    assert library.run("Vec.make", (hosts.vec("x", 2),)).outcome == Bottom("invalid")
    assert library.run("Wide.make", (hosts.wide(256, 0, 0),)).outcome == Bottom("invalid")
    assert library.run("Wide.make", (hosts.wide(True, 0, 0),)).outcome == Bottom("invalid")
    assert hosts.fields(sample)[2] == 91
    assert hosts.from_card(hosts.to_card(sample)) == sample


def test_pipeline_failures_and_invariants():
    library = build_library()
    for name in TOWER:
        item = library.get(name)
        # Promotion waits for the core parameterized-observation check.
        if name in ("?at", "?dot_wrap"):
            assert item.status == "callable"
            assert item.evidence is None
            assert item.contract is None
            assert name not in library.derived_world().scopes()
            continue
        assert item.status == "promoted"
        assert item.evidence.scope["size"] >= 50
        assert item.evidence.method in ("bounded", "exhaustive")
        assert item.contract is not None
        assert item.evidence.world_hash == library.world.world_hash()
        assert item.evidence.content_hash == library.content_hash(name)
        assert item.evidence.atoms_hash == atoms_digest(library.atoms)
        assert library.derived_world().scopes()[name] == item.evidence.scope
    assert library.get("Vec").cost.length > 0 and library.get("Wide").cost.length > 0
    assert library._deps_hash("dot") != Library._deps_hash(library, "dot")
    assert library._deps_hash("wide_dot") != Library._deps_hash(library, "wide_dot")
    machine = hosts.state(changes={16: 2, 64: 3})
    mismatched = (kernel.FnRef("dot_step"), machine, vector(16, 2), vector(64, 1))
    assert library.run("@zip_fold", mismatched).outcome == Bottom("zip_length_mismatch")
    assert library.run("mul_into", (machine,), fuel=1).outcome == kernel.Unknown("fuel")
    args = (machine, vector(16, 1), vector(64, 1))
    run = library.run("wide_dot", args, trace=True)
    inline = kernel.evaluate(kernel.inline(nodes.Call("wide_dot", tuple(nodes.Lit(arg) for arg in args)),
                                           library.scope()), scope=library.scope())
    assert outcome_equal(run.outcome, inline.outcome) and run.steps == inline.steps
    assert unfold_equivalent(run.trace, [Boundary.unfold_all(), Boundary.unfold_none()]).ok
    assert machine == args[0]


def test_decl_and_export():
    declared = load("worlds/decl/v2/computer@2.json")
    assert validate(declared) == []
    canonical = WorldDecl.from_dict(declared.to_dict())
    assert WorldDecl.from_dict(canonical.to_dict()).to_dict() == canonical.to_dict()
    assert set(canonical.open_kinds) == set(declared.extra["open_kinds"])
    exported = build_export()
    stored = json.loads(OUTPUT.read_text(encoding="utf-8"))
    # Notation v3: the display block is stamped by tools/notation3_export.py (the computer2
    # package is hashed by its evidence, so its exporter stays unchanged); it must equal a
    # fresh block of the fresh export.
    assert stored.pop("notation3") == notation3_block(exported, "worlds_v2")
    assert stored == exported
    assert OUTPUT.stat().st_size < 3_000_000
    assert len(exported["story"]) == 11
    for card in exported["story"]:
        if card["name"] in ("?at", "?dot_wrap"):
            assert card["status"] == "callable"
            assert card["evidence"] is None and card["contract"] is None
    assert all(case["answer_checked"] for case in exported["showcase"])
    grading = json.loads(GRADING.read_text(encoding="utf-8"))
    assert grading["showcase"][2]["answer"]["modular"] == [40, 40]
    assert grading["showcase"][2]["answer"]["wide"] == [[40, 42, 1], [40, 171, 0]]
    for card in exported["story"]:
        for example in card["examples"]:
            assert "Machine<regs=" not in example["text"]
            assert "s:Machine<sealed>" == example["learner_view"]["input"]
            assert "judge_view" not in example

    def ascii_only(value, path=""):
        if isinstance(value, dict):
            for key, part in value.items():
                ascii_only(part, key if not path else f"{path}.{key}")
        elif isinstance(value, list):
            for part in value:
                ascii_only(part, path)
        elif isinstance(value, str) and not any(part.endswith("_zh") for part in path.split(".")):
            assert value.isascii(), path

    ascii_only(exported)
