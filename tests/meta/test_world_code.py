"""Exact bounded obligations of code@1."""

import hashlib
import inspect
import json

import pytest

from opulse.atoms import kernel, nodes, notation
from opulse.atoms import library as core_library
from opulse.atoms.boundary import Boundary, flatten_calls
from opulse.atoms.laws import RewriteError, replay_rewrite
from opulse.atoms.library import PipelineError, VerifyRequest
from opulse.atoms.values import Bottom, Card, Ok, decode, encode, outcome_equal
from opulse.meta import arith, code, engine
from opulse.meta.check import export_problems
from opulse.meta.export_util import parse_meta_definition, parse_meta_value
from opulse.meta.identity import Ledger
from opulse.meta.notation import parse_code, show_code
from opulse.meta.worlds.code import hosts
from opulse.meta.worlds.code.export import DEST, export
from opulse.meta.worlds.code.showcase import decide_family
from opulse.meta.worlds.code.story import (
    build_story,
    call,
    lit,
    record_specialization,
    reference_specialize,
    run_code,
    semantic_check,
    specialization_family,
    specialize_source,
    var,
)
from opulse.meta.worlds.code.world import DECL, declaration, library, load_world


@pytest.fixture(scope="module")
def verifier_baseline():
    return dict(core_library._VERIFIERS)


@pytest.fixture(scope="module")
def built(verifier_baseline):
    before = verifier_baseline
    result = build_story()
    assert all(core_library._VERIFIERS[name] is verifier for name, verifier in before.items())
    assert set(core_library._VERIFIERS) - set(before) <= {"law", "bridge", "template"}
    return result


@pytest.fixture(scope="module")
def exported(built):
    return export(built)


def test_declaration_and_given_rules():
    decl = load_world()
    assert decl.world == "code" and decl.version == 1
    assert decl.to_dict()["schema"] == "opulse.world/2"
    assert decl.extra["tags"]["domain"] == "program"
    assert set(decl.extra["tags"]["open_kinds"]) == {"object", "operation", "combinator", "observation", "law", "bridge"}
    for operation in decl.operations:
        function = (getattr(engine, operation.name + "_atom") if operation.name in ("eval", "run")
                    else hosts.RULES[operation.name][1])
        assert operation.impl["host"] == function.__module__ + ":" + function.__name__
        assert operation.impl["digest"] == hashlib.sha256(inspect.getsource(function).encode()).hexdigest()
    code_object = next(obj for obj in decl.objects if obj.name == "code")
    assert code_object.canon["digest"] == hashlib.sha256(inspect.getsource(code.canonicalize).encode()).hexdigest()
    lib = library()
    assert lib.run("div", (9, 0)).outcome == Bottom("div_zero")
    assert lib.run("field", (code.lst(), 0)).outcome == Bottom("invalid")
    assert lib.run("list_len", (code.lst((1, 2, 3)),)).outcome == Ok(3)
    assert lib.run("size", (code.lst((1, 2)),)).steps == 1
    assert lib.run("mk", ("expr", "not_a_tag", code.lst())).outcome == Bottom("invalid")
    assert lib.run("mk", ("expr", "call", code.lst((4, code.lst())))).outcome == Bottom("invalid")


def test_shared_arithmetic_rules_keep_code_world_results_and_costs():
    assert all(hosts.RULES[name][1] is getattr(arith, name)
               for name in ("add", "sub", "mul", "div", "is_zero", "lt"))
    lib = library()
    for name, arguments, expected in (
        ("add", (11, 7), Ok(18)), ("sub", (11, 7), Ok(4)),
        ("mul", (-3, 7), Ok(-21)), ("div", (11, 4), Ok(2)),
        ("div", (7, 0), Bottom("div_zero")),
        ("is_zero", (0,), Ok(True)), ("lt", (7, 4), Ok(False)),
    ):
        result = lib.run(name, arguments, trace=True)
        assert (result.outcome, result.steps) == (expected, 1)
        assert result.trace.steps == 1


def test_decoded_program_run_cache_tracks_atom_identity(built):
    _, sources, _ = built
    lib = library()
    original = run_code(lib, sources[12], (2,))
    assert run_code(lib, sources[12], (2,)) is original
    lib.atoms = (lib.atoms[0],) + lib.atoms[1:]
    refreshed = run_code(lib, sources[12], (2,))
    assert refreshed is not original
    assert (refreshed.outcome, refreshed.steps) == (original.outcome, original.steps)


