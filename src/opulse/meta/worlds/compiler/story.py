"""A bounded interpreter/translation story (atoms-meta sections 3, 5, 7)."""

import hashlib
from copy import deepcopy
from dataclasses import dataclass, replace
from functools import lru_cache

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.bridges import bridge_defn
from opulse.atoms.laws import replay_rewrite
from opulse.atoms.library import Library, VerifyRequest, atoms_digest, checked_scope
from opulse.atoms.spec import (
    BridgeSpec,
    CombinatorSpec,
    Contract,
    Cost,
    Definition,
    Edge,
    Evidence,
    LawSpec,
    ObjectSpec,
    OperationSpec,
    TemplateSpec,
    content_hash,
)
from opulse.atoms.values import Bottom, Ok
from opulse.meta.cards import promote_output
from opulse.meta.code import code_hash, items, lst, quote_from_library
from opulse.meta.compiler import interp, learner
from opulse.meta.compiler import validate as translation
from opulse.meta.compiler.compile import Prog, compile_tiny
from opulse.meta.engine import call as meta_call
from opulse.meta.export_util import input_hash
from opulse.meta.generators import instantiate_family
from opulse.meta.identity import Ledger
from opulse.meta.vn import reference
from opulse.meta.worlds.compiler.world import machine_scope, make_library


def call(name, *args):
    return n.Call(name, args)


def fib_source(seed=1):
    """Iterative Fibonacci; the accumulator is an exact integer in tiny/1."""
    return n.Rec("fib", ("remaining", "a", "b"),
                 n.Case(((n.Test(call("is_zero", n.Var("remaining"))), n.Var("a")),),
                        call("fib", call("sub", n.Var("remaining"), n.Lit(1)),
                             n.Var("b"), call("add", n.Var("a"), n.Var("b")))),
                 (n.Var("x0"), n.Lit(0), n.Lit(seed)), "fuel")


def net_source(rate):
    """Pay a fixed rate per item and subtract a per-order discount."""
    return n.Rec("net", ("remaining", "balance"),
                 n.Case(((n.Test(call("is_zero", n.Var("remaining"))), n.Var("balance")),),
                        call("net", call("sub", n.Var("remaining"), n.Lit(1)),
                             call("add", n.Var("balance"),
                                  call("sub", n.Lit(rate), n.Var("x0"))))),
                 (n.Var("x0"), n.Lit(0)), "fuel")


def gap_source(k=255):
    """A negative intermediate can cross the integer/byte boundary."""
    return n.Case(((n.Test(call("is_zero", call("sub", call("sub", n.Var("x0"), n.Lit(k)),
                                                 n.Lit(1)))), n.Lit(1)),), n.Lit(0))


def _operation(name, params, body, layer):
    spec = OperationSpec(name, "transform", tuple(Edge("int") for _ in params), Edge("int"),
                         "Unfold into the declared kernel body", ("mismatch", "no_result"),
                         extra={"input_names": list(params)})
    return Definition(name, "operation", "invented", layer,
                      tuple(sorted(n.references(body))), spec, body)


def _record(library, definition, samples, reference, *, kind="operation"):
    library.write(definition)
    library.check(definition.name)
    callable_samples = (tuple(kernel.FnRef("source_fib") if param == "f" else
                              kernel.FnRef("target_fib") if param == "g" else row[0]
                              for param in definition.spec.params) for row in samples) if kind == "combinator" else samples
    library.make_callable(definition.name, tuple(callable_samples))
    scope = {"domain": f"bounded {definition.name}: explicit tuples {samples!r}",
             "inputs": samples, "size": len(samples)}
    extra = {"op_family": ["source_fib", "target_fib"]} if kind == "combinator" else {}
    if extra:
        scope["op_family"] = extra["op_family"]
    library.verify(definition.name, VerifyRequest("bounded", samples, scope,
                                                   reference=reference, extra=extra))
    library.account(definition.name)
    library.promote(definition.name, Contract("Exactly the kernel body on recorded tuples"))


