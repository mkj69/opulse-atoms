"""Kernel-node vn/1 interpreter in an integer/list world (atoms-meta, section 5).

The generic ``compose`` given atom is needed because atoms-v2 has no card-construction
node: it constructs ordinary compose-object cards, never executes a machine instruction.
"""

from __future__ import annotations

from dataclasses import replace

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
)
from opulse.atoms.values import Bottom, Card, Ok, Unknown, boolean, outcome_equal
from opulse.atoms.world import WorldDecl
from opulse.meta.code import items, lst
from opulse.meta.vn import reference


def _get(xs, index):
    try:
        values = items(xs)
        return values[index] if type(index) is int and 0 <= index < len(values) else Bottom("index")
    except (TypeError, ValueError):
        return Bottom("index")


def _set(xs, index, value):
    try:
        values = items(xs)
        if type(index) is not int or not 0 <= index < len(values):
            return Bottom("index")
        result = list(values)
        result[index] = value
        return lst(result)
    except (TypeError, ValueError):
        return Bottom("index")


def _length(xs):
    return len(items(xs))


def _mod(left, right):
    return Bottom("div_zero") if right == 0 else left % right


def _illegal():
    return Bottom("illegal")


def _compose(sort, tag, fields):
    return Card(sort, tag, items(fields))


_GIVENS = (
    ("add", 2, lambda left, right: left + right, ("int", "int"), "int", (), 1),
    ("sub", 2, lambda left, right: left - right, ("int", "int"), "int", (), 1),
    ("mod", 2, _mod, ("int", "int"), "int", ("div_zero",), 1),
    ("is_zero", 1, lambda value: boolean(value == 0), ("int",), "bool", (), 1),
    ("eq", 2, lambda left, right: boolean(left == right), ("int", "int"), "bool", (), 1),
    ("lt", 2, lambda left, right: boolean(left < right), ("int", "int"), "bool", (), 1),
    ("list_get", 2, _get, ("list", "int"), "int", ("index",), 1),
    ("list_get_list", 2, _get, ("list", "int"), "list", ("index",), 1),
    ("list_set", 3, _set, ("list", "int", "int"), "list", ("index",), 1),
    ("list_set_list", 3, _set, ("list", "int", "list"), "list", ("index",), 1),
    ("list_set_str", 3, _set, ("list", "int", "str"), "list", ("index",), 1),
    ("list_len", 1, _length, ("list",), "int", (), 1),
    ("fail_illegal", 0, _illegal, (), "list", ("illegal",), 0),
    ("compose", 3, _compose, ("str", "str", "list"), "result", (), 0),
)


def _unfolded_interpreter(scope: kernel.DictScope) -> tuple[n.Node, tuple[str, ...]]:
    """Expand once; leave inputs free for each kernel evaluation (section 5)."""
    params = tuple(f"__meta_input_{index}" for index in range(4))
    body = scope.resolve("vn_interp").body
    occupied = {item.name for item in n.walk(body) if isinstance(item, (n.Var, n.Let))}
    if occupied.intersection(params):
        raise ValueError("interpreter input names must be fresh")
    return kernel.inline(n.Call("vn_interp", tuple(n.Var(param) for param in params)), scope), params


