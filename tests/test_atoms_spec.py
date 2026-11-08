"""Definition record and validation tests for atoms-v2."""

import json
from dataclasses import replace

import pytest

from opulse.atoms.library import checked_scope
from opulse.atoms.nodes import Call, Let, Lit, Var
from opulse.atoms.spec import (
    CombinatorSpec,
    Contract,
    Cost,
    Definition,
    Edge,
    Evidence,
    ObjectSpec,
    ObservationSpec,
    OperationSpec,
    Status,
    advance,
    compute_layer,
    content_hash,
    reset,
)


def test_record_json_round_trips():
    records = [Edge("int", "saturate(-1, 255)"),
               ObjectSpec("list", "compose", tags={"nil": [], "cons": [["head", "int"], ["tail", "list"]]},
                          group=("list",), params=("T",)),
               ObjectSpec("pair", "compose", tags={"pair": [("first", "int"), ("second", "int")]}),
               ObjectSpec("hour", "refine", base="int", valid=Call("valid", (Var("x"),)),
                          canon=Call("mod", (Var("x"), Lit(12))), sealed=True, interface=("make",)),
               ObjectSpec("three", "constant", body=Let("x", Lit(3), Var("x"))),
               OperationSpec("add", "combine", (Edge("int"), Edge("int")), Edge("int"), "add integers",
                             impl={"body": Call("sum", (Var("a"), Var("b")))}),
               CombinatorSpec("twice", ("x",), ("f",), Call("f", (Call("f", (Var("x"),)),))),
               ObservationSpec("front_free", ("front_wall",), Call("front_wall"),
                               memory={"sort": "int", "init": Lit(0), "step": Call("next", (Var("memory"),))}),
               Evidence("sampled", {"domain": "int", "size": 10}, 17, ("equivalence",), "hash"),
               Contract("equal", ("R0",), ("memory",)), Cost(4, {"min": 1, "max": 3}, 2)]
    for record in records:
        assert type(record).from_dict(json.loads(json.dumps(record.to_dict()))) == record


def test_definition_content_hash_ignores_display_and_pipeline_metadata():
    body = Call("base", (Var("arg0"),))
    spec = OperationSpec("f", "transform", (Edge("int"),), Edge("int"), "identity",
                         extra={"title": "old", "input_names": ["arg0"]})
    definition = Definition("f", "operation", "invented", 1, ("base",), spec, body)
    digest = definition.content_hash({"base": "one"})
    assert digest == replace(definition, status="verified", cost=Cost(42),
                             spec=replace(spec, extra={"title": "new", "input_names": ["arg0"]})).content_hash(
                                 {"base": "one"})
    # Parameter names bind the body's variables, so renaming them is a semantic change.
    assert digest != replace(definition, spec=replace(spec, extra={"title": "old", "input_names": ["x"]})).content_hash(
        {"base": "one"})
    assert digest != definition.content_hash({"base": "two"})
    assert digest != replace(definition, body=Call("base", (Lit(1),))).content_hash({"base": "one"})
    assert Evidence.from_dict({"method": "bounded", "scope": {"domain": "x", "size": 1}}).content_hash == ""


def test_hash_changes_for_semantic_body_fields():
    from hypothesis import given, strategies

    @given(strategies.integers(), strategies.integers())
    def invariant(left, right):
        spec = OperationSpec("constant", "transform", (), Edge("int"), "constant")
        first = Definition("constant", "operation", "invented", 1, (), spec,
                           {"source": left, "value": right})
        assert first.content_hash() == replace(first, spec=replace(spec, extra={"title": "pretty"})).content_hash()
        if left != right:
            assert first.content_hash() != replace(first, body={"source": right, "value": left}).content_hash()

    invariant()


def test_object_and_operation_unknown_members_round_trip():
    obj = ObjectSpec("value", "given", extra={"host": "module:object", "doc": "shown"})
    op = OperationSpec("id", "transform", (Edge("int"),), Edge("int"), "identity",
                       extra={"symbol": "=", "input_names": ["value"], "host": "module:operator"})
    for record in (obj, op):
        data = json.loads(json.dumps(record.to_dict()))
        assert type(record).from_dict(data) == record
        assert type(record).from_dict(data).to_dict() == data


def test_edges_and_object_rules():
    for rule in ("invalid", "saturate(2,1)", "saturate(a,1)", "fold()"):
        with pytest.raises(ValueError):
            Edge("int", rule)
    for kwargs in ({"form": "compose"}, {"form": "compose", "tags": {"cons": [("tail", "list")]}, "group": ("list",)},
                   {"form": "compose", "tags": {"items": {"items": 5}}},
                   {"form": "compose", "tags": {"bad": [("name", 5)]}},
                   {"form": "refine", "base": "int"}, {"form": "constant", "body": Var("x")},
                   {"form": "constant", "body": Lit(1), "tags": {"x": []}},
                   {"form": "given", "sealed": True}, {"form": "given", "params": ("3bad",)},
                   {"form": "bad"}):
        with pytest.raises(ValueError):
            ObjectSpec("list", **kwargs)
    assert ObjectSpec("xs", "compose", tags={"items": {"items": "int"}}).tags


def test_operation_and_evidence_rules():
    for changes in ({"role": "unknown"}, {"rule": "  "}, {"impl": {"host": "x:y"}},
                    {"impl": {"table": {}, "body": Lit(1)}}):
        with pytest.raises(ValueError):
            OperationSpec(**{"name": "f", "role": "transform", "inputs": (Edge("int"),),
                             "output": Edge("int"), "rule": "f(x)", **changes})
    for method, scope, seed in (("bad", {"domain": "x", "size": 1}, None),
                                ("sampled", {"domain": "x", "size": 1}, None),
                                ("bounded", {"domain": "x"}, None)):
        with pytest.raises(ValueError):
            Evidence(method, scope, seed)