def test_story_pipeline_and_exact_unfold(built):
    lib, sources, counter = built
    records = [definition for definition in lib.definitions.values() if definition.origin == "invented"]
    assert len(records) == 17 and {definition.kind for definition in records} == {
        "object", "operation", "combinator", "law", "bridge", "template"}
    assert {1, 2, 3, 4, 5} <= {definition.layer for definition in records}
    assert all(definition.evidence and definition.contract for definition in records if definition.status == "promoted")
    assert lib.get("simplify_unsafe").status == "callable"
    assert lib.get("simplify_unsafe").evidence is None
    assert any(isinstance(node, nodes.Rec) and node.memo
               for node in nodes.walk(lib.get("const_fold").body))
    repeated = lib.run("const_fold", (counter,), trace=True)
    def frames(frame):
        return (frame, *(child_frame for child in frame.children for child_frame in frames(child)))
    assert any(frame.memo_hit for frame in frames(repeated.trace))
    for definition in records:
        if definition.kind in ("law", "template"):
            continue
        if definition.name.startswith("generated_"):
            arguments = (4,)
        else:
            arguments = (kernel.FnRef("const_fold"), kernel.FnRef("simplify_safe"), sources[11]) if definition.name == "pipeline" else (
            () if definition.name == "poly" else (counter.fields[2],) if definition.name == "has_div" else
            (specialize_source(lib), 3) if definition.name == "specialize" else
            (specialize_source(lib),) if definition.name == "specialize_zero" else
            (sources[12],) if definition.name == "fold_bridge" else
            (specialization_family(lib, sources)[int(definition.name.rsplit("_", 1)[1])],)
            if definition.name.startswith("Specialize_member_") else
            (counter,) if definition.name == "simplify_unsafe" else (sources[11],))
        invocation = nodes.Call(definition.name, tuple(nodes.Lit(arg) for arg in arguments))
        actual = kernel.evaluate(invocation, scope=lib.scope())
        unfolded = kernel.evaluate(kernel.inline(invocation, lib.scope()), scope=lib.scope())
        assert outcome_equal(actual.outcome, unfolded.outcome), definition.name
        assert actual.steps == unfolded.steps, definition.name


def test_six_kinds_scoped_evidence_and_derivation(built):
    lib, sources, counter = built
    assert lib.fold_derivation.rewrite_steps == 0
    assert len(lib.fold_derivation.steps) == 1
    assert lib.fold_derivation.steps[0].law == "fold_idempotent"
    before = call("const_fold", call("const_fold", lit(sources[12])))
    after = call("const_fold", lit(sources[12]))
    assert replay_rewrite(before, after, "fold_idempotent", lib, {}) == lib.fold_derivation
    with pytest.raises(RewriteError):
        outside = code.quote_from_library(lib, "poly")
        replay_rewrite(call("const_fold", call("const_fold", lit(outside))),
                       call("const_fold", lit(outside)), "fold_idempotent", lib, {})
    false_law = lib.get("unsafe_equivalence")
    assert false_law.status == "callable" and false_law.evidence is None
    assert kernel.evaluate(false_law.body, {"c": counter, "xs": code.lst((0,))},
                           lib.scope()).outcome == Bottom("div_zero")
    unsafe = lib.run("simplify_unsafe", (counter,)).outcome
    assert run_code(lib, counter, (0,)).outcome == Bottom("div_zero")
    assert run_code(lib, unsafe.value, (0,)).outcome == Ok(0)
    bridge = lib.get("fold_bridge")
    assert bridge.evidence.checks == ("commutes", "total_on_domain")
    for definition in (lib.get("fold_idempotent"), bridge):
        scope = definition.evidence.scope
        assert definition.status == "promoted"
        assert scope["size"] == scope["enumerated_count"] == 224
        if definition.kind == "bridge":
            assert scope["domain_size"] == 224
        assert scope["semantic_inputs"] == list(range(7))
        assert scope["semantic_cases"] == 1568
        assert len(scope["input_hashes"]) == 224
    assert bridge.evidence.scope["pairs_checked"] == 224
    assert bridge.evidence.scope["skipped"] == 0
    assert lib.bridge_semantic_cases == 1568
    assert len(lib.get("fold_idempotent").evidence.scope["values"]) == 224
    for value in (sources[12], sources[200], sources[212]):
        mapped = lib.run("fold_bridge", (value,))
        folded = lib.run("const_fold", (value,))
        assert mapped.outcome == folded.outcome
        assert lib.run("fold_bridge", (folded.outcome.value,)).outcome == folded.outcome
    template = lib.get("Specialize")
    assert template.evidence.method == "bounded"
    assert template.evidence.scope["family"] == [{"k": 0}, {"k": 3}]
    for index, member in enumerate(lib.specialize_members):
        assert member.status == "promoted" and "Specialize" in member.depends_on
        program = specialization_family(lib, sources)[index]
        constant = (0, 3)[index]
        direct = lib.run(member.name, (program,))
        result = direct.outcome
        assert result == reference_specialize(program, constant)
        adapted = lib.run("eval", (code.quote_from_library(lib, member.name), code.lst((program,))))
        assert (adapted.outcome, adapted.steps) == (direct.outcome, direct.steps)
        for value in range(7):
            assert run_code(lib, result.value, (value,)).outcome == run_code(
                lib, program, (constant, value)).outcome
    record = lib.generator_records[0]
    assert record.produced_by[0] == code.code_hash(code.quote_from_library(lib, "specialize"))
    produced = [definition for definition in lib.definitions.values()
                if definition.name.startswith("generated_")]
    assert len(produced) == 1 and produced[0].status == "callable"
    assert produced[0].evidence is None