class InterpreterLibrary(Library):
    """Reuse one scope and unfolded tree for bounded vn/1 evidence (section 5)."""

    def verify(self, name: str, request: VerifyRequest) -> Definition:
        if name != "vn_interp" or request.reference is None:
            return super().verify(name, request)
        definition = self.get(name)
        if definition.status != "callable" or request.method not in ("exhaustive", "bounded", "sampled"):
            return super().verify(name, request)
        if request.method == "sampled" and request.seed is None:
            return super().verify(name, request)
        if request.scope.get("size") != len(request.domain) or "domain" not in request.scope:
            return super().verify(name, request)
        scope = self.scope()
        expanded, params = _unfolded_interpreter(scope)
        fuel = request.extra.get("fuel", DEFAULT_VERIFY_FUEL)
        limits = kernel.Limits(fuel=fuel)
        steps = []
        for args in request.domain:
            try:
                actual = kernel.call(name, args, scope, limits, dialect=self.dialect)
                reference = (kernel.call(request.reference, args, scope, limits, dialect=self.dialect).outcome
                             if isinstance(request.reference, str) else request.reference(*args))
                if not isinstance(reference, (Ok, Bottom, Unknown)):
                    reference = Ok(reference)
                if not outcome_equal(actual.outcome, reference):
                    raise PipelineError(f"reference counterexample {args!r}: {actual.outcome!r} != {reference!r}")
                unfolded = kernel.evaluate(expanded, dict(zip(params, args)), scope, limits,
                                           dialect=self.dialect)
                if not outcome_equal(actual.outcome, unfolded.outcome) or actual.steps != unfolded.steps:
                    raise PipelineError(f"unfold_equivalence counterexample {args!r}: {actual!r} != {unfolded!r}")
                steps.append(actual.steps)
            except PipelineError:
                raise
            except (ValueError, TypeError, KeyError, RecursionError) as error:
                raise PipelineError(f"counterexample {args!r}: {error}") from error
        recorded_scope = {**request.scope, "checked": {**checked_scope(request.domain), "by": "library"}}
        evidence = Evidence(request.method, recorded_scope, request.seed,
                            ("reference", "unfold_equivalence"), self.world.world_hash(),
                            self.deps_hash(name), self.content_hash(name), atoms_digest(self.atoms))
        self._steps[name] = steps
        self._library_checked.add(name)
        self._definitions[name] = replace(definition, evidence=evidence)
        return self._advance(name, "verified")


def _call(name, *args):
    return n.Call(name, args)


def _var(name):
    return n.Var(name)


def _lit(value):
    return n.Lit(value)


def _test(name, *args):
    return n.Test(_call(name, *args))


def _when_eq(value, number, body, otherwise):
    return n.Case(((_test("eq", value, _lit(number)), body),), otherwise)


def _byte(expression):
    return _call("mod", expression, _lit(256))


def _address(expression, mem):
    return _call("mod", expression, _call("list_len", mem))


def _state(acc, mem, pc):
    result = _lit(lst((0, lst(), 0)))
    for index, value in enumerate((acc, mem, pc)):
        result = _call("list_set_list" if index == 1 else "list_set", result, _lit(index), value)
    return result


def _result(tag, *fields):
    result = _lit(lst((0,) * len(fields)))
    for index, value in enumerate(fields):
        setter = ("list_set_list" if tag == "ok" and index == 1 else
                  "list_set_str" if tag in ("err", "out") else "list_set")
        result = _call(setter,
                       result, _lit(index), value)
    return _call("compose", _lit("result"), _lit(tag), result)


def _operand():
    return _call("list_get", _var("mem"),
                 _address(_call("add", _var("pc"), _lit(1)), _var("mem")))


def _instruction():
    mem, acc, pc, operand = (_var(name) for name in ("mem", "a", "pc", "operand"))
    next_pc = _address(_call("add", pc, _lit(2)), mem)
    address = _address(operand, mem)
    branches = (
        _state(acc, mem, pc),
        _state(operand, mem, next_pc),
        _state(_call("list_get", mem, address), mem, next_pc),
        _state(acc, _call("list_set", mem, address, acc), next_pc),
        _state(_byte(_call("add", acc, _call("list_get", mem, address))), mem, next_pc),
        _state(_byte(_call("sub", acc, _call("list_get", mem, address))), mem, next_pc),
        _state(acc, mem, address),
        n.Case(((_test("is_zero", acc), _state(acc, mem, address)),),
               _state(acc, mem, next_pc)),
        _state(_byte(_call("add", acc, operand)), mem, next_pc),
    )
    body = _call("fail_illegal")
    for opcode in reversed(range(len(branches))):
        body = _when_eq(_var("op"), opcode, branches[opcode], body)
    return n.Let("operand", _operand(), body)


def _loop():
    mem, acc, pc, remaining = (_var(name) for name in ("memory", "acc", "position", "remaining"))
    step = _call("exec_one", mem, acc, pc, _var("opcode"))
    moved = _call("loop", _call("list_get_list", _var("next"), _lit(1)),
                  _call("list_get", _var("next"), _lit(0)),
                  _call("list_get", _var("next"), _lit(2)),
                  _call("sub", remaining, _lit(1)))
    body = n.Case(((_test("is_zero", remaining), _result("out", _lit("fuel"))),),
                  n.Let("opcode", _call("fetch", mem, pc),
                        n.Case(((_test("eq", _var("opcode"), _lit(0)), _result("ok", acc, mem)),
                                (_test("lt", _var("opcode"), _lit(9)),
                                 n.Let("next", step, moved))),
                               _result("err", _lit("illegal")))))
    return n.Rec("loop", ("memory", "acc", "position", "remaining"), body,
                 (_var("mem"), _var("a"), _var("pc"), _var("fuel")), remaining)


