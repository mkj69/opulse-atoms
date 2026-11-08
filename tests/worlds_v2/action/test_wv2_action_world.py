"""Independent reference and kernel-pipeline checks for the sealed maze."""

import json
import os
import re
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from opulse.atoms import kernel, nodes, notation, values
from opulse.atoms.boundary import Boundary
from opulse.atoms.library import PipelineError
from opulse.atoms.observations import observe
from opulse.atoms.verify import unfold_equivalent
from opulse.atoms.world import WorldDecl
from opulse.tasks_v2.decl import load, validate
from opulse.worlds_v2 import export_util
from opulse.worlds_v2.action import hosts
from opulse.worlds_v2.action.export import build_export, expression
from opulse.worlds_v2.action.story import (
    build_library,
    definitions,
    evidence_domain,
    example_inputs,
    reference,
    reference_outcome,
    to_reference,
)
from opulse.worlds_v2.action.world import decl, new_library


@pytest.fixture(scope="module")
def library():
    return build_library()


@pytest.fixture(scope="module")
def exported(library):
    result = build_export(lib=library)
    assert result == json.loads(Path("docs/assets/data/worlds_v2/action.json").read_text())
    return result


slow = pytest.mark.skipif(os.environ.get("OPULSE_RUN_SLOW") != "1",
                          reason="full-scope re-check; set OPULSE_RUN_SLOW=1")


def test_first_three_cards_build_fresh():
    fresh = new_library()
    samples = example_inputs()
    for definition in definitions()[:3]:
        fresh.write(definition)
        fresh.check(definition.name)
        fresh.make_callable(definition.name, (samples[definition.name],))
        callable_name = (definition.name + "." + definition.name.lower()
                         if definition.kind == "object" else definition.name)
        assert isinstance(fresh.run(callable_name, samples[definition.name]).outcome, values.Ok)


def test_checked_evidence_and_operation_families(library):
    for name in (definition.name for definition in definitions()):
        scope = library.get(name).evidence.scope
        assert scope["checked"]["size"] == scope["size"]
        assert re.fullmatch(r"[0-9a-f]{64}", scope["checked"]["sha256"])
    assert library.get("scan").evidence.scope["op_family"] == {
        "turn": ["turn_left", "turn_right"], "probe": ["sense"]}
    assert library.get("follow").evidence.scope["op_family"] == {
        "step": ["forward", "safe_step"]}


def test_declaration_and_export(library, exported):
    world = decl()
    assert WorldDecl.from_dict(world.to_dict()).to_dict() == world.to_dict()
    assert not validate(load("worlds/decl/v2/action@2.json"))
    disk = exported
    judge = json.loads(Path("worlds/judge/action.json").read_text())
    assert set(judge["fixtures"]) == {"M1", "M2", "M3"}
    assert len(judge["verification_fixtures"]) == 64
    assert all(judge["fixtures"][name]["map"] == list(hosts.MAPS[name])
               for name in ("M1", "M2", "M3"))
    assert disk["tower_source"] == "depth" and len(disk["story"]) == 12
    assert [entry["status"] for entry in disk["story"]] == ["promoted"] * 12
    for entry in disk["story"]:
        assert entry["def_layer"] == library.get(entry["name"]).layer
        assert entry["symbol"].startswith({"object": entry["name"] + "<",
                                            "operation": entry["name"] + "(",
                                            "combinator": "@", "observation": "?"}[entry["kind"]])
        assert entry["evidence"]["scope"]["size"] > 0
        assert entry["evidence"]["scope"]["size"] >= 50 or entry["name"] == "front_clear"
        assert entry["title"] and entry["definition"]
        assert entry["evidence"]["method"] in ("bounded", "exhaustive")
        for example in entry["examples"]:
            sealed = entry["name"] in ("explore", "Atlas")
            args = tuple(values.decode(arg) for arg in judge["examples"][example["id"]]["inputs"])
            assert example["text"] == ("Atlas.atlas(" + expression("explore", args) + ")"
                                       if entry["name"] == "Atlas" else expression(entry["name"], args))
            assert "judge_view" not in example
            assert example["id"] in judge["examples"]
            if not sealed:
                name = entry["name"] + "." + entry["name"].lower() if entry["kind"] == "object" else entry["name"]
                run = library.run(name, args, fuel=2_000_000)
                assert values.encode_outcome(run.outcome) == example["outcome"]
                assert run.steps == example["steps"]
            else:
                assert "ok" in example["outcome"] and example["steps"] > 0
            assert "learner_view" in example
            assert "map" not in example["text"].lower()
    assert any("bottom" in example["outcome"] for entry in disk["story"] for example in entry["examples"])
    assert Path("docs/assets/data/worlds_v2/action.json").stat().st_size < 3_000_000


