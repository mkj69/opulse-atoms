"""Invented code transformers and bounded semantic ledger (atoms-meta section 7)."""

from itertools import product

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.combinators import check_combinator
from opulse.atoms.laws import replay_rewrite
from opulse.atoms.library import (
    PipelineError,
    VerifyRequest,
    VerifyResult,
    atoms_digest,
    register_kind,
)
from opulse.atoms.spec import (
    BridgeSpec,
    CombinatorSpec,
    Contract,
    Definition,
    Edge,
    Evidence,
    LawSpec,
    ObjectSpec,
    OperationSpec,
    TemplateSpec,
    content_hash,
)
from opulse.atoms.templates import instantiate
from opulse.atoms.values import (
    Bottom,
    Card,
    Ok,
    Unknown,
    boolean,
    encode,
    outcome_equal,
)
from opulse.meta import cards, code, engine
from opulse.meta.generators import instantiate_family, run_generator
from opulse.meta.identity import Ledger

from .world import library


def call(name, *args):
    return n.Call(name, args)


def var(name):
    return n.Var(name)


def lit(value):
    return n.Lit(value)


EMPTY = lit(code.lst())


def card(tag, *fields):
    values = EMPTY
    for item in reversed(fields):
        values = call("list_cons", item, values)
    return call("mk", lit("expr"), lit(tag), values)


def test(name, *args):
    return n.Test(call(name, *args))


def both(*conditions):
    result = conditions[0]
    for condition in conditions[1:]:
        result = n.And(result, condition)
    return result


def tag_is(value, tag):
    return test("str_eq", call("tag_of", value), lit(tag))


def element(value, index):
    return call("field", value, lit(index))


def binary(fn, left, right):
    return card("call", lit(fn), call("list_cons", left, call("list_cons", right, EMPTY)))


def _rec(name, body, *args, memo=False):
    return n.Rec(name, ("expr",), body, args, call("size", var("expr")), memo=memo)


def _map_args(args, visitor="visit"):
    index = var("index")
    body = n.Case(((test("eq", index, call("list_len", args)), EMPTY),),
                  call("list_cons", call(visitor, call("list_get", args, index)),
                       call("map_args", call("add", index, lit(1)))))
    return n.Rec("map_args", ("index",), body, (lit(0),),
                 call("sub", call("list_len", args), index))


def _has_div():
    expr = var("expr")
    args = element(expr, 1)
    index = var("index")
    scan = n.Rec("scan", ("index",),
                 n.Case(((test("eq", index, call("list_len", args)), lit(boolean(False))),
                         (test("visit", call("list_get", args, index)), lit(boolean(True)))),
                        call("scan", call("add", index, lit(1)))), (lit(0),),
                 call("sub", call("list_len", args), index))
    return _rec("visit", n.Case(((tag_is(expr, "call"),
                                   n.Case(((test("str_eq", element(expr, 0), lit("div")), lit(boolean(True))),), scan)),
                                  (tag_is(expr, "case"), lit(boolean(True))),
                                  (tag_is(expr, "let"),
                                   n.Case(((test("visit", element(expr, 1)), lit(boolean(True))),),
                                          call("visit", element(expr, 2))))), lit(boolean(False))), var("e"))


