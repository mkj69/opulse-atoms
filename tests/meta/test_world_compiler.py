"""Exact compiler-world evidence and published-answer checks."""

import json
from copy import deepcopy

import pytest

from opulse.atoms import kernel, nodes
from opulse.atoms import nodes as n
from opulse.atoms.bridges import bridge_defn, verify_bridge
from opulse.atoms.laws import RewriteError, derivation_length, replay_rewrite
from opulse.atoms.library import PipelineError, VerifyRequest, atoms_digest
from opulse.atoms.spec import content_hash
from opulse.atoms.values import Bottom, Card, Ok, Unknown
from opulse.atoms.world import WorldDecl
from opulse.meta import arith, code_world
from opulse.meta import code as meta_code
from opulse.meta.check import export_problems
from opulse.meta.code import code_hash, lst, quote_from_library
from opulse.meta.compiler import validate as translation
from opulse.meta.compiler.compile import compile_tiny
from opulse.meta.engine import call as meta_call
from opulse.meta.export_util import (
    input_hash,
    outcome_json,
    parse_meta_definition,
    parse_meta_value,
    trace_json,
)
from opulse.meta.notation import show_code
from opulse.meta.vn import reference
from opulse.meta.worlds.compiler.export import (
    DECL_PATH,
    EXPORT_PATH,
    build_export,
)
from opulse.meta.worlds.compiler.story import (
    agreement,
    build_story,
    fib_source,
    gap_source,
)
from opulse.meta.worlds.compiler.world import (
    declaration,
    machine_scope,
    make_library,
    make_world,
)


def test_compiler_shared_integer_rules_and_exact_steps():
    from opulse.meta.worlds.compiler import world

    assert world._NAMED_GIVENS["add"] is arith.add
    assert world._NAMED_GIVENS["sub"] is arith.sub
    compiler = make_library()
    for name, arguments, expected in (
        ("add", (11, 7), Ok(18)), ("sub", (11, 7), Ok(4)),
        ("is_zero", (0,), Ok(Card("bool", "true"))),
        ("lt", (7, 4), Ok(Card("bool", "false"))),
    ):
        result = compiler.run(name, arguments, trace=True)
        assert (result.outcome, result.steps) == (expected, 1)
        assert result.trace.steps == 1


@pytest.fixture(scope="module")
def story():
    return build_story()


@pytest.fixture(scope="module")
def payload(story):
    return build_export(story)


def test_pair_record_is_immutable(story, payload):
    world_hash = story.library.world.world_hash()
    pair = story.validation.pair
    retrieved = story.ledger.pair_evidence(*pair, world_hash)
    assert retrieved[0].scope["size"] == 14
    retrieved[0].scope["domain"][0][0] = 999
    assert story.ledger.pair_evidence(*pair, world_hash)[0].scope["domain"][0] == [0]
    assert payload["translation"]["evidence"] == story.ledger.pair_evidence(
        *pair, world_hash)[0].to_dict()


