"""Finite, kernel-backed generic task regression coverage."""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.boundary import Boundary
from opulse.atoms.library import atoms_digest, checked_scope
from opulse.atoms.spec import (
    Contract,
    Definition,
    Edge,
    Evidence,
    ObservationSpec,
    OperationSpec,
)
from opulse.tasks_v2.fixtures import computer_world, sensor_counter_world, toy_world
from opulse.tasks_v2.generic import (
    _text,
    generate,
    generate_world,
    grade,
    write_samples,
)
from opulse.tasks_v2.hooks import from_library, show
from opulse.tasks_v2.task import ANGLES


def _add_equivalent(world, name):
    original = world.library().get(name)
    world.library()._definitions[name + "_alternative"] = replace(
        original, name=name + "_alternative", body=n.Let("held", original.body, n.Var("held")))


@pytest.mark.parametrize("kind,name", [("object", "normalized"), ("operation", "plus_one"),
                                       ("combinator", "twice"), ("observation", "parity")])
@pytest.mark.parametrize("angle", ANGLES)
def test_every_kind_angle(kind, name, angle):
    world = toy_world()
    task = generate(world, name, angle, seed=17, index=0)
    assert task.kind == kind
    assert all(character == "\n" or 32 <= ord(character) < 127 for character in task.prompt["en"])
    if angle == "compute":
        answer, wrong = task.reference["outcome"], {"unknown": "fuel"}
    elif angle == "invert":
        answer, wrong = task.reference["witness"], -1
    elif angle == "decide":
        answer = dict(task.reference)
        wrong = {"true": not answer["true"]}
    elif angle == "describe":
        answer, wrong = task.reference["choice"], "absent"
    else:
        answer = {"body": task.reference["definition"]}
        wrong = {"body": n.to_json(n.Lit(9000))}
    assert grade(world, task, answer).correct
    assert not grade(world, task, wrong).correct
    assert task == generate(world, name, angle, seed=17, index=0)


def test_settings_boundaries_renderers_and_closed_kinds():
    world = toy_world()
    plain = generate(world, "plus_one", "compute", seed=1, index=0)
    opened = generate(world, "plus_one", "compute", seed=1, index=0,
                      boundary=Boundary.unfold_all(), observation={"show": {"input": "hidden", "result": "hidden"},
                                                                     "channels": []})
    image = generate(world, "plus_one", "compute", seed=1, index=0, modality="image")
    assert plain.reference == opened.reference == image.reference
    assert plain.question["settings"]["modality"] == "text"
    assert image.question["settings"]["modality"] == "image"
    assert {key: value for key, value in plain.question.items() if key != "settings"} == {
        key: value for key, value in image.question.items() if key != "settings"}
    assert plain.prompt["en"] == image.prompt["en"]
    assert plain.prompt["rendering"] != image.prompt["rendering"]
    assert "operation plus_one =" in plain.prompt["en"]
    assert grade(world, opened, plain.reference["outcome"]).correct
    tasks = generate_world(toy_world(["operation"]), 1, seed=2)
    assert tasks and {task.kind for task in tasks} == {"operation"}


@pytest.mark.parametrize("name", ["normalized", "plus_one", "twice", "parity"])
def test_boundary_and_observation_do_not_change_truth(name):
    world = toy_world()
    if name in ("plus_one", "twice"):
        _add_equivalent(world, name)
    hidden = {"show": {"input": "hidden", "result": "hidden"}, "channels": []}
    for angle in ANGLES:
        kept = generate(world, name, angle, seed=6, index=0)
        opened = generate(world, name, angle, seed=6, index=0,
                          boundary=Boundary.unfold_all(),
                          observation=hidden if name != "parity" or angle == "compute" else None)
        assert kept.reference == opened.reference
        assert kept.judge_view == opened.judge_view == "full_state"


