"""Kernel nodes (docs/spec/atoms-v2.md, section 6.1).

Every body (of an operation, combinator, observation, ``valid`` or ``canon``) is a tree of
these nodes. The interpreter, the tracer, the type checker and cost accounting walk the same
tree. JSON: each node is ``{"node": "<class name>", ...fields}``.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, fields

# --------------------------------------------------------------- expressions


@dataclass(frozen=True)
class Var:
    name: str


@dataclass(frozen=True)
class Lit:
    value: object


@dataclass(frozen=True)
class Call:
    """Call an operation, a definition, a ``Rec`` function or an operation parameter."""

    fn: str
    args: tuple = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "args", tuple(self.args))


@dataclass(frozen=True)
class Let:
    name: str
    value: Node
    body: Node


@dataclass(frozen=True)
class Case:
    """Ordered arms ``(condition, body)``; the first true condition wins; ``default`` else."""

    arms: tuple
    default: Node | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "arms", tuple(tuple(arm) for arm in self.arms))


@dataclass(frozen=True)
class Rec:
    """Bind the recursive function ``fn(params) = body`` and call it on ``args``.

    ``measure`` is a node over ``params`` returning a non-negative int that must decrease at
    every recursive call, or the string ``"fuel"`` (no check; fuel and depth bound it; spec 0.2)
    or ``"legacy"`` (legacy-v1: the same, with the legacy depth limit). ``memo`` asks the kernel to
    serve repeated sub-calls from a table (spec 0.3); results and charged steps stay those of the
    plain recursion.
    """

    fn: str
    params: tuple
    body: Node
    args: tuple
    measure: Node | str = "legacy"
    memo: bool = False  # memoized recursion: same outcome and charged steps; the memo work is reported apart

    def __post_init__(self) -> None:
        object.__setattr__(self, "params", tuple(self.params))
        object.__setattr__(self, "args", tuple(self.args))


@dataclass(frozen=True)
class Jump:
    """Block terminator: goto ``target``."""

    target: str


@dataclass(frozen=True)
class CondJump:
    """Block terminator: goto ``then`` if ``cond`` holds, else goto ``else_``."""

    cond: Cond
    then: str
    else_: str


@dataclass(frozen=True)
class Halt:
    """Block terminator: return ``value``."""

    value: Node


@dataclass(frozen=True)
class Block:
    assigns: tuple  # ((var, node), ...) executed in order
    end: Jump | CondJump | Halt

    def __post_init__(self) -> None:
        object.__setattr__(self, "assigns", tuple(tuple(a) for a in self.assigns))


@dataclass(frozen=True)
class Blocks:
    """A flat program: ``vars`` ((name, init node), ...), the ``entry`` label, labelled blocks."""

    vars: tuple
    entry: str
    blocks: tuple  # ((label, Block), ...) in declaration order

    def __post_init__(self) -> None:
        object.__setattr__(self, "vars", tuple(tuple(v) for v in self.vars))
        object.__setattr__(self, "blocks", tuple(tuple(b) for b in self.blocks))

    def block(self, label: str) -> Block:
        for name, block in self.blocks:
            if name == label:
                return block
        raise KeyError(label)


Node = Var | Lit | Call | Let | Case | Rec | Blocks

# ---------------------------------------------------------------- conditions


@dataclass(frozen=True)
class Test:
    """The node evaluates to a boolean."""

    __test__ = False  # not a pytest test class
    expr: Node


@dataclass(frozen=True)
class And:
    left: Cond
    right: Cond


@dataclass(frozen=True)
class Or:
    left: Cond
    right: Cond


@dataclass(frozen=True)
class Not:
    operand: Cond


@dataclass(frozen=True)
class Always:
    pass


Cond = Test | And | Or | Not | Always

NODE_TYPES = (Var, Lit, Call, Let, Case, Rec, Blocks)
NODE_NAMES = tuple(cls.__name__ for cls in NODE_TYPES)

# ----------------------------------------------------------------- traversal


def children(node) -> Iterator:
    """Direct sub-nodes and sub-conditions, in evaluation order."""
    if isinstance(node, Call):
        yield from node.args
    elif isinstance(node, Let):
        yield node.value
        yield node.body
    elif isinstance(node, Case):
        for cond, body in node.arms:
            yield cond
            yield body
        if node.default is not None:
            yield node.default
    elif isinstance(node, Rec):
        yield from node.args
        if not isinstance(node.measure, str):
            yield node.measure
        yield node.body
    elif isinstance(node, Blocks):
        for _, init in node.vars:
            yield init
        for _, block in node.blocks:
            for _, value in block.assigns:
                yield value
            if isinstance(block.end, CondJump):
                yield block.end.cond
            elif isinstance(block.end, Halt):
                yield block.end.value
    elif isinstance(node, Test):
        yield node.expr
    elif isinstance(node, (And, Or)):
        yield node.left
        yield node.right
    elif isinstance(node, Not):
        yield node.operand


def walk(node) -> Iterator:
    yield node
    for child in children(node):
        yield from walk(child)


def map_nodes(node, transform, *, stop_at=()):
    """Rebuild bottom-up, transforming each expression node; ``stop_at`` leaves subtrees opaque."""
    if isinstance(node, stop_at):
        return node
    if isinstance(node, (Var, Lit, Always, Jump)) or node is None:
        return transform(node) if isinstance(node, NODE_TYPES) else node
    if isinstance(node, Call):
        rebuilt = Call(node.fn, tuple(map_nodes(arg, transform, stop_at=stop_at) for arg in node.args))
    elif isinstance(node, Let):
        rebuilt = Let(node.name, map_nodes(node.value, transform, stop_at=stop_at),
                      map_nodes(node.body, transform, stop_at=stop_at))
    elif isinstance(node, Case):
        rebuilt = Case(tuple((map_nodes(cond, transform, stop_at=stop_at),
                              map_nodes(body, transform, stop_at=stop_at)) for cond, body in node.arms),
                       map_nodes(node.default, transform, stop_at=stop_at))
    elif isinstance(node, Rec):
        rebuilt = Rec(node.fn, node.params, map_nodes(node.body, transform, stop_at=stop_at),
                      tuple(map_nodes(arg, transform, stop_at=stop_at) for arg in node.args),
                      node.measure if isinstance(node.measure, str) else map_nodes(node.measure, transform,
                                                                                   stop_at=stop_at),
                      node.memo)
    elif isinstance(node, Blocks):
        rebuilt = Blocks(tuple((name, map_nodes(init, transform, stop_at=stop_at)) for name, init in node.vars),
                         node.entry, tuple((label, map_nodes(block, transform, stop_at=stop_at))
                                           for label, block in node.blocks))
    elif isinstance(node, Block):
        return Block(tuple((name, map_nodes(value, transform, stop_at=stop_at)) for name, value in node.assigns),
                     map_nodes(node.end, transform, stop_at=stop_at))
    elif isinstance(node, CondJump):
        return CondJump(map_nodes(node.cond, transform, stop_at=stop_at), node.then, node.else_)
    elif isinstance(node, Halt):
        return Halt(map_nodes(node.value, transform, stop_at=stop_at))
    elif isinstance(node, Test):
        return Test(map_nodes(node.expr, transform, stop_at=stop_at))
    elif isinstance(node, (And, Or)):
        return type(node)(map_nodes(node.left, transform, stop_at=stop_at),
                          map_nodes(node.right, transform, stop_at=stop_at))
    elif isinstance(node, Not):
        return Not(map_nodes(node.operand, transform, stop_at=stop_at))
    else:
        raise TypeError(f"not a kernel node or condition: {node!r}")
    return transform(rebuilt) if isinstance(rebuilt, NODE_TYPES) else rebuilt


def length(node) -> int:
    """Definition length: the number of nodes and conditions in the tree."""
    return sum(1 for _ in walk(node))


def node_kinds(node) -> set[str]:
    """Kernel node names used by ``node`` (for a world's opened-node check)."""
    return {type(n).__name__ for n in walk(node) if isinstance(n, NODE_TYPES)}


def references(node) -> set[str]:
    """Names called in ``node``, excluding only local ``Rec`` functions."""
    names: set[str] = set()

    def visit(n, local: frozenset) -> None:
        if isinstance(n, Call):
            if n.fn not in local:
                names.add(n.fn)
            for arg in n.args:
                visit(arg, local)
        elif isinstance(n, Rec):
            inner = local | {n.fn}
            for arg in n.args:
                visit(arg, local)
            if not isinstance(n.measure, str):
                visit(n.measure, inner)
            visit(n.body, inner)
        else:
            for child in children(n):
                visit(child, local)

    visit(node, frozenset())
    return names


def operation_literals(node) -> set[str]:
    """Operation references inside literals, including card fields and tuples."""
    from opulse.atoms.kernel import FnRef
    from opulse.atoms.values import Card

    def names(value):
        if isinstance(value, FnRef):
            return {value.name}
        if isinstance(value, Card):
            return set().union(*(names(item) for item in value.fields))
        if isinstance(value, tuple):
            return set().union(*(names(item) for item in value))
        return set()

    return set().union(*(names(item.value) for item in walk(node) if isinstance(item, Lit)))


def all_dependencies(node) -> set[str]:
    """Called names and literal operation references used by a definition."""
    return references(node) | operation_literals(node)


def dependencies_match(depends_on, node, excluded=frozenset(), extra_nodes=()) -> bool:
    """``depends_on`` lists every called name and may add operations passed as literals (spec 8).
    ``extra_nodes`` are further bodies of the same definition (an observation's memory init/step)."""
    bodies = (node, *(item for item in extra_nodes if item is not None))
    called = set().union(*(references(body) for body in bodies)) - set(excluded)
    literals = set().union(*(operation_literals(body) for body in bodies))
    declared = set(depends_on)
    return len(declared) == len(tuple(depends_on)) and called <= declared <= called | literals


# ---------------------------------------------------------------------- JSON
_CLASSES = {cls.__name__: cls for cls in (Var, Lit, Call, Let, Case, Rec, Blocks, Block, Jump, CondJump,
                                          Halt, Test, And, Or, Not, Always)}


def _encode_lit(value: object):
    from opulse.atoms.values import Card, encode

    if isinstance(value, (bool, int, str, Card)):
        return encode(value)
    from opulse.worlds.perm import Permutation

    if isinstance(value, Permutation):
        return {"t": "perm", "v": list(value)}
    from opulse.atoms.kernel import FnRef

    if isinstance(value, FnRef):  # an operation passed to a combinator
        return {"t": "fn", "v": value.name}
    from opulse.atoms.values import Bottom

    if isinstance(value, Bottom):  # a declared failure, e.g. Bottom("not_stable") when a fixpoint runs out
        return {"t": "bottom", "v": value.reason}
    if isinstance(value, tuple):
        return {"t": "tuple", "v": [_encode_lit(item) for item in value]}
    raise TypeError(f"literal {value!r} has no JSON form")


def _decode_lit(data: dict):
    from opulse.atoms.values import FALSE, TRUE, decode

    if data["t"] == "tuple":
        return tuple(_decode_lit(item) for item in data["v"])
    if data["t"] == "bottom":
        from opulse.atoms.values import Bottom

        return Bottom(data["v"])
    if data["t"] == "fn":
        from opulse.atoms.kernel import FnRef

        return FnRef(data["v"])
    if data["t"] == "perm":
        from opulse.worlds.perm import Permutation

        return Permutation(data["v"])
    value = decode(data)
    return {TRUE: True, FALSE: False}.get(value, value) if data["t"] == "bool" else value


def to_json(node) -> object:
    if node is None or isinstance(node, (str, int)):
        return node
    if isinstance(node, Lit):
        return {"node": "Lit", "value": _encode_lit(node.value)}
    if isinstance(node, tuple):
        return [to_json(item) for item in node]
    data = {"node": type(node).__name__}
    for f in fields(node):
        data[f.name] = to_json(getattr(node, f.name))
    return data


def from_json(data: object):
    if data is None or isinstance(data, (str, int)):
        return data
    if isinstance(data, list):
        return tuple(from_json(item) for item in data)
    if data["node"] == "Lit":
        return Lit(_decode_lit(data["value"]))
    cls = _CLASSES[data["node"]]
    return cls(**{f.name: from_json(data[f.name]) for f in fields(cls) if f.name in data})  # newer fields default


__all__ = [name for name in dir() if not name.startswith("_") and name != "annotations"]
