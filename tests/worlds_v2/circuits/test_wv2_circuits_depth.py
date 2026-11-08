"""Depth tower, independent DAG oracle, export and core invariants."""

import importlib.util
import json
import os
import re
import sys
from dataclasses import replace
from itertools import product

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from opulse.atoms import kernel, notation, values
from opulse.atoms import nodes as n
from opulse.atoms.boundary import Boundary
from opulse.atoms.check import all_dependencies
from opulse.atoms.library import PipelineError, checked_scope, exhaustive
from opulse.atoms.spec import CombinatorSpec, compute_layer
from opulse.atoms.verify import unfold_equivalent
from opulse.atoms.world import WorldDecl
from opulse.tasks_v2.decl import load, validate
from opulse.worlds_v2 import export_util
from opulse.worlds_v2.circuits import deep, hosts
from opulse.worlds_v2.circuits.export import (
    DESIGN_PATH,
    EXPORT_PATH,
    JUDGE_PATH,
    build_export,
)
from opulse.worlds_v2.circuits.story import (
    basic_definitions,
    build_depth_library,
    small_circuits,
)
from opulse.worlds_v2.circuits.world import DECL_PATH, atoms, decl, new_library


def reference():
    path = DESIGN_PATH.with_suffix(".py")
    spec = importlib.util.spec_from_file_location("circuits_depth_reference", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def judge_scope(lib):
    agent = getattr(lib, "agent", "learner")
    lib.agent = "judge"
    try:
        return lib.scope()
    finally:
        lib.agent = agent


@pytest.fixture(scope="module")
def basic_lib():
    fresh = new_library()
    fresh._stable_world = fresh.world
    fresh.agent = "judge"
    basic_definitions(fresh)
    return fresh


@pytest.fixture(scope="module")
def lib(basic_lib):
    return build_depth_library(basic_lib)


@pytest.fixture(scope="module")
def data():
    return json.loads(EXPORT_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def generated_data():
    return json.loads(json.dumps(build_export(), sort_keys=True))


@pytest.fixture(scope="module")
def ripple_graph(lib):
    return lib.run("ripple", (kernel.FnRef("full_adder"), 4)).outcome.value


def test_design_oracle_and_all_tower_examples(data, lib):
    oracle = reference()
    assert oracle.table(oracle.Xor) == ((0,), (1,), (1,), (0,))
    design = json.loads(DESIGN_PATH.read_text(encoding="utf-8"))
    assert len(design["tower"]) == 10
    assert len(data["story"]) == 13
    assert {row["name"] for row in data["story"] if row["kind"] == "law"} == {
        "xor_comm", "adder_correct", "mult_comm"}
    for card, model in zip(data["story"], design["tower"]):
        assert card["layer"] == model["layer"]
        assert card["def_layer"] == lib.get(card["name"]).layer
        assert card["kind"] == model["kind"]
        assert card["design_decl"] == model["decl"]
        assert card["examples"][0]["text"].isascii()
        assert card["examples"][0]["trace"] is not None
        result = values.decode_outcome(card["examples"][0]["outcome"])
        assert isinstance(result, values.Ok)
        value = result.value
        represented = (f"List<{','.join(map(str, value.fields))}>" if card["name"] == "truth_table"
                       else f"Witness<{','.join(map(str, value.fields))}>" if card["name"] == "first_diff"
                       else value)
        assert represented == model["value"]
    assert [item["answer"] for item in data["showcase"]] == [item["answer"] for item in design["showcase"]]
    assert all(item["answer_checked"] for item in data["showcase"])
    assert data["tags"]["visibility"] == "partial"
    for card in data["story"]:
        for example in card["examples"]:
            assert example["learner_view"]["granted_probes"] == ["out_pin"]
            assert "full_state" not in example["learner_view"]
            assert "judge_view" not in example
    judge = json.loads(JUDGE_PATH.read_text(encoding="utf-8"))
    assert len(judge["examples"]) == sum(len(card["examples"]) for card in data["story"])
    assert all(example["judge_view"]["full_state"] for example in judge["examples"])


def test_learner_cannot_read_full_circuit(lib):
    graph = lib.run("xor_graph", ()).outcome.value
    for name in ("dag_gates", "dag_outputs", "eval_bits", "mult_value"):
        assert lib.scope().resolve(name) is None
    for name, args in (("dag_gates", (graph,)), ("dag_outputs", (graph,)),
                       ("eval_bits", (graph, hosts.bit_list((0, 1)))),
                       ("xor_value", (0, 1)), ("adder_value", (1, 1)),
                       ("mult_value", (1, 1))):
        with pytest.raises(PipelineError, match="judge-only"):
            lib.run(name, args)
    assert lib.run("out_pin", (graph, hosts.bit_list((0, 1)), 0)).outcome == values.Ok(1)


def test_refined_graphs_reject_invalid_values(lib):
    xor = lib.run("xor_graph", ()).outcome.value
    adder = lib.run("adder8_graph", ()).outcome.value
    inputs, gates, _ = hosts.deep_from_card(xor)
    wrong_output = hosts.deep_to_card(inputs, gates, (0,))
    for invalid in (hosts.deep_and2(), adder, wrong_output):
        assert lib.run("Xor.make", (invalid,)).outcome == values.Bottom("invalid")
    for invalid in (hosts.deep_and2(), xor, hosts.deep_to_card(16, (), (0,) * 9)):
        assert lib.run("Adder8.make", (invalid,)).outcome == values.Bottom("invalid")
    forged = values.Card("Xor", "refine", (hosts.deep_and2(),))
    assert lib.run("Xor.base", (forged,)).outcome == values.Bottom("invalid")


def test_forged_cards_cannot_pass_refinement_or_host_checks(lib):
    xor = lib.run("xor_graph", ()).outcome.value
    adder = lib.run("adder8_graph", ()).outcome.value
    for name, base in (("Xor", hosts.deep_and2()), ("Adder8", xor)):
        forged = values.Card(name, "val", (base,))
        assert lib.run(f"{name}.base", (forged,)).outcome == values.Bottom("invalid")
        assert kernel.call(f"{name}.base", (forged,), lib.scope()).outcome == values.Bottom("invalid")
        assert lib.run("eq", (forged, forged)).outcome == values.Bottom("invalid")
        assert lib.run(f"{name}._pack", (base,)).outcome == values.Bottom("invalid")
    malformed = values.Card("circuit", "dag", (2, values.Card("gates", "list", (
        values.Card("gate", "and", (0, "1")),)), values.Card("ports", "list", (2,))))
    assert hosts.deep_out(malformed, hosts.bit_list((0, 1)), 0) == values.Bottom("invalid")
    assert lib.run("out_pin", (malformed, hosts.bit_list((0, 1)), 0)).outcome == values.Bottom("invalid")
    assert lib.run("Adder8.base", (values.Card("Adder8", "val", (adder, 0)),)).outcome == values.Bottom("invalid")
    assert lib.run("Xor.base", (values.Card("Xor", "val", (xor,)),)).outcome == values.Ok(xor)
    assert lib.run("Adder8.base", (values.Card("Adder8", "val", (adder,)),)).outcome == values.Ok(adder)


def test_bounded_circuit_laws(lib, data):
    assert {row["symbol"] for row in data["laws"]} == {
        "#xor_comm", "#adder_correct", "#mult_comm"}
    for name, size in (("xor_comm", 4), ("adder_correct", 256), ("mult_comm", 256)):
        law = lib.get(name)
        assert law.evidence.scope["size"] == size
        assert {"holds", "equation"} <= set(law.evidence.checks)
    assert all(values.decode_outcome(row["examples"][0]["outcome"]) == values.Ok(values.TRUE)
               for row in data["laws"])


def test_law_examples_execute_named_laws_with_recorded_trace(lib, data):
    for row, operands in zip(data["laws"], ((0, 1), (13, 5), (13, 11))):
        example = row["examples"][0]
        run = lib.run(row["name"], operands, trace=True)
        assert example["text"] == f"{row['name']}({', '.join(map(str, operands))})"
        assert example["inputs"] == [values.encode(value) for value in operands]
        assert example["outcome"] == values.encode_outcome(run.outcome)
        assert example["steps"] == run.steps == example["trace"]["steps"]
        assert example["trace"]["children"][0]["name"] == row["name"]


def test_combinator_example_notation_matches_operation_slots(data):
    for name, operations, width in (("pair_graph", ("and2", "or2"), 2),
                                    ("ripple", ("full_adder",), 4),
                                    ("equiv", ("multiply4", "multiply4_swap"), 8)):
        example = next(row for row in data["story"] if row["name"] == name)["examples"][0]
        spelling = f"@{name}[{','.join(operations)}]({width})"
        assert spelling in example["text"]
        assert "FnRef<" not in example["text"]
        assert example["trace"]["steps"] == example["steps"]


@given(st.integers(min_value=0, max_value=15), st.integers(min_value=0, max_value=15))
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture], max_examples=20)
def test_random_ripple_boundary_invariance(lib, ripple_graph, left, right):
    row = hosts.bit_list(tuple((value >> pin) & 1 for value in (left, right) for pin in range(4)))
    observed = tuple(lib.run("out_pin", (ripple_graph, row, pin)).outcome.value for pin in range(5))
    assert sum(bit << pin for pin, bit in enumerate(observed)) == left + right