def test_invented_compiler_bridge(story):
    bridge = story.bridge.get("compile")
    assert bridge.status == "promoted" and bridge.kind == "bridge"
    assert bridge.spec.source == "compiler@1:code" and bridge.spec.target == "compiler@1:prog"
    assert bridge.evidence.checks == ("commutes", "total_on_domain")
    assert bridge.evidence.scope["size"] == 16
    assert bridge.evidence.scope["domain_size"] == 16
    assert bridge.evidence.scope["pairs_checked"] == 256
    assert len(bridge.evidence.scope["source_hashes"]) == 16
    assert bridge.evidence.scope["input_pairs"] == [[left, right] for left in range(4)
                                                     for right in range(4)]
    assert len(bridge.spec.interface) == 16
    assert bridge.evidence.scope["skipped"] == 0
    assert verify_bridge(bridge, story.bridge, VerifyRequest("bounded", ((story.bridge_family[0],),),
                         {"domain": "one accepted source", "size": 1}, extra={"fuel": 500})).ok
    assert story.bridge.run("compile", (story.bridge_family[0],)).outcome.value.sort == "prog"
    assert story.bridge.run("compile", (story.constants["learner_source"],)).outcome == Bottom("outside_domain")
    assert story.compiler.get("lcompile").status == "promoted"
    assert all(story.compiler.get(name).evidence.atoms_hash == atoms_digest(story.compiler.atoms)
               for name in ("lcompile", *story.helper_calls))
    assert story.library.get("fetch").evidence.atoms_hash == atoms_digest(story.library.atoms)
    assert atoms_digest(make_library().atoms) == atoms_digest(story.library.atoms)
    scope = story.compiler.get("lcompile").evidence.scope
    assert (scope["family_size"], scope["size"], len(scope["rejected_hashes"])) == (4618, 3325, 1293)
    assert scope["inputs_per_program"] == 256 and scope["rejected_pairs"] == 211375
    assert story.compiler.get("lcompile").evidence.method == "bounded"
    assert story.compiler.get("lcompile").contract is not None
    assert {name: (record["calls"], record["size"]) for name, record in story.helper_calls.items()} == {
        "emit": (39424, 56), "tail": (40, 40), "lookup": (5138, 15),
        "branch": (40, 40), "compile_expr": (4618, 4618)}
    for name, record in story.helper_calls.items():
        evidence = story.compiler.get(name).evidence
        assert evidence.scope["size"] == record["size"]
        assert evidence.scope["calls"] == record["calls"]
        assert evidence.scope["fingerprint"] and len(evidence.scope["fingerprint"]) == 64
        direct = story.compiler.run(name, record["sample"])
        unfolded = kernel.evaluate(kernel.inline(n.Call(name, tuple(n.Lit(arg) for arg in
                                                            record["sample"])), story.compiler.scope()),
                                   scope=story.compiler.scope())
        assert (direct.outcome, direct.steps) == (unfolded.outcome, unfolded.steps)
    assert code_hash(story.constants["learner_source"]) not in story.compiler.get(
        "lcompile").evidence.scope["accepted_hashes"]
    assert story.learner_validation.accepted
    assert story.ledger.record(story.ledger.resolve("learner_program"),
                               story.library.world.world_hash()).produced_by == (
                                   story.compiler_hash, story.learner_validation.pair[0])
    assert story.ledger.pair_evidence(*story.learner_validation.pair,
                                      story.library.world.world_hash())[0].scope["size"] == 16
    assert story.compiler.run("lcompile", (story.constants["learner_source"],)).steps == 188
    program = story.constants["learner_program"]
    assert program.fields[0] == 64 and tuple(program.fields[2].fields) == (60, 61)
    compiled = translation.Prog(64, tuple(program.fields[1].fields), (60, 61))
    assert [(compiled.run((value, 3), 500)[1].a, compiled.run((value, 3), 500)[2])
            for value in (0, 1, 10)] == [(3, 4), (4, 8), (13, 8)]


def test_transitive_callee_scope(story):
    for value in (8, 9, 10):
        assert (value,) in story.library.get("fib_crosscheck").evidence.scope["inputs"]
        assert (value,) in story.library.get("target_fib").evidence.scope["inputs"]
        loaded = reference.load(story.program.code, story.program.n, {story.program.args[0]: value})
        interpreter_scope = story.library.get("vn_interp").evidence.scope["domain"]
        assert list(loaded.mem) in interpreter_scope["programs"]
    for result in (0, 1, 2, 3, 5, 8, 13, 21, 34, 55):
        assert (result, result) in story.library.get("agrees").evidence.scope["inputs"]