def _fold_expr(mode):
    expr = var("expr")
    fn = element(expr, 0)
    args = element(expr, 1)
    left = var("left")
    right = var("right")
    original = call("with_field", expr, lit(1),
                    call("list_cons", left, call("list_cons", right, EMPTY)))
    left_value = element(left, 0)
    right_value = element(right, 0)
    if mode == "unsafe":
        simplify = (test("str_eq", fn, lit("sub")), test("eq", left, right))
    else:
        simplify = (test("str_eq", fn, lit("sub")), test("eq", left, right),
                    n.Not(test("has_div", left)))
    folded = n.Case((
        (both(*simplify), card("lit", lit(0))),
        (both(test("str_eq", fn, lit("mul")),
              n.Or(test("eq", left, card("lit", lit(0))), test("eq", right, card("lit", lit(0)))),
              *(() if mode == "unsafe" else (n.Not(test("has_div", left)), n.Not(test("has_div", right))))),
         card("lit", lit(0))),
        (both(tag_is(left, "lit"), tag_is(right, "lit"), test("str_eq", fn, lit("add"))),
         card("lit", call("add", left_value, right_value))),
        (both(tag_is(left, "lit"), tag_is(right, "lit"), test("str_eq", fn, lit("sub"))),
         card("lit", call("sub", left_value, right_value))),
        (both(tag_is(left, "lit"), tag_is(right, "lit"), test("str_eq", fn, lit("mul"))),
         card("lit", call("mul", left_value, right_value))),
    ), original)
    if mode == "fold":
        folded = n.Case(folded.arms[2:], original)
    rewritten = var("rewritten")
    binary_fold = n.Let("left", call("list_get", rewritten, lit(0)),
                        n.Let("right", call("list_get", rewritten, lit(1)), folded))
    body = n.Case(((tag_is(expr, "call"),
                    n.Let("rewritten", _map_args(args),
                          n.Case(((test("eq", call("list_len", rewritten), lit(2)), binary_fold),),
                                 call("with_field", expr, lit(1), rewritten)))),
                   (tag_is(expr, "case"),
                    call("with_field", call("with_field", expr, lit(0), _map_case(element(expr, 0))),
                         lit(1), n.Case(((tag_is(element(expr, 1), "some"),
                                         call("mk", lit("opt"), lit("some"),
                                              call("list_cons", call("visit", element(element(expr, 1), 0)), EMPTY))),),
                                        element(expr, 1)))),
                   (tag_is(expr, "let"),
                    call("with_field", call("with_field", expr, lit(1), call("visit", element(expr, 1))),
                         lit(2), call("visit", element(expr, 2))))), expr)
    return _rec("visit", body, element(var("c"), 2), memo=mode == "fold")


def _map_case(arms):
    index = var("case_index")
    arm = call("list_get", arms, index)
    mapped = call("mk", lit("arm"), lit("arm"),
                  call("list_cons", element(arm, 0),
                       call("list_cons", call("visit", element(arm, 1)), EMPTY)))
    body = n.Case(((test("eq", index, call("list_len", arms)), EMPTY),),
                  call("list_cons", mapped, call("map_case", call("add", index, lit(1)))))
    return n.Rec("map_case", ("case_index",), body, (lit(0),),
                 call("sub", call("list_len", arms), index))


def _substitute():
    expr = var("expr")
    args = element(expr, 1)
    body = n.Case((
        (both(tag_is(expr, "var"), test("str_eq", element(expr, 0), lit("x0"))),
         card("lit", var("k"))),
        (both(tag_is(expr, "var"), test("str_eq", element(expr, 0), lit("x1"))),
         card("var", lit("x0"))),
        (tag_is(expr, "call"), call("with_field", expr, lit(1), _map_args(args, "replace"))),
        (tag_is(expr, "let"),
         call("with_field", call("with_field", expr, lit(1), call("replace", element(expr, 1))),
              lit(2), call("replace", element(expr, 2)))),
    ), expr)
    return _rec("replace", body, element(var("c"), 2))


def _object_verifier(defn, lib, request):
    if not isinstance(defn.spec, ObjectSpec) or defn.spec.form != "constant" or (
            request.reference is None):
        return VerifyResult(False, (), ["constant requires a declared interface and a reference"], [])
    steps, problems = [], []
    for args in request.domain:
        actual = lib.run(defn.name, args)
        expected = request.reference(*args)
        if not isinstance(expected, Ok) or not isinstance(expected.value, Card) or (
                expected.value.sort != defn.spec.base) or not code.is_canonical(expected.value) or (
                actual.outcome != expected):
            problems.append(f"constant mismatch: {args!r}")
            break
        unfolded = kernel.evaluate(n.Lit(expected.value), scope=lib.scope())
        if not outcome_equal(actual.outcome, unfolded.outcome) or actual.steps != unfolded.steps:
            problems.append(f"unfold mismatch: {args!r}")
            break
        steps.append(actual.steps)
    return VerifyResult(not problems, ("constant", "object_interface", "unfold_equivalence")
                        if not problems else (), problems, steps)


