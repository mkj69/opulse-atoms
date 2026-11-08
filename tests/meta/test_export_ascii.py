"""Exact ASCII export declarations and examples (atoms-meta section 8)."""

import copy
import json
from dataclasses import replace
from pathlib import Path

import pytest

from opulse.atoms import nodes, notation
from opulse.atoms.kernel import FnRef
from opulse.atoms.spec import Cost, Definition, Edge, OperationSpec
from opulse.atoms.values import Bottom, Card, Ok, Unknown, encode
from opulse.meta import code
from opulse.meta.builder import world_value as world_values
from opulse.meta.check import (
    _split_example,
    _template_reference_matches,
    export_problems,
)
from opulse.meta.export_util import (
    ascii_definition,
    ascii_example,
    outcome_json,
    parse_meta_definition,
    parse_meta_expr,
    parse_meta_object_call,
    parse_meta_value,
    value_json,
)
from opulse.meta.notation import parse_code, parse_vn, show_code, show_vn, show_world

DECLARATIONS = (
    "obj Color = Red | Blue L1",
    "op increment(x: int) -> int = add(x, 1) L1",
    "comb @twice[f: A -> A](x: A) -> A = f(f(x)) L1",
    "obs ?next{s} = sense(s) L1",
    "law #identity: eq(add(x, 0), x) for x: int L1",
    "bridge ~to_color: Color -> Color = x commutes (identity -> identity) L1",
)


@pytest.mark.parametrize("source", DECLARATIONS)
def test_ascii_definition_roundtrip(source):
    definition = notation.parse_definition(source)
    promoted = replace(definition, status="promoted", cost=Cost(length=5))
    printed, reason = ascii_definition(promoted, None)
    assert reason is None
    assert printed == source
    assert notation.parse_definition(printed) == definition


def test_unprintable_definition_reports_reason():
    definition = notation.parse_definition(DECLARATIONS[1])
    source, reason = ascii_definition(replace(definition, spec=replace(definition.spec, rule="opaque")), None)
    assert source is None
    assert reason == "operation metadata has no compact ASCII declaration"


@pytest.mark.parametrize("name,kind,inputs,outcome,source", [
    ("increment", "operation", (2,), Ok(3), "increment(2) = 3"),
    ("Color", "object", (2,), Ok(Card("Color", "Red")), "Color<2> = Color.Red<>"),
    ("@twice", "combinator", (FnRef("increment"), 2), Ok(4), "@twice[increment](2) = 4"),
    ("?next", "observation", (Card("Color", "Red"),), Ok(True), "?next{Color.Red<>} = true"),
    ("~to_color", "bridge", (Card("Color", "Red"),), Ok(Card("Color", "Blue")),
     "~to_color(Color.Red<>) = Color.Blue<>"),
    ("#identity", "law", (2,), Ok(True), "#identity(2) = true"),
    ("increment", "operation", (0,), Bottom("blocked"), 'increment(0) = fail("blocked")'),
    ("increment", "operation", (0,), Unknown("fuel"), 'increment(0) = Unknown<"fuel">'),
])
def test_ascii_example(name, kind, inputs, outcome, source):
    assert ascii_example(name, kind, inputs, outcome) == source
    call, result = source.split(" = ")
    if kind not in ("law", "template"):
        assert notation.parse_expr(call, {"kinds": {notation.stored_name(name): kind}})
    if not isinstance(outcome, Unknown):
        assert notation.parse_value(result) == (outcome.value if isinstance(outcome, Ok) else outcome)


def test_vn_example_uses_meta_ascii_notation():
    state = parse_vn("VN<pc=0, a=1, halted=false, mem=Mem<16: 0, 1>>")
    source = ascii_example("sum3_loop", "operation", (state,), Ok(state))
    call, result = source.split(" = ")
    assert call.startswith("sum3_loop(VN<pc=0, a=1, halted=false, mem=Mem<")
    assert result == call.removeprefix("sum3_loop(").removesuffix(")")
    assert parse_vn(result) == state
    assert parse_meta_expr(call).args == (nodes.Lit(state),)
    assert parse_meta_value(result) == state


