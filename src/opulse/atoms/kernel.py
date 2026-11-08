"""Atoms-v2 kernel (spec sections 3, 6 and invariant 11.I1).

In the default atoms-v2 dialect, strict calls stop at the first non-Ok argument;
non-strict atoms receive Outcomes. In legacy-v1, Bottom flows through Let and
definition parameters: calls evaluate all arguments left to right unless an
Unknown stops them. Strict atoms receive the legacy NAN sentinel for Bottom
arguments and are still charged and invoked; non-strict atoms receive Outcomes.
In both dialects a Bottom Test aborts its Case as Bottom("nan_condition").
Only evaluated operations and jumps contribute steps.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping, Sequence
from copy import copy
from dataclasses import dataclass, field, fields, is_dataclass, replace
from typing import Protocol

from opulse.atoms import nodes as n
from opulse.atoms.values import Bottom, Card, Ok, Outcome, Unknown, truth, value_equal
from opulse.core.semantics import NAN
from opulse.definition.interpreter import run_with_deep_stack


@dataclass(frozen=True)
class Atom:
    name: str
    arity: int
    fn: Callable
    cost: int | Callable[..., int] = 1
    kind: str = "operation"
    strict: bool = True
    metered: bool = False
    cost_rule: str = ""


@dataclass(frozen=True)
class Defn:
    name: str
    params: tuple[str, ...]
    body: n.Node
    kind: str = "operation"
    layer: int = 1


@dataclass(frozen=True)
class FnRef:
    name: str


@dataclass(frozen=True)
class FastPath:
    defn_name: str
    fn: Callable
    steps_fn: Callable[..., int]
    scope_predicate: Callable[..., bool]


class Scope(Protocol):
    def resolve(self, name: str) -> Atom | Defn | None: ...


class DictScope:
    def __init__(self, atoms: Sequence[Atom] | Mapping[str, Atom] = (),
                 defns: Sequence[Defn] | Mapping[str, Defn] = (),
                 fast_paths: Mapping[str, FastPath] | None = None) -> None:
        self.atoms = dict(atoms) if isinstance(atoms, Mapping) else {atom.name: atom for atom in atoms}
        self.defns = dict(defns) if isinstance(defns, Mapping) else {defn.name: defn for defn in defns}
        self.fast_paths = dict(fast_paths or {})

    def resolve(self, name: str) -> Atom | Defn | None:
        return self.defns.get(name) or self.atoms.get(name)

    def extend(self, defns: Sequence[Defn] = ()) -> DictScope:
        scope = DictScope()
        scope.atoms = self.atoms.copy()
        scope.defns = {**self.defns, **{defn.name: defn for defn in defns}}
        replaced = {defn.name for defn in defns}
        scope.fast_paths = {name: path for name, path in self.fast_paths.items()
                            if name not in replaced}
        return scope


def qualify_calls(body: n.Node, world_id: str, names: set[str]) -> n.Node:
    """Bind calls in a definition to the world where it was declared."""
    def visit(node, local: frozenset[str]):
        if isinstance(node, n.Lit):
            if isinstance(node.value, FnRef) and node.value.name in names:
                return n.Lit(FnRef(f"{world_id}:{node.value.name}"))
            return node
        if isinstance(node, n.Rec):
            bound = local | {node.fn}
            measure = visit(node.measure, bound) if not isinstance(node.measure, str) else node.measure
            return replace(node, body=visit(node.body, bound),
                           args=tuple(visit(arg, local) for arg in node.args), measure=measure)
        if isinstance(node, n.Call):
            name = f"{world_id}:{node.fn}" if node.fn in names and node.fn not in local else node.fn
            return n.Call(name, tuple(visit(arg, local) for arg in node.args))
        if isinstance(node, tuple):
            return tuple(visit(item, local) for item in node)
        if is_dataclass(node):
            return replace(node, **{field.name: visit(getattr(node, field.name), local)
                                    for field in fields(node)})
        return node

    return visit(body, frozenset())


class ChainScope(DictScope):
    """A local scope with qualified lexical copies of attached worlds' definitions."""

    def __init__(self, local: DictScope, world_id: str,
                 attached: Mapping[str, DictScope]) -> None:
        atoms, defns = dict(local.atoms), dict(local.defns)
        for namespace, scope in ((world_id, local), *attached.items()):
            names = set(scope.atoms) | set(scope.defns)
            for name, atom in scope.atoms.items():
                atoms[f"{namespace}:{name}"] = replace(atom, name=f"{namespace}:{name}")
                if namespace != world_id and name not in atoms and name not in defns:
                    atoms[name] = atoms[f"{namespace}:{name}"]
            for name, definition in scope.defns.items():
                qualified = Defn(f"{namespace}:{name}", definition.params,
                                 qualify_calls(definition.body, namespace, names),
                                 definition.kind, definition.layer)
                defns[qualified.name] = qualified
                if namespace != world_id and name not in atoms and name not in defns:
                    defns[name] = qualified
        super().__init__(atoms, defns)