def _operation(name, input_sorts, output_sort, body, layer):
    params = {"fetch": ("mem", "pc"), "exec_one": ("mem", "a", "pc", "op"),
              "vn_interp": ("mem", "a", "pc", "fuel")}[name]
    from opulse.atoms.nodes import references

    spec = OperationSpec(name, "transform", tuple(Edge(sort) for sort in input_sorts),
                         Edge(output_sort), "Kernel-node vn/1 interpretation",
                         extra={"input_names": list(params)})
    return Definition(name, "operation", "invented", layer, tuple(sorted(references(body))), spec, body)


def make_library() -> Library:
    """Build and type-check the interpreter world (atoms-meta, section 5)."""
    atoms = tuple(kernel.Atom(name, arity, fn, cost=cost) for name, arity, fn, _, _, _, cost in _GIVENS)
    operations = tuple(OperationSpec(name, "decide" if output == "bool" else "transform",
                                     tuple(Edge(sort) for sort in inputs), Edge(output),
                                     "Integer/list primitive" if name != "compose" else "Generic compose-card constructor",
                                     errors, cost=cost,
                                     extra={"input_names": [f"arg{index}" for index in range(arity)]})
                       for name, arity, _, inputs, output, errors, cost in _GIVENS)
    world = WorldDecl("vn_integer_interp", 1, "atoms-v2", {}, {},
                      (ObjectSpec("int", "given"), ObjectSpec("str", "given"),
                       ObjectSpec("bool", "given"), ObjectSpec("list", "given"),
                       ObjectSpec("result", "compose", tags={"ok": [["a", "int"], ["mem", "list"]],
                                                                "err": [["reason", "str"]],
                                                                "out": [["reason", "str"]]})),
                      operations, {"nodes": ["Var", "Lit", "Call", "Let", "Case", "Rec"],
                                   "recursion": "measure"},
                      {"truth": None, "probes": [], "judge_view": "full_state"}, {})
    library = InterpreterLibrary(world, atoms)
    definitions = (
        _operation("fetch", ("list", "int"), "int",
                   _call("list_get", _var("mem"), _var("pc")), 1),
        _operation("exec_one", ("list", "int", "int", "int"), "list", _instruction(), 1),
        _operation("vn_interp", ("list", "int", "int", "int"), "result", _loop(), 2),
    )
    for definition in definitions:
        library.write(definition)
        library.check(definition.name)
        sample = {"fetch": (lst((0,) * 16), 0),
                  "exec_one": (lst((0,) * 16), 0, 0, 1),
                  "vn_interp": (lst((0,) * 16), 0, 0, 2)}[definition.name]
        library.make_callable(definition.name, (sample,))
    return library


def expected(mem: Card, acc: int, pc: int, fuel: int):
    """Independent reference adapter for bounded library verification."""
    status, state, _ = reference.run(reference.State(pc, acc, items(mem)), fuel)
    if status == "ok":
        return Card("result", "ok", (state.a, lst(state.mem)))
    return Card("result", "err" if status == "illegal" else "out",
                ("illegal" if status == "illegal" else "fuel",))


def verify_library(library: Library, domain: tuple[tuple, ...],
                   description: str = "bounded n=16, fuel <=12; caller-supplied recorded tuples") -> Library:
    """Run bounded reference/unfold checks, account, and promote all three definitions."""
    for name, arguments, reference_fn in (
        ("fetch", ((lst((0,) * 16), 0),), lambda mem, pc: items(mem)[pc]),
        ("exec_one", ((lst((1, 7) + (0,) * 14), 0, 0, 1),),
         lambda mem, acc, pc, op: lst((7, mem, 2))),
        ("vn_interp", domain, expected),
    ):
        request = VerifyRequest("bounded", arguments,
                                {"domain": description if name == "vn_interp" else
                                 "bounded n=16, one recorded primitive sample",
                                 "size": len(arguments)}, reference=reference_fn)
        library.verify(name, request)
        library.account(name)
        library.promote(name, Contract("Matches reference within recorded scope"))
    return library
