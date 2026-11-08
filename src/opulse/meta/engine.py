"""Metered meta operations (atoms-meta sections 2.5-2.7 and 8)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from contextvars import ContextVar
from dataclasses import dataclass, replace

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.library import atoms_digest
from opulse.atoms.values import Bottom, Card, Ok, Outcome, Unknown
from opulse.definition.interpreter import run_with_deep_stack
from opulse.meta import code

_NO_LIMITS = kernel.Limits()
_INSIDE_ENGINE_WORKER = ContextVar("opulse_meta_engine_worker", default=False)
_CALLABLE_KINDS = (*code.CALLABLE_KINDS, "law", "bridge")


class _WorldAtoms(Sequence):
    """Keep runtime atoms while giving core evidence a stable closure (spec 9.I4)."""

    def __init__(self, atoms: Sequence[kernel.Atom]) -> None:
        self.atoms = tuple(atoms)
        self.digest = atoms_digest(self.atoms)

    def __len__(self) -> int:
        return len(self.atoms)

    def __getitem__(self, index):
        return self.atoms[index]

    def __repr__(self) -> str:
        return f"WorldAtoms({self.digest})"


@dataclass(frozen=True)
class MeteredAtom(kernel.Atom):
    """A core metered atom; meta intercepts calls to preserve spec 2.6 budget ties."""

    cost: int = 0
    metered: bool = True
    world_atoms: tuple = ()
    digests: Mapping[str, str] | None = None
    opened_nodes: frozenset[str] | None = None


class _Context:
    def __init__(self, engine: _Engine) -> None:
        self.engine = engine

    def call(self, defn: kernel.Defn, args: tuple,
             extra_defns: tuple[kernel.Defn, ...] = (), budget: int | None = None) -> Outcome:
        engine = self.engine
        previous_scope = engine.scope
        previous_budget = engine.deadline
        previous_depth = engine.limits
        inner_depth_limit = engine.depth + 1000
        if budget is not None:
            own_deadline = engine.steps + max(0, budget)
            engine.deadline = min(own_deadline, previous_budget) if previous_budget is not None else own_deadline
            engine.limits = kernel.Limits(previous_depth.fuel, min(previous_depth.max_depth, inner_depth_limit),
                                          previous_depth.max_nodes)
        engine.scope = _extend(previous_scope, (defn, *extra_defns))
        try:
            result = engine.invoke(defn.name, tuple(n.Lit(arg) for arg in args), {}, {}, defn.layer)
            if budget is not None and result in (Unknown("budget"), Unknown("outer_budget")):
                # The run whose own deadline was hit reports out; when nested budgets end at the same step the
                # innermost run owns it, because no run takes the step after its budget (atoms-meta 2.6).
                return Unknown("budget") if engine.exhausted == own_deadline else Unknown("outer_budget")
            if result == Unknown("budget"):  # an eval between this frame and the run that owns the deadline
                return Unknown("outer_budget")
            if budget is not None and result == Unknown("depth") and inner_depth_limit <= previous_depth.max_depth:
                return Unknown("budget")
            return result
        finally:
            engine.scope = previous_scope
            engine.deadline = previous_budget
            engine.limits = previous_depth


class _ExtendedScope(kernel.DictScope):
    def __init__(self, scope: kernel.Scope, defns: Sequence[kernel.Defn]) -> None:
        super().__init__(defns=defns)
        self.parent = scope

    def resolve(self, name):
        return self.defns.get(name) or self.parent.resolve(name)


def _extend(scope: kernel.Scope, defns: Sequence[kernel.Defn]) -> kernel.DictScope:
    return _ExtendedScope(scope, defns)


def _bound(node, names: frozenset[str]) -> bool:
    if isinstance(node, n.Var):
        return node.name in names
    if isinstance(node, n.Let):
        return _bound(node.value, names) and _bound(node.body, names | {node.name})
    if isinstance(node, n.Rec):
        return (all(_bound(arg, names) for arg in node.args) and
                _bound(node.body, names | {node.fn, *node.params}) and
                (isinstance(node.measure, str) or _bound(node.measure, names | set(node.params))))
    if isinstance(node, n.Blocks):
        inner = names
        for name, init in node.vars:
            if not _bound(init, inner):
                return False
            inner = inner | {name}
        labels = {label for label, _ in node.blocks}
        for _, block in node.blocks:
            end = block.end
            targets = (end.target,) if isinstance(end, n.Jump) else (
                (end.then, end.else_) if isinstance(end, n.CondJump) else ())
            if any(target not in labels for target in targets):
                return False
        return all(_bound(child, inner) for child in list(n.children(node))[len(node.vars):])
    return all(_bound(child, names) for child in n.children(node))


class _Engine(kernel._Engine):
    """Only metered invocations and budget charging differ from the core engine."""

    def __init__(self, scope, limits, trace, dialect):
        super().__init__(scope, limits, trace, dialect)
        self.deadline: int | None = None
        self.exhausted: int | None = None  # the run deadline that stopped the evaluation

    def charge(self, cost: int, jump: bool = False):
        # A run budget that ends no later than the outer fuel wins: run stops at its budget and never
        # needs the step that would exhaust the outer fuel (atoms-meta 2.6).
        if (self.deadline is not None and self.steps + cost > self.deadline and
                (self.limits.fuel is None or self.deadline <= self.limits.fuel)):
            self.exhausted = self.deadline
            return Unknown("budget")
        if self.limits.fuel is not None and self.steps + cost > self.limits.fuel:
            return Unknown("fuel")
        return super().charge(cost, jump)

    def measure(self, node, env, local, layer):
        silent = _Engine(self.scope, kernel.Limits(fuel=self.limits.fuel,
                                                   max_depth=self.limits.max_depth), False, self.dialect)
        silent.depth = self.depth
        return silent.eval(node, env, local, layer)

    def invoke(self, name, args, env, local, layer, initial=False):
        reference = env.get(name)
        resolved = reference.name if isinstance(reference, kernel.FnRef) else name
        target = None if name in local else self.scope.resolve(resolved)
        if not isinstance(target, MeteredAtom):
            return super().invoke(name, args, env, local, layer, initial)
        if len(args) != target.arity:
            raise TypeError(f"{name!r} takes {target.arity} arguments, got {len(args)}")
        outcomes = []
        for arg in args:
            outcome = self.eval(arg, env, local, layer)
            outcomes.append(outcome)
            if not isinstance(outcome, Ok):
                return outcome
        frame = self.frame(target.name, target.kind, 0, True)
        if isinstance(frame, Unknown):
            return frame
        if frame is not None:
            frame.metered = True
        start = self.steps
        result: Outcome = Unknown("pending")
        try:
            result = target.fn(_Context(self), *(item.value for item in outcomes))
            return result
        finally:
            if frame is not None:
                frame.inputs = tuple(item.value for item in outcomes)
                frame.outcome = result
                frame.steps = self.steps - start
                self.frames.pop()


def evaluate(node: n.Node, env: Mapping[str, object] = {}, scope: kernel.Scope | None = None,
             limits: kernel.Limits = _NO_LIMITS, trace: bool = False,
             dialect: str = "atoms-v2") -> kernel.Run:
    """Evaluate with the kernel's root, accounting and trace conventions (spec 2.7)."""
    if dialect not in ("atoms-v2", "legacy-v1"):
        raise ValueError(f"unknown dialect: {dialect!r}")
    engine = _Engine(scope if scope is not None else kernel.DictScope(), limits, trace, dialect)

    def execute():
        root = (kernel.CallNode(None, "root", 0, False, (), (), Unknown("pending"), 0)
                if trace and (limits.max_nodes is None or limits.max_nodes >= 1) else None)
        if root is not None:
            engine.frames.append(root)
            engine.nodes = 1
        outcome = (Unknown("nodes") if trace and limits.max_nodes is not None and limits.max_nodes < 1
                   else engine.eval(node, env, {}, 1))
        if root is not None:
            root.outcome = outcome
            root.steps = engine.steps
        return kernel.Run(outcome, engine.steps, engine.jumps, root, engine.work)

    if _INSIDE_ENGINE_WORKER.get():
        return execute()

    def in_worker():
        token = _INSIDE_ENGINE_WORKER.set(True)
        try:
            return execute()
        finally:
            _INSIDE_ENGINE_WORKER.reset(token)

    return run_with_deep_stack(in_worker)