class _OverlayScope:
    def __init__(self, parent: Scope, defns: Sequence[Defn],
                 enable_fast_paths: bool = True) -> None:
        self.parent = parent
        self.defns = {defn.name: defn for defn in defns}
        self.fast_paths = ({name: path for name, path in getattr(parent, "fast_paths", {}).items()
                            if name not in self.defns} if enable_fast_paths else {})

    def resolve(self, name: str) -> Atom | Defn | None:
        return self.defns.get(name) or self.parent.resolve(name)


@dataclass(frozen=True)
class Limits:
    fuel: int | None = None
    max_depth: int = 10_000
    max_nodes: int | None = None


_DEFAULT_LIMITS = Limits()


@dataclass
class CallNode:
    name: str | None
    kind: str
    layer: int
    given: bool
    path: tuple[int, ...]
    inputs: tuple
    outcome: Outcome
    steps: int
    children: list[CallNode] = field(default_factory=list)
    memo_hit: bool = False
    jumps: int = 0
    metered: bool = False
    fast: bool = False
    fast_checked: bool = False


@dataclass
class Run:
    outcome: Outcome
    steps: int
    jumps: int
    trace: CallNode | None
    work: int = 0


def defined_atom() -> Atom:
    def defined(value: Outcome) -> Outcome:
        if isinstance(value, Unknown):
            return value
        return Ok(not isinstance(value, Bottom))

    return Atom("defined", 1, defined, strict=False)


def catch_atom() -> Atom:
    def catch(value: Outcome) -> Outcome:
        if isinstance(value, Unknown):
            return value
        if isinstance(value, Bottom):
            return Ok(Card("lift", "bot", (value.reason,)))
        return Ok(Card("lift", "val", (value.value,)))

    return Atom("catch", 1, catch, strict=False)


def _outcome(value: object) -> Outcome:
    if value is NAN:
        return Bottom("undefined")
    if isinstance(value, (Ok, Bottom, Unknown)):
        return value
    return Ok(value)


@dataclass(frozen=True)
class _RecFn:
    node: n.Rec
    closure: Mapping[str, object]
    locals: Mapping[str, _RecFn]
    layer: int
    current: list[tuple] = field(default_factory=list)
    table: dict[tuple, tuple[Outcome, int, int, int, tuple[CallNode, ...], int]] = field(default_factory=dict)


def _rebase(frame: CallNode, path: tuple[int, ...]) -> CallNode:
    clone = copy(frame)
    clone.path = path
    clone.children = [_rebase(child, path + (index,)) for index, child in enumerate(frame.children)]
    return clone


def _tree_size(frames: Sequence[CallNode]) -> int:
    return sum(1 + _tree_size(frame.children) for frame in frames)


def _memo_key(value: object) -> tuple:
    if isinstance(value, FnRef):
        return (FnRef, value.name)
    if isinstance(value, Card):
        return (Card, value.sort, value.tag, tuple(_memo_key(item) for item in value.fields))
    if isinstance(value, (tuple, list)):
        return (type(value), tuple(_memo_key(item) for item in value))
    if isinstance(value, (int, str, bool, Bottom)):
        return (type(value), value)
    raise TypeError("value has no stable memo key")