def test_interpreter_example_marks_uncovered_fetch(story, payload):
    interpreter = next(item for item in payload["story"] if item["name"] == "vn_interp")
    assert interpreter["examples"][0]["outside_scope"] is True
    arguments = (lst(reference.load(story.program.code, 256,
                    {story.program.args[0]: 2}).mem), 0, 0, 500)
    traced = story.library.run("vn_interp", arguments, trace=True)

    def find_fetch(frame):
        if frame.name == "fetch":
            return frame
        return next((found for child in frame.children if (found := find_fetch(child)) is not None), None)

    fetch = find_fetch(traced.trace)
    assert fetch is not None
    scope = story.library.get("fetch").evidence.scope
    assert input_hash(fetch.inputs) not in scope["input_hashes"]
    assert fetch.inputs[0] == arguments[0]
    assert input_hash((lst((0,) * 16), 0)) in scope["input_hashes"]


def test_showcase_is_self_contained_and_examples_are_distinct(story, payload):
    assert declaration().to_dict() == payload["decl"]
    assert all(item["kinds_involved"] for item in payload["showcase"])
    assert all("all other cells are 0" in item["prompt"] for item in payload["showcase"])
    assert all(str(list(story.program.code)) in item["prompt"] and
               f"address {story.program.args[0]}" in item["prompt"]
               for item in payload["showcase"][:2])
    assert "(x0*(k-x0)) modulo 256" in payload["showcase"][2]["prompt"]
    assert all(item["examples"] for item in payload["story"])
    assert all("inputs" in item["examples"][0] and "outcome" in item["examples"][0]
               and type(item["examples"][0]["steps"]) is int for item in payload["story"])
    assert len({item["examples"][0]["text"] for item in payload["story"]}) == len(payload["story"])
    assert all(item["examples"][0].get("outside_scope", False) for item in payload["story"]
               if item["name"] in ("vn_interp", "target_fib", "validated",
                                   "fib_crosscheck", "fib_recurrence"))
    assert next(item for item in payload["story"] if item["name"] == "source_fib")[
        "examples"][0].get("outside_scope", False) is False
    assert next(item for item in payload["story"] if item["name"] == "lcompile")[
        "examples"][0]["outside_scope"]


def test_exported_declarations_round_trip_exact_bodies(story, payload):
    for row in payload["story"]:
        parsed = parse_meta_definition(row["ascii"])
        if row["kind"] == "template":
            continue
        body = bridge_defn(parsed.spec).body if parsed.kind == "bridge" else parsed.body
        assert body == nodes.from_json(row["body"]), row["name"]
        assert "see_json_body" not in row["ascii"]


def test_compiler_template_source_parses_on_current_core(payload):
    row = next(item for item in payload["story"] if item["name"] == "compiled")
    parsed = parse_meta_definition(row["ascii"])
    assert parsed.kind == "template"
    assert parsed.spec.pattern == row["source_pattern"]
    assert content_hash(parsed.spec.to_dict()) == row["source_spec_hash"]


def test_empty_list_example_has_unambiguous_ascii(payload):
    row = next(item for item in payload["story"] if item["name"] == "tail")
    example = row["examples"][0]
    assert example["ascii"].endswith(" = list.items<>")
    assert parse_meta_value(example["ascii"].rsplit(" = ", 1)[1]) == lst(())
    assert example["outcome"] == outcome_json(Ok(lst(())))


def test_exported_bridge_keeps_verified_domain(story, payload):
    row = next(item for item in payload["story"] if item["name"] == "compile")
    parsed = parse_meta_definition(row["ascii"])
    actual = story.bridge.get("compile").spec
    assert (parsed.spec.domain, parsed.spec.interface, parsed.spec.source, parsed.spec.target) == (
        actual.domain, actual.interface, actual.source, actual.target)
    candidate = story.constants["learner_source"]
    assert story.bridge.run("compile", (candidate,)).outcome == Bottom("outside_domain")
    assert kernel.evaluate(parsed.spec.domain, {"x": candidate}, story.bridge.scope()).outcome == Ok(False)