def test_semantic_preservation_and_exact_cost(built):
    lib, sources, _ = built
    assert len(sources) == 224
    assert len({code.code_hash(value) for value in sources}) == 224
    assert max(hosts.size(value) for value in sources) == 42
    assert max(nodes.length(code.decode(value).main.body) for value in sources) == 10
    assert [code.decode(value).main.body.__class__ for value in sources[200:]] == [nodes.Let] * 12 + [nodes.Case] * 12
    assert any(run_code(lib, value, (0,)).outcome == Bottom("div_zero") for value in sources)
    assert lib.semantic_results["const_fold"] == (True, None, (2443, 1267))
    assert lib.semantic_results["simplify_safe"] == (True, None, (2443, 1246))
    assert lib.get("const_fold").evidence.scope["semantic_cases"] == 1568
    assert lib.get("simplify_safe").evidence.scope["semantic_cases"] == 1568


def test_nested_lets_and_unary_calls(built):
    lib, _, _ = built
    def resolve(name):
        operation = next((op for op in lib.world.operations if op.name == name), None)
        return code.Resolved(digest=code.atom_digest(operation)) if operation else None
    program = code.make_code("operation", code.sig_op((("int", "bottom"),), ("bool", "bottom")),
                             ("x0",), nodes.Let("temporary", call("add", lit(2), lit(3)),
                                call("is_zero", call("sub", var("temporary"), var("x0")))), resolve)
    folded = lib.run("const_fold", (program,)).outcome
    assert isinstance(folded, Ok)
    assert folded.value.fields[2].fields[1] == code.encode_node(nodes.Lit(5))
    for argument in range(7):
        assert outcome_equal(run_code(lib, program, (argument,)).outcome,
                             run_code(lib, folded.value, (argument,)).outcome)


def test_folding_case_arms_and_default(built):
    lib, sources, _ = built
    original = sources[218]
    folded = lib.run("const_fold", (original,)).outcome.value
    decoded = code.decode(folded).main.body
    assert isinstance(decoded, nodes.Case)
    assert decoded.arms[0][1] == nodes.Lit(5)
    assert decoded.default == nodes.Lit(0)
    safe = code.decode(lib.run("simplify_safe", (original,)).outcome.value).main.body
    assert safe.arms[0][1] == nodes.Lit(5) and safe.default == nodes.Lit(0)
    assert all(outcome_equal(run_code(lib, original, (argument,)).outcome,
                             run_code(lib, folded, (argument,)).outcome) for argument in range(7))


def test_exact_trace_and_boundary_view(built):
    lib, sources, _ = built
    run = lib.run("expr_size", (sources[0],), trace=True)
    assert run.outcome == Ok(2) and run.steps == 2
    assert [(node.name, node.steps, node.given) for node in flatten_calls(run.trace, Boundary())] == [
        ("expr_size", 2, False)]
    assert [(node.name, node.steps, node.given) for node in flatten_calls(run.trace, Boundary.unfold_all())] == [
        ("field", 1, True), ("size", 1, True)]