def _checked_cost(cost: int) -> int:
    if type(cost) is not int or cost < 0:
        raise ValueError("atom cost must be a non-negative integer")
    return cost


class _MeterContext:
    def __init__(self, engine: _Engine) -> None:
        self.engine = engine
        self.unknown: Unknown | None = None

    def call(self, defn: Defn | str, args: Sequence[object],
             extra_defns: Sequence[Defn] = (), budget: int | None = None) -> Outcome:
        if budget is not None and budget < 0:
            raise ValueError("negative inner budget")
        engine = self.engine
        old_scope = engine.scope
        additions = (*extra_defns, defn) if isinstance(defn, Defn) else extra_defns
        engine.scope = _OverlayScope(old_scope, additions) if additions else old_scope
        bound = engine.steps + budget if budget is not None else None
        if bound is not None:
            engine.budgets.append(bound)
        try:
            result = engine.invoke(defn.name if isinstance(defn, Defn) else defn,
                                   tuple(n.Lit(arg) for arg in args), {}, {}, 1)
            if isinstance(result, Unknown) and self.unknown is None:
                self.unknown = result
            return result
        finally:
            if bound is not None:
                engine.budgets.pop()
            engine.scope = old_scope


class _Engine:
    def __init__(self, scope: Scope, limits: Limits, trace: bool, dialect: str) -> None:
        self.scope = scope
        self.limits = limits
        self.dialect = dialect
        self.steps = 0
        self.work = 0
        self.jumps = 0
        self.depth = 0
        self.trace = trace
        self.frames: list[CallNode] = []
        self.nodes = 0
        self.budgets: list[int] = []
        self.peak_depth = 0
        self.rec_peaks: list[list[int]] = []

    def charge(self, cost: int, jump: bool = False) -> Outcome | None:
        if cost < 0:
            raise ValueError("negative atom cost")
        if ((self.limits.fuel is not None and self.steps + cost > self.limits.fuel) or
                any(self.steps + cost > bound for bound in self.budgets)):
            return Unknown("fuel")
        self.steps += cost
        self.work += cost
        if jump:
            self.jumps += 1
            if self.frames:
                self.frames[-1].jumps += 1
        return None

    def frame(self, name: str, kind: str, layer: int, given: bool) -> CallNode | Unknown | None:
        if not self.trace:
            return None
        if self.limits.max_nodes is not None and self.nodes >= self.limits.max_nodes:
            return Unknown("nodes")
        parent = self.frames[-1]
        frame = CallNode(name, kind, layer, given, parent.path + (len(parent.children),),
                         (), Unknown("pending"), 0)
        parent.children.append(frame)
        self.frames.append(frame)
        self.nodes += 1
        return frame

    def invoke(self, name: str, args: Sequence[n.Node], env: Mapping[str, object],
               local: Mapping[str, _RecFn], layer: int, initial: bool = False) -> Outcome:
        # Resolution order: local Rec functions, then scope definitions and atoms, then a variable
        # holding an operation reference. A variable never shadows a scope name (inline relies on it).
        target = local.get(name)
        if target is None:
            target = self.scope.resolve(name)
        if target is None:
            reference = env.get(name)
            if isinstance(reference, FnRef):
                target = self.scope.resolve(reference.name)
        if target is None:
            raise KeyError(name)
        arity = (len(target.node.params) if isinstance(target, _RecFn) else
                 len(target.params) if isinstance(target, Defn) else target.arity)
        if len(args) != arity:
            raise TypeError(f"{name!r} takes {arity} arguments, got {len(args)}")
        is_atom = isinstance(target, Atom)
        # Arguments belong to the caller: they are evaluated before the call's own trace frame,
        # so a frame's children and steps are exactly the work done inside the call.
        outcomes: list[Outcome] = []
        for arg in args:
            outcome = self.eval(arg, env, local, layer)
            outcomes.append(outcome)
            if isinstance(outcome, Unknown) and (self.dialect == "legacy-v1" or
                                                 outcome.resource in ("fuel", "depth", "nodes")):
                return outcome
            if (not is_atom or target.strict) and not isinstance(outcome, Ok) and self.dialect != "legacy-v1":
                return outcome
        frame = self.frame(name if isinstance(target, _RecFn) else target.name,  # FnRef: the real operation
                           target.kind if not isinstance(target, _RecFn) else "operation",
                           0 if is_atom else target.layer, is_atom)
        if isinstance(frame, Unknown):
            return frame
        if frame is not None and is_atom:
            frame.metered = target.metered
        start = self.steps
        result: Outcome = Unknown("pending")
        try:
            if is_atom:
                inputs = ([item.value if isinstance(item, Ok) else NAN for item in outcomes]
                          if target.strict else outcomes)
            else:
                inputs = [item.value if isinstance(item, Ok) else item for item in outcomes]
            if is_atom:
                cost = 0 if target.metered else _checked_cost(
                    target.cost(*inputs) if callable(target.cost) else target.cost)
                exhausted = self.charge(cost)
                if exhausted is not None:
                    result = exhausted
                else:
                    if target.metered:
                        context = _MeterContext(self)
                        result = _outcome(target.fn(context, *inputs))
                        if context.unknown is not None:
                            result = context.unknown
                    else:
                        result = _outcome(target.fn(*inputs))
            elif self.depth >= self.limits.max_depth:
                result = Unknown("depth")
            else:
                self.depth += 1
                self.peak_depth = max(self.peak_depth, self.depth)
                for peak in self.rec_peaks:
                    peak[0] = max(peak[0], self.depth)
                try:
                    values = inputs
                    if isinstance(target, Defn):
                        fast_path = getattr(self.scope, "fast_paths", {}).get(target.name)
                        if (fast_path is not None and fast_path.defn_name == target.name and
                                fast_path.scope_predicate(*values)):
                            if frame is not None:
                                frame.fast = True
                            exhausted = self.charge(_checked_cost(fast_path.steps_fn(*values)))
                            result = exhausted if exhausted is not None else _outcome(fast_path.fn(*values))
                            if frame is not None:
                                try:
                                    plain = _OverlayScope(self.scope, (), enable_fast_paths=False)
                                    remaining = (None if self.limits.fuel is None else
                                                 max(0, self.limits.fuel - start))
                                    expected = call(target.name, values, plain, Limits(fuel=remaining),
                                                    dialect=self.dialect)
                                    frame.fast_checked = (self.steps - start == expected.steps and
                                                          (result == expected.outcome if exhausted is not None
                                                           else not isinstance(expected.outcome, Unknown) and
                                                           type(result) is type(expected.outcome) and
                                                           (value_equal(result.value, expected.outcome.value)
                                                            if isinstance(result, Ok) else result == expected.outcome)))
                                except (ValueError, TypeError, KeyError, RecursionError):
                                    pass
                        else:
                            result = self.eval(target.body, dict(zip(target.params, values)), {}, target.layer)
                    else:
                        rec = target.node
                        bound = {**target.closure, **dict(zip(rec.params, values))}
                        rec_locals = {**target.locals, rec.fn: target}
                        if rec.measure not in ("legacy", "fuel") and not initial:
                            old_env = {**target.closure, **dict(zip(rec.params, target.current[-1]))}
                            old = self.measure(rec.measure, old_env, rec_locals, target.layer)
                            if isinstance(old, Unknown):
                                result = old
                                return result
                            new = self.measure(rec.measure, bound, rec_locals, target.layer)
                            if isinstance(new, Unknown):
                                result = new
                                return result
                            if not (isinstance(old, Ok) and type(old.value) is int and
                                    isinstance(new, Ok) and type(new.value) is int and
                                    0 <= new.value < old.value):
                                result = Bottom("measure")
                                return result
                        cache_key = None
                        if rec.memo:
                            try:
                                cache_key = tuple(_memo_key(value) for value in values)
                            except TypeError:
                                cache_key = None
                        if cache_key is not None and cache_key in target.table:
                            cached, cost, jumps, height, children, own_jumps = target.table[cache_key]
                            if (self.depth + height <= self.limits.max_depth and
                                    (not self.trace or self.limits.max_nodes is None or
                                     self.nodes + _tree_size(children) <= self.limits.max_nodes) and
                                    (self.limits.fuel is None or self.steps + cost <= self.limits.fuel) and
                                    all(self.steps + cost <= bound for bound in self.budgets)):
                                self.steps += cost
                                self.jumps += jumps
                                self.peak_depth = max(self.peak_depth, self.depth + height)
                                for peak in self.rec_peaks:
                                    peak[0] = max(peak[0], self.depth + height)
                                if frame is not None:
                                    frame.memo_hit = True
                                    frame.jumps = own_jumps
                                    frame.children = [_rebase(child, frame.path + (index,))
                                                      for index, child in enumerate(children)]
                                    self.nodes += _tree_size(children)
                                result = cached
                                return result
                        rec_start, jump_start, depth_start = self.steps, self.jumps, self.depth
                        peak = [self.depth]
                        self.rec_peaks.append(peak)
                        target.current.append(tuple(values))
                        try:
                            result = self.eval(rec.body, bound, rec_locals, target.layer)
                        finally:
                            target.current.pop()
                            self.rec_peaks.pop()
                        if cache_key is not None and not isinstance(result, Unknown):
                            target.table[cache_key] = (result, self.steps - rec_start,
                                                       self.jumps - jump_start,
                                                       peak[0] - depth_start,
                                                       tuple(frame.children) if frame is not None else (),
                                                       frame.jumps if frame is not None else 0)
                finally:
                    self.depth -= 1
            return result
        finally:
            if frame is not None:
                frame.inputs = tuple(item.value if isinstance(item, Ok) else item for item in outcomes)
                frame.outcome = result
                frame.steps = self.steps - start
                self.frames.pop()

    def measure(self, node: n.Node, env: Mapping[str, object], local: Mapping[str, _RecFn],
                layer: int) -> Outcome:
        silent = _Engine(self.scope, Limits(fuel=self.limits.fuel,
                                            max_depth=self.limits.max_depth), False, self.dialect)
        silent.depth = self.depth
        return silent.eval(node, env, local, layer)

    def cond(self, cond: n.Cond, env: Mapping[str, object], local: Mapping[str, _RecFn],
             layer: int) -> Outcome:
        if isinstance(cond, n.Always):
            return Ok(True)
        if isinstance(cond, n.Test):
            value = self.eval(cond.expr, env, local, layer)
            if isinstance(value, Bottom):
                return Bottom("nan_condition")
            return Ok(truth(value.value)) if isinstance(value, Ok) else value
        if isinstance(cond, n.Not):
            value = self.cond(cond.operand, env, local, layer)
            return Ok(not value.value) if isinstance(value, Ok) else value
        first = self.cond(cond.left, env, local, layer)
        if not isinstance(first, Ok):
            return first
        if isinstance(cond, n.And) and not first.value or isinstance(cond, n.Or) and first.value:
            return first
        return self.cond(cond.right, env, local, layer)

    def eval(self, node: n.Node, env: Mapping[str, object], local: Mapping[str, _RecFn],
             layer: int) -> Outcome:
        if isinstance(node, n.Lit):
            return _outcome(node.value)
        if isinstance(node, n.Var):
            return _outcome(env[node.name])
        if isinstance(node, n.Call):
            return self.invoke(node.fn, node.args, env, local, layer)
        if isinstance(node, n.Let):
            value = self.eval(node.value, env, local, layer)
            if isinstance(value, Ok):
                return self.eval(node.body, {**env, node.name: value.value}, local, layer)
            if isinstance(value, Bottom) and self.dialect == "legacy-v1":
                return self.eval(node.body, {**env, node.name: value}, local, layer)
            return value
        if isinstance(node, n.Case):
            for cond, body in node.arms:
                matched = self.cond(cond, env, local, layer)
                if not isinstance(matched, Ok):
                    return matched
                if matched.value:
                    return self.eval(body, env, local, layer)
            return self.eval(node.default, env, local, layer) if node.default is not None else Bottom("no_branch")
        if isinstance(node, n.Rec):
            recursive = _RecFn(node, env, local, layer)
            arguments = []
            for arg in node.args:
                item = self.eval(arg, env, local, layer)
                if not isinstance(item, Ok) and not (isinstance(item, Bottom) and
                                                     self.dialect == "legacy-v1"):
                    return item
                arguments.append(item)
            if node.measure not in ("legacy", "fuel"):
                bound = {**env, **dict(zip(node.params, (item.value if isinstance(item, Ok) else item
                                                           for item in arguments)))}
                current = self.measure(node.measure, bound, {**local, node.fn: recursive}, layer)
                if isinstance(current, Unknown):
                    return current
                if not isinstance(current, Ok) or type(current.value) is not int or current.value < 0:
                    return Bottom("measure")
            return self.invoke(node.fn, tuple(n.Lit(item.value if isinstance(item, Ok) else item)
                                               for item in arguments), env,
                               {**local, node.fn: recursive}, layer, initial=True)
        if isinstance(node, n.Blocks):
            state = dict(env)
            for name, init in node.vars:
                value = self.eval(init, state, local, layer)
                if not isinstance(value, Ok):
                    return value
                state[name] = value.value
            label = node.entry
            while True:
                block = node.block(label)
                for name, expr in block.assigns:
                    value = self.eval(expr, state, local, layer)
                    if not isinstance(value, Ok):
                        return value
                    state[name] = value.value
                end = block.end
                if isinstance(end, n.Halt):
                    return self.eval(end.value, state, local, layer)
                if isinstance(end, n.CondJump):
                    branch = self.cond(end.cond, state, local, layer)
                    if not isinstance(branch, Ok):
                        return branch
                    label = end.then if branch.value else end.else_
                else:
                    label = end.target
                exhausted = self.charge(1, jump=True)
                if exhausted is not None:
                    return exhausted
        raise TypeError(f"unknown kernel node: {node!r}")