def test_real_siblings_and_held_out():
    world = toy_world()
    described = generate(world, "plus_one", "describe", seed=3, index=0)
    assert "minus_one" in described.question["options"]
    assert "absent" not in described.question["options"]
    task = generate(world, "twice", "create", seed=3, index=0, variant="reusable")
    assert task.question["held_out"]
    assert grade(world, task, {"body": task.reference["definition"]}).correct
    observation = generate(world, "parity", "create", seed=3, index=0)
    assert grade(world, observation, {"body": observation.reference["definition"],
                                      "reads": ["probe", "secret"]}).reason == "forbidden_probe"
    combinator = generate(world, "twice", "induce", seed=3, index=0)
    assert all("trace" in example for example in combinator.question["examples"])


def test_sweep_includes_given_and_all_solutions():
    world = toy_world()
    tasks = generate_world(world, 2, seed=3)
    assert len(tasks) + len(tasks.skipped) == 12 * len(ANGLES) * 2 * 2
    assert {task.kind for task in tasks} == {"object", "operation", "combinator", "observation"}
    task = generate(world, "parity", "invert", seed=1, index=1)
    assert task.answer_shape == "all_solutions"
    assert grade(world, task, task.reference["solutions"]).correct
    assert not grade(world, task, task.reference["solutions"] * 2).correct
    with pytest.raises((ValueError, KeyError)):
        generate(world, "inc", "create", seed=3, index=0)





def test_realistic_sensor_counter_matrix():
    world = sensor_counter_world()
    tasks = generate_world(world, 1, seed=29)
    assert not tasks.skipped
    assert {(task.kind, task.angle) for task in tasks} == {
        (kind, angle) for kind in ("object", "operation", "combinator", "observation") for angle in ANGLES}
    assert any(task.family == "thrice" and task.angle == "decide" for task in tasks)
    assert all(task.prompt["en"].isascii() and "Answer format:" in task.prompt["en"] for task in tasks)
    for task in tasks:
        if task.answer_shape == "choice":
            assert len(task.question["options"]) >= 3
            assert task.reference["choice"] not in task.prompt["en"].split("Options:", 1)[0]
        if task.answer_shape == "verdict":
            assert "Scope:" in task.prompt["en"]
        if task.answer_shape == "definition":
            assert "Behavior:" in task.prompt["en"] and "Grading scope:" in task.prompt["en"]
    assert len([definition for definition in world.library().definitions.values()
                if definition.origin == "invented" and definition.kind == "object"]) >= 2


def test_object_canon_obligations_and_layer_zero():
    world = toy_world()
    task = generate(world, "normalized", "create", seed=7, index=0)
    assert grade(world, task, {"body": n.to_json(n.Call("inc", (n.Var("value"),)))}).reason == "object_obligation"
    shown = generate(world, "plus_one", "compute", seed=7, index=0,
                     boundary=Boundary.unfold_all()).prompt["en"]
    assert "operation inc: given" in shown
    assert "operation plus_one =" in shown


def test_skips_unavailable_choices_and_invert():
    world = toy_world(["operation"])
    library = world.library()
    library._definitions["flat"] = Definition("flat", "operation", "invented", 1, (),
        OperationSpec("flat", "transform", (Edge("int"),), Edge("int"), "constant"),
        n.Lit(0), status="callable")
    with pytest.raises(ValueError, match="invert needs"):
        generate(world, "flat", "invert", seed=1, index=0)
    tasks = generate_world(world, 1, seed=1)
    assert any(item["definition"] == "flat" and item["angle"] == "invert" for item in tasks.skipped)





def test_computer_mul_library_hook():
    world = computer_world()
    task = generate(world, "mul", "compute", seed=4, index=0)
    assert grade(world, task, task.reference["outcome"]).correct
    assert task.prompt["en"].isascii()