def test_code_example_has_parseable_exact_source():
    program = code.make_code("operation", code.sig_op([], ("int", "bottom")), (), nodes.Lit(2),
                             lambda name: None)
    source = ascii_example("run_code", "operation", (program,), Ok(program))
    assert source.count(" = ") == 3
    assert parse_code(source.split(") = ", 1)[-1]) == program
    exported = {"story": [{"name": "run_code", "kind": "operation", "symbol": "run_code",
                           "ascii": "op run_code(x: int) -> int = x L1",
                           "definition": "Run the program.", "status": "callable",
                           "examples": [{"ascii": source, "inputs": [value_json(program)],
                                         "outcome": outcome_json(Ok(program))}]}]}
    assert export_problems(exported, "sample.json", strict=True) == []
    call, result = source.split(") = ", 1)
    assert parse_meta_expr(call + ")").args == (nodes.Lit(program),)
    assert parse_meta_value(result) == program


def test_bridge_code_example_does_not_split_at_inner_arrow():
    program = code.make_code("bridge", code.sig_bridge("int", "int", (("add", "add"),)),
                             ("x",), nodes.Var("x"), lambda name: None)
    source = ascii_example("identity", "operation", (program,), Ok(program))
    assert export_problems({"story": [{"name": "identity", "kind": "operation", "symbol": "identity",
                                       "definition": "Evaluate an identity program.", "status": "callable",
                                       "ascii": "op identity(x: int) -> int = x L1",
                                       "examples": [{"ascii": source, "inputs": [value_json(program)],
                                                     "outcome": outcome_json(Ok(program))}]}]}, "sample", strict=True) == []


def test_world_example_with_law_is_checked_as_exact_meta_value():
    law = code.make_code("law", code.sig_law((("x", "digit"),)), ("x",), nodes.Lit(True),
                         lambda name: None)
    world = world_values.world("mini", 1, (world_values.range_sort("digit", 0, 1),), (),
                               ("Lit",), "none", (), "full_state", ("law",), (),
                               (world_values.law("yes", law),))
    source = ascii_example("wf", "operation", (world,), Ok(world))
    assert show_world(world) in source
    call, result = _split_example(source)
    assert parse_meta_expr(call).args == (nodes.Lit(world),)
    assert parse_meta_value(result) == world
    assert export_problems({"story": [{"name": "wf", "kind": "operation", "symbol": "wf",
                                       "definition": "Check a world.", "status": "callable",
                                       "ascii": "op wf(w: world) -> world = w L1",
                                       "examples": [{"ascii": source, "inputs": [value_json(world)],
                                                     "outcome": outcome_json(Ok(world))}]}]}, "sample", strict=True) == []


def test_meta_declarations_lowercase_and_qualified_sorts():
    sources = (
        "op wf(w: world) -> report = wf_inner(w) L1",
        "law #reflexive: eq(x, x) for x: z L2",
        "bridge ~embed: z5@1:z -> pair@1:pair = x commutes (add -> add) L2",
        "obj base_z5 = (make_world()) L1",
    )
    for source in sources:
        definition = parse_meta_definition(source)
        assert definition.name == notation.stored_name(source.split()[1].split("(")[0].split(":")[0])
    assert parse_meta_definition(sources[0]).spec.inputs[0].sort == "world"
    assert parse_meta_definition(sources[2]).spec.source == "z5@1:z"
    assert parse_meta_definition(sources[2]).spec.target == "pair@1:pair"


def test_meta_declaration_printer_roundtrips_lowercase_and_code_literals():
    object_def = notation.parse_definition("obj Holder = (1) L1")
    object_def = replace(object_def, name="holder", spec=replace(object_def.spec, name="holder"))
    printed, reason = ascii_definition(object_def, None)
    assert reason is None
    assert printed == "obj holder = (1) L1"
    assert parse_meta_definition(printed) == object_def

    program = code.make_code("operation", code.sig_op([], ("int", "bottom")), (), nodes.Lit(2),
                             lambda name: None)
    operation = notation.parse_definition("op evaluate(x: int) -> int = x L1")
    operation = replace(operation, body=nodes.Lit(program))
    printed, reason = ascii_definition(operation, None)
    assert reason is None
    assert printed == "op evaluate(x: int) -> int = Code<op () -> int = 2> L1"
    assert parse_meta_definition(printed) == operation

    for source in ("law #reflexive: eq(x, x) for x: z L2",
                   "bridge ~embed: z5@1:z -> pair@1:pair = x commutes (add -> add) L2"):
        definition = parse_meta_definition(source)
        printed, reason = ascii_definition(definition, None)
        assert reason is None
        assert printed == source
        assert parse_meta_definition(printed) == definition


