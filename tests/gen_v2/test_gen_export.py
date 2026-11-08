import json

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.spec import Definition, Edge, OperationSpec
from opulse.gen_v2.admit import admit
from opulse.gen_v2.base import Candidate, Entry, GenState, Signature, count_summary
from opulse.gen_v2.export import (
    export,
    export_compact,
    export_jsonl,
    export_story,
    export_summary_md,
)
from opulse.gen_v2.library import GenLibrary
from opulse.gen_v2.notation import parse_declaration, parse_term
from opulse.gen_v2.worlds import toy


def test_count_summary_keeps_kind_and_layer_totals():
    entries = [Entry("A1", "object", 1, None, "test", ()),
               Entry("f2", "operation", 2, None, "test", ()),
               Entry("f3", "operation", 2, None, "test", ())]
    counts = count_summary(iter(entries))
    assert counts["per_kind"]["operation"] == 2
    assert counts["per_layer"] == {"1": 1, "2": 2}
    assert counts["per_kind_layer"]["object"] == {"1": 1}


def test_review6_1_combinator_slot_examples_replay(tmp_path):
    from opulse.gen_v2.export import _decode_example
    from opulse.gen_v2.run import generate
    from opulse.gen_v2.worlds import toy_truth

    state = generate(toy_truth.gen_world(("object", "operation", "combinator", "observation")),
                     12, 9, per_kind_min=2, layer_target=1, time_limit=12)
    entries = [item for item in export(state, tmp_path / "comb.json")["entries"]
               if item["kind"] == "combinator"]
    assert entries
    for entry in entries:
        for example in entry["examples"]:
            args = tuple(_decode_example(item, state) for item in example["inputs"])
            run = kernel.call(entry["name"], args, state.library.scope(),
                              kernel.Limits(fuel=state.world.fuel), dialect=state.world.dialect)
            from opulse.gen_v2.codec import encode_outcome

            assert encode_outcome(run.outcome) == example["outcome"]
            assert run.steps == example["steps"]


def test_review6_4_object_and_observation_replay_recipes(tmp_path):
    from opulse.gen_v2.codec import encode_outcome
    from opulse.gen_v2.export import _decode_example
    from opulse.gen_v2.kinds.observations import (
        _evaluate,
        _probe_values,
        _read_arguments,
    )
    from opulse.gen_v2.run import generate
    from opulse.gen_v2.worlds import toy_truth

    state = generate(toy_truth.gen_world(("object", "operation", "combinator", "observation")),
                     12, 9, per_kind_min=2, layer_target=1, time_limit=12)
    entries = export(state, tmp_path / "replay.json")["entries"]
    assert {item["kind"] for item in entries} >= {"object", "observation"}
    for entry in entries:
        for example in entry["examples"]:
            recipe = example["replay"]
            if entry["kind"] == "object":
                args = tuple(_decode_example(item, state) for item in recipe["inputs"])
                result = kernel.call(recipe["name"], args, state.library.scope(),
                                     kernel.Limits(fuel=state.world.fuel), dialect=state.world.dialect)
                assert encode_outcome(result.outcome) == example["outcome"]
            elif entry["kind"] == "observation":
                defn = state.library.get(entry["name"])
                scope = state.library.scope()
                history = tuple(_decode_example(item, state) for item in recipe["history"])
                outcome, steps = _evaluate(state, defn, history, scope)
                assert encode_outcome(outcome) == example["outcome"] and steps == example["steps"]
                arguments = _read_arguments(state, defn, scope)
                for truth_state, stored in zip(history, recipe["reads"]):
                    reads, _, error = _probe_values(state, defn.spec.reads, truth_state, scope, arguments)
                    assert error is None
                    assert {name: _decode_example(value, state) for name, value in stored.items()} == reads
                for calls in recipe["probe_calls"]:
                    for call in calls:
                        args = tuple(_decode_example(item, state) for item in call["inputs"])
                        result = kernel.call(call["name"], args, scope,
                                             kernel.Limits(fuel=state.world.fuel), dialect=state.world.dialect)
                        assert encode_outcome(result.outcome) == call["outcome"]


