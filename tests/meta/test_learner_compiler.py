"""Executable translation claims for the invented compiler (atoms-meta section 5)."""

import hashlib
import json
import random

import pytest

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.library import VerifyRequest, checked_scope
from opulse.atoms.spec import content_hash
from opulse.atoms.values import Bottom, Ok, boolean
from opulse.meta import code as C
from opulse.meta.compiler import learner
from opulse.meta.vn import reference, report


def source(body, params=("x0", "x1")):
    return C.make_code("operation", C.sig_op([("int", "bottom")] * len(params), ("int", "bottom")),
                       params, body, learner.source_atom)


@pytest.fixture(scope="module")
def library():
    return learner.build_library()


@pytest.fixture(scope="module")
def family():
    return learner.source_family()


def test_fast_source_matches_kernel_on_entire_family(family):
    atoms = (kernel.Atom("add", 2, lambda left, right: left + right),
             kernel.Atom("sub", 2, lambda left, right: left - right),
             kernel.Atom("is_zero", 1, lambda value: boolean(value == 0)))
    checks = 0
    for source_code in family:
        decoded = C.decode(source_code).main
        scope = kernel.DictScope(atoms, (decoded,))
        grid = learner._source_grid(decoded.body)
        for left in range(4):
            for right in range(4):
                result = kernel.call(decoded.name, (left, right), scope)
                assert result.outcome == Ok(grid[left * 16 + right])
                checks += 1
    assert checks == 73_888


def test_fast_source_matches_kernel_on_seeded_sample(family):
    atoms = (kernel.Atom("add", 2, lambda left, right: left + right),
             kernel.Atom("sub", 2, lambda left, right: left - right),
             kernel.Atom("is_zero", 1, lambda value: boolean(value == 0)))
    randomizer = random.Random(137)
    for source_code in (*randomizer.sample(family, 160), family[-1], family[-2]):
        decoded = C.decode(source_code).main
        scope = kernel.DictScope(atoms, (decoded,))
        grid = learner._source_grid(decoded.body)
        for _ in range(10):
            left, right = randomizer.randrange(16), randomizer.randrange(16)
            result = kernel.call(decoded.name, (left, right), scope)
            assert result.outcome == Ok(learner.source_value(decoded.body, left, right)) == Ok(grid[left * 16 + right])
        if source_code == family[-1]:
            assert kernel.call(decoded.name, (0, 1), scope).outcome == Ok(grid[1]) == Ok(9)


def test_cached_compiler_verification_matches_kernel_verifier(family):
    randomizer = random.Random(241)
    sample = randomizer.sample(family, 24)
    baseline = learner.build_library()
    optimized = learner.build_library()
    scope = baseline.scope()
    runs = {source_code: kernel.call("lcompile", (source_code,), scope) for source_code in sample}
    expected = {C.code_hash(source_code): run.outcome.value for source_code, run in runs.items()}
    domain = tuple((source_code,) for source_code in sample)
    evidence_scope = {"domain": "seeded family sample of 24 programs", "size": len(sample)}
    reference_output = lambda source_code: expected[C.code_hash(source_code)]
    standard = super(learner.LearnerLibrary, baseline).verify(
        "lcompile", VerifyRequest("bounded", domain, evidence_scope, reference=reference_output))
    cached = optimized.verify("lcompile", VerifyRequest(
        "bounded", domain, evidence_scope, reference=reference_output,
        extra={"kernel_runs": runs, "deps_hash": optimized.deps_hash("lcompile"),
               "world_hash": optimized.world.world_hash(),
               "definition_hash": content_hash(optimized.get("lcompile").to_dict())}))
    assert cached.evidence == standard.evidence
    assert cached.status == standard.status == "verified"
    assert optimized._steps["lcompile"] == baseline._steps["lcompile"]


def test_fast_machine_matches_reference_on_seeded_sample(library, family):
    randomizer = random.Random(137)
    for source_code in randomizer.sample(family, 120):
        compilation = learner.compile_code(library, source_code)
        assert isinstance(compilation.outcome, Ok)
        program = C.items(compilation.outcome.value)
        for _ in range(10):
            left, right = randomizer.randrange(16), randomizer.randrange(16)
            status, state, steps = reference.run(reference.load(program, 64, {60: left, 61: right}), 500)
            assert learner.run_batch_program(program, left, right) == (
                status, state.a if state is not None else None, steps)


def test_four_exact_programs(library):
    programs = (
        (n.Var("x0"), (2, 60, 0, 0)),  # LD x0; HALT
        (n.Lit(7), (1, 7, 0, 0)),  # LDI 7; HALT
        (n.Call("add", (n.Var("x0"), n.Var("x1"))),
         (2, 60, 3, 48, 2, 61, 4, 48, 0, 0)),  # LD x0; ST tmp; LD x1; ADD tmp; HALT
        (n.Call("sub", (n.Var("x0"), n.Var("x1"))),
         (2, 60, 3, 48, 2, 61, 3, 49, 2, 48, 5, 49, 0, 0)),
        # LD x0; ST tmp; LD x1; ST tmp+1; LD tmp; SUB tmp+1; HALT
    )
    for (body, expected), expected_steps in zip(programs, (47, 48, 92, 105)):
        result = library.run("lcompile", (source(body),), trace=True)
        assert result.outcome == Ok(C.lst(expected))
        assert result.steps == expected_steps
        assert result.trace.children[0].steps == expected_steps
        assert reference.run(reference.load(expected, 64, {60: 3, 61: 2}), 500)[0] == "ok"