def test_named_bodies_dependencies_and_hidden_answer():
    world = toy_world()
    library = world.library()
    library._definitions["after_plus_one"] = Definition(
        "after_plus_one", "operation", "invented", 2, ("plus_one",),
        OperationSpec("after_plus_one", "transform", (Edge("int"),), Edge("int"), "repeat"),
        n.Call("plus_one", (n.Var("arg0"),)), status="callable")
    decision = generate(world, "twice", "decide", seed=3, index=1)
    assert "comb @twice[" in decision.prompt["en"]
    assert f"comb @{decision.question['other']}[" in decision.prompt["en"]
    described = generate(world, "plus_one", "describe", seed=3, index=0)
    for option in described.question["options"]:
        assert f"operation {option} =" in described.prompt["en"]
    assert "Examples: t(" in described.prompt["en"]
    assert "Examples: plus_one(" not in described.prompt["en"]
    computed = generate(world, "after_plus_one", "compute", seed=3, index=0)
    assert "operation after_plus_one =" in computed.prompt["en"]
    assert "operation plus_one =" in computed.prompt["en"]
    opened = generate(world, "after_plus_one", "compute", seed=3, index=0,
                      boundary=Boundary.unfold_all())
    assert "operation plus_one =" in opened.prompt["en"]
    created = generate(world, "after_plus_one", "create", seed=3, index=0)
    assert "operation after_plus_one =" not in created.prompt["en"]
    assert "operation plus_one =" in created.prompt["en"]
    object_creation = generate(world, "normalized", "create", seed=3, index=0,
                               boundary=Boundary.unfold_all())
    assert "Normalized canon =" not in object_creation.prompt["en"]
    assert "object Normalized =" not in object_creation.prompt["en"]


def test_counterexample_is_an_input_row():
    world = toy_world()
    task = generate(world, "plus_one", "decide", seed=3, index=2)
    row = task.reference["counterexample"]
    assert row in task.question["domain"]
    assert grade(world, task, {"true": False, "counterexample": row}).correct
    assert not grade(world, task, {"true": False, "counterexample": ["not an input"]}).correct
    assert not grade(world, task, {"true": False, "counterexample": 0}).correct
    library = world.library()
    library.atoms += (kernel.Atom("positive", 1, lambda value: value > 0),)
    library._definitions["partly_plus_one"] = Definition(
        "partly_plus_one", "operation", "invented", 1, ("inc", "dec", "positive"),
        OperationSpec("partly_plus_one", "transform", (Edge("int"),), Edge("int"), "conditional"),
        n.Case(((n.Test(n.Call("positive", (n.Var("arg0"),))),
                 n.Call("inc", (n.Var("arg0"),))),), n.Call("dec", (n.Var("arg0"),))),
        status="callable")
    conditional = generate(world, "partly_plus_one", "decide", seed=3, index=0)
    assert conditional.reference["true"] is False
    assert grade(world, conditional, conditional.reference).correct
    non_witnesses = [row for row in conditional.question["domain"]
                     if not grade(world, conditional, {"true": False, "counterexample": row}).correct]
    assert non_witnesses


def test_computer_codec_has_no_host_repr():
    from opulse.worlds_v2.computer import machine

    world = computer_world()
    state = machine.State((0, 3, 0, 0))
    assert world.from_value(world.to_value(state)) == state
    for task in generate_world(world, 1, seed=5):
        assert "State(" not in task.prompt["en"]
        assert "b'" not in task.prompt["en"]
        assert "State(" not in json.dumps(task.reference)
        assert "b'" not in json.dumps(task.reference)
        if task.angle == "compute":
            assert grade(world, task, task.reference["outcome"]).correct


@pytest.mark.parametrize("world_name,build", [("generic_toy", toy_world),
                                               ("sensor_counter", sensor_counter_world),
                                               ("computer", computer_world)])
