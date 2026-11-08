"""Invented tiny/1-to-vn/1 compiler (atoms-meta section 5).

Calling convention: n=64, code at address 0, x_i in cell 60+i (poked by
the caller), temporary cells 48..59, result in a at HALT. Programs must fit
in cells 0..47, including HALT. No temporary or argument cell is code.

Subset: operation Code<...> with one or two int inputs and an int result;
var, lit (integer 0..255), call(add/sub, two expressions), let (at most six
simultaneously nested bindings), and case with one or more ordered arms of
test(call(is_zero, one expression)) and an expression default. No rec, other
calls, or dependencies. Spills share the 12 temporary cells with let bindings;
exceeding that capacity or the code region returns Bottom("unsupported").
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from functools import lru_cache

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.library import (
    DEFAULT_VERIFY_FUEL,
    Library,
    PipelineError,
    VerifyRequest,
    atoms_digest,
    checked_scope,
)
from opulse.atoms.spec import (
    Contract,
    Definition,
    Edge,
    Evidence,
    ObjectSpec,
    OperationSpec,
    content_hash,
)
from opulse.atoms.values import Bottom, Card, Ok, Unknown, boolean, outcome_equal
from opulse.atoms.world import WorldDecl
from opulse.meta import code as C
from opulse.meta.vn.report import routine_id


def _size(value):
    """Count nodes of a card tree, including primitive leaves (section 5)."""
    return 1 + sum(_size(child) for child in value.fields) if isinstance(value, Card) else 1


def _field(value, index):
    return value.fields[index] if isinstance(value, Card) and 0 <= index < len(value.fields) else Bottom("unsupported")


def _get(value, index):
    return value.fields[index] if _length(value) != Bottom("unsupported") and type(index) is int and 0 <= index < len(value.fields) else Bottom("unsupported")


def _lt(left, right):
    return boolean(left < right) if type(left) is int and type(right) is int else Bottom("unsupported")


def _length(value):
    return len(value.fields) if isinstance(value, Card) and value.sort == "list" and value.tag == "items" else Bottom("unsupported")


def _append(values, value):
    return C.lst((*values.fields, value)) if isinstance(values, Card) and values.sort == "list" and values.tag == "items" else Bottom("unsupported")


def _concat(left, right):
    return C.lst((*left.fields, *right.fields)) if _length(left) != Bottom("unsupported") and _length(right) != Bottom("unsupported") else Bottom("unsupported")


def _unsupported():
    return Bottom("unsupported")


def _pack_prog(code):
    try:
        return Card("prog", "prog", (64, code, C.lst((60, 61)), "a")) if all(
            type(byte) is int and 0 <= byte < 256 for byte in C.items(code)
        ) else Bottom("unsupported")
    except (TypeError, ValueError):
        return Bottom("unsupported")


def _source_at(code, left, right):
    try:
        decoded = C.decode(code)
        if len(decoded.main.params) != 2:
            return Bottom("unsupported")
        value = source_value(decoded.main.body, left, right)
        return value if 0 <= value < 256 else Bottom("overflow")
    except (TypeError, ValueError, KeyError):
        return Bottom("unsupported")


def _prog_at(program, left, right):
    if not isinstance(program, Card) or program.sort != "prog" or program.tag != "prog":
        return Bottom("unsupported")
    try:
        size, code, addresses, output = program.fields
        if size != 64 or tuple(C.items(addresses)) != (60, 61) or output != "a":
            return Bottom("unsupported")
        status, value, _ = run_batch_program(C.items(code), left, right)
        return value if status == "ok" else Bottom("illegal" if status == "illegal" else "fuel")
    except (TypeError, ValueError):
        return Bottom("unsupported")


def source_at_00(code):
    return _source_at(code, 0, 0)


def source_at_13(code):
    return _source_at(code, 1, 3)


def prog_at_00(program):
    return _prog_at(program, 0, 0)


def prog_at_13(program):
    return _prog_at(program, 1, 3)


def _spec(name, inputs, output, fn, *, cost=1):
    arity = len(inputs)
    role = "decide" if output == "bool" else "combine" if arity > 1 else "transform"
    spec = OperationSpec(name, role, tuple(Edge(sort) for sort in inputs), Edge(output),
                         f"{name} on canonical compiler values", ("unsupported",), cost=cost,
                         extra={"input_names": [f"arg{index}" for index in range(arity)]})
    return spec, kernel.Atom(name, arity, fn, cost)


def world_and_atoms():
    """Given compiler-world atoms and declaration (atoms-meta sections 2.3, 5)."""
    operations = (
        _spec("add", ("int", "int"), "int", lambda left, right: left + right),
        _spec("sub", ("int", "int"), "int", lambda left, right: left - right),
        _spec("lt", ("int", "int"), "bool", _lt),
        _spec("eq", ("int", "int"), "bool", lambda left, right: boolean(left == right)),
        _spec("is_zero", ("int",), "bool", lambda value: boolean(value == 0)),
        _spec("tag_of", ("expr",), "str", lambda value: value.tag if isinstance(value, Card) else Bottom("unsupported")),
        _spec("tag_of_code", ("code",), "str", lambda value: value.tag if isinstance(value, Card) else Bottom("unsupported")),
        _spec("field", ("expr", "int"), None, _field),
        _spec("field_code", ("code", "int"), None, _field),
        _spec("str_eq", ("str", "str"), "bool", lambda left, right: boolean(left == right)),
        _spec("len", ("list",), "int", _length),
        _spec("get", ("list", "int"), None, _get),
        _spec("append", ("list", "int"), "list", _append),
        _spec("concat", ("list", "list"), "list", _concat),
        _spec("size", ("expr",), "int", _size),
        _spec("unsupported", (), None, _unsupported, cost=0),
        _spec("pack_prog", ("list",), "prog", _pack_prog, cost=0),
        _spec("code_hash", ("code",), "str", C.code_hash, cost=0),
        _spec("source_at_00", ("code",), "int", source_at_00, cost=0),
        _spec("source_at_13", ("code",), "int", source_at_13, cost=0),
        _spec("prog_at_00", ("prog",), "int", prog_at_00, cost=0),
        _spec("prog_at_13", ("prog",), "int", prog_at_13, cost=0),
    )
    world = WorldDecl("learner_compiler", 1, "atoms-v2", {}, {},
                      tuple(ObjectSpec(sort, "given") for sort in ("int", "str", "bool", "code", "expr", "list", "prog")),
                      tuple(spec for spec, _ in operations),
                      {"nodes": ["Var", "Lit", "Call", "Let", "Case", "Rec"], "recursion": "measure"},
                      {"truth": None, "probes": [], "judge_view": "full_state"}, {},
                      open_kinds=("object", "operation", "combinator", "observation", "law", "bridge"))
    return world, tuple(atom for _, atom in operations)


class LearnerLibrary(Library):
    """Reuse the scope and unfolding for bounded compiler evidence (section 5)."""

    def verify(self, name: str, request: VerifyRequest) -> Definition:
        definition = self.get(name)
        if (name != "lcompile" or definition.status != "callable" or request.reference is None
                or request.method not in ("exhaustive", "bounded", "sampled")
                or request.method == "sampled" and request.seed is None
                or request.scope.get("size") != len(request.domain) or "domain" not in request.scope):
            return super().verify(name, request)
        scope = self.scope()
        parameter = "__meta_compiler_input_0"
        expanded = kernel.inline(n.Call(name, (n.Var(parameter),)), scope)
        if any(isinstance(node, n.Let) and node.name == parameter for node in n.walk(expanded)):
            raise ValueError("compiler input name must be fresh")
        limits = kernel.Limits(fuel=request.extra.get("fuel", DEFAULT_VERIFY_FUEL))
        cached_runs = request.extra.get("kernel_runs", {})
        if cached_runs and (request.extra.get("definition_hash") != content_hash(definition.to_dict())
                            or request.extra.get("deps_hash") != self.deps_hash(name)
                            or request.extra.get("world_hash") != self.world.world_hash()):
            raise PipelineError("compiler changed since the cached kernel runs")
        steps = []
        for args in request.domain:
            try:
                actual = cached_runs.get(args[0]) if len(args) == 1 else None
                if (actual is None or isinstance(actual.outcome, Unknown)
                        or limits.fuel is not None and actual.steps > limits.fuel):
                    actual = kernel.call(name, args, scope, limits, dialect=self.dialect)
                expected = (kernel.call(request.reference, args, scope, limits, dialect=self.dialect).outcome
                            if isinstance(request.reference, str) else request.reference(*args))
                if not isinstance(expected, (Ok, Bottom, Unknown)):
                    expected = Ok(expected)
                if not outcome_equal(actual.outcome, expected):
                    raise PipelineError(f"reference counterexample {args!r}: {actual.outcome!r} != {expected!r}")
                unfolded = kernel.evaluate(expanded, {parameter: args[0]}, scope, limits, dialect=self.dialect)
                if not outcome_equal(actual.outcome, unfolded.outcome) or actual.steps != unfolded.steps:
                    raise PipelineError(f"unfold_equivalence counterexample {args!r}: {actual!r} != {unfolded!r}")
                steps.append(actual.steps)
            except PipelineError:
                raise
            except (ValueError, TypeError, KeyError, RecursionError) as error:
                raise PipelineError(f"counterexample {args!r}: {error}") from error
        evidence_scope = dict(request.scope)
        evidence_scope["checked"] = {**checked_scope(request.domain), "by": "library"}
        evidence = Evidence(request.method, evidence_scope, request.seed,
                            ("reference", "unfold_equivalence"), self.world.world_hash(),
                            self.deps_hash(name), self.content_hash(name), atoms_digest(self.atoms))
        self._steps[name] = steps
        self._library_checked.add(name)
        self._definitions[name] = replace(definition, evidence=evidence)
        return self._advance(name, "verified")


@lru_cache(maxsize=3)
def source_atom(name):
    """Resolve a source atom against this world's actual declaration digest."""
    world, _ = world_and_atoms()
    return C.Resolved(digest=C.atom_digest(next(op for op in world.operations if op.name == name)))