class PairLedger(Ledger):
    """Keep translation records keyed by source, full program, and world hash."""

    def claim_equivalent(self, source_hash, program_hash, world_hash, evidence):
        if evidence.world_hash != world_hash:
            raise ValueError("pair evidence belongs to another world")
        key = (source_hash, program_hash, world_hash)
        if key in self._pairs:
            raise ValueError("pair evidence is immutable")
        self._pairs[key] = (deepcopy(evidence),)

    def pair_evidence(self, source_hash, program_hash, world_hash):
        return deepcopy(self._pairs.get((source_hash, program_hash, world_hash), ()))


@dataclass
class Story:
    library: object
    ledger: Ledger
    program: object
    validation: object
    rejection: object
    constants: dict
    compiler: object
    compiler_hash: str
    learner_validation: object
    helper_calls: dict
    bridge: object = None
    law_rewrite: object = None
    fib_near_miss: object = None
    bridge_family: tuple = ()


def _bridge(compiler, validation, helper_calls):
    """Check a recorded family with the core commuting bridge verifier (section 5)."""
    def fixed_evaluator(left, right, source):
        def evaluate(value):
            if source:
                return learner._source_at(value, left, right)
            return learner._prog_at(value, left, right)

        return evaluate

    interface = []
    extra_specs = []
    extra_atoms = []
    for left in range(4):
        for right in range(4):
            source_name, target_name = f"source_at_{left}{right}", f"prog_at_{left}{right}"
            interface.append((source_name, target_name))
            if (left, right) in ((0, 0), (1, 3)):
                continue
            for name, sort, source in ((source_name, "code", True),
                                       (target_name, "prog", False)):
                extra_specs.append(OperationSpec(name, "transform", (Edge(sort),), Edge("int"),
                                                 "Read the result channel at fixed byte inputs",
                                                 ("unsupported", "overflow"), cost=0))
                extra_atoms.append(kernel.Atom(name, 1, fixed_evaluator(left, right, source), cost=0))
    world = replace(compiler.world, world="compiler",
                    operations=compiler.world.operations + tuple(extra_specs))
    bridge_lib = Library(world, compiler.atoms + tuple(extra_atoms))
    for name in (*HELPERS, "lcompile"):
        definition = compiler.get(name)
        bridge_lib.write(replace(definition, status="written", evidence=None, contract=None))
        bridge_lib.check(name)
        sample = ((validation.accepted[next(iter(validation.accepted))][0],)
                  if name == "lcompile" else helper_calls[name]["sample"])
        bridge_lib.make_callable(name, (sample,))
    accepted_sources = tuple(source for source, _ in validation.accepted.values())
    def select(predicate):
        return next(source for source in accepted_sources if predicate(translation.C.decode(source).main.body))

    representatives = (select(lambda body: isinstance(body, n.Var)),
                       select(lambda body: isinstance(body, n.Call) and body.fn == "add"),
                       select(lambda body: isinstance(body, n.Call) and body.fn == "sub"),
                       select(lambda body: isinstance(body, n.Let)))
    sources = representatives + tuple(source for source in accepted_sources
                                      if source not in representatives)[:12]
    predicate = n.Case(tuple((n.Test(call("str_eq", call("code_hash", n.Var("x")),
                                            n.Lit(code_hash(source)))), n.Lit(True))
                             for source in sources), n.Lit(False))
    spec = BridgeSpec("compile", "compiler@1:code", "compiler@1:prog",
                      call("pack_prog", call("lcompile", n.Var("x"))), predicate,
                      tuple(interface))
    definition = Definition("compile", "bridge", "invented", compiler.get("lcompile").layer + 1,
                            tuple(sorted(n.references(bridge_defn(spec).body))), spec, bridge_defn(spec).body)
    bridge_lib.write(definition)
    bridge_lib.check("compile")
    bridge_lib.make_callable("compile", ((sources[0],),))
    bridge_lib.verify("compile", VerifyRequest("bounded", tuple((source,) for source in sources),
                     {"domain": "16 accepted tiny/1 codes; x0,x1 each in 0..3",
                      "size": len(sources), "source_hashes": [code_hash(source) for source in sources],
                      "input_pairs": [[left, right] for left in range(4) for right in range(4)]},
                     extra={"fuel": 500}))
    bridge_lib.account("compile")
    bridge_lib.promote("compile", Contract("16 accepted codes, x0,x1 each in 0..3 only"))
    source_spec = OperationSpec("recorded_source", "transform", (), Edge("code"),
                                "Return the first accepted tiny source code")
    bridge_lib.write(Definition("recorded_source", "operation", "invented", 1, (),
                                source_spec, n.Lit(sources[0])))
    bridge_lib.check("recorded_source")
    bridge_lib.make_callable("recorded_source", ((),))
    bridge_lib.verify("recorded_source", VerifyRequest("bounded", ((),),
                      {"domain": "one closed source code", "size": 1,
                       "input_hashes": [input_hash(())]},
                      reference=lambda: sources[0]))
    bridge_lib.account("recorded_source")
    bridge_lib.promote("recorded_source", Contract("The first accepted family member only"))
    pattern = {"role": "transform", "inputs": [], "output": {"sort": "prog"},
               "rule": "compile the recorded source operation", "input_names": [],
               "definition_body": n.to_json(call("pack_prog", call("lcompile", call("$src"))))}
    template = Definition("Compiled", "template", "invented", 1, (),
                          TemplateSpec("Compiled", (("src", "operation"),), "operation", pattern,
                                       {"family": [{"src": "recorded_source"}]}), n.Lit(0))
    bridge_lib.write(template)
    bridge_lib.check("Compiled")
    bridge_lib.make_callable("Compiled", ((),))
    expected = bridge_lib.run("compile", (sources[0],)).outcome.value
    members = instantiate_family(bridge_lib, "Compiled", ({"src": "recorded_source"},),
                                 lambda _index, _args, _member: VerifyRequest(
                                     "bounded", ((),), {"domain": "one recorded source", "size": 1,
                                                         "input_hashes": [input_hash(())]},
                                     reference=lambda: expected))
    bridge_lib.account(members[0].name)
    bridge_lib.account("Compiled")
    return bridge_lib, sources