def test_case_arms_and_let_nesting(library):
    program = source(n.Let("temporary", n.Var("x0"),
                           n.Case(((n.Test(n.Call("is_zero", (n.Var("temporary"),))), n.Lit(7)),
                                   (n.Test(n.Call("is_zero", (n.Var("x1"),))), n.Lit(8))), n.Lit(9))))
    result = learner.compile_code(library, program)
    assert isinstance(result.outcome, Ok)
    for left, right, expected in ((0, 0, 7), (0, 2, 7), (2, 0, 8), (2, 2, 9)):
        status, state, _ = reference.run(reference.load(C.items(result.outcome.value), 64,
                                                       {60: left, 61: right}), 500)
        assert status == "ok" and state.a == expected

    nested = n.Var("last")
    for index in reversed(range(6)):
        nested = n.Let("last" if index == 5 else f"temporary{index}", n.Var("x0"), nested)
    compiled = learner.compile_code(library, source(nested)).outcome
    assert isinstance(compiled, Ok)
    assert reference.run(reference.load(C.items(compiled.value), 64, {60: 4, 61: 0}), 500)[1].a == 4
    seven = n.Let("extra", n.Var("x0"), nested)
    assert learner.compile_code(library, source(seven)).outcome == Bottom("unsupported")


def test_alpha_identity_and_unsupported(library):
    assert learner.compile_code(library, source(n.Var("x0"), ("x0",))).outcome == Ok(C.lst((2, 60, 0, 0)))
    left = source(n.Let("foo", n.Var("x0"), n.Call("add", (n.Var("foo"), n.Lit(3)))))
    right = source(n.Let("bar", n.Var("x0"), n.Call("add", (n.Var("bar"), n.Lit(3)))))
    assert left == right and C.code_hash(left) == C.code_hash(right)
    first = learner.compile_code(library, left).outcome
    second = learner.compile_code(library, right).outcome
    assert first == second and isinstance(first, Ok)
    payload = [0, list(C.items(first.value))]
    expected = hashlib.sha256(("opulse.vn/1\n64\n" + json.dumps(
        payload, separators=(",", ":"))).encode("ascii")).hexdigest()
    assert learner.routine_identity(first.value) == expected
    assert learner.routine_identity(first.value) == report.routine_id(64, 0, C.items(first.value))
    unsupported = library.run("lcompile", (source(n.Call("is_zero", (n.Var("x0"),))),), trace=True)
    assert unsupported.outcome == Bottom("unsupported") and unsupported.steps == 41

    def leaves(trace):
        return [trace] if not trace.children else [leaf for child in trace.children for leaf in leaves(child)]

    assert any(leaf.name == "unsupported" and leaf.steps == 0 and leaf.outcome == Bottom("unsupported")
               for leaf in leaves(unsupported.trace))
    assert learner.compile_code(library, source(n.Rec("loop", ("v",), n.Var("v"),
                                                        (n.Var("x0"),), "fuel"))).outcome == Bottom("unsupported")
    assert learner.compile_code(library, source(n.Lit(256))).outcome == Bottom("unsupported")


@pytest.fixture(scope="module")
def validated(library, family):
    return learner.validate_family(library, family)


def test_family_counts_and_bounded_promotion(library, validated):
    assert validated.family_size == 4618
    assert len(validated.accepted) == 3325
    assert len(validated.rejected) == 1293
    assert validated.reasons == {"overflow": 211360, "negative_zero": 15}
    assert sum(map(len, validated.rejected.values())) == 211375
    assert validated.scope["inputs_per_program"] == 256
    assert validated.compiler_steps == 644167
    compiler = learner.promote_validated(library, validated)
    assert compiler.status == "promoted"
    assert compiler.evidence.method == "bounded"
    expected_scope = {**validated.scope, "checked": {**checked_scope(
        tuple((source,) for source, _ in validated.accepted.values())), "by": "library"}}
    assert compiler.evidence.scope == expected_scope
    assert validated.scope["pairs"] == [
        [digest, hashlib.sha256(("opulse.vn/1\n64\n" + json.dumps(
            [0, list(C.items(program))], separators=(",", ":"))).encode("ascii")).hexdigest()]
        for digest, (_, program) in sorted(validated.accepted.items())
    ]
    assert compiler.cost.steps["over"] == expected_scope
    assert all(library.get(name).status == "promoted" and library.get(name).evidence.method == "bounded"
               for name in ("emit", "tail", "lookup", "branch", "compile_expr", "lcompile"))
    assert all(isinstance(definition.body, n.NODE_TYPES)
               for definition in library.definitions.values() if definition.origin == "invented")
    assert library.get("lcompile").layer == 4


def test_real_overflow_is_rejected(validated):
    program = source(n.Call("sub", (n.Var("x0"), n.Var("x1"))))
    failures = validated.rejected[C.code_hash(program)]
    assert (0, 1, "overflow") in failures
    assert len(failures) == 120  # pairs x0 < x1 in the 16 x 16 square
    assert C.code_hash(program) not in validated.accepted


def test_negative_intermediate_zero_image_is_rejected(library, validated):
    program = learner.source_family()[-1]
    assert (0, 1, "negative_zero") in validated.rejected[C.code_hash(program)]
    assert validated.reasons["negative_zero"] == 15
    decoded = C.decode(program).main
    source_scope = kernel.DictScope((kernel.Atom("add", 2, lambda left, right: left + right),
                                     kernel.Atom("sub", 2, lambda left, right: left - right),
                                     kernel.Atom("is_zero", 1, lambda value: boolean(value == 0))), (decoded,))
    source_run = kernel.call(decoded.name, (0, 1), source_scope)
    compiled = learner.compile_code(library, program)
    machine_status, machine_state, machine_steps = reference.run(
        reference.load(C.items(compiled.outcome.value), 64, {60: 0, 61: 1}), 500)
    assert source_run.outcome == Ok(9) and source_run.steps == 3
    assert machine_status == "ok" and machine_state.a == 7 and machine_steps == 14