def var(name):
    return n.Var(name)


def lit(value):
    return n.Lit(value)


def call(name, *args):
    return n.Call(name, args)


def bind(name, value, body):
    return n.Let(name, value, body)


def when(condition, yes, no):
    return n.Case(((n.Test(condition), yes),), no)


def tagged(value, name):
    return call("str_eq", call("tag_of", value), lit(name))


def at(value, index):
    return call("field", value, lit(index))


def plus(left, right):
    return call("add", left, right)


def emit(opcode, operand):
    return call("emit", lit(opcode), operand)


def join(*parts):
    result = parts[-1]
    for part in reversed(parts[:-1]):
        result = call("concat", part, result)
    return result


EMPTY = lit(C.lst())
BAD = call("unsupported")


def _definitions():
    emit_body = call("append", call("append", EMPTY, var("opcode")), var("operand"))
    lookup_body = n.Rec("search", ("index",),
                        when(call("eq", var("index"), call("len", var("names"))), BAD,
                             when(call("str_eq", var("name"), call("get", var("names"), var("index"))),
                                  call("get", var("slots"), var("index")),
                                  call("search", plus(var("index"), lit(1))))),
                        (lit(0),), call("sub", call("len", var("names")), var("index")))

    branch_body = bind("body_pc", plus(plus(plus(var("pc"), call("len", var("test"))),
                                          call("len", var("rest"))), lit(4)),
                       join(var("test"), emit(7, var("body_pc")), var("rest"),
                            emit(6, plus(var("body_pc"), call("len", var("body")))), var("body")))

    expr = var("expr")
    depth = var("depth")
    pc = var("pc")
    names = var("names")
    slots = var("slots")
    lets = var("lets")

    args = at(expr, 1)
    first = call("get", args, lit(0))
    second = call("get", args, lit(1))
    subtraction = bind("left", call("walk", first, names, slots, depth, lets, pc),
                       bind("right_pc", plus(pc, plus(call("len", var("left")), lit(2))),
                            bind("right", call("walk", second, names, slots, plus(depth, lit(1)), lets,
                                               var("right_pc")),
                                 join(var("left"), emit(3, plus(lit(48), depth)), var("right"),
                                      emit(3, plus(lit(48), plus(depth, lit(1)))),
                                      emit(2, plus(lit(48), depth)),
                                      emit(5, plus(lit(48), plus(depth, lit(1))))))))
    binary = bind("left", call("walk", first, names, slots, depth, lets, pc),
                  bind("right_pc", plus(pc, plus(call("len", var("left")), lit(2))),
                       bind("right", call("walk", second, names, slots, plus(depth, lit(1)), lets,
                                          var("right_pc")),
                            join(var("left"), emit(3, plus(lit(48), depth)), var("right"),
                                 emit(4, plus(lit(48), depth))))))
    invocation = when(call("eq", call("len", args), lit(2)),
                      when(call("str_eq", at(expr, 0), lit("add")), binary,
                           when(call("str_eq", at(expr, 0), lit("sub")),
                                when(call("lt", depth, lit(11)), subtraction, BAD), BAD)), BAD)

    let_body = when(call("lt", lets, lit(6)),
                    bind("value", call("walk", at(expr, 1), names, slots, depth, lets, pc),
                         join(var("value"), emit(3, plus(lit(48), depth)),
                              call("walk", at(expr, 2),
                                   call("append", names, at(expr, 0)),
                                   call("append", slots, plus(lit(48), depth)),
                                   plus(depth, lit(1)), plus(lets, lit(1)),
                                   plus(pc, plus(call("len", var("value")), lit(2)))))), BAD)

    arms = var("arms")
    arm = var("arm")
    cond = at(arm, 0)
    predicate = at(cond, 0)
    predicate_args = at(predicate, 1)
    arm_valid = when(tagged(cond, "test"),
                     when(tagged(predicate, "call"),
                          when(call("str_eq", at(predicate, 0), lit("is_zero")),
                               call("eq", call("len", predicate_args), lit(1)), lit(False)), lit(False)), lit(False))
    arm_body = bind("test_code", call("walk", call("get", predicate_args, lit(0)), names, slots,
                                      depth, lets, var("arm_pc")),
                    bind("rest_pc", plus(var("arm_pc"), plus(call("len", var("test_code")), lit(2))),
                         bind("rest", call("arms_walk", call("tail", arms), var("rest_pc")),
                              bind("body_pc", plus(var("rest_pc"), plus(call("len", var("rest")), lit(2))),
                                   call("branch", var("test_code"), var("rest"),
                                        call("walk", at(arm, 1), names, slots, depth, lets, var("body_pc")),
                                        var("arm_pc"))))))
    arms_body = when(call("eq", call("len", arms), lit(0)),
                     call("walk", at(at(expr, 1), 0), names, slots, depth, lets, var("arm_pc")),
                     bind("arm", call("get", arms, lit(0)), when(arm_valid, arm_body, BAD)))
    case_body = when(tagged(at(expr, 1), "some"),
                     when(call("lt", lit(0), call("len", at(expr, 0))),
                          n.Rec("arms_walk", ("arms", "arm_pc"), arms_body,
                                (at(expr, 0), pc), call("len", arms)), BAD), BAD)

    walk_body = when(call("lt", depth, lit(12)),
                     when(tagged(expr, "var"), emit(2, call("lookup", at(expr, 0), names, slots)),
                          when(tagged(expr, "lit"),
                               when(call("lt", lit(-1), at(expr, 0)),
                                    when(call("lt", at(expr, 0), lit(256)), emit(1, at(expr, 0)), BAD), BAD),
                               when(tagged(expr, "call"), invocation,
                                    when(tagged(expr, "let"), let_body,
                                         when(tagged(expr, "case"), case_body, BAD))))), BAD)
    walk_body = n.Rec("walk", ("expr", "names", "slots", "depth", "lets", "pc"), walk_body,
                      tuple(var(name) for name in ("expr", "names", "slots", "depth", "lets", "pc")),
                      call("size", expr))
    tail_body = n.Rec("tail_loop", ("index", "result"),
                      when(call("eq", var("index"), call("len", var("values"))), var("result"),
                           call("tail_loop", plus(var("index"), lit(1)),
                                call("append", var("result"), call("get", var("values"), var("index"))))),
                      (lit(1), EMPTY), call("sub", call("len", var("values")), var("index")))
    signature = var("signature")
    input_edges = at(signature, 0)
    signature_ok = when(call("str_eq", at(at(signature, 1), 0), lit("int")),
                        when(call("str_eq", at(call("get", input_edges, lit(0)), 0), lit("int")),
                             when(call("eq", call("len", input_edges), lit(1)), lit(True),
                                  call("str_eq", at(call("get", input_edges, lit(1)), 0), lit("int"))),
                             lit(False)), lit(False))
    top = when(call("str_eq", call("tag_of_code", var("source")), lit("def")),
               when(call("str_eq", call("field_code", var("source"), lit(0)), lit("operation")),
                    bind("signature", call("field_code", var("source"), lit(1)),
                         when(tagged(var("signature"), "op"),
                              when(call("lt", lit(0), call("len", at(var("signature"), 0))),
                                   when(call("lt", call("len", at(var("signature"), 0)), lit(3)),
                                        when(signature_ok,
                                             when(call("eq", call("len", call("field_code", var("source"), lit(4))), lit(0)),
                                                  bind("program", call("compile_expr", call("field_code", var("source"), lit(2)),
                                                                       lit(C.lst(("x0", "x1"))),
                                                                       lit(C.lst((60, 61))), lit(0), lit(0), lit(0)),
                                                       when(call("lt", call("len", var("program")), lit(47)),
                                                            call("concat", var("program"), emit(0, lit(0))), BAD)), BAD), BAD),
                                        BAD), BAD), BAD)), BAD), BAD)

    return (
        ("emit", ("opcode", "operand"), ("int", "int"), "list", emit_body),
        ("tail", ("values",), ("list",), "list", tail_body),
        ("lookup", ("name", "names", "slots"), ("str", "list", "list"), "int", lookup_body),
        ("branch", ("test", "rest", "body", "pc"), ("list", "list", "list", "int"), "list", branch_body),
        ("compile_expr", ("expr", "names", "slots", "depth", "lets", "pc"),
         ("expr", "list", "list", "int", "int", "int"), "list", walk_body),
        ("lcompile", ("source",), ("code",), "list", top),
    )