def evaluate(node: n.Node, env: Mapping[str, object] = {}, scope: Scope | None = None,
             limits: Limits = _DEFAULT_LIMITS, trace: bool = False,
             dialect: str = "atoms-v2") -> Run:
    if dialect not in ("atoms-v2", "legacy-v1"):
        raise ValueError(f"unknown dialect: {dialect!r}")
    engine = _Engine(scope if scope is not None else DictScope(), limits, trace, dialect)

    def run() -> Run:
        root = (CallNode(None, "root", 0, False, (), (), Unknown("pending"), 0)
                if trace and (limits.max_nodes is None or limits.max_nodes >= 1) else None)
        if root is not None:
            engine.frames.append(root)
            engine.nodes = 1
        outcome = (Unknown("nodes") if trace and limits.max_nodes is not None and limits.max_nodes < 1
                   else engine.eval(node, env, {}, 1))
        if root is not None:
            root.outcome = outcome
            root.steps = engine.steps
        return Run(outcome, engine.steps, engine.jumps, root, engine.work)

    if threading.current_thread().name.startswith("opulse-eval"):  # nested evaluation (a host atom
        return run()                                                 # that evaluates): already deep
    return run_with_deep_stack(run)


def call(name: str, args: Sequence[object], scope: Scope, limits: Limits = _DEFAULT_LIMITS,
         trace: bool = False, dialect: str = "atoms-v2") -> Run:
    return evaluate(n.Call(name, tuple(n.Lit(arg) for arg in args)), scope=scope, limits=limits,
                    trace=trace, dialect=dialect)