def test_review6_7_classic_bottom_showcase_has_story():
    from opulse.gen_v2.run import generate
    from opulse.gen_v2.worlds.classic import gen_world

    state = generate(gen_world("integer"), 28, 1, per_kind_min=0, layer_target=0, time_limit=20)
    assert "w10" in state.entries
    stories = export_story(state, ["w10"])
    assert len(stories) == 1 and stories[0]["examples"]
    assert any("bottom" in example["outcome"] for example in stories[0]["examples"])
    assert json.dumps(stories, ensure_ascii=True)


def test_review6_8_classic_examples_use_copyable_values(tmp_path):
    from opulse.gen_v2.export import _decode_example
    from opulse.gen_v2.run import generate
    from opulse.gen_v2.worlds.classic import gen_world

    for name in ("integer", "lists", "perm"):
        state = generate(gen_world(name), 8, 1, per_kind_min=0, layer_target=0, time_limit=20)
        entries = export(state, tmp_path / f"{name}.json")["entries"]
        assert entries
        for entry in entries:
            for example in entry["examples"]:
                assert example["copyable"] and example["text_format"] == "notation"
                parsed = parse_term(example["text"])
                assert isinstance(parsed, n.Call) and parsed.fn == entry["name"]
                assert tuple(part.value for part in parsed.args) == tuple(
                    _decode_example(item, state) for item in example["inputs"])


def test_exports_admitted_operations(tmp_path):
    world = toy.gen_world()
    state = GenState(world, GenLibrary(world.decl, world.atoms, world.dialect), dict(world.sorts), seed=7)
    body = n.Call("add", (n.Call("mul", (n.Var("x"), n.Var("x"))), n.Lit(2)))
    spec = OperationSpec("f1", "transform", (Edge("int"),), Edge("int"), "generated",
                         extra={"input_names": ["x"]})
    candidate = Candidate(Definition("f1", "operation", "invented", 1, tuple(sorted(n.references(body))),
                                     spec, body), Signature(("int",), "int"), "op.test")
    assert isinstance(admit(state, candidate), Entry)
    path = tmp_path / "full.json"
    data = export(state, path)
    assert data == json.loads(path.read_text())
    original = path.read_bytes()
    export(state, path)
    assert path.read_bytes() == original
    assert data["schema"] == "opulse.gen_v2/1" and data["counts"]["per_kind"]["operation"] == 1
    assert data["title"] == world.title and data["tags"] == world.tags
    item = data["entries"][0]
    assert item["ascii"].isascii() and item["ascii"].startswith("op f1(x: int) -> int = ")
    assert all(token["kind"] for token in item["tokens"])
    assert "".join(token["text"] for token in item["tokens"]) == item["ascii"]
    assert parse_declaration(item["ascii"])["params"] == [("x", "int")]
    assert all("".join(token["text"] for token in example["text_tokens"]) == example["text"]
               for example in item["examples"])
    assert n.from_json(item["body"]) == body
    assert item["examples"] and item["examples"][0]["inputs"][0]["t"] == "int"
    assert item["examples"][0]["outcome"]["ok"]["t"] == "int"
    assert item["evidence"]["method"] == "bounded"
    assert "L1: 1" in export_summary_md(state)
    compact = export_compact(state, tmp_path / "compact.json", max_entries=1)
    assert "body" not in compact["entries"][0]
    assert export_jsonl(state, tmp_path / "data.jsonl") == 1
    assert json.loads((tmp_path / "data.jsonl").read_text().strip()) == item
    story = export_story(state, ["f1"])
    assert len(story) == 1 and story[0]["symbol"] == "f1"
    assert story[0]["examples"][0]["trace"]["name"] == "f1"
    assert story[0]["examples"][0]["trace"]["children"]
    assert json.dumps(story, ensure_ascii=True)