def test_reference_every_card_and_showcase(library, exported):
    depth = json.loads(Path("worlds/catalogue/depth/action.json").read_text())
    disk = exported
    ref = reference()
    judge = json.loads(Path("worlds/judge/action.json").read_text())
    keys = ("clear", "step", "scan_object", "sense", "scan", "known", "merge",
            "frontier", "route_known", "follow", "explore", "atlas")
    for card, entry, key in zip(depth["tower"], disk["story"], keys):
        example = entry["examples"][0]
        if entry["name"] not in ("explore", "Atlas"):
            assert example["outcome"] == values.encode_outcome(
                library.run(entry["name"] + "." + entry["name"].lower() if entry["kind"] == "object" else entry["name"], tuple(values.decode(arg) for arg in judge["examples"][example["id"]]["inputs"]),
                            fuel=2_000_000).outcome)
        shown = judge["examples"][example["id"]]["judge_view"]["value"]
        if entry["name"] == "explore":
            assert shown["probes"] < card["value"]["probes"]
            assert {part: value for part, value in shown.items() if part != "probes"} == {
                part: value for part, value in card["value"].items() if part != "probes"}
        else:
            assert shown == card["value"] == ref._result(key)
    for task, key in zip(disk["showcase"], ("compute", "invert", "decide")):
        assert task["answer"] == ref._result(key) and task["answer_checked"]


@slow
def test_all_three_sealed_maps_and_boundary(library):
    ref = reference()
    for maze_id in ("M1", "M2", "M3"):
        bot = hosts.start(hosts.maze(maze_id))
        assert hosts.from_card(hosts.to_card(bot)) == bot
        assert library.learner_view(bot) == {
            "pose": hosts.pose(bot), "front_wall": hosts.front_wall(bot),
            "front_water": hosts.front_water(bot), "odometer": hosts.odometer(bot)}
        survey = library.run("explore", (kernel.FnRef("scan_default"), kernel.FnRef("safe_step"),
                                         kernel.FnRef("route_known"), bot), fuel=2_000_000)
        assert isinstance(survey.outcome, values.Ok)
        expected = ref.explore(ref.start(ref.Maze(maze_id)))
        actual = to_reference(survey.outcome.value)
        assert actual == expected
        assert set(actual.known.scanned) == ref._oracle_reachable(ref.Maze(maze_id))
        assert not ref.frontier(actual.known)
        assert library.run("make_atlas", (survey.outcome.value,)).outcome == values.Ok(
            values.Card("Atlas", "atlas", (survey.outcome.value,)))
    assert hosts.front_wall(hosts.turn_left(hosts.start(hosts.maze("M1")))) == values.TRUE
    blocked = library.run("safe_step", (hosts.turn_left(hosts.start(hosts.maze("M1"))),))
    assert blocked.outcome == values.Bottom("blocked")
    assert library.judge_verdict(hosts.start(hosts.maze("M1")),
                                library.run("safe_step", (hosts.start(hosts.maze("M1")),)).outcome)