HELPERS = ("emit", "tail", "lookup", "branch", "compile_expr")


def _verify_helper(library, name, domain, scope, reference=None, cached_runs=None,
                   reference_scope=None):
    """Verify each family call with a single pre-unfolded kernel body (section 9.I1)."""
    definition = library.get(name)
    params = library._params(definition)
    execution_scope = library.scope()
    if reference_scope is not None and (execution_scope.atoms != reference_scope.atoms
                                        or any(definition != reference_scope.defns.get(member)
                                               for member, definition in execution_scope.defns.items())):
        raise AssertionError(f"helper {name} differs from the reference kernel scope")
    unfolded = kernel.inline(n.Call(name, tuple(n.Var(param) for param in params)),
                             execution_scope)
    steps = []
    for args in domain:
        actual = (cached_runs.get(args[0]) if cached_runs is not None else None)
        if actual is None:
            actual = kernel.call(name, args, execution_scope, dialect=library.dialect)
        expected = actual.outcome if reference_scope is not None else reference(*args)
        if not isinstance(expected, (Ok, Bottom)):
            expected = Ok(expected)
        expanded = kernel.evaluate(unfolded, dict(zip(params, args)), scope=execution_scope)
        if (actual.outcome != expected or actual.outcome != expanded.outcome
                or actual.steps != expanded.steps):
            raise AssertionError(f"helper {name} disagrees with its reference or unfolding at {args!r}")
        steps.append(actual.steps)
    evidence = Evidence("bounded", {**deepcopy(scope), "checked": checked_scope(domain)},
                        checks=("reference", "unfold_equivalence"),
                        world_hash=library.world.world_hash(), deps_hash=library._deps_hash(name),
                        content_hash=library.content_hash(name), atoms_hash=atoms_digest(library.atoms))
    library.record_evidence(name, evidence)
    library._steps[name] = steps