def test_exported_constants_keep_card_values(story, payload):
    for name, key in (("SourceCode", "source_code"), ("CompiledProgram", "compiled_program"),
                      ("LearnerSource", "learner_source"), ("LearnerProgram", "learner_program")):
        row = next(item for item in payload["story"] if item["name"] == name)
        actual = story.constants[key]
        assert parse_meta_definition(row["ascii"]).body == nodes.Lit(actual)
        assert parse_meta_value(row["examples"][0]["ascii"].split(" = ", 1)[1]) == actual


def test_closed_verified_claims_commit_to_the_empty_tuple(payload):
    for name in ("SourceCode", "CompiledProgram", "LearnerSource", "LearnerProgram",
                 "recorded_source", "compiled_member_0"):
        row = next(item for item in payload["story"] if item["name"] == name)
        assert row["status"] == ("verified" if name == "compiled_member_0" else "promoted")
        assert row["evidence"]["scope"]["size"] == 1
        assert row["evidence"]["scope"]["input_hashes"] == [input_hash(())]


def test_branch_example_replays_reserved_parameter(payload):
    branch = next(item for item in payload["story"] if item["name"] == "branch")
    assert branch["ascii"].startswith("op branch(arg0: list")
    assert branch["spec"]["input_names"][0] == "test"
    assert not any("semantic verification unavailable" in problem for problem in
                   export_problems(payload, "compiler", strict=True))
    changed = deepcopy(payload)
    example = next(item for item in changed["story"] if item["name"] == "branch")["examples"][0]
    example["ascii"] = example["ascii"].rsplit(" = ", 1)[0] + " = list<items: 0>"
    example["outcome"] = outcome_json(Ok(lst((0,))))
    assert any("ascii outcome differs from declaration evaluation" in problem for problem in
               export_problems(changed, "compiler", strict=True))


def test_exported_scope_flags_follow_recorded_inputs(payload):
    for name in ("target_fib", "fib_crosscheck", "fib_recurrence"):
        row = next(item for item in payload["story"] if item["name"] == name)
        sample = [value["v"] for value in row["examples"][0]["inputs"]]
        assert sample in row["evidence"]["scope"]["inputs"]
        assert row["examples"][0]["outside_scope"] is True


def test_declaration_and_committed_export(story, payload):
    decl = make_world().to_dict()
    assert json.loads(DECL_PATH.read_text()) == decl
    assert WorldDecl.from_dict(decl).to_dict() == decl
    assert next(obj for obj in story.library.world.objects if obj.name == "code") == code_world.code_object()
    assert story.library.world.operations[-3:] == code_world.operations()
    assert json.loads(EXPORT_PATH.read_text()) == payload
    assert export_problems(payload, "compiler", strict=True) == []
    assert {1, 2, 3, 4, 5} <= {entry["layer"] for entry in payload["story"]}
    assert {entry["kind"] for entry in payload["story"]} == {"object", "operation", "combinator", "law", "bridge", "template"}
    assert len([entry for entry in payload["story"] if entry["status"] == "promoted"]) >= 6
    assert all(isinstance(entry["definition"], str) and entry["definition"].endswith(".")
               for entry in payload["story"])
    assert payload["translation"]["bridge"] == "~compile: Code -> Prog"
    assert payload["translation"]["scope"]["size"] == 14


def test_scoped_law_rewrite_and_false_near_miss(story, payload):
    assert story.library.get("interp_agrees").evidence.scope["size"] == 14
    assert derivation_length(story.law_rewrite) == 1
    assert story.law_rewrite.charged_steps == story.library.run("target_fib", (0,)).steps
    with pytest.raises(RewriteError, match="verified scope"):
        replay_rewrite(n.Call("source_fib", (n.Lit(14),)),
                       n.Call("target_fib", (n.Lit(14),)),
                       "interp_agrees", story.library, {})
    assert story.fib_near_miss.status == "callable" and story.fib_near_miss.evidence is None
    with pytest.raises(PipelineError, match="law counterexample"):
        story.library.verify("fib_commutes", VerifyRequest("bounded", ((14,),),
                             {"domain": "integer input 14", "size": 1}))
    assert next(row for row in payload["story"] if row["name"] == "fib_commutes")["status"] == "callable"
    assert payload["law_near_miss"]["counterexamples"] == [
        {"input": 14, "source": outcome_json(Ok(377)), "target": outcome_json(Ok(121))},
        {"input": 15, "source": outcome_json(Ok(610)), "target": outcome_json(Ok(98))},
    ]
    assert story.bridge.get("Compiled").status == "verified"
    assert story.bridge.get("Compiled_member_0").status == "verified"
    assert story.bridge.run("Compiled_member_0", ()).outcome == story.bridge.run(
        "compile", (story.bridge_family[0],)).outcome


