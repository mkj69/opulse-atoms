"""Meta index and module protocol regressions (atoms-meta section 8)."""

import json
import shutil
import sys
from pathlib import Path

import pytest

from opulse.meta.check import check, export_problems
from opulse.meta.worlds.code.world import declaration
from opulse.meta.worlds.index import build_index, present_worlds

ROOT = Path(__file__).resolve().parents[2]
DECL = "worlds/decl/meta/code@1.json"
EXPORT = "docs/assets/data/meta/code.json"
INDEX = "docs/assets/data/meta/index.json"


@pytest.fixture
def site_copy(tmp_path):
    for location in ("docs/spec/atoms-meta.md", DECL, EXPORT):
        target = tmp_path / location
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / location, target)
    (tmp_path / DECL).write_text(json.dumps(declaration().to_dict()))
    exported = json.loads((tmp_path / EXPORT).read_text())
    exported.pop('notation3', None)
    for item in exported["story"]:
        item["symbol"] = {"object": "Poly", "combinator": "@pipeline"}.get(
            item["kind"], item["symbol"])
        if item["kind"] == "template":
            item["symbol"] = "specialize_fixed[n]"
            item["name"] = "specialize_fixed"
        elif item["kind"] == "object":
            item["name"] = "Poly"
        elif item["kind"] == "operation" and item["symbol"][0].isupper():
            item["symbol"] = item["name"].lower()
        if item["kind"] in ("operation", "law", "bridge"):
            item["name"] = item["symbol"].lstrip("#~")
        name = item["name"]
        item.pop("body", None)
        item.pop("spec", None)
        item["ascii"] = {
            "object": f"obj {name} = Red | Blue L1",
            "operation": f"op {name}() -> int = 1 L1",
            "combinator": f"comb @{name}[f: A -> A](x: A) -> A = f(x) L1",
            "law": f"law #{name}: true for x: int L1",
            "bridge": f"bridge ~{name}: Color -> Color = x L1",
            "template": f"template op {name}[n: int] = add(n, 1) L1",
        }[item["kind"]]
        for example in item["examples"]:
            example["inputs"] = {"combinator": [{"fn": "add"}, 1],
                                 "object": [], "template": [1], "law": [1],
                                 "bridge": [1]}.get(item["kind"], [])
            example["outcome"] = {"kind": "Ok", "value": {"t": "int", "v": 1}}
            example["ascii"] = {
                "object": f"{name}<> = 1",
                "operation": f"{name}() = 1",
                "combinator": f"@{name}[add](1) = 1",
                "law": f"#{name}(1) = true",
                "bridge": f"~{name}(1) = 1",
                "template": f"{name}[1] = 1",
            }[item["kind"]]
            if item["kind"] == "law":
                example["outcome"]["value"] = {"t": "bool", "tag": "true", "f": []}
    (tmp_path / EXPORT).write_text(json.dumps(exported))
    for part in ("world", "story", "showcase", "export"):
        path = tmp_path / f"src/opulse/meta/worlds/code/{part}.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    (tmp_path / INDEX).write_text(json.dumps(build_index(tmp_path)))
    return tmp_path


def _change(root, location, modify):
    path = root / location
    data = json.loads(path.read_text())
    modify(data)
    path.write_text(json.dumps(data))


def test_index_and_code_protocol(site_copy):
    from opulse.meta.worlds.code.world import declaration

    assert present_worlds(site_copy) == ("code",)
    assert json.loads((site_copy / INDEX).read_text()) == build_index(site_copy)
    assert build_index(site_copy)["worlds"][0]["showcase_angles"] == ["Invert", "Decide", "Compute"]
    assert json.loads((site_copy / DECL).read_text()) == declaration().to_dict()
    assert check(site_copy, fresh_exports=False) == []


def test_modified_declaration(site_copy):
    _change(site_copy, DECL, lambda data: data.update(version=2))
    assert any("declaration differs" in problem for problem in check(site_copy, False))