def test_layer_zero_primitives_and_independent_scope(library):
    ref = reference()
    for maze_id, rows in ((name, hosts.MAPS[name]) for name in ("M1", "M2", "M3")):
        assert len(rows) == 10 and all(len(row) == 12 for row in rows)
        maze = ref.Maze(maze_id)
        for x, y in ref._oracle_reachable(maze):
            for heading in range(4):
                bot = hosts.mint_bot(hosts.maze(maze_id), x, y, heading, 0, 0)
                expected = ref.Bot(maze, x, y, heading)
                assert hosts.front_wall(bot) == values.boolean(ref.front_wall(expected))
                assert hosts.front_water(bot) == values.boolean(ref.front_water(expected))
                result = library.run("safe_step", (bot,))
                assert result.outcome == reference_outcome("safe_step", bot) if not ref.front_clear(expected) else result.outcome == values.Ok(
                    hosts.mint_bot(hosts.maze(maze_id), *ref.safe_step(expected).pos, heading, 1, 0))


def test_kernel_boundary_and_evidence_invalidation(library):
    bot = hosts.start(hosts.maze("M1"))
    sequential = library.run("seq", (kernel.FnRef("turn_right"),
                                     kernel.FnRef("turn_left"), bot), trace=True)
    assert sequential.outcome == values.Ok(hosts.mint_bot(*bot.fields[:-1], 2))
    assert sequential.steps == 2 and unfold_equivalent(sequential.trace, [Boundary()]).ok
    for name, args in (("safe_step", (bot,)), ("sense", (bot,)),
                       ("scan", example_inputs()["scan"])):
        trace = library.run(name, args, trace=True)
        assert unfold_equivalent(trace.trace, [Boundary(), Boundary(depth=0), Boundary(depth=1)]).ok
    virgin = new_library()
    virgin.write(definitions()[0])
    virgin.check("front_clear")
    with pytest.raises(PipelineError):
        virgin.promote("front_clear", library.get("front_clear").contract)
    changed = new_library()
    changed.write(definitions()[0])
    changed._definitions["front_clear"] = library.get("front_clear")
    changed.world = replace(changed.world, constants={"different": True})
    assert changed.get("front_clear").status == "callable"


def test_export_ascii_and_seal():
    data = json.loads(Path("docs/assets/data/worlds_v2/action.json").read_text())
    forbidden = re.compile("[\u27e8\u27e9\u27e6\u27e7\u2985\u2986\u2660\u2666\u25cb\u25c9\u211a\U0001d400-\U0001d7ff]")

    def visit(value, key=""):
        if isinstance(value, dict):
            for name, item in value.items():
                yield from visit(item, name)
        elif isinstance(value, list):
            for item in value:
                yield from visit(item, key)
        elif isinstance(value, str) and not key.endswith("_zh"):
            yield value

    assert not [text for text in visit({key: value for key, value in data.items()
                                        if key != 'notation3'}) if forbidden.search(text)]
    for card in data["story"]:
        for example in card["examples"]:
            assert not re.search(r"#{12}|#\.\.|##\.\.", example["text"])
    assert "judge_view" not in json.dumps(data["story"])
    assert "############" not in json.dumps(data)


def test_story_ascii_matches_stored_bodies(exported, library):
    for row in exported["story"]:
        digest = export_util.body_sha256(library.get(row["name"]).body)
        assert row["body_sha256"] == digest
        if "ascii" in row:
            assert export_util.source_matches(row["ascii"], digest)


def test_story_declarations_are_parseable_at_computed_layer(exported, library):
    assert not any("ascii" in row for row in exported["story"])
    for row in exported["story"]:
        digest = export_util.body_sha256(library.get(row["name"]).body)
        assert row["body_sha256"] == digest
        if "ascii" in row:
            parsed = notation.parse_definition(row["ascii"])
            assert parsed.name == row["name"]
            assert parsed.kind == row["kind"]
            assert parsed.layer == row["def_layer"]
            assert row["decl"].endswith(f" L{row['def_layer']}")
            assert row["ascii"] == row["decl"]
            assert export_util.source_matches(row["ascii"], digest)
        else:
            assert "decl" not in row
        assert row["design_decl"] == row["design_text"]


def test_ascii_examples_are_exactly_the_parseable_text(exported):
    for row in exported["story"]:
        for example in row["examples"]:
            try:
                notation.parse_expr(example["text"])
            except notation.NotationError:
                assert "ascii" not in example
            else:
                assert example["ascii"] == example["text"]