def check_fast_path(fast_path: FastPath, scope: Scope, domain: Sequence[Sequence[object]],
                    dialect: str = "atoms-v2") -> list[str]:
    """Check outcome and exact layer-0 steps on every input of an exhaustive scope."""
    target = scope.resolve(fast_path.defn_name)
    if not isinstance(target, Defn):
        return [f"{fast_path.defn_name}: not a definition"]
    plain_scope = _OverlayScope(scope, (), enable_fast_paths=False)
    problems = []
    for args in domain:
        args = tuple(args)
        try:
            if not fast_path.scope_predicate(*args):
                problems.append(f"{args!r}: outside fast-path scope")
                continue
            expected = call(target.name, args, plain_scope, dialect=dialect)
            actual_cost = _checked_cost(fast_path.steps_fn(*args))
            actual = _outcome(fast_path.fn(*args))
            if (type(actual) is not type(expected.outcome) or
                    isinstance(actual, Ok) and not value_equal(actual.value, expected.outcome.value) or
                    isinstance(actual, (Bottom, Unknown)) and actual != expected.outcome or
                    actual_cost != expected.steps):
                problems.append(f"{args!r}: outcome or steps differ")
        except (TypeError, ValueError, KeyError) as error:
            problems.append(f"{args!r}: {error}")
    return problems