def _combinator_verifier(defn, lib, request):
    problems = check_combinator(defn, lib)
    family = request.extra.get("op_family", ())
    if not family or not set(family) <= set(request.scope.get("op_family", ())) or not callable(
            request.reference):
        problems.append("combinator needs a declared operation family and a reference")
    if any(lib.get(name).status != "promoted" or lib.get(name).kind != "operation" for name in family):
        problems.append("operation family contains unpromoted operations")
    if problems:
        return VerifyResult(False, (), problems, [])
    steps = []
    for names in product(family, repeat=len(defn.spec.op_params)):
        assignment = dict(zip(defn.spec.op_params, names))
        for inputs in request.domain:
            args = tuple(kernel.FnRef(assignment[param]) if param in assignment else inputs[
                [item for item in defn.spec.params if item not in assignment].index(param)]
                for param in defn.spec.params)
            actual = lib.run(defn.name, args)
            expected = request.reference(assignment, inputs)
            if not isinstance(expected, (Ok, Bottom, Unknown)):
                expected = Ok(expected)
            invocation = call(defn.name, *(lit(arg) for arg in args))
            unfolded = engine.evaluate(kernel.inline(invocation, lib.scope()), scope=lib.scope())
            if actual.outcome != expected or not outcome_equal(actual.outcome, unfolded.outcome) or (
                    actual.steps != unfolded.steps):
                return VerifyResult(False, (), [f"combinator mismatch: {names!r}, {inputs!r}"], steps)
            steps.append(actual.steps)
    return VerifyResult(True, ("unfold_equivalence", "reference", "operation_family"), [], steps)


def _op(name, params, output, body):
    return Definition(name, "operation", "invented", 1, tuple(sorted(n.references(body))),
                      OperationSpec(name, "transform", tuple(Edge(sort) for sort in params), Edge(output),
                                    "Invented kernel-node code transformation", extra={"input_names":
                                    ["c", "k"][:len(params)] if name == "specialize" else
                                    ["e"] if name == "has_div" else ["c"]}), body)


def family(lib):
    """200 arithmetic trees plus 12 Let and 12 Case programs."""
    leaves = [n.Var("x0"), *(n.Lit(value) for value in range(4))]
    trees = list(leaves)
    for operator in ("add", "sub", "mul", "div"):
        for left in leaves:
            for right in leaves:
                trees.append(call(operator, left, right))
    for operator in ("add", "sub", "mul", "div"):
        for left in trees[5:30]:
            for right in leaves:
                trees.append(call(operator, left, right))
                if len(trees) >= 200:
                    break
            if len(trees) >= 200:
                break
        if len(trees) >= 200:
            break
    def resolve(name):
        op = next((op for op in lib.world.operations if op.name == name), None)
        return code.Resolved(digest=code.atom_digest(op)) if op else None
    trees = trees[:199] + [call("sub", call("div", var("x0"), lit(0)),
                                       call("div", var("x0"), lit(0)))]
    trees += [n.Let("saved", call("add", lit(2), lit(3)), call("add", tree, var("saved")))
              for tree in trees[5:17]]
    trees += [n.Case(((test("is_zero", var("x0")), call("add", lit(2), lit(3))),), tree)
              for tree in trees[5:17]]
    return tuple(code.make_code("operation", code.sig_op((("int", "bottom"),), ("int", "bottom")),
                                ("x0",), tree, resolve) for tree in trees)


def run_code(lib, value, args):
    cache = getattr(lib, "_code_run_cache", None)
    if cache is None:
        cache = lib._code_run_cache = {}
    key = (lib._world_hash, id(lib.atoms), value, tuple(args))
    if key in cache:
        return cache[key]
    decoded = code.decode(value)
    result = engine.call(decoded.main.name, args,
                         kernel.DictScope(lib.atoms, (*decoded.deps, decoded.main)),
                         kernel.Limits(fuel=100_000))
    cache[key] = result
    return result