def build_library():
    """Build helpers; leave lcompile callable until translation validation."""
    world, atoms = world_and_atoms()
    library = LearnerLibrary(world, atoms)
    for name, params, sorts, output, body in _definitions():
        dependencies = n.references(body)
        layer = 1 + max((library.get(dep).layer for dep in dependencies), default=0)
        spec = OperationSpec(name, "transform", tuple(Edge(sort) for sort in sorts), Edge(output),
                             f"invented {name} kernel-node expansion", extra={"input_names": list(params)})
        library.write(Definition(name, "operation", "invented", layer,
                                 tuple(sorted(dependencies)), spec, body))
        library.check(name)
        sample = {
            "emit": (1, 0), "tail": (C.lst((1, 2)),),
            "lookup": ("x0", C.lst(("x0",)), C.lst((60,))),
            "branch": (C.lst((1, 0)), C.lst((1, 1)), C.lst((1, 2)), 0),
            "compile_expr": (C.encode_node(n.Lit(0)), C.lst(("x0",)), C.lst((60,)), 0, 0, 0),
            "lcompile": (C.make_code("operation", C.sig_op([("int", "bottom")], ("int", "bottom")),
                                     ("x",), n.Var("x"), lambda _: None),),
        }[name]
        library.make_callable(name, (sample,))
        if name != "lcompile":
            expected = {
                "emit": C.lst((1, 0)), "tail": C.lst((2,)), "lookup": 60,
                "branch": C.lst((1, 0, 7, 8, 1, 1, 6, 10, 1, 2)),
                "compile_expr": C.lst((1, 0)),
            }[name]
            request = VerifyRequest("bounded", (sample,),
                                    {"domain": "bound to the recorded 1 sample", "size": 1},
                                    reference=lambda *args, expected=expected: expected)
            library.verify(name, request)
            library.account(name)
            library.promote(name, Contract("Same output as the kernel-node expansion on the recorded sample"))
    return library