@pytest.mark.slow
@pytest.mark.skipif(os.environ.get("OPULSE_RUN_SLOW") != "1", reason="Set OPULSE_RUN_SLOW=1 for the full DAG wire comparison")
def test_dag_wire_for_wire_and_full_product_domain(lib):
    oracle = reference()
    for name, expected in (("xor_graph", oracle.Xor), ("full_adder", oracle.full_adder()),
                           ("adder8_graph", oracle.Adder8), ("multiply4", oracle.multiply4()),
                           ("cut_add8", oracle.cut_add8()),
                           ("multiply4_swap", oracle.multiply4_swap())):
        actual = lib.run(name, ()).outcome.value
        inputs, gates, outputs = hosts.deep_from_card(actual)
        assert (inputs, outputs) == (expected.inputs, expected.outputs)
        assert tuple((gate.tag.upper(), gate.fields[0],
                      gate.fields[1] if gate.tag == "and" else None)
                     for gate in gates) == expected.gates
        assert hosts.deep_to_card(inputs, gates, outputs) == actual
    product = lib.run("multiply4", ()).outcome.value
    for first, second in ((0, 0), (13, 11), (15, 15)):
        bits = oracle.to_bits(first, 4) + oracle.to_bits(second, 4)
        assert hosts.deep_eval(product, hosts.bit_list(bits)).fields == oracle.eval_circuit(oracle.multiply4(), bits)