def call(name: str, args: Sequence[object], scope: kernel.Scope,
         limits: kernel.Limits = _NO_LIMITS, trace: bool = False,
         dialect: str = "atoms-v2") -> kernel.Run:
    return evaluate(n.Call(name, tuple(n.Lit(arg) for arg in args)), scope=scope,
                    limits=limits, trace=trace, dialect=dialect)


def _operation_calls(decoded: code.Decoded) -> dict[int, set[int]]:
    """Find unshadowed operation parameter call arities, including nested binders (spec 2.5)."""
    params = {name: index for index, name in enumerate(decoded.main.params)}
    calls: dict[int, set[int]] = {}

    def visit(node, shadowed):
        if isinstance(node, n.Call) and node.fn in params and node.fn not in shadowed:
            calls.setdefault(params[node.fn], set()).add(len(node.args))
        if isinstance(node, n.Let):
            visit(node.value, shadowed)
            visit(node.body, shadowed | {node.name})
        elif isinstance(node, n.Rec):
            for arg in node.args:
                visit(arg, shadowed)
            visit(node.body, shadowed | {node.fn, *node.params})
            if not isinstance(node.measure, str):
                visit(node.measure, shadowed | set(node.params))
        else:
            for child in n.children(node):
                visit(child, shadowed)

    visit(decoded.main.body, frozenset())
    return calls