def test_unsound_counterexample_cannot_promote(built):
    lib, sources, original = built
    assert sources[199] == original
    transformed = lib.run("simplify_unsafe", (original,)).outcome
    assert isinstance(transformed, Ok)
    assert run_code(lib, original, (0,)).outcome == Bottom("div_zero")
    assert run_code(lib, transformed.value, (0,)).outcome == Ok(0)
    assert lib.run("simplify_safe", (original,)).outcome.value == original
    sound, witness, _ = semantic_check(lib, sources, "simplify_unsafe")
    assert sound is False and witness == (original, 0, Bottom("div_zero"), Ok(0))
    with pytest.raises(PipelineError, match="reference counterexample"):
        lib.verify("simplify_unsafe", VerifyRequest("bounded", ((original,),),
            {"domain": "one counterexample, input bounded 0..6", "size": 1},
            reference=lambda _: Bottom("semantic_counterexample")))
    with pytest.raises(PipelineError, match="promote requires verified status"):
        lib.promote("simplify_unsafe", lib.get("poly").contract)


def test_specialization_and_pipeline(built):
    lib, sources, _ = built
    programs = specialization_family(lib, sources)
    assert len(programs) == 30
    assert lib.specialization_result == (True, None, 1470)
    assert lib.get("specialize").evidence.scope["semantic_cases"] == 1470
    assert lib.get("specialize_zero").layer == 5
    assert len(set(lib.generated_hashes)) == 2
    for digest in lib.generated_hashes:
        record = lib.generated_ledger.record(digest, lib.world.world_hash())
        assert record.status == "promoted" and len(record.produced_by) == 3
    for program in programs[:3]:
        generated = lib.run("specialize_zero", (program,)).outcome.value
        assert all(outcome_equal(run_code(lib, generated, (argument,)).outcome,
                                 run_code(lib, program, (0, argument)).outcome) for argument in range(7))
    program = programs[12]
    generated = lib.run("specialize", (program, 3)).outcome.value
    ledger = Ledger()
    world_hash = lib.world.world_hash()
    generator_hash = code.code_hash(code.quote_from_library(lib, "specialize"))
    from opulse.atoms.spec import content_hash
    from opulse.atoms.values import encode
    produced_by = (generator_hash, code.code_hash(program), content_hash(encode(3)))
    digest = ledger.add(generated, world_hash, produced_by=produced_by)
    assert ledger.record(digest, world_hash).status == "callable"
    assert ledger.record(digest, world_hash).evidence == ()
    assert lib.get("specialize").evidence is not None
    ledger, produced = record_specialization(lib, program, 3, ledger)
    assert produced == digest
    record = ledger.record(digest, world_hash)
    assert record.produced_by == produced_by
    assert record.status == "promoted" and len(record.evidence) == 1
    assert record.evidence[0] != lib.get("specialize").evidence
    value = sources[11]
    first = lib.run("const_fold", (value,)).outcome.value
    second = lib.run("simplify_safe", (first,)).outcome.value
    expected = lib.run("stable_simplify", (second,)).outcome
    actual = lib.run("pipeline", (kernel.FnRef("const_fold"), kernel.FnRef("simplify_safe"), value)).outcome
    assert actual == expected


def test_identity_and_quote(built):
    lib, sources, _ = built
    original = sources[11]
    folded = lib.run("const_fold", (original,)).outcome.value
    assert code.code_hash(folded) != code.code_hash(original)
    assert not hasattr(folded, "evidence")
    atom = next(op for op in lib.world.operations if op.name == "add")
    resolve = lambda name: code.Resolved(digest=code.atom_digest(atom)) if name == "add" else None
    left = code.make_code("operation", code.sig_op((("int", "bottom"),), ("int", "bottom")),
                          ("source",), nodes.Let("temporary", nodes.Var("source"),
                                                   nodes.Call("add", (nodes.Var("temporary"), nodes.Lit(2)))), resolve)
    right = code.make_code("operation", left.fields[1], ("input",),
                           nodes.Let("renamed", nodes.Var("input"),
                                     nodes.Call("add", (nodes.Var("renamed"), nodes.Lit(2)))), resolve)
    assert code.code_hash(left) == code.code_hash(right)
    assert code.quote_from_library(lib, "poly").sort == "code"