def test_frozen_samples(world_name, build, tmp_path):
    tasks = generate_world(build(), 1, seed=5)
    # The new Boundary.to_dict includes law and bridge in its default kinds.
    assert all({"law", "bridge"} <= set(task.boundary["kinds"]) for task in tasks)
    root = Path(__file__).resolve().parents[2] / "worlds/tasks/generic" / world_name
    built = tmp_path / world_name
    assert write_samples((build(),), tmp_path)
    names = set()
    for task in tasks:
        if task.question["settings"]["modality"] != "text":
            continue
        name = f"{task.family}_{task.angle}.json"
        names.add(name)
        assert json.loads((built / name).read_text()) == task.to_dict()
        assert json.loads((root / name).read_text()) == task.to_dict()
    assert {path.name for path in root.glob('*.json')} == names


def test_printer():
    from opulse.atoms.values import Card

    assert show(Card("Frac", "Frac", (1, 2))) == "Frac<1, 2>"
    assert show(True) == "true"


def test_binary_audio_renderer():
    base = toy_world()
    world = from_library(base.library(), domains={"int": (-2, 0, 1, 3)},
                         modalities={"audio": lambda state: b"RIFF"})
    task = generate(world, "plus_one", "compute", seed=5, index=0, modality="audio")
    assert task.prompt["rendering"] == "data:audio/wav;base64,UklGRg=="
    assert task.reference == generate(base, "plus_one", "compute", seed=5, index=0).reference


def test_bottom_is_equal_but_unknown_is_not():
    from opulse.atoms.values import Bottom

    base = toy_world().library()
    base.atoms += (kernel.Atom("fail_atom", 1, lambda value: Bottom("first")),)
    base._definitions["fail"] = Definition("fail", "operation", "invented", 1, ("fail_atom",),
        OperationSpec("fail", "transform", (Edge("int"),), Edge("int"), "fails"),
        n.Call("fail_atom", (n.Var("arg0"),)), status="callable")
    world = from_library(base, domains={"int": (0,)})
    task = generate(world, "fail", "compute", seed=2, index=0)
    assert grade(world, task, {"bottom": "different reason"}).correct
    assert not grade(world, task, {"unknown": "fuel"}).correct


def test_memory_observation_sequences():
    base = toy_world()
    # The new observation checker forbids truth-sort literals even in memory.init.
    specification = ObservationSpec("history", ("probe",), n.Var("memory"),
                                    {"init": n.Lit(False), "step": n.Var("probe")})
    base.library()._definitions["history"] = Definition("history", "observation", "invented", 1,
        (), specification, specification.body, status="callable")
    task = generate(base, "history", "invert", seed=2, index=1)
    assert all(len(row) == 1 for row in task.question["domain"])
    assert len(task.question["domain"]) == len(base.states()) ** 2
    assert grade(base, task, task.reference["solutions"]).correct
    assert not grade(base, task, []).correct
    from opulse.atoms.observations import check_observation

    assert not check_observation(base.library().get("history"), base.library())
    created = generate(base, "history", "create", seed=2, index=0, variant="reusable")
    assert grade(base, created, {"body": created.reference["definition"]}).correct


def test_integer_story_if_importable():
    """The hook on the worlds lead's integer story; it depends only on promoted invented Int operations.

    generate() rejects given definitions (integration round 5: the first promoted operation was succ)."""
    from opulse.atoms.library import PipelineError

    story = pytest.importorskip("opulse.worlds_v2.integer.story")
    try:
        library = story.build_library()
    except PipelineError as error:  # owned by the worlds lead; the tasks hook is not involved
        pytest.skip(f"worlds integer story does not build on this core: {error}")
    candidates = [definition.name for definition in library.definitions.values()
                  if definition.kind == "operation" and definition.status == "promoted"
                  and definition.origin == "invented"
                  and definition.spec.inputs and all(edge.sort == "int" for edge in definition.spec.inputs)]
    if not candidates:
        pytest.skip("worlds integer story has no promoted invented operation over Int")
    world = from_library(library, domains={"int": tuple(range(-2, 3))})
    task = generate(world, candidates[0], "compute", seed=2, index=0)
    assert grade(world, task, task.reference["outcome"]).correct