def _known_sort(value: object) -> str | None:
    if isinstance(value, Card):
        return value.sort
    if type(value) is bool:
        return "bool"
    if type(value) is int:
        return "int"
    if type(value) is str:
        return "str"
    return None


def _prepare(value: Card, xs: Card, digests: Mapping[str, str], scope: kernel.Scope,
             opened_nodes: frozenset[str] | None, world_atoms: Sequence[kernel.Atom],
             digest_known: bool):
    try:
        arguments = code.items(xs)
        value = code._need(value, "code", "def", 5)
        kind, sig = value.fields[:2]
        if code._SIG_KIND.get(sig.tag) != kind:
            return Bottom("ill_formed")
        arity = code.sig_arity(sig)
    except (code.CodeError, ValueError, TypeError, KeyError, IndexError, AttributeError):
        return Bottom("ill_formed")
    if len(arguments) != arity:
        return Bottom("arity")
    try:
        if not code.is_canonical(value):
            return Bottom("ill_formed")
        decoded = code.decode(value)
    except (code.CodeError, ValueError, TypeError, KeyError, IndexError, AttributeError):
        return Bottom("ill_formed")
    given = {atom.name: atom for atom in world_atoms}
    for name in ("eval", "run"):
        metered = scope.resolve(name)
        if isinstance(metered, MeteredAtom):
            given[name] = metered
    checked = _check_code(value, decoded, digests, opened_nodes, given, digest_known)
    if checked is not None:
        return checked
    if decoded.kind not in _CALLABLE_KINDS:
        return Bottom("not_callable")
    if decoded.kind == "law":
        for argument, variable in zip(arguments, code.items(decoded.sig.fields[0])):
            actual = _known_sort(argument)
            expected = variable.fields[1]
            if actual is not None and expected in ("int", "str", "bool") and actual != expected:
                return Bottom("ill_formed")
    converted = []
    argument_defns = []
    call_arities = _operation_calls(decoded)
    op_params = (set(code.items(decoded.sig.fields[1])) if decoded.kind == "combinator"
                 else set(call_arities))
    for index, arg in enumerate(arguments):
        if index in op_params and not (isinstance(arg, Card) and (arg.sort == "code" or
                                                                    arg.sort == "expr" and arg.tag == "fn")):
            return Bottom("ill_formed")  # the body calls this parameter, so it must receive an operation
        if index in op_params and isinstance(arg, Card) and arg.sort == "code":
            try:
                if not code.is_canonical(arg):
                    return Bottom("ill_formed")
                argument = code.decode(arg)
            except (code.CodeError, ValueError, TypeError, KeyError, IndexError, AttributeError):
                return Bottom("ill_formed")
            if argument.kind != "operation":
                return Bottom("ill_formed")
            if any(arity != len(argument.main.params) for arity in call_arities.get(index, ())):
                return Bottom("ill_formed")
            checked = _check_code(arg, argument, digests, opened_nodes, given, digest_known)
            if checked is not None:
                return checked
            argument_defns.extend((argument.main, *argument.deps))
            arg = kernel.FnRef(argument.main.name)
        elif isinstance(arg, Card) and arg.sort == "expr" and arg.tag == "fn":
            try:
                arg = code.decode_node(arg).value
            except (code.CodeError, AttributeError):
                return Bottom("ill_formed")
            if arg.name not in given:
                return Bottom("ill_formed")
            if any(arity != given[arg.name].arity for arity in call_arities.get(index, ())):
                return Bottom("ill_formed")
        converted.append(arg)
    return replace(decoded, deps=(*decoded.deps, *argument_defns)), tuple(converted), kernel.DictScope(atoms=given)