def test_quote_eval_law_for_every_story_member(built):
    lib, sources, counter = built
    for definition in lib.definitions.values():
        if definition.origin != "invented" or definition.kind not in ("operation", "object") or definition.name.startswith(("Specialize_member_", "generated_")):
            continue
        quoted = code.quote_from_library(lib, definition.name)
        arguments = (() if definition.name == "poly" else (counter.fields[2],) if definition.name == "has_div" else
            (specialize_source(lib), 3) if definition.name == "specialize" else
            (specialize_source(lib),) if definition.name == "specialize_zero" else
            (counter,) if definition.name == "simplify_unsafe" else (sources[11],))
        actual = engine.call(definition.name, arguments, lib.scope())
        quoted_run = engine.call("eval", (quoted, code.lst(arguments)), lib.scope())
        assert outcome_equal(actual.outcome, quoted_run.outcome), definition.name
        assert actual.steps == quoted_run.steps, definition.name


def test_metered_eval_rejects_foreign_or_malformed_code(built):
    lib, sources, _ = built
    quoted = sources[11]
    assert engine.call("eval", (quoted, code.lst()), lib.scope()).outcome == Bottom("arity")
    assert engine.call("eval", (Card("expr", "lit", (3,)), code.lst()), lib.scope()).outcome == Bottom("ill_formed")
    forged_atoms = tuple(Card("atom", "atom", (atom.fields[0], "0" * 64))
                         for atom in code.items(quoted.fields[3]))
    foreign = Card("code", "def", (*quoted.fields[:3], code.lst(forged_atoms), quoted.fields[4]))
    assert engine.call("eval", (foreign, code.lst((0,))), lib.scope()).outcome == Bottom("foreign_code")
    constant = code.quote_from_library(lib, "poly")
    assert engine.call("eval", (constant, code.lst()), lib.scope()).outcome == lib.run("poly", ()).outcome
    measured = code.quote_from_library(lib, "expr_size")
    assert engine.call("eval", (measured, code.lst((quoted,))), lib.scope()).steps == 2
    assert lib.run("expr_size", (quoted,)).steps == 2
    traced = engine.call("eval", (measured, code.lst((quoted,))), lib.scope(), trace=True)
    assert traced.outcome == lib.run("expr_size", (quoted,)).outcome and traced.steps == 2
    inner = traced.trace.children[0].children[0]
    assert [child.name for child in inner.children] == ["field", "size"]
    assert [child.steps for child in inner.children] == [1, 1]
    budgeted = engine.call("run", (measured, code.lst((quoted,)), 1), lib.scope())
    assert budgeted.outcome == Ok(Card("result", "out", (1,))) and budgeted.steps == 1