def test_object_member_calls_print_as_ascii_identifiers():
    """Refinement constructors such as frac.make (integer story) have no core notation yet."""
    node = n.Call("frac.make", (n.Call("pair", (n.Var("a"), n.Var("b"))),))
    assert _text(toy_world(), node) == "frac_make(pair(a, b))"


def test_prompts_print_bodies_in_ascii_not_node_json():
    for build in (toy_world, sensor_counter_world, computer_world):
        for task in generate_world(build(), 1, seed=5):
            prompt = task.prompt["en"]
            assert '"node"' not in prompt and "{'node'" not in prompt
            assert all(ord(char) < 128 for char in prompt)


@pytest.mark.parametrize("name", ("normalized", "plus_one", "twice", "parity"))
def test_decide_distribution_and_no_self_comparison(name):
    world = toy_world()
    if name == "twice":
        with pytest.raises(ValueError, match="distinct equivalent definition"):
            generate(world, name, "decide", seed=5, index=0)
        _add_equivalent(world, name)
    tasks = [generate(world, name, "decide", seed=5, index=index) for index in range(8)]
    assert {task.reference["true"] for task in tasks} == {True, False}
    assert any(tasks[index].reference["true"] == tasks[index + 1].reference["true"]
               for index in range(len(tasks) - 1))
    assert all(task.question.get("other") != name for task in tasks)
    for verdict in (True, False):
        task = next(task for task in tasks if task.reference["true"] == verdict)
        assert grade(world, task, task.reference).correct


@given(st.integers(min_value=0, max_value=1000))
@settings(max_examples=5, deadline=None)
def test_equivalent_decide_claims_use_distinct_definitions(seed):
    world = toy_world()
    _add_equivalent(world, "plus_one")
    for index in range(3):
        task = generate(world, "plus_one", "decide", seed=seed, index=index)
        assert task.question["other"] != task.question["definition"]
        assert grade(world, task, task.reference).correct


def test_injective_observation_has_both_decide_verdicts():
    world = toy_world()
    world.library().atoms += (kernel.Atom("identity_probe", 1, lambda state: state,
                                          kind="observation"),)
    spec = ObservationSpec("identity", ("identity_probe",), n.Var("identity_probe"))
    world.library()._definitions["identity"] = Definition(
        "identity", "observation", "invented", 1, (), spec, spec.body, status="callable")
    tasks = [generate(world, "identity", "decide", seed=5, index=index) for index in range(8)]
    assert {task.reference["true"] for task in tasks} == {True, False}
    assert all(grade(world, task, task.reference).correct for task in tasks)


@given(st.integers(min_value=0, max_value=30))
@settings(max_examples=6, deadline=None)
def test_boundary_preserves_grading_truth(seed):
    world = toy_world()
    opened = generate(world, "plus_one", "compute", seed=seed, index=0)
    kept = generate(world, "plus_one", "compute", seed=seed, index=0,
                    boundary=Boundary(depth=0, keep_names=frozenset({"inc"})))
    assert opened.reference == kept.reference
    assert grade(world, kept, opened.reference["outcome"]).correct


def test_kept_target_never_opens_and_skips_with_reason():
    world = toy_world()
    boundary = Boundary(keep_names=frozenset({"plus_one"}))
    with pytest.raises(ValueError, match="boundary keeps required target plus_one closed"):
        generate(world, "plus_one", "compute", seed=6, index=0, boundary=boundary)
    tasks = generate_world(world, 1, seed=6, boundary=boundary)
    assert any(entry["definition"] == "plus_one" and entry["angle"] == "compute"
               and "boundary keeps required target" in entry["reason"] for entry in tasks.skipped)