def inline(node: n.Node, scope: Scope) -> n.Node:
    """Unfold named definitions, binding arguments once in caller evaluation order."""
    serial = [0]
    occupied: set[str] = set()

    def reserve(expr: n.Node) -> None:
        for item in n.walk(expr):
            if isinstance(item, (n.Var, n.Let)):
                occupied.add(item.name)
            if isinstance(item, n.Call):
                occupied.add(item.fn)
            if isinstance(item, n.Rec):
                occupied.add(item.fn)
                occupied.update(item.params)
            if isinstance(item, n.Blocks):
                occupied.update(name for name, _ in item.vars)
                for _, block in item.blocks:
                    occupied.update(name for name, _ in block.assigns)

    reserve(node)
    pending = [item.fn for item in n.walk(node) if isinstance(item, n.Call)]
    pending.extend(item.value.name for item in n.walk(node)
                   if isinstance(item, n.Lit) and isinstance(item.value, FnRef))
    seen: set[str] = set()
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        seen.add(name)
        target = scope.resolve(name)
        if isinstance(target, Defn):
            reserve(target.body)
            occupied.update(target.params)
            pending.extend(item.fn for item in n.walk(target.body) if isinstance(item, n.Call))
            pending.extend(item.value.name for item in n.walk(target.body)
                           if isinstance(item, n.Lit) and isinstance(item.value, FnRef))

    def fresh() -> str:
        while True:
            serial[0] += 1
            candidate = f"__inline_arg_{serial[0]}"
            if candidate not in occupied:
                occupied.add(candidate)
                return candidate

    functions: set[str] = set()  # fresh names given to local Rec functions

    def rename_cond(cond, bindings):
        if isinstance(cond, n.Test):
            return n.Test(rename(cond.expr, bindings))
        if isinstance(cond, (n.And, n.Or)):
            return type(cond)(rename_cond(cond.left, bindings), rename_cond(cond.right, bindings))
        if isinstance(cond, n.Not):
            return n.Not(rename_cond(cond.operand, bindings))
        return cond

    def rename(expr, bindings):
        if isinstance(expr, n.Var):
            return n.Var(bindings.get(expr.name, expr.name))
        if isinstance(expr, n.Call):
            # Local functions always rename; a variable renames in call position only when no scope
            # name shadows it (the kernel resolves scope names before variables).
            fn = expr.fn
            if fn in bindings and (bindings[fn] in functions or scope.resolve(fn) is None):
                fn = bindings[fn]
            return n.Call(fn, tuple(rename(arg, bindings) for arg in expr.args))
        if isinstance(expr, n.Let):
            name = fresh()
            return n.Let(name, rename(expr.value, bindings),
                         rename(expr.body, {**bindings, expr.name: name}))
        if isinstance(expr, n.Case):
            return n.Case(tuple((rename_cond(cond, bindings), rename(body, bindings))
                                for cond, body in expr.arms),
                          rename(expr.default, bindings) if expr.default is not None else None)
        if isinstance(expr, n.Rec):
            inner = {**bindings, expr.fn: fresh()}
            functions.add(inner[expr.fn])
            for param in expr.params:
                inner[param] = fresh()
            return n.Rec(inner[expr.fn], tuple(inner[param] for param in expr.params),
                         rename(expr.body, inner), tuple(rename(arg, bindings) for arg in expr.args),
                         rename(expr.measure, inner) if not isinstance(expr.measure, str) else expr.measure,
                         expr.memo)
        if isinstance(expr, n.Blocks):
            inner = dict(bindings)
            vars = []
            for name, init in expr.vars:
                value = rename(init, inner)
                inner[name] = fresh()
                vars.append((inner[name], value))
            blocks = []
            for label, block in expr.blocks:
                assigns = tuple((inner.get(name, name), rename(value, inner))
                                for name, value in block.assigns)
                end = block.end
                if isinstance(end, n.CondJump):
                    end = n.CondJump(rename_cond(end.cond, inner), end.then, end.else_)
                elif isinstance(end, n.Halt):
                    end = n.Halt(rename(end.value, inner))
                blocks.append((label, n.Block(assigns, end)))
            return n.Blocks(tuple(vars), expr.entry, tuple(blocks))
        return expr

    def unfold(expr, active: frozenset[str], substitutions: Mapping[str, str]):
        if isinstance(expr, n.Call):
            name = substitutions.get(expr.fn, expr.fn)
            args = tuple(unfold(arg, active, substitutions) for arg in expr.args)
            target = scope.resolve(name)
            if not isinstance(target, Defn) or name in active:
                return n.Call(name, args)
            if len(args) != len(target.params):
                raise TypeError(f"{name!r} takes {len(target.params)} arguments, got {len(args)}")
            reserve(target.body)
            params = [fresh() for _ in target.params]
            recursive = name in n.references(target.body)
            rec_name = fresh() if recursive else name
            if recursive:
                functions.add(rec_name)
            bindings = dict(zip(target.params, params))
            if recursive:
                bindings[name] = rec_name
            renamed = rename(target.body, bindings)
            mapping = {param: arg.value.name for param, arg in zip(params, args)
                       if isinstance(arg, n.Lit) and isinstance(arg.value, FnRef)}
            body = unfold(renamed, active | {name}, mapping)
            if recursive:
                body = n.Rec(rec_name, tuple(params), body,
                             tuple(n.Var(param) for param in params), "legacy")
            temporaries = [fresh() for _ in args]
            for param, temporary in reversed(tuple(zip(params, temporaries))):
                body = n.Let(param, n.Var(temporary), body)
            for temporary, arg in reversed(tuple(zip(temporaries, args))):
                body = n.Let(temporary, arg, body)
            return body
        if isinstance(expr, n.Let):
            return n.Let(expr.name, unfold(expr.value, active, substitutions),
                         unfold(expr.body, active, {key: value for key, value in substitutions.items()
                                                    if key != expr.name}))
        if isinstance(expr, n.Case):
            return n.Case(tuple((condition(cond, active, substitutions), unfold(body, active, substitutions))
                                for cond, body in expr.arms),
                          unfold(expr.default, active, substitutions) if expr.default is not None else None)
        if isinstance(expr, n.Rec):
            return n.Rec(expr.fn, expr.params, unfold(expr.body, active | {expr.fn}, substitutions),
                         tuple(unfold(arg, active, substitutions) for arg in expr.args),
                         unfold(expr.measure, active, substitutions) if not isinstance(expr.measure, str) else expr.measure,
                         expr.memo)
        if isinstance(expr, n.Blocks):
            return n.Blocks(tuple((name, unfold(init, active, substitutions)) for name, init in expr.vars),
                            expr.entry, tuple((label, n.Block(
                                tuple((name, unfold(value, active, substitutions)) for name, value in block.assigns),
                                n.CondJump(condition(block.end.cond, active, substitutions), block.end.then,
                                           block.end.else_) if isinstance(block.end, n.CondJump) else
                                n.Halt(unfold(block.end.value, active, substitutions))
                                if isinstance(block.end, n.Halt) else block.end))
                                              for label, block in expr.blocks))
        return expr

    def condition(cond, active, substitutions):
        if isinstance(cond, n.Test):
            return n.Test(unfold(cond.expr, active, substitutions))
        if isinstance(cond, (n.And, n.Or)):
            return type(cond)(condition(cond.left, active, substitutions),
                              condition(cond.right, active, substitutions))
        if isinstance(cond, n.Not):
            return n.Not(condition(cond.operand, active, substitutions))
        return cond

    return unfold(rename(node, {}), frozenset(), {})