@pytest.mark.parametrize("source", (
    "op f(x: world) -> report = x L1",
    "comb @twice[f: A -> A](x: A) -> A = f(f(x)) L1",
    "obs ?next{s} = sense(s) L1",
    "template op specialize[n: int] = add(n, 1) L1",
))
def test_meta_declaration_heads_roundtrip(source):
    definition = parse_meta_definition(source)
    printed, reason = ascii_definition(definition, None)
    assert reason is None
    assert printed == source
    assert parse_meta_definition(printed) == definition


def test_composite_ascii_examples_reject_malformed_or_wrong_calls():
    state = parse_vn("VN<pc=0, a=1, halted=false, mem=Mem<16: 0, 1>>")
    program = code.make_code("operation", code.sig_op([], ("int", "bottom")), (), nodes.Lit(2),
                             lambda name: None)
    assert parse_meta_object_call("Holder<" + show_vn(state) + ", " + show_code(
        program, signature=True, deps=True, exact=True) + ">", "Holder") == (state, program)
    for source in ("wf(VN<pc=0, a=1>)", "wf(World<bad@1>)", "wf(Code<op = ?>)",
                   "wf(VN<pc=0, a=1, halted=false, mem=Mem<16: 0, 1>>))",
                   "wf(VN<pc=0, a=1, halted=false, mem=Mem<16: 0, 1>>",
                   "wf(\u221e)"):
        with pytest.raises(ValueError):
            parse_meta_expr(source)
    assert parse_meta_expr('wf("VN<not a literal>")') == nodes.Call(
        "wf", (nodes.Lit("VN<not a literal>"),))
    assert parse_meta_expr('wf("Code<wrong> and VN<bad>")') == nodes.Call(
        "wf", (nodes.Lit("Code<wrong> and VN<bad>"),))
    assert parse_meta_expr('wf("__meta_literal_0__", VN<pc=0, a=1, halted=false, mem=Mem<16: 0, 1>>)') == (
        nodes.Call("wf", (nodes.Lit("__meta_literal_0__"), nodes.Lit(state))))
    assert parse_meta_expr('wf("&no_ref", VN<pc=0, a=1, halted=false, mem=Mem<16: 0, 1>>)').args[0] == (
        nodes.Lit("&no_ref"))
    with pytest.raises(ValueError):
        parse_meta_value("World<bad@1>")


def test_export_ascii_strict_and_default():
    exported = {"story": [{"name": "increment", "symbol": "increment", "kind": "operation",
                           "definition": "Increase a number.", "status": "callable",
                           "examples": [{"inputs": [2], "outcome": outcome_json(Ok(3))}]}]}
    assert export_problems(exported, "sample.json") == []
    assert [problem.split(": ")[-1] for problem in export_problems(exported, "sample.json", strict=True)] == [
        "missing ascii", "missing ascii"]
    exported["story"][0]["ascii"] = DECLARATIONS[1]
    exported["story"][0]["examples"][0]["ascii"] = "increment(2) = 3"
    exported["story"][0]["examples"][0]["outcome"] = outcome_json(Ok(3))
    assert export_problems(exported, "sample.json", strict=True) == []
    exported["story"][0]["examples"][0]["ascii"] = "increment(2 = 3"
    assert any("invalid ascii example" in issue for issue in export_problems(exported, "sample.json"))
    exported["story"][0]["ascii"] = "op increment(x: int) -> int = 1 L1 \u00e9"
    assert any("ascii must be ASCII text" in issue for issue in export_problems(exported, "sample.json"))