def test_modified_index(site_copy):
    _change(site_copy, INDEX, lambda data: data.update(spec_version="wrong"))
    assert any("index differs" in problem for problem in check(site_copy, False))


def test_modified_export(site_copy, monkeypatch):
    from opulse.meta.worlds.code import export

    committed = json.loads((site_copy / EXPORT).read_text())
    monkeypatch.setattr(export, "build_export", lambda: committed)
    _change(site_copy, EXPORT, lambda data: data.update(pitch="wrong"))
    assert any("export differs" in problem for problem in check(site_copy))


@pytest.mark.parametrize("method,size,expected", [
    ("sampled", 1, "promoted requires exhaustive or bounded evidence"),
    ("bounded", 0, "promoted requires scope.size > 0"),
])
def test_promoted_evidence(site_copy, method, size, expected):
    def modify(data):
        data["story"][0]["evidence"]["method"] = method
        data["story"][0]["evidence"]["scope"]["size"] = size

    _change(site_copy, EXPORT, modify)
    assert any(expected in problem for problem in check(site_copy, False))


@pytest.mark.parametrize("text,codepoint", [("non-ascii: \u00e9", "U+00E9"),
                                           ("em dash: \u2014", "U+2014")])
def test_ascii(site_copy, text, codepoint):
    _change(site_copy, EXPORT, lambda data: data.update(title=text))
    assert any(codepoint in problem for problem in check(site_copy, False))


@pytest.mark.parametrize("location", ["definition", "prompt"])
def test_ascii_story_and_prompt(site_copy, location):
    def modify(data):
        if location == "definition":
            data["story"][0]["definition"] += " \u221e"
        else:
            data["showcase"][0]["prompt"] += " \u221e"

    _change(site_copy, EXPORT, modify)
    assert any("U+221E" in problem for problem in check(site_copy, False))


@pytest.mark.parametrize("value", [{"node": "Call"}, "Code<call(x)>\nLit(0)", ""])
def test_definition_is_plain_english(site_copy, value):
    _change(site_copy, EXPORT, lambda data: data["story"][0].update(definition=value))
    assert any("definition must be plain English" in problem for problem in check(site_copy, False))


def test_examples_present_and_distinct(site_copy):
    _change(site_copy, EXPORT, lambda data: data["story"][0].update(examples=[]))
    assert any("examples must be nonempty" in problem for problem in check(site_copy, False))
    _change(site_copy, EXPORT, lambda data: data["story"][1].update(examples=data["story"][2]["examples"]))
    assert any("duplicate example" in problem for problem in check(site_copy, False))


def test_showcase_protocol(site_copy):
    _change(site_copy, EXPORT, lambda data: data["showcase"][0].pop("kinds_involved"))
    assert any("requires angle and kinds_involved" in problem for problem in check(site_copy, False))


def test_missing_export_and_subset(site_copy):
    (site_copy / EXPORT).unlink()
    assert any("missing export" in problem for problem in check(site_copy, False))
    assert build_index(site_copy)["worlds"] == []


def test_callable_only_index(site_copy):
    def modify(data):
        data["story"][0]["status"] = "callable"
        data["story"][0]["evidence"]["method"] = "sampled"

    _change(site_copy, EXPORT, modify)
    index = build_index(site_copy)["worlds"][0]
    assert index["counts"]["promoted"] == 13
    assert index["counts"]["callable_only"][0] == {
        "name": "Poly", "kind": "object", "reason": "sampled evidence is not promotable"}