def test_bridge_given_interface_matches_kernel_and_machine(story):
    source_atoms = tuple(atom for atom in story.compiler.atoms if atom.name in ("add", "sub", "is_zero"))
    assert tuple(type(meta_code.decode(code).main.body) for code in story.bridge_family[:4]) == (
        n.Var, n.Call, n.Call, n.Let)
    assert tuple(meta_code.decode(code).main.body.fn for code in story.bridge_family[1:3]) == (
        "add", "sub")
    for code in story.bridge_family[:4]:
        decoded = meta_code.decode(code)
        source_scope = kernel.DictScope(source_atoms, (decoded.main, *decoded.deps))
        translated = story.bridge.run("compile", (code,))
        assert isinstance(translated.outcome, Ok)
        size, bytes_card, addresses_card, output = translated.outcome.value.fields
        assert (size, tuple(addresses_card.fields), output) == (64, (60, 61), "a")
        for left, right, source_name, target_name in (
                (0, 0, "source_at_00", "prog_at_00"),
                (1, 3, "source_at_13", "prog_at_13")):
            direct = kernel.call(decoded.main.name, (left, right), source_scope)
            expected = direct.outcome if not isinstance(direct.outcome, Ok) or 0 <= direct.outcome.value < 256 else Bottom("overflow")
            given = story.bridge.run(source_name, (code,))
            assert given.outcome == expected
            status, final, steps = reference.run(reference.load(bytes_card.fields, size,
                                                                 {60: left, 61: right}), 500)
            assert status == "ok"
            if code == story.bridge_family[0]:
                assert steps == 2
            target = story.bridge.run(target_name, (translated.outcome.value,))
            assert target.outcome == Ok(final.a) == expected
            assert (given.steps, target.steps) == (0, 0)


def test_extended_bridge_interface_is_exact(story):
    for source_code in story.bridge_family[:1]:
        mapped = story.bridge.run("compile", (source_code,)).outcome
        assert isinstance(mapped, Ok)
        for left in range(4):
            for right in range(4):
                suffix = f"{left}{right}"
                source = story.bridge.run(f"source_at_{suffix}", (source_code,)).outcome
                target = story.bridge.run(f"prog_at_{suffix}", (mapped.value,)).outcome
                assert source == target


def test_pair_provenance_and_no_compiler_wide_evidence(story):
    pair = story.validation.pair
    assert pair == (code_hash(story.constants["source_code"]),
                    translation.prog_hash(story.program))
    assert story.validation.routine_id == translation.routine_id(story.program)
    assert story.validation.accepted
    assert story.validation.scope["domain"] == tuple((value,) for value in range(14))
    assert story.ledger.pair_evidence(*pair, story.library.world.world_hash())[0].scope["size"] == 14
    assert story.ledger.record(story.ledger.resolve("compiled_program"),
                               story.library.world.world_hash()).produced_by == ("reference_tiny/1", pair[0])
    second = fib_source(2)
    compiled = compile_tiny(second, ("x0",), n=256)
    other_pair = (code_hash(translation.source_code(second, ("x0",))),
                  translation.routine_id(compiled))
    assert other_pair != pair and not story.ledger.pair_evidence(*other_pair,
                                                                  story.library.world.world_hash())
    assert "compile" not in story.library.definitions
    assert translation.validate(second, ("x0",), compiled, ((0,), (1,)), 500).accepted
    assert not story.ledger.pair_evidence(*other_pair, story.library.world.world_hash())