def test_status_and_definition_validation():
    spec = OperationSpec("twice", "transform", (Edge("int"),), Edge("int"), "double")
    body = Call("add", (Var("x"), Var("x")))
    evidence = Evidence("bounded", {"domain": "int", "size": 100,
                                    "checked": checked_scope([(value,) for value in range(100)])})
    definition = Definition("twice", "operation", "invented", 1, ("add",), spec, body)
    assert definition.validate() == []
    assert Definition.from_dict(json.loads(json.dumps(definition.to_dict()))) == definition
    assert replace(definition, status="verified").validate()
    assert replace(definition, status="promoted", evidence=evidence).validate()
    promoted = replace(definition, status="promoted", evidence=evidence, contract=Contract())
    assert promoted.validate() == []
    assert Definition.from_dict(json.loads(json.dumps(promoted.to_dict()))) == promoted
    unrecorded = Evidence("bounded", {"domain": "int", "size": 100})
    assert evidence.checked_recorded() and not unrecorded.checked_recorded()
    for changes in ({"kind": "object"}, {"origin": "given"}, {"layer": 0},
                    {"depends_on": ()}, {"depends_on": ("add", "add")}, {"status": "bad"}):
        assert replace(definition, **changes).validate()
    assert replace(promoted, evidence=Evidence("sampled", evidence.scope, 2)).validate()
    assert replace(definition, origin="given", layer=0, status="promoted").validate() == []
    assert replace(definition, origin="given", layer=0, status="verified").validate()
    assert replace(definition, spec=CombinatorSpec("twice", ("x",), ("add",), body),
                   kind="combinator", depends_on=()).validate() == []
    assert list(Status) == [Status.WRITTEN, Status.CHECKED, Status.CALLABLE, Status.VERIFIED, Status.PROMOTED]
    assert advance("written", "checked") == "checked"
    assert reset("verified") == "callable"
    for left, right in (("written", "verified"), ("checked", "written"), ("bad", "checked")):
        with pytest.raises(ValueError):
            advance(left, right)
    assert compute_layer([], {}) == 1
    assert compute_layer(["a", "b"], {"a": 0, "b": 3}) == 4
    assert compute_layer(["a"], lambda name: 2) == 3
    assert content_hash(promoted) == content_hash(Definition.from_dict(promoted.to_dict()))


def test_layer0_host_rules_and_edge_names():
    from opulse.atoms.spec import Definition, Edge, ObjectSpec, is_host_rule

    rule = {"host": "opulse.worlds.pitch:valid_note", "digest": "0" * 64}
    assert is_host_rule(rule) and not is_host_rule({"host": "no module", "digest": "0" * 64})
    note = ObjectSpec("note", "refine", base="int", valid=rule)
    assert ObjectSpec.from_dict(note.to_dict()) == note
    edge = Edge("int", name="a")
    assert Edge.from_dict(edge.to_dict()) == edge and "name" not in Edge("int").to_dict()
    invented = Definition("note2", "object", "invented", 1, (), note, None)
    assert "host rules are allowed only for given layer-0 objects" in invented.validate()


def test_content_hash_depends_on_parameter_order():
    from opulse.atoms import nodes
    from opulse.atoms.spec import Definition, Edge, OperationSpec

    def make(names, symbol):
        spec = OperationSpec("d", "combine", (Edge("int"), Edge("int")), Edge("int"), "a - b",
                             extra={"input_names": list(names), "symbol": symbol})
        return Definition("d", "operation", "invented", 1, ("sub",), spec,
                          nodes.Call("sub", (nodes.Var("a"), nodes.Var("b"))))

    assert make(("a", "b"), "x").content_hash() == make(("a", "b"), "y").content_hash()
    assert make(("a", "b"), "x").content_hash() != make(("b", "a"), "x").content_hash()


def test_law_bridge_and_template_records_round_trip():
    from opulse.atoms import KINDS
    from opulse.atoms.nodes import Call, Var
    from opulse.atoms.spec import BridgeSpec, Definition, LawSpec, TemplateSpec

    assert KINDS[-2:] == ("law", "bridge")
    law = LawSpec("mul_comm", (("a", "Int"), ("b", "Int")),
                  Call("eq", (Call("mul", (Var("a"), Var("b"))), Call("mul", (Var("b"), Var("a"))))))
    assert law.equation is not None and LawSpec.from_dict(law.to_dict()) == law
    bridge = BridgeSpec("to_frac", "MyFrac", "Frac", Call("convert", (Var("x"),)), interface=(("add2", "add"),))
    assert BridgeSpec.from_dict(bridge.to_dict()) == bridge
    template = TemplateSpec("Quot", (("T", "object"), ("canon", "operation")), "object",
                            {"form": "refine", "base": "$T", "canon": "$canon"})
    assert TemplateSpec.from_dict(template.to_dict()) == template
    record = Definition("mul_comm", "law", "invented", 1, ("eq", "mul"), law, law.statement)
    assert Definition.from_dict(record.to_dict()) == record and record.validate() == []


def test_observation_memory_references_are_dependencies():
    from opulse.atoms.nodes import Call, Lit, Var
    from opulse.atoms.spec import Definition, ObservationSpec

    memory = {"sort": "int", "init": Lit(0), "step": Call("inc", (Var("memory"),))}
    spec = ObservationSpec("count", ("p",), Var("memory"), memory)
    assert Definition("count", "observation", "invented", 1, ("inc",), spec, spec.body).validate() == []
    assert Definition("count", "observation", "invented", 1, (), spec, spec.body).validate() != []