@pytest.mark.parametrize("kind,symbol", [
    ("object", "lower"), ("object", "A<1>"), ("operation", "Upper"),
    ("operation", "run(x)"), ("combinator", "combine"),
    ("combinator", "@combine[f]"), ("observation", "sense"),
    ("observation", "?sense{x}"), ("law", "mul_comm"),
    ("bridge", "to_frac"), ("bridge", "~to_frac(x)"),
])
def test_kind_symbol_rejected(site_copy, kind, symbol):
    _change(site_copy, EXPORT, lambda data: data["story"][0].update(kind=kind, symbol=symbol))
    assert any(f"invalid {kind} symbol {symbol!r}" in problem
               for problem in check(site_copy, False))


@pytest.mark.parametrize("kind,symbol", [
    ("object", "SampleProgram"), ("operation", "run_routine"),
    ("combinator", "@twice_run"), ("observation", "?next_op"),
    ("law", "#mul_comm"), ("bridge", "~to_frac"),
])
def test_kind_symbol_accepted(kind, symbol):
    assert not any("symbol" in problem for problem in export_problems(
        {"story": [{"name": symbol, "kind": kind, "symbol": symbol,
                    "status": "callable", "definition": "An example.",
                    "examples": [{"inputs": [symbol]}]}]}, "test.json"))


def _extra_story(kind, symbol):
    name = symbol.lstrip("#~").split("[", 1)[0]
    source = {"law": f"law #{name}: true for x: int L5",
              "bridge": f"bridge ~{name}: Color -> Color = x L5",
              "template": f"template obj {name}[T: object] = T L5"}[kind]
    example_source = {"law": f"#{name}(1) = true", "bridge": f"~{name}(1) = 1",
                      "template": f"{name}[1] = 1"}[kind]
    value = {"t": "bool", "tag": "true", "f": []} if kind == "law" else {"t": "int", "v": 1}
    return {"kind": kind, "name": symbol if kind != "template" else name, "symbol": symbol, "layer": 5,
            "status": "promoted", "definition": "A verified construction.",
            "ascii": source, "examples": [{"input": symbol, "ascii": example_source,
                                          "inputs": [1], "outcome": {"kind": "Ok", "value": value}}],
            "evidence": {"method": "bounded", "scope": {"size": 2, "domain_hash": "a" * 64},
                         "world_hash": declaration().world_hash(), "atoms_hash": "b" * 64,
                         "content_hash": "c" * 64, "deps_hash": "d" * 64,
                         "checks": ["commutes"]},
            "contract": {"guarantees": "Exact results on the recorded scope",
                         "may_change": [], "keeps": []}}


def test_six_kinds_and_index(site_copy):
    def add(data):
        law = _extra_story("law", "#identity")
        bridge = _extra_story("bridge", "~to_color")
        bridge["interface"] = [["source_op", "target_op"]]
        template = _extra_story("template", "Quot[T]")
        template.update(produces="object", family_scope={"members": ["Frac", "Hour"]})
        data["story"].extend([law, bridge, template])

    _change(site_copy, EXPORT, add)
    (site_copy / INDEX).write_text(json.dumps(build_index(site_copy)))
    assert sorted(problem.split("code.json: ", 1)[1] for problem in check(
        site_copy, False, strict=True)) == [
        "story[17] #identity: semantic verification unavailable: no matching definition",
        "story[18] ~to_color: semantic verification unavailable: no matching definition",
        "story[19] Quot: invalid ascii declaration: unsupported object template pattern at column 34",
        "story[19] Quot: semantic verification unavailable: no matching definition",
    ]
    world = build_index(site_copy)["worlds"][0]
    assert {kind: world["counts"]["by_kind"][kind]
            for kind in ("law", "bridge", "template")} == {
                "law": 3, "bridge": 2, "template": 2}
    assert world["story"][-2]["interface"] == [["source_op", "target_op"]]
    assert world["story"][-1]["family_scope"] == {"members": ["Frac", "Hour"]}
    assert world["story"][-1]["produces"] == "object"