def test_three_way_exact_counts_and_unfolding(story):
    expected_fib = (0, 1, 1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 144, 233)
    for value, expected in enumerate(expected_fib):
        row = agreement(story, value)
        assert row["source"] == row["machine"] == row["interpreter"] == expected
        assert row["source_steps"] == 3 * value + 1
        assert row["machine_steps"] == row["run_prog_steps"] == 20 * value + 11
        assert row["interpreter_steps"] == 499 * value + 242
    loaded = reference.load(story.program.code, story.program.n, {story.program.args[0]: 10})
    traced = story.library.run("vn_interp", (lst(loaded.mem), 0, 0, 500), trace=True)
    assert traced.outcome.value.fields[0] == 55
    assert traced.trace.steps == traced.steps == 5232

    def leaf_steps(frame):
        return frame.steps if frame.given else sum(leaf_steps(child) for child in frame.children)

    assert leaf_steps(traced.trace) == 5232
    for name, arguments in (("fetch", (lst((0,) * 16), 0)),
                            ("exec_one", (lst((0,) * 16), 0, 0, 1)),
                            ("vn_interp", (lst((0,) * 16), 0, 0, 4)),
                            ("fib_crosscheck", (10,)), ("fib_recurrence", (8,))):
        actual = story.library.run(name, arguments)
        unfolded = kernel.evaluate(kernel.inline(n.Call(name, tuple(n.Lit(arg) for arg in arguments)),
                                                 story.library.scope()), scope=story.library.scope())
        assert (actual.outcome, actual.steps) == (unfolded.outcome, unfolded.steps)
    assert story.library.run("fib_crosscheck", (10,)).outcome == Ok(55)
    assert story.library.run("fib_recurrence", (8,)).outcome == Ok(55)


def test_metered_adapter(story):
    scope = machine_scope(story.library)
    assert story.library.get("run_prog").origin == "given"
    actual = meta_call("run_prog", (story.program.card, lst((10,)), 500), scope,
                       limits=kernel.Limits(fuel=211), trace=True)
    assert (actual.outcome.value.fields[0], actual.steps, actual.trace.steps) == (55, 211, 211)
    short = meta_call("run_prog", (story.program.card, lst((10,)), 500), scope,
                      limits=kernel.Limits(fuel=210))
    assert (short.outcome, short.steps) == (Unknown("fuel"), 210)
    assert meta_call("run_prog", (story.program.card, lst((10,)), 1), scope).outcome == Ok(
        Card("result", "out", ("fuel",)))
    assert meta_call("run_prog", (story.program.card, lst((256,)), 500), scope).outcome == Bottom("invalid")
    illegal = Card("prog", "prog", (16, lst((9, 0)), lst(), "a"))
    illegal_run = meta_call("run_prog", (illegal, lst(), 10), scope, trace=True)
    assert (illegal_run.outcome, illegal_run.steps, illegal_run.trace.steps) == (
        Ok(Card("result", "err", ("illegal",))), 1, 1)