def test_hidden_observation_never_exposes_truth_input():
    world = toy_world()
    hidden = {"show": {"input": "hidden", "result": "hidden"}, "channels": []}
    for modality in ("text", "image"):
        task = generate(world, "parity", "compute", seed=5, index=0,
                        modality=modality, observation=hidden)
        assert task.question["inputs"] == ["hidden"]
        assert "input withheld" in task.prompt["en"]
        assert "?parity{hidden}" in task.prompt["en"]
        assert "arg0 in" not in task.prompt["en"]
        assert task.prompt["rendering"] == (task.prompt["en"] if modality == "text" else "image:hidden")
        assert grade(world, task, task.reference["outcome"]).correct
    with pytest.raises(ValueError, match="hidden observation input"):
        generate(world, "parity", "invert", seed=5, index=0, observation=hidden)


def test_only_valid_promotion_may_close_definition():
    world = toy_world()
    library = world.library()
    library._definitions["plus_one"] = replace(
        library.get("plus_one"), spec=replace(library.get("plus_one").spec,
                                               rule="private_implementation_rule"))
    boundary = Boundary(depth=0, keep_names=frozenset({"plus_one"}))
    with pytest.raises(ValueError, match="unverified definition"):
        generate(world, "plus_one", "describe", seed=5, index=0,
                 boundary=boundary)
    domain = tuple((value,) for value in world.domain("int"))
    evidence = Evidence("exhaustive", {"domain": "toy", "size": len(domain),
                                        "checked": checked_scope(domain)},
                        checks=("unfold_equivalence",), world_hash=library.world.world_hash(),
                        deps_hash=library._deps_hash("plus_one"),
                        content_hash=library.content_hash("plus_one"), atoms_hash=atoms_digest(library.atoms))
    contract = Contract("returns successor")
    library._definitions["plus_one"] = replace(library.get("plus_one"), status="promoted",
                                                evidence=evidence, contract=contract)
    task = generate(world, "plus_one", "describe", seed=5, index=0,
                    boundary=boundary)
    assert "operation plus_one =" not in task.prompt["en"]
    assert task.source["evidence_scope"] == evidence.scope
    assert task.source["contract"] == contract.to_dict()
    assert task.question["description"] == contract.guarantees
    assert "contract: returns successor" in task.prompt["en"]
    assert "private_implementation_rule" not in json.dumps(task.question)
    assert "private_implementation_rule" not in task.prompt["en"]
    computed = generate(world, "plus_one", "compute", seed=5, index=0,
                        boundary=boundary)
    assert "operation plus_one =" not in computed.prompt["en"]
    assert computed.source["evidence_scope"] == evidence.scope
    assert grade(world, computed, computed.reference["outcome"]).correct
    library._definitions["after_plus_one"] = Definition(
        "after_plus_one", "operation", "invented", 2, ("plus_one",),
        OperationSpec("after_plus_one", "transform", (Edge("int"),), Edge("int"), "repeat"),
        n.Call("plus_one", (n.Var("arg0"),)), status="callable")
    dependency = generate(world, "after_plus_one", "compute", seed=5, index=0,
                          boundary=boundary)
    assert "operation plus_one =" not in dependency.prompt["en"]
    assert dependency.source["promotions"]["plus_one"]["evidence_scope"] == evidence.scope
    assert dependency.source["promotions"]["plus_one"]["contract"] == contract.to_dict()
    library._definitions["plus_one"] = replace(library.get("plus_one"),
                                                evidence=replace(evidence, content_hash="invalid"))
    with pytest.raises(ValueError, match="unverified definition"):
        generate(world, "plus_one", "describe", seed=5, index=0,
                 boundary=boundary)