def record_specialization(lib, program, constant, ledger=None):
    """Verify an individual generated operation before its own promotion (spec 7)."""
    ledger = ledger if ledger is not None else Ledger()
    result = lib.run("specialize", (program, constant)).outcome
    if not isinstance(result, Ok):
        raise PipelineError(f"specialize failed: {result!r}")
    generated = result.value
    generator_hash = code.code_hash(code.quote_from_library(lib, "specialize"))
    world_hash = lib.world.world_hash()
    digest = ledger.add(generated, world_hash, produced_by=(
        generator_hash, code.code_hash(program), content_hash(encode(constant))))
    decoded = code.decode(generated)
    cases = []
    for argument in range(7):
        before = run_code(lib, program, (constant, argument))
        actual = run_code(lib, generated, (argument,))
        scope = kernel.DictScope(lib.atoms, (*decoded.deps, decoded.main))
        invocation = n.Call(decoded.main.name, (n.Lit(argument),))
        unfolded = engine.evaluate(engine.inline(invocation, scope), scope=scope)
        if (isinstance(actual.outcome, Unknown) or not outcome_equal(before.outcome, actual.outcome)
                or not outcome_equal(actual.outcome, unfolded.outcome) or actual.steps != unfolded.steps):
            raise PipelineError(f"generated output failed at x0={argument}")
        cases.append([code.code_hash(program), constant, argument])
    ledger.attach_evidence(digest, world_hash, Evidence("bounded", {
        "domain": "fixed source and constant, y in 0..6", "size": len(cases),
        "cases": cases, "domain_hash": content_hash(cases)},
        checks=("semantic_preservation", "unfold_equivalence"), world_hash=world_hash,
        content_hash=digest, atoms_hash=atoms_digest(lib.atoms)))
    cards.promote_output(ledger, digest, world_hash, lib.atoms,
                         Contract("Matches its source with x0 fixed to k on y=0..6."))
    return ledger, digest


def semantic_check(lib, source, transformed, inputs=range(7)):
    before = after = 0
    for value in source:
        changed = lib.run(transformed, (value,)).outcome
        if not isinstance(changed, Ok):
            return False, (value, changed), (before, after)
        for argument in inputs:
            old = run_code(lib, value, (argument,))
            new = run_code(lib, changed.value, (argument,))
            if isinstance(old.outcome, Unknown) or isinstance(new.outcome, Unknown) or not outcome_equal(old.outcome, new.outcome):
                return False, (value, argument, old.outcome, new.outcome), (before, after)
            before += old.steps
            after += new.steps
    return True, None, (before, after)


def bridge_semantic_check(lib, source, inputs=range(7)):
    """Check both commuting code paths on every recorded input (atoms-v2 19.2)."""
    cases = 0
    for value in source:
        folded = lib.run("const_fold", (value,)).outcome
        mapped = lib.run("fold_bridge", (value,)).outcome
        if not isinstance(folded, Ok) or not isinstance(mapped, Ok):
            return False, (value, folded, mapped), cases
        translated = lib.run("fold_bridge", (folded.value,)).outcome
        targeted = lib.run("const_fold", (mapped.value,)).outcome
        if not isinstance(translated, Ok) or not isinstance(targeted, Ok):
            return False, (value, translated, targeted), cases
        for argument in inputs:
            left = run_code(lib, translated.value, (argument,))
            right = run_code(lib, targeted.value, (argument,))
            if isinstance(left.outcome, Unknown) or isinstance(right.outcome, Unknown) or not outcome_equal(left.outcome, right.outcome):
                return False, (value, argument, left.outcome, right.outcome), cases
            cases += 1
    return True, None, cases


def reference_transform(value, mode):
    """Independent Python verification oracle; invented bodies remain kernel nodes."""
    decoded = code.decode(value)
    atom_digests = dict(decoded.atoms)
    dependencies = {definition.name: dependency for dependency in code.items(value.fields[4])
                    for definition in (code.decode(dependency).main,)}

    def rewrite(node):
        if isinstance(node, n.Let):
            return n.Let(node.name, rewrite(node.value), rewrite(node.body))
        if isinstance(node, n.Case):
            return n.Case(tuple((condition, rewrite(body)) for condition, body in node.arms),
                          rewrite(node.default) if node.default is not None else None)
        if not isinstance(node, n.Call):
            return node
        arguments = tuple(rewrite(argument) for argument in node.args)
        if len(arguments) != 2:
            return n.Call(node.fn, arguments)
        left, right = arguments
        if mode != "fold":
            no_failure = mode == "unsafe" or all(
                not (isinstance(part, n.Case) or isinstance(part, n.Call) and part.fn == "div")
                for subtree in (left, right) for part in n.walk(subtree))
            if no_failure and node.fn == "sub" and left == right:
                return n.Lit(0)
            if no_failure and node.fn == "mul" and (left == n.Lit(0) or right == n.Lit(0)):
                return n.Lit(0)
        if isinstance(left, n.Lit) and isinstance(right, n.Lit) and all(
                type(part.value) is int for part in (left, right)):
            if node.fn == "add":
                return n.Lit(left.value + right.value)
            if node.fn == "sub":
                return n.Lit(left.value - right.value)
            if node.fn == "mul":
                return n.Lit(left.value * right.value)
        return n.Call(node.fn, (left, right))

    def resolve(name):
        if name in dependencies:
            return code.Resolved(code=dependencies[name])
        return code.Resolved(digest=atom_digests[name]) if name in atom_digests else None

    return code.make_code(decoded.kind, decoded.sig, decoded.main.params,
                          rewrite(decoded.main.body), resolve)


