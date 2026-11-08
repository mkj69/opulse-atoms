"""Bounded translation validation (docs/spec/atoms-meta.md, section 5)."""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass
from itertools import product

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.values import Bottom, Ok, Unknown, boolean, encode
from opulse.definition.interpreter import run_with_deep_stack
from opulse.meta import code as C
from opulse.meta.compiler.compile import CompileError, Prog, compile_tiny
from opulse.meta.compiler.tiny import check_tiny, definition

_ARITIES = {"add": 2, "sub": 2, "is_zero": 1}
_DIGESTS = {name: hashlib.sha256(f"tiny/1:{name}:{arity}:exact-integer".encode()).hexdigest()
            for name, arity in _ARITIES.items()}


def source_code(body, params, defs=None):
    """Quote a tiny body, including the complete transitive definition closure."""
    defs = defs or {}
    memo = {}

    def quote_dep(name):
        if name not in memo:
            dep_body, dep_params = definition(defs[name])
            memo[name] = C.make_code("operation", signature(len(dep_params)), dep_params,
                                     dep_body, resolve)
        return memo[name]

    def resolve(name):
        if name in _DIGESTS:
            return C.Resolved(digest=_DIGESTS[name])
        if name in defs:
            return C.Resolved(code=quote_dep(name))
        return None

    return C.make_code("operation", signature(len(params)), params, body, resolve)


def signature(arity):
    return C.sig_op([("int", "bottom")] * arity, ("int", "bottom"))


def routine_id(prog: Prog) -> str:
    """Routine identity of the program bytes at base 0 (atoms-meta 4.3)."""
    from opulse.meta.vn.report import routine_id as vn_routine_id

    return vn_routine_id(prog.n, 0, prog.code)