def compile_code(library: Library, source: Card):
    """Run the stored definition, returning a kernel Run (spec section 5)."""
    return library.run("lcompile", (source,))


def routine_identity(program):
    """Identity of a routine loaded at address 0 in n=64 (section 4.3)."""
    return routine_id(64, 0, C.items(program))


@dataclass(frozen=True)
class Validation:
    """Exact bounded validation ledger; rejected pairs are never evidence."""

    family_size: int
    accepted: dict[str, tuple[Card, Card]]
    rejected: dict[str, tuple[tuple[int, int, str], ...]]
    reasons: dict[str, int]
    compiler_steps: int
    scope: dict
    kernel_runs: dict[Card, kernel.Run] = field(default_factory=dict, repr=False, compare=False)
    deps_hash: str = ""
    world_hash: str = ""
    definition_hash: str = ""


def source_family():
    """All well-scoped trees <=5 nodes (var/lit/add/sub/let), plus 40 cases."""
    def trees(size, bound=()):
        if size == 1:
            return tuple(n.Var(name) for name in ("x0", "x1", *bound)) + tuple(n.Lit(value) for value in range(4))
        result = []
        for first_size in range(1, size - 1):
            second_size = size - first_size - 1
            if second_size < 1:
                continue
            result.extend(n.Call(op, (left, right)) for op in ("add", "sub")
                          for left in trees(first_size, bound) for right in trees(second_size, bound))
            name = f"v{len(bound)}"
            result.extend(n.Let(name, value, body) for value in trees(first_size, bound)
                          for body in trees(second_size, (*bound, name)))
        return tuple(result)

    small = tuple(expr for size in range(1, 6) for expr in trees(size))
    deeper = tuple(
        n.Let("temporary", n.Call("add", (n.Var("x0"), n.Lit(offset))),
              n.Case(((n.Test(n.Call("is_zero", (
                  n.Call("sub", (n.Var("temporary"), n.Lit(offset))),))),
                       n.Call("add", (n.Var("temporary"), n.Lit(offset)))),),
                     n.Call("sub", (n.Var("temporary"), n.Var("x0")))))
        for offset in range(39)
    ) + (n.Let("temporary", n.Call("sub", (
        n.Var("x0"), n.Call("add", (n.Lit(255), n.Var("x1"))))),
        n.Case(((n.Test(n.Call("is_zero", (n.Var("temporary"),))), n.Lit(7)),), n.Lit(9))),)
    signature = C.sig_op((("int", "bottom"), ("int", "bottom")), ("int", "bottom"))
    return tuple(C.make_code("operation", signature, ("x0", "x1"), expr, source_atom)
                 for expr in (*small, *deeper))