def test_pair_operation_family_all_two_bit_inputs(lib):
    family = lib.get("pair_graph").evidence.scope["op_family"]
    assert len(family) == 8
    assert lib.get("pair_graph").evidence.scope["operation_cases"] == 64
    assert lib.get("pair_graph").evidence.scope["size"] == 256
    assert "truth_rows" in lib.get("pair_graph").evidence.checks
    assert lib.get("or2").evidence.scope["size"] == 1
    assert "truth_rows" in lib.get("or2").evidence.checks
    assert lib.get("ripple").evidence.scope["size"] == 512
    assert "truth_rows" in lib.get("ripple").evidence.checks
    assert lib.get("equiv").evidence.scope["size"] == 64
    family_equiv = lib.get("equiv").evidence.scope["op_family"]
    assert len(family_equiv) == 8
    assert lib.run("equiv", (kernel.FnRef("or2"), kernel.FnRef("or2"), 2)).outcome == values.Ok(1)
    assert lib.run("equiv", (kernel.FnRef("or2"), kernel.FnRef("and2"), 2)).outcome == values.Ok(0)
    for first, second in product(("and2", "or2"), repeat=2):
        paired = lib.run("pair_graph", (kernel.FnRef(first), kernel.FnRef(second), 2)).outcome.value
        for bits in product((0, 1), repeat=2):
            row = hosts.bit_list(bits)
            expected = (hosts.deep_eval(lib.run(first, ()).outcome.value, row).fields +
                        hosts.deep_eval(lib.run(second, ()).outcome.value, row).fields)
            assert hosts.deep_eval(paired, row).fields == expected
    or_circuit = lib.run("or2", ()).outcome.value
    for bits in product((0, 1), repeat=2):
        assert hosts.deep_eval(or_circuit, hosts.bit_list(bits)).fields == (bits[0] | bits[1],)