def prog_hash(prog: Prog) -> str:
    """Identity of the full prog card (atoms-meta 5), not just its routine bytes."""
    payload = json.dumps(encode(prog.card), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(("opulse.prog/1\n" + payload).encode("ascii")).hexdigest()


@dataclass(frozen=True)
class Counterexample:
    inputs: tuple[int, ...]
    source: object
    compiled: object
    source_steps: int
    compiled_steps: int
    reason: str


@dataclass(frozen=True)
class ValidationResult:
    method: str
    scope: dict
    pair: tuple[str, str]
    accepted: bool
    counterexample: Counterexample | None = None
    unverifiable: tuple[Counterexample, ...] = ()
    routine_id: str = ""

    @property
    def source_hash(self):
        return self.pair[0]

    @property
    def prog_id(self):
        return self.pair[1]


def validate(source_body, params, prog: Prog, scope_inputs, fuel, full_state=False) -> ValidationResult:
    """Accept only exact source/result agreement on every enumerated input tuple.

    The source is an integer operation, not a state transition; full-state comparisons
    are unverifiable without a source-state specification.
    """
    params = tuple(params)
    inputs = tuple(tuple(row) for row in scope_inputs)
    errors = check_tiny(source_body, params, prog.defs)
    if errors:
        raise ValueError("; ".join(errors))
    if len(params) != len(prog.args):
        raise ValueError("parameter count does not match program")
    prog._check_interface()
    identity = (C.code_hash(source_code(source_body, params, prog.defs)), prog_hash(prog))
    scope = {"domain": inputs, "size": len(inputs), "description": "explicit tiny/1 input tuples"}
    atoms = [kernel.Atom("add", 2, lambda left, right: left + right),
             kernel.Atom("sub", 2, lambda left, right: left - right),
             kernel.Atom("is_zero", 1, lambda value: boolean(value == 0))]
    definitions = [kernel.Defn(name, definition(value)[1], definition(value)[0])
                   for name, value in prog.defs.items()]
    definitions.append(kernel.Defn("__tiny_source__", params, source_body))
    world = kernel.DictScope(atoms, definitions)
    unverifiable = []
    first = None
    for row in inputs:
        if len(row) != len(params) or any(type(value) is not int or not 0 <= value < 256 for value in row):
            raise ValueError("scope input must be a tuple of bytes, one per parameter")
        source_run = kernel.call("__tiny_source__", row, world, limits=kernel.Limits(fuel=fuel))
        source = source_run.outcome
        if isinstance(source, Ok) and (type(source.value) is not int or not 0 <= source.value < 256):
            source = Bottom("overflow")
        status, final, compiled_steps = prog.run(row, fuel)
        compiled = Ok(final.a) if status == "ok" else (Bottom("illegal") if status == "illegal"
                                                          else Unknown("fuel"))
        reason = None
        if full_state:
            reason = "no source full-state semantics"
        elif isinstance(source, Unknown) or isinstance(compiled, Unknown):
            reason = "fuel: outcome unverifiable"
        elif isinstance(source, Bottom):
            if compiled != source:
                reason = ("Bottom reason mismatch" if isinstance(compiled, Bottom) else
                          "overflow" if source.reason == "overflow" else "source Bottom vs compiled Ok")
        elif not isinstance(compiled, Ok) or compiled.value != source.value:
            reason = "value mismatch" if isinstance(compiled, Ok) else "compiled Bottom vs source Ok"
            if reason == "value mismatch":
                traced = kernel.call("__tiny_source__", row, world,
                                     limits=kernel.Limits(fuel=fuel), trace=True).trace
                def negative_zero_test(frame):
                    return ((frame.name == "is_zero" and frame.inputs and
                             type(frame.inputs[0]) is int and frame.inputs[0] < 0) or
                            any(negative_zero_test(child) for child in frame.children))
                if traced is not None and negative_zero_test(traced):
                    reason = "is_zero on negative intermediate"
        if reason:
            example = Counterexample(row, source, compiled, source_run.steps, compiled_steps, reason)
            if "unverifiable" in reason or full_state:
                unverifiable.append(example)
            if first is None:
                first = example
            break
    return ValidationResult("bounded", scope, identity, bool(inputs) and first is None,
                            first, tuple(unverifiable), routine_id(prog))


def tiny_family():
    """All 1806 expressions of the finite arithmetic grammar through five nodes.

    Grammar: E := x0 | x1 | 0 | 1 | 2 | 3 | add(E,E) | sub(E,E).
    A call counts as one node; sizes 1, 3, 5 contribute 6, 72, 1728.
    No binder names or Rec arities are included (those have unbounded grammars).
    """
    by_size = {1: tuple([n.Var("x0"), n.Var("x1")] + [n.Lit(value) for value in range(4)])}
    for size in (3, 5):
        by_size[size] = tuple(n.Call(op, (left, right)) for op in ("add", "sub")
                              for left_size in range(1, size - 1)
                              for left in by_size.get(left_size, ())
                              for right in by_size.get(size - 1 - left_size, ()))
    return tuple(node for size in (1, 3, 5) for node in by_size[size])


@dataclass(frozen=True)
class FamilyResult:
    method: str
    scope: dict
    total: int
    passed: int
    rejected: tuple


def _validate_compiler(family, scope) -> FamilyResult:
    """Check each source and machine result on the recorded finite domain (section 5)."""
    family = tiny_family() if family is None else tuple(family)
    inputs = tuple(product(range(16), repeat=2)) if scope is None else tuple(tuple(row) for row in scope)
    if not inputs or not family:
        raise ValueError("compiler validation needs a non-empty family and input scope")
    passed = 0
    rejected = []
    for index, member in enumerate(family):
        body, params = (member, ("x0", "x1")) if isinstance(member, n.NODE_TYPES) else definition(member)
        try:
            prog = compile_tiny(body, params)
            result = validate(body, params, prog, inputs, fuel=10000)
        except CompileError as exc:
            rejected.append((index, str(exc)))
            continue
        if result.accepted:
            passed += 1
        else:
            rejected.append((index, result.counterexample.reason, result.counterexample.inputs))
    return FamilyResult("bounded", {"domain": inputs, "size": len(inputs),
                                     "description": "explicit tiny/1 input tuples"},
                        len(family), passed, tuple(rejected))


def validate_compiler(family=None, scope=None) -> FamilyResult:
    """Compile and validate a family in one worker; nested kernel calls reuse its deep stack."""
    if threading.current_thread().name.startswith("opulse-eval"):
        return _validate_compiler(family, scope)
    return run_with_deep_stack(_validate_compiler, family, scope)