def _check_code(value: Card, decoded: code.Decoded, digests: Mapping[str, str],
                opened_nodes: frozenset[str] | None, given: Mapping[str, object],
                digest_known: bool) -> Bottom | None:
    closure = (value, *(dep for dep in code.items(value.fields[4])
                        if isinstance(dep, Card) and dep.sort == "code"))
    definitions = (decoded.main, *decoded.deps)
    declared = {name for name, _ in decoded.atoms}
    operations = {defn.name for defn in definitions if defn.kind in ("operation", "template")}
    inner = kernel.DictScope(atoms=given, defns=definitions)
    for defn in definitions if digest_known or decoded.kind in _CALLABLE_KINDS else ():
        if opened_nodes is not None and not n.node_kinds(defn.body) <= frozenset(opened_nodes):
            return Bottom("ill_formed")
        if not _bound(defn.body, frozenset(defn.params)):
            return Bottom("ill_formed")
        if any(inner.resolve(name) is None or name not in declared and not name.startswith("#")
               for name in n.references(defn.body) - set(defn.params)):
            return Bottom("ill_formed")
        if any((inner.resolve(item.value.name) is None or
                item.value.name not in declared and item.value.name not in operations)
               and item.value.name not in defn.params
               for item in n.walk(defn.body)
               if isinstance(item, n.Lit) and isinstance(item.value, kernel.FnRef)):
            return Bottom("ill_formed")
    if (digest_known or decoded.kind in _CALLABLE_KINDS) and any(
           digests.get(name) != digest for card in closure for name, digest in
           (atom.fields for atom in code.items(card.fields[3]))):
        return Bottom("foreign_code")
    return None


def eval_atom(world_atoms: Sequence[kernel.Atom], atom_digests: Mapping[str, str] | None = None,
             opened_nodes: frozenset[str] | None = None) -> MeteredAtom:
    """Given eval(c, xs); its child call uses the same engine (spec 2.5)."""
    digests = atom_digests if atom_digests is not None else {}
    stable_atoms = _WorldAtoms(world_atoms)
    opened = tuple(sorted(opened_nodes)) if opened_nodes is not None else None

    def apply(ctx, value, xs):
        prepared = _prepare(value, xs, digests, ctx.engine.scope, opened, stable_atoms,
                            atom_digests is not None)
        if isinstance(prepared, Bottom):
            return prepared
        decoded, arguments, inner_scope = prepared
        previous = ctx.engine.scope
        ctx.engine.scope = inner_scope
        try:
            return ctx.call(decoded.main, arguments, decoded.deps)
        finally:
            ctx.engine.scope = previous

    return MeteredAtom("eval", 2, apply, world_atoms=tuple(world_atoms),
                       digests=atom_digests, opened_nodes=opened_nodes)