@given(st.integers(min_value=0, max_value=2))
@settings(max_examples=3, deadline=None)
def test_all_grading_paths_respect_resource_limit(index):
    world = toy_world()
    _add_equivalent(world, "twice")
    for angle in ANGLES:
        task = generate(world, "twice", angle, seed=5, index=index)
        limited = replace(task, grader={**task.grader, "fuel": 1})
        answer = (task.reference.get("outcome") if angle == "compute" else
                  task.reference.get("witness") if angle == "invert" and index % 2 == 0 else
                  task.reference.get("solutions") if angle == "invert" else
                  task.reference if angle == "decide" else
                  task.reference.get("choice") if angle == "describe" else
                  {"body": task.reference["definition"]})
        assert not grade(world, limited, answer).correct


def test_observation_with_two_inputs_uses_domain_and_truth():
    base = toy_world()
    library = base.library()
    spec = ObservationSpec("offset", ("probe",), n.Call("inc", (n.Var("offset"),)),
                           extra={"input_names": ("s", "offset"), "input_sorts": ("int", "int")})
    library._definitions["offset"] = Definition("offset", "observation", "invented", 1,
                                                ("inc",), spec, spec.body, status="callable")
    task = generate(base, "offset", "compute", seed=2, index=0)
    assert len(task.question["inputs"]) == 2
    assert grade(base, task, task.reference["outcome"]).correct
    assert len(generate(base, "offset", "invert", seed=2, index=1).question["domain"]) == 16


def test_observation_address_input_uses_full_truth_state():
    base = toy_world()
    library = base.library()
    library.atoms += (kernel.Atom("probe_addr", 2, lambda state, address: state + address,
                                  kind="observation"),)
    spec = ObservationSpec("lookup", ("probe_addr",),
                           n.Call("probe_addr", (n.Var("s"), n.Var("addr"))))
    library._definitions["lookup"] = Definition("lookup", "observation", "invented", 1,
                                               ("probe_addr",), spec, spec.body, status="callable")
    world = from_library(library, domains={"Addr": (0, 1)}, states=(-2, 3))
    task = generate(world, "lookup", "compute", seed=2, index=0)
    assert len(task.question["inputs"]) == 2
    assert task.reference["outcome"] == {"ok": {"t": "int", "v": sum(map(int, task.question["inputs"]))}}
    assert grade(world, task, task.reference["outcome"]).correct


def test_observation_infers_three_argument_domain():
    world = toy_world()
    spec = ObservationSpec("combine", ("probe",), n.Call("inc", (n.Var("x"),)))
    world.library()._definitions["combine"] = Definition(
        "combine", "observation", "invented", 1, ("inc",), spec, spec.body,
        status="callable")
    task = generate(world, "combine", "compute", seed=2, index=0)
    assert len(task.question["inputs"]) == 2
    assert grade(world, task, task.reference["outcome"]).correct
    world.library().atoms += (kernel.Atom("sum_three", 3,
                                          lambda state, first, second: state + first + second),)
    spec = ObservationSpec("combine_three", ("probe",),
                           n.Call("sum_three", (n.Var("s"), n.Var("x"), n.Var("y"))),
                           extra={"input_names": ("s", "x", "y"), "input_sorts": ("int", "int", "int")})
    world.library()._definitions["combine_three"] = Definition(
        "combine_three", "observation", "invented", 1, ("sum_three",), spec, spec.body,
        status="callable")
    task = generate(world, "combine_three", "compute", seed=2, index=0)
    assert len(task.question["inputs"]) == 3
    assert task.reference["outcome"] == {"ok": {"t": "int", "v": sum(map(int, task.question["inputs"]))}}
    assert grade(world, task, task.reference["outcome"]).correct
    hidden = {"show": {"input": "hidden", "result": "hidden"}, "channels": []}
    image = generate(world, "combine_three", "compute", seed=2, index=0,
                     modality="image", observation=hidden)
    assert image.question["inputs"] == ["hidden"] * 3
    assert image.prompt["rendering"] == "image:hidden"
    assert all(input_value not in image.prompt["en"] for input_value in task.question["inputs"]
               if input_value not in ("0", "1"))
    assert grade(world, image, image.reference["outcome"]).correct