def _family_compiler():
    """Capture actual helper arguments while validating section 5's family."""
    seed = learner.build_library()
    recorded = {name: {} for name in HELPERS}
    counts = dict.fromkeys(HELPERS, 0)
    plain_scope = seed.scope
    base = plain_scope()
    capture_atoms = []
    wrappers = []
    for name in HELPERS:
        original = base.defns[name]

        def capture(*args, member=name):
            counts[member] += 1
            recorded[member].setdefault(args, None)
            return 0

        capture_atoms.append(kernel.Atom(f"capture_{name}", len(original.params), capture, cost=0))
        wrappers.append(replace(original, body=n.Let("_capture",
                         n.Call(f"capture_{name}", tuple(n.Var(param) for param in original.params)),
                         original.body)))
    captured_scope = kernel.DictScope((*seed.atoms, *capture_atoms),
                                      (*base.defns.values(), *wrappers))
    seed.scope = lambda: captured_scope
    try:
        validation = learner.validate_family(seed)
    finally:
        del seed.scope

    compiler = Library(seed.world, seed.atoms)
    for name in (*HELPERS, "lcompile"):
        definition = replace(seed.get(name), status="written", evidence=None, cost=None, contract=None)
        compiler.write(definition)
        compiler.check(name)
        samples = tuple(recorded[name]) if name in recorded else ((validation.accepted[next(iter(validation.accepted))][0],),)
        compiler.make_callable(name, samples[:1])
        if name == "lcompile":
            continue
        observed = recorded[name]
        if not observed:
            raise AssertionError(f"helper {name} was not called")
        rows = tuple(observed)
        fingerprint = hashlib.sha256("\n".join(map(repr, rows)).encode("utf-8")).hexdigest()
        scope = {"domain": f"actual helper calls in the {validation.family_size}-program family",
                 "fingerprint": fingerprint, "size": len(rows), "calls": counts[name],
                 "family_size": validation.family_size}
        _verify_helper(compiler, name, rows, scope, reference_scope=base)
        compiler.account(name)
        compiler.promote(name, Contract("Kernel expansion on recorded family call arguments"))
    return compiler, validation, {name: {"calls": counts[name], "size": len(recorded[name]),
                                        "sample": next(iter(recorded[name]))}
                                  for name in HELPERS}


