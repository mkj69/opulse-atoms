"""Shared export helpers used by every world export."""

from types import SimpleNamespace

from opulse.atoms import kernel
from opulse.atoms.values import Ok
from opulse.worlds_v2 import export_util


def _node(name, children=(), steps=1):
    return SimpleNamespace(name=name, kind="operation", layer=0, given=True, inputs=(1,), outcome=Ok(2),
                           steps=steps, children=list(children))


def test_size_counts_deep_trees_without_recursion():
    node = _node("leaf")
    for _ in range(20_000):
        node = _node("wrap", [node])
    assert export_util._size(node) == 20_001


def test_trace_json_keeps_budget_and_counts_elided_nodes():
    root = _node("root", [_node(f"c{index}", [_node("g")]) for index in range(10)], steps=30)
    data = export_util.trace_json(root, max_nodes=5)
    kept = 1 + len(data["children"]) + sum(len(child["children"]) for child in data["children"])
    elided = data.get("elided", 0) + sum(child.get("elided", 0) for child in data["children"])
    assert kept + elided == export_util._size(root)
    assert data["steps"] == 30


def test_trace_json_encodes_operation_references():
    node = _node("call")
    node.inputs = (kernel.FnRef("add"), (1, 2))
    assert export_util.trace_json(node)["inputs"] == [{"fn": "add"}, {"t": "tuple", "v": [
        {"t": "int", "v": 1}, {"t": "int", "v": 2}]}]


def test_normalize_zh_moves_chinese_to_zh_members_and_keeps_decl():
    data = export_util.normalize_zh({"modalities_zh": {"text": "文字"}, "knobs": "八乘八", "decl": {"doc": "中文"},
                                     "title": "Title"})
    assert data == {"modalities_zh": {"text_zh": "文字"}, "knobs_zh": "八乘八", "decl": {"doc": "中文"},
                    "title": "Title"}


def test_finalize_export_adds_ascii_steps_and_one_layer_convention():
    from opulse.atoms import notation

    digest = export_util.body_sha256(notation.parse_definition("op f(x: Int) -> Int = g(x) L3").body)
    data = export_util.finalize_export({"story": [{
        "layer": 3, "design_layer": 7, "decl": "op f(x: Int) -> Int = g(x) L3", "cost": {"length": 2},
        "body_sha256": digest,
        "examples": [{"text": "f(1)", "steps": 4}, {"text": "f(2)", "steps": 9}]}]})
    row = data["story"][0]
    assert (row["layer"], row["def_layer"]) == (7, 3)
    assert row["design_text"] == "op f(x: Int) -> Int = g(x) L3"
    assert row["example_steps"] == {"min": 4, "max": 9}
    assert row["cost"] == {"length": 2}
    assert [example["ascii"] for example in row["examples"]] == ["f(1)", "f(2)"]


def test_parseable_declaration_carries_the_computed_layer_and_rejects_prose():
    assert export_util.parseable_declaration("op f(x: Int) -> Int = g(x) L7", 2) == "op f(x: Int) -> Int = g(x) L2"
    assert export_util.parseable_declaration("obj Route = every public edge exists L3", 1) is None
    assert export_util.parseable_expression("f(1)") and not export_util.parseable_expression("Bake one bread")


def test_finalize_export_publishes_only_the_real_body():
    from opulse.atoms import notation

    real = "op f(x: Int) -> Int = g(x) L1"
    digest = export_util.body_sha256(notation.parse_definition(real).body)
    data = export_util.finalize_export({"story": [
        {"name": "f", "layer": 1, "decl": real, "body_sha256": digest, "examples": []},
        {"name": "g", "layer": 1, "decl": "op g(x: Int) -> Int = x L1", "body_sha256": digest, "examples": []},
        {"name": "h", "layer": 1, "decl": real, "examples": []}]})
    faithful, sketch, unbound = data["story"]
    assert faithful["ascii"] == real and faithful["design_text"] == real
    assert "ascii" not in sketch and "decl" not in sketch and sketch["design_text"] == "g"
    assert "ascii" not in unbound and "decl" not in unbound


def test_source_matches_requires_the_header_to_bind_the_body():
    """Round 6 review: printed observations with subject {s} whose body reads w are not the definition."""
    from opulse.atoms import notation

    def digest(text):
        return export_util.body_sha256(notation.parse_definition(text).body)

    unbound_obs = "obs ?count{s} = size(w) L2"
    assert digest(unbound_obs) == digest("obs ?count{w} = size(w) L2")
    assert not export_util.source_matches(unbound_obs, digest(unbound_obs))
    assert export_util.source_matches("obs ?count{w} = size(w) L2", digest(unbound_obs))
    assert not export_util.source_matches("op f(x: Int) -> Int = add(x, y) L1",
                                          digest("op f(x: Int) -> Int = add(x, y) L1"))
    assert export_util.source_matches("op f(x: Int, y: Int) -> Int = add(x, y) L1",
                                      digest("op f(x: Int) -> Int = add(x, y) L1"))
    combinator = "comb @k[f: A -> A](n: A) -> A = f(n) L1"
    assert export_util.source_matches(combinator, digest(combinator))
    assert not export_util.source_matches("comb @k[f: A -> A](m: A) -> A = f(n) L1", digest(combinator))
    law = "law #comm: eq(add(a, b), add(b, a)) for a: int, b: int L1"
    assert export_util.source_matches(law, digest(law))