def test_export_counts_unencodable_examples_instead_of_silently_dropping(tmp_path):
    world = toy.gen_world()
    state = GenState(world, GenLibrary(world.decl, world.atoms, world.dialect), dict(world.sorts))
    body = n.Call("add", (n.Var("x"), n.Lit(2)))
    spec = OperationSpec("f1", "transform", (Edge("int"),), Edge("int"), "generated",
                         extra={"input_names": ["x"]})
    candidate = Candidate(Definition("f1", "operation", "invented", 1, tuple(sorted(n.references(body))),
                                     spec, body), Signature(("int",), "int"), "op.test")
    entry = admit(state, candidate)
    assert isinstance(entry, Entry)
    entry.examples.append(((object(),), {"ok": {"t": "int", "v": 1}}, 0))
    data = export(state, tmp_path / "unencodable.json")
    assert sum(data["examples_dropped"].values()) == 1
    assert "host value" in next(iter(data["examples_dropped"]))
    assert len(data["entries"][0]["examples"]) == len(entry.examples) - 1
    assert data["entries"][0]["examples_dropped"] == data["examples_dropped"]
    assert export_compact(state, tmp_path / "compact.json")["examples_dropped"] == data["examples_dropped"]
    export_jsonl(state, tmp_path / "examples.jsonl")
    assert json.loads((tmp_path / "examples.jsonl").read_text())["examples_dropped"] == data["examples_dropped"]


def test_export_all_kinds_declarations_and_story(tmp_path):
    from opulse.gen_v2.run import generate
    from opulse.gen_v2.worlds import toy_truth

    state = generate(toy_truth.gen_world(("object", "operation", "combinator", "observation")),
                     12, 9, per_kind_min=2, layer_target=1, time_limit=12)
    data = export(state, tmp_path / "four.json")
    assert {entry["kind"] for entry in data["entries"]} == set(state.world.open_kinds)
    assert data["title"] == state.world.title and data["tags"] == state.world.tags
    for entry in data["entries"]:
        head = parse_declaration(entry["ascii"])
        assert (head["kind"], head["name"], head["layer"]) == (
            entry["kind"], entry["name"], entry["layer"])
        assert "".join(token["text"] for token in entry["tokens"]) == entry["ascii"]
        assert all(token["kind"] for token in entry["tokens"])
        assert any(token["text"] == entry["display"] and token["kind"] == entry["kind"]
                   for token in entry["tokens"])
        assert entry["ascii"].isascii()
        for example in entry["examples"]:
            assert example["text"].isascii()
            assert "".join(token["text"] for token in example["text_tokens"]) == example["text"]
            if entry["kind"] == "object":
                assert parse_term(example["text"]).fn == example["replay"]["name"]
    stories = export_story(state, [entry["name"] for entry in data["entries"]])
    assert len(stories) == len(data["entries"])
    for story in stories:
        assert "title_zh" not in story and "definition_zh" not in story
        assert all(example["trace"] is None or example["trace"]["name"] == story["name"]
                   for example in story["examples"])
        if story["kind"] == "combinator":
            assert story["examples"] and all(example["text"].startswith("@" + story["name"] + "[")
                                              and example["trace"] is not None for example in story["examples"])


def test_round5_classic_grid_examples_use_the_published_grid_codec(tmp_path):
    # integration round 5: grid outcomes were published in the generator codec ({"t": "tuple"})
    from opulse.atoms.golden import decode as decode_published
    from opulse.gen_v2.export import _decode_example
    from opulse.gen_v2.run import generate
    from opulse.gen_v2.worlds.classic import gen_world

    state = generate(gen_world("grid"), 12, 1, per_kind_min=0, layer_target=0, time_limit=30)
    data = export(state, tmp_path / "grid.json")
    rows = data["entries"] + data.get("story", [])
    examples = [example for entry in rows for example in entry["examples"]]
    assert examples
    assert any(example["outcome"].get("ok", {}).get("t") == "grid" for example in examples)
    for example in examples:
        for item in example["inputs"]:
            _decode_example(item, state)
        if "ok" in example["outcome"]:
            assert example["outcome"]["ok"]["t"] != "tuple"
            decode_published(example["outcome"]["ok"])


def test_round5_published_decoder_reads_a_bottom_field_inside_a_card():
    from types import SimpleNamespace

    from opulse.atoms.values import Bottom, Card
    from opulse.gen_v2.export import _decode_example

    state = SimpleNamespace(world=SimpleNamespace(dialect="atoms-v2"))
    value = {"t": "Pair", "tag": "pair", "f": [{"t": "int", "v": 1}, {"t": "bottom", "v": "invalid"}]}
    assert _decode_example(value, state) == Card("Pair", "pair", (1, Bottom("invalid")))