def run_atom(world_atoms: Sequence[kernel.Atom], atom_digests: Mapping[str, str] | None = None,
             opened_nodes: frozenset[str] | None = None) -> MeteredAtom:
    """Given run(c, xs, budget); failures are values except preflight (spec 2.6)."""
    digests = atom_digests if atom_digests is not None else {}
    stable_atoms = _WorldAtoms(world_atoms)
    opened = tuple(sorted(opened_nodes)) if opened_nodes is not None else None

    def apply(ctx, value, xs, budget):
        prepared = _prepare(value, xs, digests, ctx.engine.scope, opened, stable_atoms,
                            atom_digests is not None)
        if isinstance(prepared, Bottom):
            return prepared
        if type(budget) is not int or budget < 0:
            return Bottom("ill_formed")
        decoded, arguments, inner_scope = prepared
        previous = ctx.engine.scope
        ctx.engine.scope = inner_scope
        try:
            result = ctx.call(decoded.main, arguments, decoded.deps, budget=budget)
        finally:
            ctx.engine.scope = previous
        if isinstance(result, Ok):
            return Ok(Card("result", "ok", (result.value,)))
        if isinstance(result, Bottom):
            return Ok(Card("result", "err", (result.reason,)))
        if result.resource == "budget":
            return Ok(Card("result", "out", (budget,)))
        return result

    return MeteredAtom("run", 3, apply, world_atoms=tuple(world_atoms),
                       digests=atom_digests, opened_nodes=opened_nodes)


def inline(node: n.Node, scope: kernel.Scope) -> n.Node:
    """Unfold literal eval calls and then ordinary definitions (spec 2.7, I1)."""
    defns: dict[str, kernel.Defn] = {}

    def condition(cond):
        if isinstance(cond, n.Test):
            return n.Test(expand(cond.expr))
        if isinstance(cond, (n.And, n.Or)):
            return type(cond)(condition(cond.left), condition(cond.right))
        if isinstance(cond, n.Not):
            return n.Not(condition(cond.operand))
        return cond

    def expand(expr):
        if isinstance(expr, n.Call):
            args = tuple(expand(arg) for arg in expr.args)
            if expr.fn == "eval" and len(args) == 2 and all(isinstance(arg, n.Lit) for arg in args):
                value, xs = (arg.value for arg in args)
                try:
                    metered = scope.resolve("eval")
                    if not isinstance(metered, MeteredAtom):
                        return n.Call(expr.fn, args)
                    prepared = _prepare(value, xs, metered.digests or {}, scope, metered.opened_nodes,
                                        metered.world_atoms, metered.digests is not None)
                    if isinstance(prepared, Bottom):
                        return n.Call(expr.fn, args)
                    decoded, converted, _ = prepared
                    for defn in (decoded.main, *decoded.deps):
                        if defn.name not in defns:
                            defns[defn.name] = defn
                            defns[defn.name] = kernel.Defn(defn.name, defn.params, expand(defn.body),
                                                            defn.kind, defn.layer)
                    return n.Call(decoded.main.name, tuple(n.Lit(item) for item in converted))
                except (code.CodeError, ValueError, TypeError, KeyError, IndexError, AttributeError):
                    pass
            return n.Call(expr.fn, args)
        if isinstance(expr, n.Let):
            return n.Let(expr.name, expand(expr.value), expand(expr.body))
        if isinstance(expr, n.Case):
            return n.Case(tuple((condition(cond), expand(body)) for cond, body in expr.arms),
                          expand(expr.default) if expr.default is not None else None)
        if isinstance(expr, n.Rec):
            return n.Rec(expr.fn, expr.params, expand(expr.body), tuple(expand(arg) for arg in expr.args),
                         expr.measure if isinstance(expr.measure, str) else expand(expr.measure), expr.memo)
        if isinstance(expr, n.Blocks):
            blocks = []
            for label, block in expr.blocks:
                end = block.end
                if isinstance(end, n.CondJump):
                    end = n.CondJump(condition(end.cond), end.then, end.else_)
                elif isinstance(end, n.Halt):
                    end = n.Halt(expand(end.value))
                blocks.append((label, n.Block(tuple((name, expand(value)) for name, value in block.assigns), end)))
            return n.Blocks(tuple((name, expand(value)) for name, value in expr.vars), expr.entry, tuple(blocks))
        return expr

    expanded = expand(node)
    return kernel.inline(expanded, _extend(scope, tuple(defns.values())))