def test_checked_scopes_bind_exact_local_domains(lib):
    full_adder_rows = tuple((hosts.bit_list(bits),) for bits in product((0, 1), repeat=3))
    assert lib.get("full_adder").evidence.scope["checked"] == checked_scope(full_adder_rows)

    first_diff = lib.get("first_diff").evidence.scope
    assert first_diff["checked"]["size"] == first_diff["size"] == 53
    assert first_diff["checked"]["sha256"] != lib.get("truth_table").evidence.scope["checked"]["sha256"]
    for name in ("Xor", "Adder8", "pair_graph", "ripple", "equiv"):
        checked = lib.get(name).evidence.scope["checked"]
        assert checked["size"] == lib.get(name).evidence.scope["size"]


def test_pipeline_evidence_and_error_example(lib, data):
    for card in data["story"]:
        definition = lib.get(card["name"])
        assert definition.status == "promoted"
        assert definition.evidence.method in ("exhaustive", "bounded")
        assert definition.evidence.scope["size"] > 0
        assert definition.layer == card["def_layer"]
        assert definition.layer == compute_layer(
            all_dependencies(definition) - {definition.name} -
            (set(definition.spec.op_params) if definition.kind == "combinator" else set()),
            lambda key: lib.get(key.split(".")[0] if "." in key and
                                key.split(".")[0] in lib.definitions else key).layer)
        assert n.operation_literals(definition.body) <= set(definition.depends_on)
        if definition.kind == "combinator":
            assert definition.evidence.scope["fixed_ops"] == []
        assert definition.contract and definition.cost.steps["max"] >= 0
    assert len(lib.derived_world().promoted) >= 10
    for name in ("pair_graph", "ripple", "equiv"):
        for example in next(card for card in data["story"] if card["name"] == name)["examples"]:
            assert any(item["t"] == "fn" for item in example["inputs"])
    assert lib.get("Xor").spec.form == lib.get("Adder8").spec.form == "refine"
    assert {"canon_total", "canon_idempotent", "canon_keeps_valid"} <= set(
        lib.get("Xor").evidence.checks)
    raw = lib.run("xor_graph", ()).outcome.value
    wrapped = lib.run("Xor.make", (raw,)).outcome.value
    assert wrapped.sort == "Xor" and lib.run("Xor.base", (wrapped,)).outcome.value == raw
    assert lib.run("Xor.make", (hosts.deep_and2(),)).outcome == values.Bottom("invalid")
    assert lib.run("Xor.make", (lib.run("full_adder", ()).outcome.value,)).outcome == values.Bottom("invalid")
    assert all("title" in item and "definition" in item for item in data["story"])
    bad = data["story"][8]["examples"][1]
    assert bad["text"].startswith("?first_diff{")
    assert bad["outcome"] == {"bottom": "index"} and bad["steps"] > 0
    malformed = values.Card("circuit", "dag", (2, values.Card("gates", "list", (
        values.Card("gate", "not", (2,)),)), values.Card("ports", "list", (2,))))
    assert hosts.deep_eval(malformed, hosts.bit_list((0, 1))) == values.Bottom("cycle")
    assert lib.run("out_pin", (hosts.deep_and2(), hosts.bit_list((1, 0)), 3)).outcome == values.Bottom("port")
    assert hosts.deep_eval(hosts.deep_and2(), hosts.bit_list((0,))) == values.Bottom("arity")