def test_strict_rejects_recorded_body_signature_inputs_and_outcome_drift():
    example = {"ascii": "increment(2) = 3", "inputs": [2],
               "outcome": {"kind": "Ok", "value": {"t": "int", "v": 3}}}
    entry = {"name": "increment", "kind": "operation", "symbol": "increment",
             "definition": "Increase a number.", "status": "callable",
             "ascii": "op increment(x: int) -> int = add(x, 1) L1",
             "spec": {"inputs": [{"name": "x", "sort": "int"}], "output": {"sort": "int"}},
             "body": nodes.to_json(nodes.Call("add", (nodes.Var("x"), nodes.Lit(1)))),
             "examples": [example]}
    exported = {"story": [entry]}
    assert export_problems(exported, "sample", strict=True) == []
    for location, changed, message in (
            ("body", nodes.to_json(nodes.Lit(0)), "declaration body"),
            ("spec", {"inputs": [{"name": "x", "sort": "str"}], "output": {"sort": "int"}},
             "declaration signature"),
            ("inputs", [4], "call inputs"),
            ("outcome", {"kind": "Ok", "value": {"t": "int", "v": 4}}, "outcome")):
        altered = copy.deepcopy(exported)
        (altered["story"][0]["examples"][0] if location in ("inputs", "outcome")
         else altered["story"][0])[location] = changed
        assert any(message in problem for problem in export_problems(altered, "sample", strict=True))


def test_code_hash_outcome_is_exact_and_provenance_sensitive():
    program = code.make_code("operation", code.sig_op([], ("int", "bottom")), (), nodes.Lit(2),
                             lambda name: None)
    entry = {"name": "quoted", "kind": "operation", "symbol": "quoted", "status": "callable",
             "definition": "Return a quoted program.",
             "ascii": f"op quoted(x: int) -> code = {show_code(program, signature=True, deps=True, exact=True)} L1",
             "examples": [{"ascii": ascii_example("quoted", "operation", (2,), Ok(program)),
                           "inputs": [2],
                           "outcome": {"kind": "Ok", "code_hash": code.code_hash(program)}}]}
    assert export_problems({"story": [entry]}, "sample", strict=True) == []
    entry["examples"][0]["outcome"]["code_hash"] = "0" * 64
    assert any("outcome differs" in problem for problem in export_problems(
        {"story": [entry]}, "sample", strict=True))


def test_quoted_template_origin_round_trips_with_nested_case_dependencies():
    root = Path(__file__).resolve().parents[2] / "docs/assets/data/meta/code.json"
    template = next(item for item in json.loads(root.read_text())["story"]
                    if item["kind"] == "template")
    example = template["examples"][0]
    rendered = example["ascii"].split(" = ", 1)[1]
    parsed = parse_meta_value(rendered)
    assert code.canonicalize(parsed) == parsed
    assert encode(parsed) == example["outcome"]["value"]
    with pytest.raises(ValueError, match="noncanonical code origin"):
        parse_meta_value(rendered.replace(" args ", "  args ", 1))


def test_template_reference_marker_is_checked_against_the_source_pattern():
    root = Path(__file__).resolve().parents[2] / "docs/assets/data/meta/code.json"
    story = json.loads(root.read_text())["story"]
    source = next(item["ascii"] for item in story if item["kind"] == "template")
    member = next(item for item in story if item["name"] == "specialize_member_1")
    body = parse_meta_definition(member["ascii"]).body
    assert _template_reference_matches(source, body)
    assert not _template_reference_matches(source, replace(body, body=nodes.Call(
        "specialize", (nodes.Lit(1), nodes.Lit(4)))))


def test_core_template_reference_has_exact_meta_declaration():
    body = nodes.Let("_template_ref_0", nodes.Lit(FnRef("Template")),
                     nodes.Call("add", (nodes.Var("value"), nodes.Lit(3))))
    spec = OperationSpec("example", "transform", (Edge("int", "bottom", name="value"),),
                         Edge("int", "bottom"), "example")
    definition = Definition("example", "operation", "invented", 2, ("Template",), spec, body)
    source, reason = ascii_definition(definition, None)
    assert reason is None
    assert source == "op example(value: int) -> int = let _template_ref_0 = &Template in add(value, 3) L2"
    assert parse_meta_definition(source).body == body


def test_nested_template_reference_replay_rejects_changed_arguments():
    source = "template op compiled[src: op] = pack_prog(lcompile(src)) L1"
    body = nodes.Let("_template_ref_0", nodes.Lit(FnRef("Compiled")),
                     nodes.Call("pack_prog", (nodes.Call("lcompile", (
                         nodes.Call("recorded_source", ()),)),)))
    assert _template_reference_matches(source, body)
    assert _template_reference_matches(source, body, [{"src": "recorded_source"}])
    assert not _template_reference_matches(source, body, [{"src": "another_source"}])
    assert not _template_reference_matches(source, replace(body, body=nodes.Call(
        "pack_prog", (nodes.Call("lcompile", (nodes.Lit("recorded_source"),)),))))
    assert not _template_reference_matches(source, replace(body, body=nodes.Var(body.name)))