def reference_specialize(value, constant):
    """Independent syntax oracle for x0 := k, x1 := x0, then safe folds."""
    decoded = code.decode(value)
    if decoded.kind != "operation" or len(decoded.main.params) != 2:
        return Bottom("arity")

    def substitute(node):
        if isinstance(node, n.Var):
            return n.Lit(constant) if node.name == "x0" else n.Var("x0") if node.name == "x1" else node
        if isinstance(node, n.Call):
            return n.Call(node.fn, tuple(substitute(argument) for argument in node.args))
        if isinstance(node, n.Let):
            return n.Let(node.name, substitute(node.value), substitute(node.body))
        return node

    digests = dict(decoded.atoms)
    dependencies = {code.decode(dep).main.name: dep for dep in code.items(value.fields[4])}

    def resolve(name):
        if name in dependencies:
            return code.Resolved(code=dependencies[name])
        return code.Resolved(digest=digests[name]) if name in digests else None

    new_sig = Card("sig", "op", (code.lst((code.items(decoded.sig.fields[0])[1],)),
                                    decoded.sig.fields[1]))
    result = code.make_code("operation", new_sig, ("x0",), substitute(decoded.main.body), resolve)
    for mode in ("fold", "fold", "safe", "fold", "fold"):
        result = reference_transform(result, mode)
    return Ok(result)


def specialize_source(lib):
    def resolve(name):
        op = next((op for op in lib.world.operations if op.name == name), None)
        return code.Resolved(digest=code.atom_digest(op)) if op else None
    return code.make_code("operation", code.sig_op((("int", "bottom"), ("int", "bottom")),
                                                    ("int", "bottom")), ("x0", "x1"),
                          call("add", call("mul", var("x0"), var("x1")), lit(3)), resolve)


def specialization_family(lib, one_input):
    """30 two-input programs: 0..9, 80..89, 100..109 with a free x1."""
    chosen = (*one_input[:10], *one_input[80:90], *one_input[100:110])
    result = []
    for value in chosen:
        decoded = code.decode(value)
        def resolve(name):
            op = next((op for op in lib.world.operations if op.name == name), None)
            return code.Resolved(digest=code.atom_digest(op)) if op else None
        result.append(code.make_code("operation", code.sig_op((("int", "bottom"), ("int", "bottom")),
                                                          ("int", "bottom")), ("x0", "x1"),
                                     call("add", decoded.main.body, var("x1")), resolve))
    return tuple(result)


def specialization_check(lib, programs, constants=range(7), inputs=range(7)):
    cases = 0
    for program in programs:
        for constant in constants:
            specialized = lib.run("specialize", (program, constant)).outcome
            if not isinstance(specialized, Ok):
                return False, (program, constant, specialized), cases
            for argument in inputs:
                before = run_code(lib, program, (constant, argument)).outcome
                after = run_code(lib, specialized.value, (argument,)).outcome
                if isinstance(before, Unknown) or isinstance(after, Unknown) or not outcome_equal(before, after):
                    return False, (program, constant, argument, before, after), cases
                cases += 1
    return True, None, cases


def build_story():
    """Write/check/call/verify/account/promote each member in dependency order.

    The object verifier of this world is registered only while the story is built; the core keeps
    verifiers in a process-wide table, so leaving it installed would change other worlds' checks.
    """
    from opulse.atoms import library as core_library

    previous = core_library._VERIFIERS.get("object")
    register_kind("object", verifier=_object_verifier)
    try:
        return _build_story()
    finally:
        if previous is None:
            core_library._VERIFIERS.pop("object", None)
        else:
            register_kind("object", verifier=previous)