def test_forged_sealed_survey_is_not_authorized(library):
    bot = hosts.start(hosts.maze("M1"))
    origin = values.Card("Pos", "pos", (1, 1))
    known = values.Card("Known", "known", (origin, values.Card("List", "items"),
                                            values.Card("List", "items", (origin,))))
    forged = values.Card("Survey", "survey", (bot, known, 1))
    for sort in ("Survey", "Scan", "Known", "Atlas"):
        assert library.run("card", (sort, sort.lower(), values.Card("List", "items"))).outcome == values.Bottom("invalid")
    for name in ("make_atlas", "Atlas.atlas"):
        assert library.run(name, (forged,)).outcome == values.Bottom("invalid")
    assert library.run("survey", (bot, known, 1)).outcome == values.Bottom("invalid")


def test_compose_constructors_reject_invalid_fields(library):
    origin = values.Card("Pos", "pos", (1, 1))
    empty = values.Card("List", "items")
    faces = values.Card("List", "items", ("#", ".", ".", "#"))
    for args in ((-1, 1, faces), (12, 1, faces), (1, 10, faces),
                 (1, 1, empty), (1, 1, values.Card("List", "items", ("#", ".", "X", "#")))):
        assert library.run("Scan.scan", args).outcome == values.Bottom("invalid")
    valid_tiles = values.Card("List", "items", (values.Card("Pair", "pair", (origin, ".")),))
    for args in ((origin, empty, empty), (origin, valid_tiles,
                  values.Card("List", "items", (origin, origin))),
                 (origin, values.Card("List", "items", (
                     values.Card("Pair", "pair", (origin, "?")),)), empty)):
        assert library.run("Known.known", args).outcome == values.Bottom("invalid")


def test_forged_bot_is_rejected_at_probe_and_learner_boundary(library):
    maze = hosts.maze("M1")
    forged = values.Card("Bot", "bot", (maze, 2, 1, 1, 0, 0))
    assert hosts.front_wall(forged) == values.Bottom("invalid")
    assert library.run("front_wall", (forged,)).outcome == values.Bottom("invalid")
    assert library.run("safe_step", (forged,)).outcome == values.Bottom("invalid")
    assert library.run("explore", (kernel.FnRef("scan_default"), kernel.FnRef("safe_step"),
                                    kernel.FnRef("route_known"), forged)).outcome == values.Bottom("invalid")
    valid = hosts.start(maze)
    assert hosts.valid_state(deepcopy(valid))


def test_scan_requires_actual_four_face_measurement(library):
    faces = values.Card("List", "items", (".", ".", ".", "."))
    assert library.run("Scan.scan", (1, 1, faces)).outcome == values.Bottom("invalid")
    measured = library.run("scan", example_inputs()["scan"])
    assert isinstance(measured.outcome, values.Ok)
    scan = measured.outcome.value.fields[1]
    assert library.run("Scan.scan", scan.fields).outcome == values.Ok(scan)


def test_atlas_example_replays_its_nested_expression(library, exported):
    example = exported["story"][-1]["examples"][0]
    assert example["text"] == "Atlas.atlas(" + expression("explore", example_inputs()["explore"]) + ")"
    assert example["steps"] == exported["story"][-2]["examples"][0]["steps"] + 1
    assert example["trace"]["steps"] == example["steps"]
    assert [child["name"] for child in example["trace"]["children"]] == ["explore", "Atlas.atlas"]
    assert example["outcome"] == {"ok": {"sealed_fixture": example["id"]}}


def test_survey_measurement_survives_copy_and_forgery_fails(library):
    result = library.run("explore", example_inputs()["explore"], fuel=2_000_000)
    survey = result.outcome.value
    assert hosts.stats(deepcopy(survey)) == hosts.stats(survey)
    forged = values.Card("Survey", "survey", (*survey.fields[:3], survey.fields[3] + 100, survey.fields[4]))
    assert hosts.stats(forged) == values.Bottom("invalid")
    assert library.run("Atlas.atlas", (forged,)).outcome == values.Bottom("invalid")