def test_published_declarations_and_examples_are_strictly_exact():
    root = Path(__file__).resolve().parents[2] / "docs/assets/data/meta"
    for world in ("code", "vonneumann", "compiler", "builder"):
        path = root / f"{world}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert path.stat().st_size < 3_000_000
        assert export_problems({key: value for key, value in data.items()
                                if key != 'notation3'}, world, strict=True) == []
        for entry in data["story"]:
            assert "ascii_projection" not in entry
            assert all("ascii_projection" not in example for example in entry["examples"])
    compiler = json.loads((root / "compiler.json").read_text())
    compiled = next(item for item in compiler["story"] if item["name"] == "compiled")
    assert parse_meta_definition(compiled["ascii"]).spec.params == (("src", "operation"),)
    accepted = next(item for item in compiler["story"] if item["name"] == "lcompile")
    assert accepted["evidence"]["scope"]["pairs"]["count"] == 3325
    builder = json.loads((root / "builder.json").read_text())
    fold = next(item for item in builder["story"] if item["name"] == "for_each_tuple")
    assert parse_meta_definition(fold["ascii"]).spec.params == tuple(fold["spec"]["params"])
    assert fold["spec"]["params"][0] == "f"
    for world, payload in (("code", json.loads((root / "code.json").read_text())),
                           ("compiler", compiler), ("builder", builder)):
        changed = copy.deepcopy(payload)
        template = next(item for item in changed["story"] if item["kind"] == "template")
        template["source_spec_hash"] = "0" * 64
        assert any("template pattern or source hash differs" in issue
                   for issue in export_problems(changed, world, strict=True))


@pytest.mark.parametrize("source", (
    "wf(World<bad@1>) = report.ok()",
    "wf(VN<pc=0, a=1>) = true",
    "wf(Code<op = ?>) = true",
    "wf(1) = World<bad@1>",
    "wf(1) = Unknown<1>",
    "other(1) = true",
    "wf(1) = true \u221e",
))
def test_checker_rejects_malformed_meta_examples(source):
    exported = {"story": [{"name": "wf", "symbol": "wf", "kind": "operation",
                           "definition": "Check a world.", "status": "callable",
                           "ascii": "op wf(w: world) -> report = w L1",
                           "examples": [{"ascii": source}]}]}
    problems = export_problems(exported, "sample.json", strict=True)
    assert any("invalid ascii example" in issue or "ascii must be ASCII text" in issue
               for issue in problems)


def test_template_reference_replay_rebuilds_core_bindings_exactly():
    source = "template op compiled[src: op] = pack_prog(lcompile(src)) L1"
    used = nodes.Call("pack_prog", (nodes.Call("lcompile", (nodes.Call("recorded_source", ()),)),))
    legitimate = nodes.Let("_template_ref_0", nodes.Lit(FnRef("Compiled")), used)
    forged = replace(legitimate, body=nodes.Let("_template_ref_1", nodes.Lit(FnRef("source_fib")), used))
    assert _template_reference_matches(source, legitimate, [{"src": "recorded_source"}])
    assert not _template_reference_matches(source, forged, [{"src": "recorded_source"}])
    unused = "template op compiled[src: op] = pack_prog(7) L1"
    constant = nodes.Call("pack_prog", (nodes.Lit(7),))
    core_body = nodes.Let("_template_ref_1", nodes.Lit(FnRef("recorded_source")),
                          nodes.Let("_template_ref_0", nodes.Lit(FnRef("Compiled")), constant))
    assert _template_reference_matches(unused, core_body, [{"src": "recorded_source"}])
    assert not _template_reference_matches(unused, core_body, [{"src": "another_source"}])
    swapped = nodes.Let("_template_ref_0", nodes.Lit(FnRef("Compiled")),
                        nodes.Let("_template_ref_1", nodes.Lit(FnRef("recorded_source")), constant))
    assert not _template_reference_matches(unused, swapped)