@lru_cache(maxsize=1)
def build_story():
    """Promote definitions only after exact bounded evidence has been checked."""
    library = make_library()
    body = fib_source()
    program = compile_tiny(body, ("x0",), n=256)
    interpreter_domain = ((lst((0,) * 16), 0, 0, 4),
                          (lst((1, 7, 0, 0) + (0,) * 12), 0, 0, 4)) + tuple(
        (lst(reference.load(program.code, program.n, {program.args[0]: value}).mem), 0, 0, 500)
        for value in range(14))
    interp.verify_library(library, interpreter_domain,
                          {"description": "n=16 HALT and LDI 7; n=256 reference fib, x0=0..13",
                           "programs": [list(items(row[0])) for row in interpreter_domain],
                           "arguments": [list(row[1:]) for row in interpreter_domain]})
    rows = tuple((value,) for value in range(14))
    validation = translation.validate(body, ("x0",), program, rows, 500)
    if not validation.accepted:
        raise ValueError(f"reference compilation failed: {validation.counterexample}")

    _record(library, _operation("source_fib", ("x0",), body, 1), rows,
            lambda value: (0, 1, 1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 144, 233)[value])
    _record(library, _operation("agrees", ("left", "right"),
                               n.Case(((n.Test(call("eq", n.Var("left"), n.Var("right"))),
                                        n.Var("left")),), call("fail_mismatch")), 1),
            tuple((value, value) for value in (0, 1, 2, 3, 5, 8, 13, 21, 34, 55)) + ((1, 2),),
            lambda left, right: left if left == right else Bottom("mismatch"))

    comb_body = call("agrees", call("f", n.Var("x")), call("g", n.Var("x")))
    comb_spec = CombinatorSpec("validated", ("f", "g", "x"), ("f", "g"), comb_body,
                               "substitute")
    combinator = Definition("validated", "combinator", "invented", 2, ("agrees",),
                            comb_spec, comb_body)

    memory = lst(program.code + (0,) * (program.n - len(program.code)))
    target = call("result_a", call("vn_interp",
               call("list_set", n.Lit(memory), n.Lit(program.args[0]), n.Var("x0")),
               n.Lit(0), n.Lit(0), n.Lit(500)))
    _record(library, _operation("target_fib", ("x0",), target, 3),
            rows, lambda value: (0, 1, 1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 144, 233)[value])
    _record(library, combinator, ((0,), (10,)), None, kind="combinator")
    crosscheck = call("agrees", call("source_fib", n.Var("x0")),
                      call("target_fib", n.Var("x0")))
    _record(library, _operation("fib_crosscheck", ("x0",), crosscheck, 4),
            tuple((value,) for value in range(11)),
            lambda value: (0, 1, 1, 2, 3, 5, 8, 13, 21, 34, 55)[value])
    recurrence = call("agrees", call("fib_crosscheck", call("add", n.Var("x0"), n.Lit(2))),
                      call("add", call("fib_crosscheck", n.Var("x0")),
                           call("fib_crosscheck", call("add", n.Var("x0"), n.Lit(1)))))
    _record(library, _operation("fib_recurrence", ("x0",), recurrence, 5),
            ((0,), (8,)), lambda value: 1 if value == 0 else 55)

    source_card = translation.source_code(body, ("x0",))
    compiler, family_validation, helper_calls = _family_compiler()
    learner_body = n.Case(((n.Test(call("is_zero", n.Var("x0"))), n.Var("x1")),),
                          call("add", n.Var("x0"), n.Var("x1")))
    learner_source = translation.source_code(learner_body, ("x0", "x1"))
    compiled = learner.compile_code(compiler, learner_source)
    if not isinstance(compiled.outcome, Ok):
        raise TypeError("invented compiler rejected the case source")
    learner_program = Prog(64, items(compiled.outcome.value), (60, 61), params=("x0", "x1"))
    learner_rows = tuple((value, 3) for value in range(16))
    learner_validation = translation.validate(learner_body, ("x0", "x1"),
                                               learner_program, learner_rows, 500)
    if not learner_validation.accepted or learner_validation.source_hash != code_hash(learner_source):
        raise ValueError(f"invented compilation failed: {learner_validation.counterexample}")
    compiler_hash = code_hash(quote_from_library(compiler, "lcompile"))
    constants = {"source_code": source_card, "compiled_program": program.card,
                 "learner_source": learner_source, "learner_program": learner_program.card}
    compiler_code = quote_from_library(compiler, "lcompile")
    accepted = tuple((source,) for source, _ in family_validation.accepted.values())
    if (family_validation.world_hash != compiler.world.world_hash()
            or family_validation.definition_hash != content_hash(
                replace(compiler.get("lcompile"), cost=Cost()).to_dict())):
        raise ValueError("compiler cache no longer matches its world or definition")
    _verify_helper(compiler, "lcompile", accepted, family_validation.scope,
                   lambda source: family_validation.accepted[code_hash(source)][1],
                   cached_runs=family_validation.kernel_runs)
    compiler.account("lcompile")
    compiler.promote("lcompile", Contract(
        "Translation-validated only on accepted hashes and x0,x1 in 0..15"))
    bridge, bridge_family = _bridge(compiler, family_validation, helper_calls)
    statement = call("eq", call("source_fib", n.Var("value")),
                     call("target_fib", n.Var("value")))
    law_spec = LawSpec("interp_agrees", (("value", "int"),), statement)
    law = Definition("interp_agrees", "law", "invented", 4,
                     tuple(sorted(n.references(statement))), law_spec, statement)
    library.write(law)
    library.check("interp_agrees")
    library.make_callable("interp_agrees", ((0,),))
    library.verify("interp_agrees", VerifyRequest("bounded", rows,
                   {"domain": "compiled Fibonacci source and invented interpreter, x0=0..13",
                    "size": len(rows)}))
    library.account("interp_agrees")
    library.promote("interp_agrees", Contract("Fibonacci result channel on x0=0..13 only"))
    original = call("source_fib", n.Lit(0))
    rewrite = replay_rewrite(original, call("target_fib", n.Lit(0)), "interp_agrees", library, {})
    near_statement = call("eq", call("source_fib", n.Var("value")),
                          call("target_fib", n.Var("value")))
    near_spec = LawSpec("fib_commutes", (("value", "int"),), near_statement)
    near_miss = Definition("fib_commutes", "law", "invented", 4,
                           tuple(sorted(n.references(near_statement))), near_spec, near_statement)
    library.write(near_miss)
    library.check("fib_commutes")
    library.make_callable("fib_commutes", ((0,),))
    near_miss = library.get("fib_commutes")
    ledger = PairLedger.from_library(library)
    ledger.add(compiler_code, compiler.world.world_hash(), "lcompile")
    # The library's deps hash commits to library records; the ledger binds the evidence to the code's own
    # dependency commitment (atoms-meta 3.3).
    ledger.attach_evidence(compiler_hash, compiler.world.world_hash(),
                           replace(compiler.get("lcompile").evidence, deps_hash=""))
    ledger.promote(compiler_hash, compiler.world.world_hash(), compiler.get("lcompile").contract)
    for name, value in constants.items():
        definition = Definition(name, "object", "invented", 1, (),
                                ObjectSpec(name, "constant", body=n.Lit(value)), n.Lit(value))
        assert not definition.validate()
        quoted = translation.C.quote(definition, lambda _: None, {})
        provenance = ((compiler_hash, code_hash(learner_source)) if name == "learner_program"
                      else ("reference_tiny/1", code_hash(source_card)) if name == "compiled_program" else ())
        digest = ledger.add(quoted, library.world.world_hash(), name, produced_by=provenance)
        actual = kernel.evaluate(definition.body)
        assert actual.outcome == Ok(value) and actual.steps == 0
        evidence = Evidence("bounded", {"domain": "bounded closed literal, one empty input tuple",
                                         "size": 1, "input_hashes": [input_hash(())]},
                            checks=("literal", "unfold_equivalence"),
                            world_hash=library.world.world_hash(), content_hash=digest,
                            atoms_hash=atoms_digest(library.atoms))
        ledger.attach_evidence(digest, library.world.world_hash(), evidence)
        promote_output(ledger, digest, library.world.world_hash(), library.atoms,
                       Contract("Immutable named constant"))

    pair_evidence = Evidence("bounded", {"domain": [list(row) for row in rows],
                                         "size": len(rows), "fuel": 500},
                             checks=("translation_validation", "result_channel"),
                             world_hash=library.world.world_hash())
    if validation.pair[0] != code_hash(source_card):
        raise ValueError("translation validation used a different source")
    ledger.claim_equivalent(*validation.pair, library.world.world_hash(), pair_evidence)
    learner_evidence = Evidence("bounded", {"domain": [list(row) for row in learner_rows],
                                            "size": len(learner_rows), "fuel": 500},
                                checks=("translation_validation", "result_channel"),
                                world_hash=library.world.world_hash())
    ledger.claim_equivalent(*learner_validation.pair, library.world.world_hash(), learner_evidence)

    rejected_body = gap_source()
    rejected_program = compile_tiny(rejected_body, ("x0",), n=32)
    rejection = translation.validate(rejected_body, ("x0",), rejected_program,
                                      ((value,) for value in range(16)), 500)
    if rejection.accepted:
        raise ValueError("the negative-intermediate counterexample was not detected")
    return Story(library, ledger, program, validation, rejection, constants,
                 compiler, compiler_hash, learner_validation, helper_calls,
                 bridge, rewrite, near_miss, bridge_family)


def agreement(story, value):
    """Three independent channels, with both step counts retained."""
    program = story.program
    machine_status, machine_state, machine_steps = program.run((value,), 500)
    metered = meta_call("run_prog", (program.card, lst((value,)), 500),
                        machine_scope(story.library), limits=kernel.Limits(fuel=500))
    interpreter = story.library.run("vn_interp", (
        lst(reference.load(program.code, program.n, {program.args[0]: value}).mem),
        0, 0, 500), trace=True)
    source_run = story.library.run("source_fib", (value,), trace=True)
    if (machine_status != "ok" or metered.outcome != Ok(interpreter.outcome.value)
            or metered.steps != machine_steps or source_run.outcome.value != machine_state.a):
        raise ValueError(f"three-way mismatch at x0={value}")
    return {"input": value, "source": source_run.outcome.value,
            "machine": machine_state.a if machine_status == "ok" else machine_status,
            "interpreter": interpreter.outcome.value.fields[0],
            "source_steps": source_run.steps, "machine_steps": machine_steps,
            "run_prog_steps": metered.steps,
            "interpreter_steps": interpreter.steps}
