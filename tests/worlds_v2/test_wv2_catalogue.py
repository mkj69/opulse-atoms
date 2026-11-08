"""Every generated world export follows the shared shape and the decided catalogue."""

import json
import re
from pathlib import Path

import pytest

from opulse.atoms.world import WorldDecl
from opulse.worlds_v2 import index

ROOT = Path(__file__).resolve().parents[2]
CATALOGUE = {world["id"]: world for world in
             json.loads((ROOT / "worlds/catalogue/world_catalog.json").read_text(encoding="utf-8"))["worlds"]}
DEPTH = {path.stem: json.loads(path.read_text(encoding="utf-8"))
         for path in (ROOT / "worlds/catalogue/depth").glob("*.json")}
EXPORTS = index.exports()
NOT_ASCII_NOTATION = re.compile("[\u27e8\u27e9\u27e6\u27e7\u2985\u2986\u2660\u2666\u25cb\u25c9\u211a\u211d\u2115\u2124"
                                "\U0001d400-\U0001d7ff]")
STATUSES = ("written", "checked", "callable", "verified", "promoted")
OUTCOMES = ({"ok"}, {"bottom"}, {"unknown"})


def test_index_is_current():
    stored = json.loads((index.DATA / "index.json").read_text(encoding="utf-8"))
    assert stored == index.build_index()
    assert [item["world"] for item in stored["worlds"]] == sorted(EXPORTS, key=lambda name: (EXPORTS[name]["wave"], name))


@pytest.mark.parametrize("name", sorted(EXPORTS))
def test_export_shape(name):
    data = EXPORTS[name]
    assert data["schema"] == "opulse.world_v2_export/1"
    assert data["world"] == name and name in CATALOGUE
    assert {"decl", "layer0", "story", "title", "title_zh", "pitch_zh", "modality_zh",
            "emerges_zh", "checking_zh", "wave", "version"} <= set(data)
    decl_file = index.DECLS / f"{name}@{data['version']}.json"
    def without_open_kinds(declaration):  # core spec 0.3 writes open_kinds back by default
        return {key: value for key, value in declaration.items() if key != "open_kinds"}

    stored = json.loads(decl_file.read_text(encoding="utf-8"))
    assert without_open_kinds(WorldDecl.from_dict(stored).to_dict()) == without_open_kinds(data["decl"])
    assert WorldDecl.from_dict(data["decl"]).world_hash()
    assert set(data["layer0"]) == {"objects", "operations", "combinators", "observation"}


@pytest.mark.parametrize("name", sorted(EXPORTS))
def test_story_follows_catalogue(name):
    story = EXPORTS[name]["story"]
    kinds = [item["kind"] for item in story]
    source = DEPTH[name]["tower"] if EXPORTS[name].get("tower_source") == "depth" else CATALOGUE[name]["story"]
    expected = [item["kind"] for item in source]
    position = 0
    for kind in kinds:  # catalogue cards appear in order; helper cards may sit between them
        if position < len(expected) and kind == expected[position]:
            position += 1
    assert position == len(expected), (kinds, expected)
    for item in story:
        assert item["status"] in STATUSES
        if item["status"] == "promoted":
            assert item["evidence"]["method"] in ("exhaustive", "bounded")
            assert item["evidence"]["scope"]["size"] > 0
        assert item["examples"], item["name"]
        for example in item["examples"]:
            assert set(example["outcome"]) in OUTCOMES
            assert type(example["steps"]) is int and example["steps"] >= 0


def _strings(value, key=""):
    if isinstance(value, dict):
        for name, item in value.items():
            yield from _strings(item, name)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item, key)
    elif isinstance(value, str) and not key.endswith("_zh"):
        yield value


@pytest.mark.parametrize("name", sorted(name for name in EXPORTS if EXPORTS[name].get("tower_source") == "depth"))
def test_depth_exports_use_ascii_notation(name):
    data = EXPORTS[name]
    assert {"ladder", "showcase", "tags", "open_kinds"} <= set(data)
    bad = sorted({text for text in _strings({k: v for k, v in data.items()
                                            if k not in ("decl", "notation3")}) if NOT_ASCII_NOTATION.search(text)})
    assert not bad, bad[:5]


SIGIL = {"combinator": "@", "observation": "?", "law": "#", "bridge": "~"}


@pytest.mark.parametrize("name", sorted(name for name in EXPORTS if EXPORTS[name].get("tower_source") == "depth"))
def test_depth_rows_carry_kind_sigils(name):
    for row in EXPORTS[name]["story"]:
        symbol = row["symbol"]
        if row["kind"] in SIGIL:
            assert symbol.startswith(SIGIL[row["kind"]]), (row["name"], symbol)
        elif row["kind"] == "object":
            assert symbol[:1].isupper(), (row["name"], symbol)
        elif row["kind"] == "operation":
            assert symbol[:1].islower(), (row["name"], symbol)


@pytest.mark.parametrize("name", sorted(name for name in EXPORTS if EXPORTS[name].get("tower_source") == "depth"))
def test_depth_examples_are_public_traced_ascii(name):
    from opulse.atoms import notation

    for row in EXPORTS[name]["story"]:
        assert row.get("design_text"), row["name"]
        if "ascii" in row:  # runnable source only, carrying the computed layer
            notation.parse_definition(row["ascii"])
            if row.get("def_layer") is not None and not row["ascii"].rstrip().endswith(" given"):
                assert row["ascii"].rstrip().endswith(f" L{row['def_layer']}"), row["name"]
        for example in row["examples"]:
            assert "judge_view" not in example, (row["name"], "judge data belongs in worlds/judge/")
            assert example.get("text", "").isascii(), row["name"]
            if "ascii" in example:
                notation.parse_expr(example["ascii"])
            assert isinstance(example.get("trace"), dict), (row["name"], "every example needs a real trace")


BRIDGES = json.loads((ROOT / "docs/assets/data/worlds_v2/bridges/bridges.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", sorted(EXPORTS) + ["bridges"])
def test_published_source_is_the_real_body(name):
    """Review round 5 S1: an `ascii` or parseable `decl` must parse to the stored definition's body, never a sketch."""
    from opulse.atoms import notation
    from opulse.worlds_v2.export_util import source_matches

    data = BRIDGES if name == "bridges" else EXPORTS[name]
    for row in data["story"]:
        if "ascii" in row:
            assert source_matches(row["ascii"], row.get("body_sha256")), row["name"]
        try:
            notation.parse_definition(row.get("decl") or "")
        except notation.NotationError:
            continue
        assert source_matches(row["decl"], row.get("body_sha256")), (row["name"], row["decl"])


def test_catalogue_text_is_english():
    # The catalogue ships in the public English repository; notation symbols are allowed.
    text = (ROOT / "worlds/catalogue/world_catalog.json").read_text(encoding="utf-8")
    assert not re.search("[㐀-鿿豈-﫿　-〿＀-￯]", text)