def _build_story():
    lib = library()
    lib.semantic_results = {}
    source = family(lib)
    resolve = lambda name: code.Resolved(digest=code.atom_digest(next(op for op in lib.world.operations
                                                                         if op.name == name)))
    poly = code.make_code("operation", code.sig_op((("int", "bottom"),), ("int", "bottom")),
                          ("x0",), call("add", call("mul", var("x0"), var("x0")), lit(3)), resolve)

    contracts = {
        "poly": "Returns the fixed quoted polynomial Code<op(x0)=add(mul(x0,x0),3)>.",
        "expr_size": "Returns the card-tree node count of the expression.",
        "has_div": "Detects div in Call and Let trees; conservatively guards Case subtrees.",
        "const_fold": "Preserves all outcomes on 224 programs and x0=0..6.",
        "simplify_safe": "Preserves all outcomes on 224 programs and x0=0..6.",
        "stable_simplify": "Unfolds to simplify_safe(const_fold(c)).",
        "specialize": "Preserves outcomes on 30 programs, k=0..6, y=0..6.",
        "specialize_zero": "Produces the zero-input specialization on 30 programs, y=0..6.",
        "pipeline": "Unfolds to stable_simplify(t2(t1(c))) for the recorded operation family.",
    }

    def install(defn, samples, reference, promote=True,
                scope="first eight code cards in the bounded 224-program family, size <= 60"):
        dependencies = tuple(sorted(n.references(defn.body) - ({"t1", "t2"} if defn.kind == "combinator" else set())))
        layer = 1 + max((lib.get(dep).layer for dep in dependencies), default=0)
        defn = Definition(defn.name, defn.kind, "invented", layer, dependencies, defn.spec, defn.body)
        lib.write(defn)
        lib.check(defn.name)
        lib.make_callable(defn.name, [(kernel.FnRef("const_fold"), kernel.FnRef("simplify_safe"), samples[0][0])]
                          if defn.kind == "combinator" else samples[:2])
        request = VerifyRequest("bounded", samples, {"domain": scope, "size": len(samples),
                               "enumerated_count": len(samples),
                               "code_hashes": [code.code_hash(args[0]) for args in samples
                                               if args and isinstance(args[0], Card)
                                               and args[0].sort == "code"],
                               "op_family": ["const_fold", "simplify_safe"],
                               "semantic_inputs": list(range(7)) if defn.name in
                               ("const_fold", "simplify_safe", "specialize") else [],
                               "semantic_cases": len(samples) * 7
                               if defn.name in ("const_fold", "simplify_safe", "specialize") else 0},
                                reference=reference,
                                extra={"op_family": ("const_fold", "simplify_safe")})
        from opulse.atoms import library as library_module
        previous = library_module._VERIFIERS.get("combinator")
        if defn.kind == "combinator":
            register_kind("combinator", verifier=_combinator_verifier)
        try:
            try:
                lib.verify(defn.name, request)
            except PipelineError:
                if promote:
                    raise
                return
        finally:
            if defn.kind == "combinator":
                if previous is None:
                    library_module._VERIFIERS.pop("combinator", None)
                else:
                    register_kind("combinator", verifier=previous)
        if defn.name in ("const_fold", "simplify_safe"):
            result = semantic_check(lib, [args[0] for args in samples], defn.name)
            lib.semantic_results[defn.name] = result
            sound, witness, _ = result
            if not sound:
                raise PipelineError(f"semantic counterexample: {witness!r}")
        if defn.name == "specialize":
            result = specialization_check(lib, [args[0] for args in samples[::7]])
            lib.specialization_result = result
            sound, witness, cases = result
            if not sound or cases != len(samples) * 7:
                raise PipelineError(f"specialization counterexample: {witness!r}")
        lib.account(defn.name)
        if promote:
            lib.promote(defn.name, Contract(contracts[defn.name]))

    install(Definition("poly", "object", "invented", 1, (),
                       ObjectSpec("poly", "constant", base="code", body=lit(poly)), lit(poly)), [()],
            lambda: Ok(poly), scope="single named constant, size <= 1")
    from .hosts import size
    install(_op("expr_size", ("code",), "int", call("size", element(var("c"), 2))),
            [(value,) for value in source[:8]], lambda value: Ok(size(value.fields[2])))
    has_div = _has_div()
    install(_op("has_div", ("expr",), "bool", has_div),
            [(source[index].fields[2],) for index in (0, 5, 61, 80, 100, 199)],
            lambda expr: Ok(boolean(any(isinstance(node, n.Call) and node.fn == "div"
                                        for node in n.walk(code.decode_node(expr))))),
            scope="expression indices 0, 5, 61, 80, 100 and 199, size <= 35")
    fold = call("with_field", var("c"), lit(2), _fold_expr("fold"))
    install(_op("const_fold", ("code",), "code", fold), [(value,) for value in source],
            lambda value: Ok(reference_transform(value, "fold")),
            scope="224 programs, each of size <= 60")
    unsafe = call("with_field", var("c"), lit(2), _fold_expr("unsafe"))
    counter = source[199]
    def unsound_reference(value):
        changed = reference_transform(value, "unsafe")
        if any(not outcome_equal(run_code(lib, value, (argument,)).outcome,
                                 run_code(lib, changed, (argument,)).outcome) for argument in range(7)):
            return Bottom("semantic_counterexample")
        return Ok(changed)

    install(_op("simplify_unsafe", ("code",), "code", unsafe), [(value,) for value in source],
            unsound_reference, promote=False, scope="224 programs of size <= 60, x0 in 0..6")
    safe = call("const_fold", call("with_field", var("c"), lit(2), _fold_expr("safe")))
    install(_op("simplify_safe", ("code",), "code", safe), [(value,) for value in source],
            lambda value: Ok(reference_transform(value, "safe")),
            scope="224 programs, each of size <= 60")
    stable = call("simplify_safe", call("const_fold", var("c")))
    install(_op("stable_simplify", ("code",), "code", stable), [(value,) for value in source[:8]],
            lambda value: Ok(reference_transform(reference_transform(value, "fold"), "safe")))
    new_sig = call("with_field", element(var("c"), 1), lit(0),
                   call("list_cons", call("list_get", element(element(var("c"), 1), 0), lit(1)), EMPTY))
    specialize = call("stable_simplify", call("with_field", call("with_field", var("c"), lit(2),
                                                            _substitute()), lit(1), new_sig))
    two_input = specialization_family(lib, source)
    install(_op("specialize", ("code", "int"), "code", specialize),
            [(value, constant) for value in two_input for constant in range(7)],
            reference_specialize,
            scope="30 two-input trees of size <= 35, k and y each 0..6")
    install(_op("specialize_zero", ("code",), "code", call("specialize", var("c"), lit(0))),
            [(value,) for value in two_input], lambda value: reference_specialize(value, 0),
            scope="30 two-input programs, fixed x0=0, y in 0..6")
    pipeline = call("stable_simplify", call("t2", call("t1", var("c"))))
    def pipeline_reference(assignment, inputs):
        current = inputs[0]
        for name in (assignment["t1"], assignment["t2"], "stable_simplify"):
            outcome = lib.run(name, (current,)).outcome
            if not isinstance(outcome, Ok):
                return outcome
            current = outcome.value
        return Ok(current)

    install(Definition("pipeline", "combinator", "invented", 1, (),
                       CombinatorSpec("pipeline", ("t1", "t2", "c"), ("t1", "t2"), pipeline), pipeline),
            [(source[0],), (source[10],)], pipeline_reference,
            scope="code family indices 0 and 10, size <= 35; op family const_fold and simplify_safe")
    install_six_kinds(lib, source, counter, two_input)
    lib.generated_ledger = Ledger()
    lib.generated_hashes = tuple(record_specialization(lib, program, constant, lib.generated_ledger)[1]
                                 for program, constant in ((two_input[12], 3), (two_input[13], 2)))
    lib.generator_records = run_generator(lib, lib.generated_ledger, "specialize", (two_input[0], 2))
    return lib, source, counter