def test_combinator_code_scope(story):
    assert story.library.get("validated").evidence.scope["op_family"] == ["source_fib", "target_fib"]
    assert story.library.run("validated", (kernel.FnRef("source_fib"),
                                           kernel.FnRef("target_fib"), 10)).outcome == Ok(55)
    scope = story.library.scope()
    quoted = quote_from_library(story.library, "validated")
    fn = Card("expr", "fn", ("list_len",))
    given = meta_call("eval", (quoted, lst((fn, fn, lst((4, 5))))), scope)
    assert (given.outcome, given.steps) == (Ok(2), 3)
    source_fn = Card("expr", "fn", ("source_fib",))
    target_fn = Card("expr", "fn", ("target_fib",))
    missing = meta_call("eval", (quoted, lst((source_fn, target_fn, 10))), scope)
    assert (missing.outcome, missing.steps) == (Bottom("ill_formed"), 0)
    assert len(quoted.fields[4].fields) == 1
    for name, arguments in (("fetch", (lst((0,) * 16), 0)),
                            ("exec_one", (lst((0,) * 16), 0, 0, 1)),
                            ("vn_interp", (lst((0,) * 16), 0, 0, 4)),
                            ("source_fib", (10,)), ("agrees", (2, 2)),
                            ("target_fib", (10,)), ("fib_crosscheck", (10,)),
                            ("fib_recurrence", (8,))):
        code = quote_from_library(story.library, name)
        result = meta_call("eval", (code, lst(arguments)), scope,
                           limits=kernel.Limits(fuel=200000))
        direct = story.library.run(name, arguments, fuel=200000)
        assert (result.outcome, result.steps) == (direct.outcome, direct.steps)
    for name, value in story.constants.items():
        constant = story.ledger.record(story.ledger.resolve(name),
                                       story.library.world.world_hash()).code
        result = meta_call("eval", (constant, lst()), scope)
        assert (result.outcome, result.steps) == (Ok(value), 0)
    fib = quote_from_library(story.library, "source_fib")
    metered = story.library.run("eval", (fib, lst((10,))), trace=True)
    assert (metered.outcome, metered.steps, metered.trace.steps) == (Ok(55), 31, 31)
    assert trace_json(metered.trace)["outcome"] == outcome_json(Ok(55))
    assert trace_json(metered.trace)["children"][0]["steps"] == 31
    reflected = story.library.run("run", (fib, lst((10,)), 31))
    assert (reflected.outcome, reflected.steps) == (Ok(Card("result", "ok", (55,))), 31)
    foreign = meta_call("eval", (story.constants["source_code"], lst((10,))), scope)
    assert (foreign.outcome, foreign.steps) == (Bottom("foreign_code"), 0)


def test_rejection_and_showcase(story, payload):
    counterexample = story.rejection.counterexample
    assert not story.rejection.accepted
    assert (counterexample.inputs, counterexample.source, counterexample.compiled,
            counterexample.source_steps, counterexample.compiled_steps,
            counterexample.reason) == ((0,), Ok(0), Ok(1), 3, 7,
                                        "is_zero on negative intermediate")
    rejected = compile_tiny(gap_source(), ("x0",), n=32)
    for value in range(16):
        status, state, _ = rejected.run((value,), 500)
        assert status == "ok" and 0 <= state.a <= 255
        verdict = translation.validate(gap_source(), ("x0",), rejected, ((value,),), 500)
        assert verdict.accepted == (value != 0)
    published = payload["showcase"]
    compute = published[0]["answer"]
    mismatches = published[1]["answer"]["mismatches"]
    literals = published[2]["answer"]
    assert compute == {"input": 10, "source": 55, "machine": 55, "interpreter": 55,
                       "source_steps": 31, "machine_steps": 211, "run_prog_steps": 211,
                       "interpreter_steps": 5232}
    assert mismatches == [14, 15]
    assert literals == list(range(15, 33))
    assert [item["answer"] for item in published] == [
        compute, {"agrees": False, "mismatches": [14, 15]}, literals]
    assert show_code(story.constants["source_code"]) in published[0]["prompt"]
    for item in published:
        assert item["prompt"].isascii() and "~compile" in item["prompt"]
    for value, output, steps in ((14, 121, 291), (15, 98, 311)):
        verdict = translation.validate(fib_source(), ("x0",), story.program, ((value,),), 500)
        assert (verdict.counterexample.source, verdict.counterexample.compiled,
                verdict.counterexample.compiled_steps) == (
                    Bottom("overflow"), Ok(output), steps)
    assert reference.run(reference.load(story.program.code, story.program.n,
                                        {story.program.args[0]: 10}), 500)[2] == 211