def test_sparse_evidence_identifies_its_actual_ids(library):
    family = {name for name in hosts.MAPS if name.startswith("E")}
    assert len(family) == 64 and "E112" in family and "E063" not in family
    assert "E000-E112" in library.get("explore").evidence.scope["domain"]


def test_front_clear_observes_real_bot_probes(library):
    bot = hosts.start(hosts.maze("M1"))
    hosts._observed.clear()
    assert library.run("front_clear", (bot,)).outcome == values.Ok(values.TRUE)
    assert hosts._observed[("M1", 1, 1, 1)] == "."
    wall = hosts.turn_left(bot)
    assert library.run("front_clear", (wall,)).outcome == values.Ok(values.FALSE)
    water_facing = hosts.mint_bot(hosts.maze("M1"), 2, 5, 2, 0, 0)
    assert hosts.front_water(water_facing) == values.TRUE
    assert library.run("front_clear", (water_facing,)).outcome == values.Ok(values.FALSE)
    assert library.get("front_clear").evidence.scope["size"] == 52


def test_count_template_has_two_memory_instantiations(library, exported):
    assert {item["name"] for item in exported["templates"][0]["instances"]} == {
        "count_front_wall", "count_front_water"}
    for probe in ("front_wall", "front_water"):
        definition = library.get("count_" + probe)
        assert definition.spec.memory is not None
        assert definition.spec.reads == (probe,)
        assert "Count" in definition.depends_on
        assert definition.spec.extra["template"]["args"] == {"probe": probe}
        history = [hosts.mint_bot(hosts.maze("M1"), 1, 1, heading, 0, 0)
                   for heading in range(4)]
        expected = 0
        for outcome, state in zip(observe(definition, library, history), history):
            expected += getattr(hosts, probe)(state) == values.TRUE
            assert outcome == values.Ok(expected)


@given(st.sampled_from(("M1", "M2", "M3")), st.integers(min_value=1, max_value=10),
       st.integers(min_value=1, max_value=8), st.integers(min_value=0, max_value=3))
def test_random_pose_unfold_and_boundary(library, maze_id, x, y, heading):
    if hosts.MAPS[maze_id][y][x] != ".":
        return
    bot = hosts.mint_bot(hosts.maze(maze_id), x, y, heading, 0, 0)
    result = library.run("safe_step", (bot,), trace=True)
    call = nodes.Call("safe_step", (nodes.Lit(bot),))
    replay = kernel.evaluate(kernel.inline(call, library.scope()), scope=library.scope())
    assert (replay.outcome, replay.steps) == (result.outcome, result.steps)
    expected = reference_outcome("safe_step", bot)
    assert result.outcome == (expected if isinstance(expected, values.Bottom) else values.Ok(expected))


@slow
def test_evidence_families_and_generated_object_operations(library):
    samples = example_inputs()
    domains = {}
    for name in ("safe_step", "Scan", "sense", "scan", "Known", "make_known",
                 "merge_scan", "frontier", "route_known", "follow", "explore",
                 "Atlas", "make_atlas"):
        domain = evidence_domain(library, name, samples)
        domains[name] = domain
        assert len(domain) >= 50
        assert len({repr(row) for row in domain}) == len(domain)
        assert library.get(name).evidence.scope["size"] == len(domain)
    assert {row[0].name for row in evidence_domain(library, "scan", samples)} == {
        "turn_right", "turn_left"}
    assert {row[0].name for row in evidence_domain(library, "follow", samples)} == {
        "safe_step", "forward"}
    assert {row[1].name for row in evidence_domain(library, "explore", samples)} == {
        "safe_step", "forward"}
    for name in ("Scan", "Known", "Atlas"):
        constructor = name + "." + name.lower()
        assert library.get(name).spec.interface == (constructor,)
        assert library.get(name).spec.sealed
        assert library.scope().resolve(constructor) is not None
        assert library.scope().resolve(name) is None
        assert isinstance(library.run(constructor, domains[name][0]).outcome, values.Ok)
        with pytest.raises(KeyError):
            library.run(name, domains[name][0])