def run_batch_program(program, left, right, fuel=500):
    """Run one compiled vn/1 program with the section 5 calling convention.

    Return (status, accumulator or None, steps), matching reference.run's
    status, final accumulator, and instruction count. This is tooling, not an
    invented definition; tests compare it against the vn/1 reference machine.
    """
    memory = list(program)
    if len(memory) < 64:
        memory.extend((0,) * (64 - len(memory)))
    memory[60], memory[61] = left, right
    accumulator = pc = steps = 0
    while steps < fuel:
        opcode, operand = memory[pc], memory[(pc + 1) & 63]
        steps += 1
        if opcode == 0:
            return "ok", accumulator, steps
        pc = (pc + 2) & 63
        if opcode == 1:
            accumulator = operand
        elif opcode == 2:
            accumulator = memory[operand & 63]
        elif opcode == 3:
            memory[operand & 63] = accumulator
        elif opcode == 4:
            accumulator = (accumulator + memory[operand & 63]) & 255
        elif opcode == 5:
            accumulator = (accumulator - memory[operand & 63]) & 255
        elif opcode == 6:
            pc = operand & 63
        elif opcode == 7:
            if accumulator == 0:
                pc = operand & 63
        elif opcode == 8:
            accumulator = (accumulator + operand) & 255
        else:
            return "illegal", None, steps
    return "fuel", None, fuel