def test_invariants_boundaries_and_non_interference(lib):
    scope = judge_scope(lib)
    graph = kernel.evaluate(deep.xor_graph(), scope=scope, trace=True)
    assert isinstance(graph.outcome, values.Ok)
    unfolded = kernel.evaluate(kernel.inline(deep.xor_graph(), scope), scope=scope)
    assert (graph.outcome, graph.steps) == (unfolded.outcome, unfolded.steps)
    assert unfold_equivalent(graph.trace,
                             (Boundary(), Boundary(depth=0))).ok
    xor = graph.outcome.value
    inputs, gates, outputs = hosts.deep_from_card(xor)
    equivalent = hosts.deep_to_card(inputs, (*gates, values.Card("gate", "not", (0,))), outputs)
    assert xor != equivalent
    left = lib.run("truth_table", (xor,)).outcome
    right = lib.run("truth_table", (equivalent,)).outcome
    assert left == right == values.Ok(hosts.bit_list((0, 1, 1, 0)))
    assert hosts.deep_from_card(xor) == (inputs, gates, outputs)


def test_evidence_invalidation_and_promotion_guards(lib):
    assert lib.run("equiv", (kernel.FnRef("or2"), kernel.FnRef("or2"), 8)).outcome == values.Bottom("index")
    fresh = new_library()
    original = lib.get("or2")
    fresh.write(replace(original, status="written", evidence=None, contract=None))
    fresh.check("or2")
    fresh.make_callable("or2", ((),))
    with pytest.raises(PipelineError, match="verified"):
        fresh.promote("or2", original.contract)
    request = replace(exhaustive((), "the one 2-input OR wiring"),
                      reference=lambda: lib.run("or2", ()).outcome.value)
    fresh.verify("or2", request)
    fresh.account("or2")
    fresh.promote("or2", original.contract)
    fresh.world = replace(fresh.world, params={**fresh.world.params, "max_gates": 1000})
    assert fresh.get("or2").status == "callable" and fresh.get("or2").evidence is None


def _strings(value, key=""):
    if isinstance(value, dict):
        for name, item in value.items():
            if name == "notation3":  # Notation v3: the generated display block is not machine notation
                continue
            yield from _strings(item, name)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item, key)
    elif isinstance(value, str) and not key.endswith("_zh"):
        yield value


def test_declaration_export_and_ascii(data):
    raw = json.loads(DECL_PATH.read_text(encoding="utf-8"))
    compose = raw["combinators"]["library"][0]
    assert compose == CombinatorSpec("compose", ("f", "g", "n"), ("f", "g"),
                                     deep.compose_body()).to_dict()
    assert list(new_library().scope().defns).count("compose") == 1
    assert validate(load(DECL_PATH)) == []
    assert WorldDecl.from_dict(raw).to_dict() == raw
    assert decl().params == {"inputs": 16, "max_gates": 1024, "max_outputs": 16}
    assert all(atom.cost == 1 for atom in atoms())
    assert json.loads(EXPORT_PATH.read_text(encoding="utf-8")) == data
    assert data["tower_source"] == "depth" and len(data["ladder"]) == 5
    assert EXPORT_PATH.stat().st_size < 3_000_000
    banned = re.compile("[\u27e8\u27e9\u27e6\u27e7\u2985\u2986\u2660\u2666\u25cb\u25c9\u211a\U0001d400-\U0001d7ff]")
    assert not [item for item in _strings(data) if banned.search(item)]


@pytest.mark.slow
@pytest.mark.skipif(os.environ.get("OPULSE_RUN_SLOW") != "1", reason="Full fresh export exceeds 60 seconds")
def test_regenerated_export_matches_committed(data, generated_data):
    assert generated_data == data


def test_law_rows_have_story_metadata(data):
    rows = data["story"][10:]
    assert [row["name"] for row in rows] == ["xor_comm", "adder_correct", "mult_comm"]
    assert [row["name"] for row in data["laws"]] == [row["name"] for row in rows]
    for group in (rows, data["laws"]):
        for layer, row in enumerate(group, start=11):
            assert row["layer"] == layer
            assert isinstance(row["def_layer"], int)
            assert all(isinstance(row[key], str) and row[key].strip() for key in
                       ("title", "definition", "title_zh", "definition_zh", "symbol", "decl"))
            assert row["symbol"] == "#" + row["name"]
            assert row["decl"].startswith("law " + row["symbol"] + ": eq(")
            assert row["decl"].isascii() and row["symbol"].isascii()