def test_showcase_answers_and_export(built, exported):
    lib, sources, counterexample = built
    data = exported
    tasks = data["showcase"]
    assert [task["angle"] for task in tasks] == ["Invert", "Decide", "Compute"]
    assert "Number from zero" not in " ".join(task["prompt"] for task in tasks)
    assert "hash" not in tasks[0]["prompt"] and "indices" not in tasks[0]["prompt"]
    target = sources[2]
    assert show_code(target) in tasks[0]["prompt"]
    assert tasks[0]["answer"] == {"programs": sorted(show_code(source) for source in sources[:105]
        if lib.run("const_fold", (source,)).outcome == Ok(target))}
    assert len(tasks[0]["answer"]["programs"]) == 7
    assert len(set(sources[:105])) == 105

    candidates = decide_family(lib)
    assert len(candidates) == len(set(candidates)) == 72
    assert show_code(counterexample) not in tasks[1]["prompt"]
    failures = []
    for source in candidates:
        transformed = lib.run("simplify_unsafe", (source,)).outcome
        assert isinstance(transformed, Ok)
        for argument in range(7):
            before = run_code(lib, source, (argument,)).outcome
            after = run_code(lib, transformed.value, (argument,)).outcome
            if not outcome_equal(before, after):
                failures.append((nodes.length(code.decode(source).main.body), show_code(source),
                                 argument, before, after))
                break
    size, printed, argument, before, after = min(failures)
    assert printed not in tasks[1]["prompt"]
    assert tasks[1]["answer"] == {"preserves": False, "failing_programs": len(failures),
                                  "counterexample": printed, "input": argument,
                                  "before": f"Bottom({before.reason})", "after": f"Ok({after.value})"}
    assert len(failures) == 16 and size == 5 and argument == 0
    assert printed == "Code<op (x0) = mul(div(0, 0), 0)>"
    assert before == Bottom("div_zero") and after == Ok(0)
    assert tasks[2]["answer"] == {"before": 2443, "after": 1267, "saved": 1176, "all_outcomes_equal": True}
    assert lib.semantic_results["const_fold"] == (True, None, (2443, 1267))
    near_miss = next(entry for entry in data["story"] if entry["name"] == "unsafe_equivalence")
    assert near_miss["status"] == "callable" and near_miss["evidence"] is None
    assert near_miss["counterexample"] == {
        "program": show_code(counterexample), "input": 0,
        "before": {"kind": "Bottom", "reason": "div_zero"},
        "after": {"kind": "Ok", "value": {"t": "int", "v": 0}},
    }
    assert json.loads(DECL.read_text(encoding="utf-8")) == declaration().to_dict()
    assert data["schema"] == "opulse.world_v2_export/1"
    assert len(data["story"]) == 17 and len(data["ladder"]) == 5 and len(data["showcase"]) == 3
    assert len(data["generated"]) == 3
    assert all(item["status"] == "promoted" for item in data["generated"][:2])
    assert [task["angle"] for task in data["showcase"]] == ["Invert", "Decide", "Compute"]
    assert all(task["kinds_involved"] for task in data["showcase"])
    for item in data["story"]:
        assert isinstance(item["definition"], str)
        assert item["examples"] and isinstance(item["examples"][0]["steps"], int)
        assert all("t" in value or "fn" in value for value in item["examples"][0]["inputs"])
    assert len({json.dumps(item["examples"][0]["inputs"], sort_keys=True)
                for item in data["story"]}) == len(data["story"])
    assert DEST.read_text(encoding="utf-8") == json.dumps(
        data, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"


def test_every_code_story_entry_has_parseable_ascii(exported):
    data = exported
    assert export_problems(data, "code.json", strict=True) == []
    assert len(data["story"]) == 17
    assert sum(len(item["examples"]) for item in data["story"]) == 17
    assert {item["kind"] for item in data["story"]} == {
        "object", "operation", "combinator", "law", "bridge", "template"}
    for item in data["story"]:
        definition = parse_meta_definition(item["ascii"])
        if item["kind"] == "template":
            assert notation.parse_definition(item["ascii"]).spec.pattern == item["spec"]["pattern"]
            assert item["runtime_spec"]["pattern"]["definition_body"] == nodes.to_json(
                nodes.Call("specialize", (nodes.Var("arg0"), nodes.Lit("$k"))))
        if item["name"] == "has_div":
            assert nodes.to_json(definition.body) == item["body"]
        assert (definition.name, definition.kind, definition.layer) == (
            item["name"], item["kind"], item["layer"])
        assert "ascii_projection" not in item
        for example in item["examples"]:
            source = example["ascii"]
            assert source.isascii() and " = " in source
            for value in example["inputs"]:
                if value.get("t") == "code":
                    assert show_code(decode(value), signature=True, deps=True, exact=True) in source
            if item["kind"] == "template":
                shown = parse_meta_value("Code<" + source.split(" = Code<", 1)[1])
                assert example["outcome"]["kind"] == "Ok"
                assert example["outcome"]["code_hash"] == code.code_hash(shown)
                assert code.canonicalize(shown) == shown
                assert encode(shown) == example["outcome"]["value"]
                assert example["member"]["name"] == "Specialize_member_1"
                assert shown.sort == "code"
            elif example["outcome"]["kind"] == "Ok" and example["outcome"]["value"].get("t") == "code":
                quoted = decode(example["outcome"]["value"])
                shown = parse_code("Code<" + source.split(" = Code<", 1)[1])
                assert shown == quoted


def test_building_the_story_leaves_the_core_verifier_table_unchanged(built, verifier_baseline):
    assert built[0].get("fold_bridge").status == "promoted"
    assert all(core_library._VERIFIERS[name] is verifier
               for name, verifier in verifier_baseline.items())
    assert set(core_library._VERIFIERS) - set(verifier_baseline) <= {"law", "bridge", "template"}