def source_value(expr, left, right):
    """Evaluate the section 5 source subset with exact integer arithmetic.

    This independent tooling evaluator is checked against the core kernel on
    a seeded family/input sample before using it for evidence.
    """
    def evaluate(node, bindings):
        if isinstance(node, n.Var):
            return bindings[node.name]
        if isinstance(node, n.Lit):
            return node.value
        if isinstance(node, n.Call):
            if node.fn == "is_zero":
                return evaluate(node.args[0], bindings) == 0
            first = evaluate(node.args[0], bindings)
            second = evaluate(node.args[1], bindings)
            if node.fn == "add":
                return first + second
            if node.fn == "sub":
                return first - second
        if isinstance(node, n.Let):
            value = evaluate(node.value, bindings)
            return evaluate(node.body, {**bindings, node.name: value})
        if isinstance(node, n.Case):
            for condition, body in node.arms:
                if evaluate(condition.expr, bindings):
                    return evaluate(body, bindings)
            return evaluate(node.default, bindings)
        raise ValueError(f"source outside the section 5 subset: {node!r}")

    return evaluate(expr, {"x0": left, "x1": right})


def _source_grid(expr):
    """Evaluate all 256 source inputs in one tree walk (section 5)."""
    def evaluate(node, bindings):
        if isinstance(node, n.Var):
            return bindings[node.name]
        if isinstance(node, n.Lit):
            return [node.value] * 256
        if isinstance(node, n.Call):
            if node.fn == "is_zero":
                return [value == 0 for value in evaluate(node.args[0], bindings)]
            first = evaluate(node.args[0], bindings)
            second = evaluate(node.args[1], bindings)
            if node.fn == "add":
                return [left + right for left, right in zip(first, second)]
            if node.fn == "sub":
                return [left - right for left, right in zip(first, second)]
        if isinstance(node, n.Let):
            return evaluate(node.body, {**bindings, node.name: evaluate(node.value, bindings)})
        if isinstance(node, n.Case):
            result = evaluate(node.default, bindings)
            for condition, body in reversed(node.arms):
                tests = evaluate(condition.expr, bindings)
                values = evaluate(body, bindings)
                result = [value if test else other for test, value, other in zip(tests, values, result)]
            return result
        raise ValueError(f"source outside the section 5 subset: {node!r}")

    return evaluate(expr, {"x0": [left for left in range(16) for _ in range(16)],
                           "x1": [right for _ in range(16) for right in range(16)]})