def test_story_ascii_matches_stored_bodies(data, lib):
    for row in data["story"]:
        digest = export_util.body_sha256(lib.get(row["name"]).body)
        assert row["body_sha256"] == digest
        if "ascii" in row:
            assert export_util.source_matches(row["ascii"], digest)


def test_story_ascii_declarations_and_examples(data, lib):
    # Round 6: an observation printed with subject {s} whose body reads another variable is not published.
    assert [row["name"] for row in data["story"] if "ascii" in row] == [
        "pair_graph", "ripple", "equiv", "xor_comm", "adder_correct", "mult_comm",
    ]
    for row in data["story"]:
        digest = export_util.body_sha256(lib.get(row["name"]).body)
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
        assert row["design_text"] == row["design_decl"]
        for example in row["examples"]:
            if "ascii" in example:
                assert notation.parse_expr(example["text"])
                assert example["ascii"] == example["text"]
    assert len(data["story"]) == 13
    assert sum("ascii" in example for row in data["story"] for example in row["examples"]) == 6


def test_fresh_first_three_cards(basic_lib):
    for name in ("or2", "pair_graph", "Xor"):
        assert basic_lib.get(name).status == "promoted"


@pytest.mark.slow
@pytest.mark.skipif(os.environ.get("OPULSE_RUN_SLOW") != "1", reason="Set OPULSE_RUN_SLOW=1 for the full <=3-gate family")
def test_all_three_gate_truth_tables_and_first_differences(lib):
    """Check every <=3-gate graph; pair every <=2-gate graph with one graph per truth signature.

    The full 308**2 structural pair product takes hours through Library.run. Each of the 308 small graphs is
    paired, on both sides, with a representative of each of the nine distinct four-row signatures, so every
    structural graph meets every signature in both argument positions.
    """
    graphs = small_circuits()
    assert len(graphs) == 7508
    rows = tuple(hosts.bit_list(bits) for bits in product((0, 1), repeat=2))
    scope = judge_scope(lib)
    representatives = {}
    small = []
    for graph in graphs:
        signature = tuple(hosts.deep_out(graph, bits, 0) for bits in rows)
        assert lib.run("truth_table", (graph,)).outcome == values.Ok(hosts.bit_list(signature))
        extended = kernel.evaluate(deep.or_from(deep.lit(graph), deep.lit(0), deep.lit(1)),
                                   scope=scope).outcome.value
        for bits in rows:
            assert lib.run("out_pin", (extended, bits, 0)).outcome == values.Ok(bits.fields[0] | bits.fields[1])
        if len(hosts.deep_from_card(graph)[1]) <= 2:
            small.append((signature, graph))
            representatives.setdefault(signature, graph)
    assert len(small) == 308
    assert len(representatives) == 9
    pairs = {(first, second) for item in small for chosen in representatives.items()
             for first, second in ((item, chosen), (chosen, item))}
    for (left_signature, left), (right_signature, right) in sorted(pairs, key=repr):
        difference = next(((index // 2, index % 2, left_bit, right_bit)
                           for index, (left_bit, right_bit) in enumerate(zip(left_signature, right_signature))
                           if left_bit != right_bit), None)
        expected = values.Card("witness", "first", difference) if difference else values.Card("witness", "none")
        assert lib.run("first_diff", (left, right)).outcome == values.Ok(expected)
        pair_scope = scope.extend((kernel.Defn("left_graph", (), n.Lit(left)),
                                   kernel.Defn("right_graph", (), n.Lit(right))))
        decision = kernel.call("equiv", (kernel.FnRef("left_graph"),
                                        kernel.FnRef("right_graph"), 2), pair_scope)
        assert decision.outcome == values.Ok(int(difference is None))


@pytest.mark.slow
@pytest.mark.skipif(os.environ.get("OPULSE_RUN_SLOW") != "1", reason="Set OPULSE_RUN_SLOW=1 for all 65536 byte pairs")
def test_full_design_oracle():
    reference().verify()