def install_six_kinds(lib, source, counter, two_input):
    """Record scoped laws, a commuting bridge and a finite specialization template (spec 19)."""
    folded = call("const_fold", var("c"))
    equation = call("eq", call("const_fold", folded), folded)
    law = Definition("fold_idempotent", "law", "invented", 2, ("const_fold", "eq"),
                     LawSpec("fold_idempotent", (("c", "code"),), equation), equation)
    lib.write(law)
    lib.check(law.name)
    lib.make_callable(law.name, [(source[0],)])
    lib.verify(law.name, VerifyRequest("bounded", [(value,) for value in source],
                                      {"domain": "all 224 recorded programs, including let and case", "size": 224,
                                       "semantic_inputs": list(range(7)), "semantic_cases": 1568}))
    lib.account(law.name)
    lib.promote(law.name, Contract("Idempotent on the 224 recorded programs; semantic inputs x0=0..6."))
    before = call("const_fold", call("const_fold", lit(source[12])))
    after = call("const_fold", lit(source[12]))
    lib.fold_derivation = replay_rewrite(before, after, "fold_idempotent", lib, {})

    unsafe_statement = call("eq", call("eval", call("simplify_unsafe", var("c")), var("xs")),
                            call("eval", var("c"), var("xs")))
    unsafe_law = Definition("unsafe_equivalence", "law", "invented", 2,
                            ("eq", "eval", "simplify_unsafe"),
                            LawSpec("unsafe_equivalence", (("c", "code"), ("xs", "list")), unsafe_statement),
                            unsafe_statement)
    lib.write(unsafe_law)
    lib.check(unsafe_law.name)
    lib.make_callable(unsafe_law.name, [(counter, code.lst((0,)))])
    try:
        lib.verify(unsafe_law.name, VerifyRequest("bounded", [(counter, code.lst((0,)))],
                                                 {"domain": "the strict-division counterexample at x0=0", "size": 1}))
    except PipelineError:
        pass
    else:
        raise PipelineError("unsound law unexpectedly verified")
    lib.account(unsafe_law.name)

    bridge_map = call("const_fold", var("x"))
    bridge = Definition("fold_bridge", "bridge", "invented", 2, ("const_fold",),
                        BridgeSpec("fold_bridge", "code", "code", bridge_map,
                                   interface=(("const_fold", "const_fold"),)), bridge_map)
    lib.write(bridge)
    lib.check(bridge.name)
    lib.make_callable(bridge.name, [(source[0],)])
    lib.verify(bridge.name, VerifyRequest("bounded", [(value,) for value in source],
                                         {"domain": "all 224 recorded programs, including let and case", "size": 224,
                                          "semantic_inputs": list(range(7)), "semantic_cases": 1568}))
    sound, witness, cases = bridge_semantic_check(lib, source)
    if not sound or cases != len(source) * 7:
        raise PipelineError(f"bridge semantic counterexample: {witness!r}")
    lib.bridge_semantic_cases = cases
    lib.account(bridge.name)
    lib.promote(bridge.name, Contract("Commutes with const_fold on 224 programs; semantic inputs x0=0..6."))

    pattern = OperationSpec("member", "transform", (Edge("code"),), Edge("code"),
                            "Specialize the first input to a fixed integer",
                            extra={"input_names": ["arg0"]}).to_dict()
    pattern["definition_body"] = n.to_json(call("specialize", var("arg0"), lit("$k")))
    template = Definition("Specialize", "template", "invented", 1, (),
                          TemplateSpec("Specialize", (("k", "int"),), "operation", pattern,
                                       {"family": [{"k": 0}, {"k": 3}]}), lit(0))
    lib.write(template)
    lib.check(template.name)
    lib.make_callable(template.name, [()])

    def member_request(index, args, member):
        program = two_input[index]
        constant = args["k"]
        return VerifyRequest("bounded", [(program,)],
                             {"domain": f"two-input source index {index}, k={constant}", "size": 1},
                             reference=lambda value: reference_specialize(value, constant))

    lib.specialize_members = instantiate_family(lib, "Specialize", [{"k": 0}, {"k": 3}], member_request)
    lib.account(template.name)
    lib.promote(template.name, Contract("Produces unary specializers only for k=0 and k=3."))
    refreshed = []
    for index, member in enumerate(lib.specialize_members):
        args = {"k": (0, 3)[index]}
        lib.replace(member.name, instantiate(lib.get(template.name), args, member.name, lib=lib))
        lib.check(member.name)
        request = member_request(index, args, lib.get(member.name))
        lib.make_callable(member.name, request.domain)
        lib.verify(member.name, request)
        lib.account(member.name)
        lib.promote(member.name, Contract("Produces a unary code card for its recorded source and k."))
        refreshed.append(lib.get(member.name))
    lib.specialize_members = tuple(refreshed)