def validate_family(library, family=None):
    """Translate, run all 0..15 pairs, reject differing pairs (section 5)."""
    family = source_family() if family is None else tuple(family)
    accepted, rejected = {}, {}
    kernel_runs = {}
    reasons = {"overflow": 0, "negative_zero": 0}
    steps = 0
    source_atoms = (kernel.Atom("add", 2, lambda left, right: left + right),
                    kernel.Atom("sub", 2, lambda left, right: left - right),
                    kernel.Atom("is_zero", 1, lambda value: boolean(value == 0)))
    compiler_scope = library.scope()
    for source in family:
        digest = C.code_hash(source)
        compilation = kernel.call("lcompile", (source,), compiler_scope, dialect=library.dialect)
        steps += compilation.steps
        if not isinstance(compilation.outcome, Ok):
            raise TypeError(f"family source does not compile: {digest}: {compilation.outcome!r}")
        program = compilation.outcome.value
        decoded = C.decode(source).main
        source_scope = kernel.DictScope(source_atoms, (decoded,))
        source_results = _source_grid(decoded.body)
        program_bytes = C.items(program)
        padded_program = (*program_bytes, *((0,) * (64 - len(program_bytes))))
        failures = []
        for left in range(16):
            for right in range(16):
                source_result = source_results[left * 16 + right]
                status, accumulator, _ = run_batch_program(padded_program, left, right)
                if status != "ok":
                    raise AssertionError(f"vn/1 did not halt: {digest}, {left}, {right}: {status}")
                if not 0 <= source_result < 256:
                    failures.append((left, right, "overflow"))
                    reasons["overflow"] += 1
                elif accumulator != source_result:
                    traced = kernel.call(decoded.name, (left, right), source_scope, trace=True)

                    def has_negative_zero(frame):
                        return (frame.name == "is_zero" and len(frame.inputs) == 1
                                and type(frame.inputs[0]) is int and frame.inputs[0] < 0
                                and frame.inputs[0] % 256 == 0) or any(
                                    has_negative_zero(child) for child in frame.children)

                    if not has_negative_zero(traced.trace):
                        raise AssertionError(f"unexpected translation mismatch: {digest}, {left}, {right}: "
                                             f"source={source_result}, target={accumulator}")
                    failures.append((left, right, "negative_zero"))
                    reasons["negative_zero"] += 1
        if failures:
            rejected[digest] = tuple(failures)
        else:
            accepted[digest] = source, program
            kernel_runs[source] = compilation
    scope = {"domain": "bounded family: all 4578 well-scoped expressions <=5 nodes plus 40 nested let/case; "
                       "only accepted hashes, x0 and x1 each 0..15, vn/1 fuel 500",
             "size": len(accepted), "family_size": len(family), "inputs_per_program": 256,
             "pairs": [[digest, routine_identity(program)] for digest, (_, program) in sorted(accepted.items())],
             "accepted_hashes": sorted(accepted), "rejected_hashes": sorted(rejected),
             "rejected_pairs": sum(reasons.values())}
    return Validation(len(family), accepted, rejected, reasons, steps, scope, kernel_runs,
                      library.deps_hash("lcompile"), library.world.world_hash(),
                      content_hash(library.get("lcompile").to_dict()))


def promote_validated(library, validation):
    """Promote only programs whose every input pair translation-validated."""
    if library.get("lcompile").status != "callable":
        raise ValueError("lcompile must be callable, not already verified")
    request = VerifyRequest("bounded", tuple((source,) for source, _ in validation.accepted.values()),
                            validation.scope,
                            reference=lambda source: validation.accepted[C.code_hash(source)][1],
                            extra={"kernel_runs": validation.kernel_runs, "deps_hash": validation.deps_hash,
                                   "world_hash": validation.world_hash,
                                   "definition_hash": validation.definition_hash})
    library.verify("lcompile", request)
    library.account("lcompile")
    return library.promote("lcompile", Contract("Translation-validated only on accepted hashes and x0,x1 in 0..15"))