def test_law_needs_promoted_evidence(site_copy):
    def add(data):
        law = _extra_story("law", "#identity")
        law["evidence"]["method"] = "sampled"
        data["story"].append(law)

    _change(site_copy, EXPORT, add)
    assert any("#identity: promoted requires exhaustive or bounded evidence" in problem
               for problem in check(site_copy, False))


@pytest.mark.parametrize("field,value,message", [
    ("interface", [], "bridge requires nonempty interface pairs"),
    ("interface", [["only_one"]], "bridge requires nonempty interface pairs"),
    ("evidence", {"method": "bounded", "scope": {"size": 1}},
     "bridge evidence requires commutes check"),
    ("evidence", {"method": "bounded", "scope": {"size": 1}, "checks": None},
     "bridge evidence requires commutes check"),
])
def test_bridge_checks(site_copy, field, value, message):
    def add(data):
        bridge = _extra_story("bridge", "~to_code")
        bridge["interface"] = [["decode", "encode"]]
        bridge[field] = value
        data["story"].append(bridge)

    _change(site_copy, EXPORT, add)
    assert any(message in problem for problem in check(site_copy, False))


@pytest.mark.parametrize("field,value,message", [
    ("produces", "wrong", "template requires produces kind"),
    ("family_scope", {}, "template requires family_scope"),
    ("evidence", {"method": "exhaustive", "scope": {"size": 2}},
     "template must not claim exhaustive evidence"),
])
def test_template_checks(site_copy, field, value, message):
    def add(data):
        template = _extra_story("template", "Quot[T]")
        template.update(produces="object", family_scope={"members": ["Frac"]})
        template[field] = value
        data["story"].append(template)

    _change(site_copy, EXPORT, add)
    assert any(message in problem for problem in check(site_copy, False))


def test_strict_coverage_and_default_warning(site_copy, monkeypatch, capsys):
    import opulse.meta.check as checker

    _change(site_copy, EXPORT, lambda data: data.update(
        story=[entry for entry in data["story"] if entry["kind"] not in ("law", "bridge")]))
    (site_copy / INDEX).write_text(json.dumps(build_index(site_copy)))
    assert not any("requires at least one" in problem for problem in check(site_copy, False))
    assert [problem.rsplit(": ", 1)[-1] for problem in check(site_copy, False, strict=True)
            if "requires at least one" in problem] == [
                "story requires at least one law", "story requires at least one bridge"]
    monkeypatch.setattr(checker, "ROOT", site_copy)
    monkeypatch.setattr(checker, "check", lambda root, strict: check(root, False, strict))
    monkeypatch.setattr(sys, "argv", ["check"])
    checker.main()
    output = capsys.readouterr().out
    assert "warning:" in output and "at least one law" in output and "at least one bridge" in output
    assert "missing ascii" not in output
    monkeypatch.setattr(sys, "argv", ["check", "--strict"])
    with pytest.raises(SystemExit, match="1"):
        checker.main()


def test_default_mode_warns_on_missing_ascii(site_copy, monkeypatch, capsys):
    import opulse.meta.check as checker

    _change(site_copy, EXPORT, lambda data: data["story"][0]["examples"][0].pop("ascii"))
    (site_copy / INDEX).write_text(json.dumps(build_index(site_copy)))
    monkeypatch.setattr(checker, "ROOT", site_copy)
    monkeypatch.setattr(checker, "check", lambda root, strict: check(root, False, strict))
    monkeypatch.setattr(sys, "argv", ["check"])
    checker.main()
    output = capsys.readouterr().out
    assert "warning:" in output and "example[0]: missing ascii" in output
    assert any("example[0]: missing ascii" in problem for problem in check(site_copy, False, strict=True))


def test_committed_tree_is_current():
    """All four worlds follow the module protocol and publish fresh strict exports."""
    from opulse.meta.check import check
    from opulse.meta.worlds.index import present_worlds

    assert sorted(present_worlds(ROOT)) == ["builder", "code", "compiler", "vonneumann"]
    assert check(ROOT, strict=True) == []
