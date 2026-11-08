"""Code objects: definitions as values (docs/spec/atoms-meta.md, sections 2 and 3).

A code value is a card tree of sort ``code`` that mirrors the kernel nodes one to one. ``quote``
turns a definition into its canonical code value; ``decode`` turns a code value back into kernel
definitions. ``code_hash`` is the content hash used for identity and evidence.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.values import FALSE, TRUE, Bottom, Card, encode

if TYPE_CHECKING:
    from opulse.atoms.spec import Definition

HASH_PREFIX = "opulse.code/1\n"
CALLABLE_KINDS = ("operation", "combinator", "object")
DISPLAY_ONLY = frozenset({"title", "title_zh", "doc", "source", "symbol", "input_names"})


class CodeError(ValueError):
    """A value that is not a well-formed code value, or a body that cannot be quoted."""


# ------------------------------------------------------------------ small cards
def lst(items: Sequence = ()) -> Card:
    return Card("list", "items", tuple(items))


def items(card: Card) -> tuple:
    if not (isinstance(card, Card) and card.sort == "list" and card.tag == "items"):
        raise CodeError(f"not a list: {card!r}")
    return card.fields


def _expr(tag: str, *fields) -> Card:
    return Card("expr", tag, fields)


def _cond(tag: str, *fields) -> Card:
    return Card("cond", tag, fields)


def _lit_value(value: object) -> object:
    if value is True:
        return TRUE
    if value is False:
        return FALSE
    if isinstance(value, Bottom) and isinstance(value.reason, str):
        return Card("literal", "bottom", (value.reason,))
    if isinstance(value, Card) and value in (TRUE, FALSE):
        return Card("literal", "bool_card", (value,))
    if isinstance(value, tuple):
        return Card("literal", "tuple", tuple(_lit_value(item) for item in value))
    from opulse.worlds.perm import Permutation

    if isinstance(value, Permutation):
        return Card("literal", "perm", tuple(value))
    if isinstance(value, (int, str, Card)):
        return value
    raise CodeError(f"literal {value!r} has no code form")


# ------------------------------------------------------------- raw node <-> card
def encode_node(node) -> Card:
    """The code card of a kernel node or condition, names unchanged (not canonical)."""
    if isinstance(node, n.Var):
        return _expr("var", node.name)
    if isinstance(node, n.Lit):
        if isinstance(node.value, kernel.FnRef):
            return _expr("fn", node.value.name)
        return _expr("lit", _lit_value(node.value))
    if isinstance(node, n.Call):
        return _expr("call", node.fn, lst(encode_node(arg) for arg in node.args))
    if isinstance(node, n.Let):
        return _expr("let", node.name, encode_node(node.value), encode_node(node.body))
    if isinstance(node, n.Case):
        arms = lst(Card("arm", "arm", (encode_node(cond), encode_node(body))) for cond, body in node.arms)
        default = Card("opt", "none") if node.default is None else Card("opt", "some", (encode_node(node.default),))
        return _expr("case", arms, default)
    if isinstance(node, n.Rec):
        measure = (Card("measure", node.measure) if isinstance(node.measure, str)
                   else Card("measure", "node", (encode_node(node.measure),)))
        fields = (node.fn, lst(node.params), encode_node(node.body),
                  lst(encode_node(arg) for arg in node.args), measure)
        return _expr("rec", *fields, *((True,) if node.memo else ()))
    if isinstance(node, n.Blocks):
        binds = lst(Card("bind", "bind", (name, encode_node(init))) for name, init in node.vars)
        blocks = lst(Card("block", "block", (label, lst(Card("bind", "bind", (name, encode_node(value)))
                                                        for name, value in block.assigns),
                                             _encode_end(block.end)))
                     for label, block in node.blocks)
        return _expr("blocks", binds, node.entry, blocks)
    if isinstance(node, n.Test):
        return _cond("test", encode_node(node.expr))
    if isinstance(node, n.And):
        return _cond("and", encode_node(node.left), encode_node(node.right))
    if isinstance(node, n.Or):
        return _cond("or", encode_node(node.left), encode_node(node.right))
    if isinstance(node, n.Not):
        return _cond("not", encode_node(node.operand))
    if isinstance(node, n.Always):
        return _cond("always")
    raise CodeError(f"no code form for {node!r}")


def _encode_end(end) -> Card:
    if isinstance(end, n.Jump):
        return Card("end", "jump", (end.target,))
    if isinstance(end, n.CondJump):
        return Card("end", "cjump", (encode_node(end.cond), end.then, end.else_))
    if isinstance(end, n.Halt):
        return Card("end", "halt", (encode_node(end.value),))
    raise CodeError(f"no code form for block end {end!r}")


def _need(card: object, sort: str, tag: str | None = None, arity: int | None = None) -> Card:
    if not isinstance(card, Card) or card.sort != sort or (tag is not None and card.tag != tag) or (
            arity is not None and len(card.fields) != arity):
        raise CodeError(f"expected {sort}{'.' + tag if tag else ''}, got {card!r}")
    return card


def _text(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise CodeError(f"expected a name, got {value!r}")
    return value


_EXPR_ARITY = {"var": 1, "lit": 1, "fn": 1, "call": 2, "let": 3, "case": 2, "blocks": 3}
_COND_ARITY = {"test": 1, "and": 2, "or": 2, "not": 1, "always": 0}


def decode_node(card: Card):
    """The kernel node or condition of a code card (names unchanged)."""
    if isinstance(card, Card) and card.sort == "cond":
        if _COND_ARITY.get(card.tag) != len(card.fields):
            raise CodeError(f"malformed condition {card!r}")
        if card.tag == "test":
            return n.Test(decode_node(_need(card.fields[0], "expr")))
        if card.tag in ("and", "or"):
            cls = n.And if card.tag == "and" else n.Or
            return cls(decode_node(_need(card.fields[0], "cond")), decode_node(_need(card.fields[1], "cond")))
        if card.tag == "not":
            return n.Not(decode_node(_need(card.fields[0], "cond")))
        return n.Always()
    card = _need(card, "expr")
    if (card.tag == "rec" and len(card.fields) not in (5, 6)) or (
            card.tag != "rec" and _EXPR_ARITY.get(card.tag) != len(card.fields)):
        raise CodeError(f"malformed expression {card!r}")
    f = card.fields
    if card.tag == "var":
        return n.Var(_text(f[0]))
    if card.tag == "lit":
        value = f[0]
        if not isinstance(value, (int, str, Card)) or isinstance(value, bool):
            raise CodeError(f"bad literal {value!r}")
        if value == TRUE:
            return n.Lit(True)
        if value == FALSE:
            return n.Lit(False)
        if isinstance(value, Card) and value.sort == "literal":
            if value.tag == "bool_card" and value.fields in ((TRUE,), (FALSE,)):
                return n.Lit(value.fields[0])
            if value.tag == "bottom" and len(value.fields) == 1:
                return n.Lit(Bottom(_text(value.fields[0])))
            if value.tag == "tuple":
                return n.Lit(tuple(decode_node(_expr("lit", item)).value for item in value.fields))
            if value.tag == "perm":
                from opulse.worlds.perm import Permutation

                if not all(type(item) is int for item in value.fields):
                    raise CodeError("invalid permutation literal")
                return n.Lit(Permutation(value.fields))
            raise CodeError("invalid declared literal")
        return n.Lit(value)
    if card.tag == "fn":
        return n.Lit(kernel.FnRef(_text(f[0])))
    if card.tag == "call":
        return n.Call(_text(f[0]), tuple(decode_node(_need(arg, "expr")) for arg in items(f[1])))
    if card.tag == "let":
        return n.Let(_text(f[0]), decode_node(_need(f[1], "expr")), decode_node(_need(f[2], "expr")))
    if card.tag == "case":
        arms = []
        for arm in items(f[0]):
            arm = _need(arm, "arm", "arm", 2)
            arms.append((decode_node(_need(arm.fields[0], "cond")), decode_node(_need(arm.fields[1], "expr"))))
        default = _need(f[1], "opt")
        if default.tag == "none" and not default.fields:
            return n.Case(tuple(arms), None)
        if default.tag == "some" and len(default.fields) == 1:
            return n.Case(tuple(arms), decode_node(_need(default.fields[0], "expr")))
        raise CodeError(f"malformed case default {default!r}")
    if card.tag == "rec":
        if len(f) == 6 and f[5] is not True:
            raise CodeError("rec memo must be true when present")
        measure = _need(f[4], "measure")
        if measure.tag in ("fuel", "legacy") and not measure.fields:
            decoded_measure = measure.tag
        elif measure.tag == "node" and len(measure.fields) == 1:
            decoded_measure = decode_node(_need(measure.fields[0], "expr"))
        else:
            raise CodeError(f"malformed measure {measure!r}")
        return n.Rec(_text(f[0]), tuple(_text(p) for p in items(f[1])), decode_node(_need(f[2], "expr")),
                     tuple(decode_node(_need(arg, "expr")) for arg in items(f[3])), decoded_measure, len(f) == 6)
    # blocks
    variables = []
    for bind in items(f[0]):
        bind = _need(bind, "bind", "bind", 2)
        variables.append((_text(bind.fields[0]), decode_node(_need(bind.fields[1], "expr"))))
    blocks = []
    for block in items(f[2]):
        block = _need(block, "block", "block", 3)
        assigns = []
        for bind in items(block.fields[1]):
            bind = _need(bind, "bind", "bind", 2)
            assigns.append((_text(bind.fields[0]), decode_node(_need(bind.fields[1], "expr"))))
        blocks.append((_text(block.fields[0]), n.Block(tuple(assigns), _decode_end(block.fields[2]))))
    labels = [label for label, _ in blocks]
    if len(set(labels)) != len(labels) or _text(f[1]) not in labels:
        raise CodeError("blocks need unique labels and an existing entry")
    return n.Blocks(tuple(variables), f[1], tuple(blocks))


def _decode_end(card) -> object:
    card = _need(card, "end")
    if card.tag == "jump" and len(card.fields) == 1:
        return n.Jump(_text(card.fields[0]))
    if card.tag == "cjump" and len(card.fields) == 3:
        return n.CondJump(decode_node(_need(card.fields[0], "cond")), _text(card.fields[1]), _text(card.fields[2]))
    if card.tag == "halt" and len(card.fields) == 1:
        return n.Halt(decode_node(_need(card.fields[0], "expr")))
    raise CodeError(f"malformed block end {card!r}")


# ------------------------------------------------------------------- signatures
def sig_op(inputs: Sequence[tuple[str, str]], output: tuple[str, str]) -> Card:
    return Card("sig", "op", (lst(Card("edge", "edge", edge) for edge in inputs), Card("edge", "edge", output)))


def sig_comb(arity: int, op_params: Sequence[int]) -> Card:
    return Card("sig", "comb", (arity, lst(op_params)))


def sig_obs(reads: Sequence[str]) -> Card:
    return Card("sig", "obs", (lst(reads),))


def sig_const() -> Card:
    return Card("sig", "const")


def sig_law(variables: Sequence[tuple[str, str]]) -> Card:
    return Card("sig", "law", (lst(Card("var", "var", pair) for pair in variables),))


def sig_bridge(source: str, target: str, interface: Sequence[tuple[str, str]] = (),
               domain=None) -> Card:
    optional = Card("opt", "none") if domain is None else Card("opt", "some", (encode_node(domain),))
    return Card("sig", "bridge", (source, target, lst(Card("pair", "pair", pair)
                                                     for pair in interface), optional))


def sig_template(params: Sequence[tuple[str, str]], produces: str) -> Card:
    return Card("sig", "template", (lst(Card("param", "param", pair) for pair in params), produces))


def sig_arity(sig: Card) -> int:
    sig = _need(sig, "sig")
    def edge(value):
        from opulse.atoms.spec import Edge

        value = _need(value, "edge", "edge", 2)
        sort, enter = value.fields
        _text(sort)
        _text(enter)
        try:
            Edge(sort, enter)
        except (TypeError, ValueError) as error:
            raise CodeError("invalid signature edge") from error

    if sig.tag == "op":
        _need(sig, "sig", "op", 2)
        inputs = items(sig.fields[0])
        for value in inputs:
            edge(value)
        edge(sig.fields[1])
        return len(inputs)
    if sig.tag == "comb":
        _need(sig, "sig", "comb", 2)
        arity, positions = sig.fields
        if type(arity) is not int or arity < 0 or any(
                type(position) is not int or position < 0 or position >= arity
                for position in items(positions)) or len(set(items(positions))) != len(items(positions)):
            raise CodeError("invalid combinator signature")
        return arity
    if sig.tag == "obs":
        _need(sig, "sig", "obs", 1)
        for read in items(sig.fields[0]):
            _text(read)
        return 0
    if sig.tag in ("law", "template"):
        _need(sig, "sig", sig.tag, 1 if sig.tag == "law" else 2)
        pairs = items(sig.fields[0])
        for pair in pairs:
            pair = _need(pair, "var" if sig.tag == "law" else "param",
                         "var" if sig.tag == "law" else "param", 2)
            _text(pair.fields[0])
            _text(pair.fields[1])
        if sig.tag == "template":
            from opulse.atoms import KINDS
            if sig.fields[1] not in KINDS:
                raise CodeError("invalid template output kind")
            return 0
        return len(pairs)
    if sig.tag == "bridge":
        _need(sig, "sig", "bridge", 4)
        _text(sig.fields[0])
        _text(sig.fields[1])
        for pair in items(sig.fields[2]):
            pair = _need(pair, "pair", "pair", 2)
            _text(pair.fields[0])
            _text(pair.fields[1])
        domain = _need(sig.fields[3], "opt")
        if domain.tag == "some" and len(domain.fields) == 1:
            decode_node(_need(domain.fields[0], "expr"))
        elif domain.tag != "none" or domain.fields:
            raise CodeError("invalid bridge domain")
        return 1
    _need(sig, "sig", "const", 0)
    return 0


def encode_pattern(value) -> Card:
    """Lossless card tree for TemplateSpec.pattern, including nodes and placeholders (2.1)."""
    if isinstance(value, n.NODE_TYPES):
        return Card("pattern", "node", (encode_node(value),))
    if isinstance(value, dict) and "node" in value:
        return Card("pattern", "node", (encode_node(n.from_json(value)),))
    if isinstance(value, dict):
        return Card("pattern", "map", (lst(Card("pattern", "entry", (key, encode_pattern(item)))
                                           for key, item in sorted(value.items())),))
    if isinstance(value, (tuple, list)):
        return Card("pattern", "tuple" if isinstance(value, tuple) else "list",
                    (lst(encode_pattern(item) for item in value),))
    if value is None:
        return Card("pattern", "none")
    if isinstance(value, Bottom):
        return Card("pattern", "bottom", (_text(value.reason),))
    if type(value) is bool:
        return Card("pattern", "bool", (TRUE if value else FALSE,))
    return Card("pattern", "value", (_lit_value(value),))


def _origin_arg(value, kind: str, resolve_definition=None, resolve_code=None) -> Card:
    from opulse.atoms.spec import Definition

    if isinstance(value, Definition):
        if value.kind != kind and not (kind == "sort" and value.kind == "object"):
            raise CodeError(f"{value.name} expects {kind}, got {value.kind}")
        resolved = resolve_code(value.name) if resolve_code is not None else None
        if resolved is None or resolved.code is None or resolved.code.fields[0] != value.kind:
            return Card("pattern", "definition", (value.name, value.kind, value.content_hash()))
        return Card("pattern", "definition", (value.name, value.kind, code_hash(resolved.code)))
    if resolve_definition is not None and kind not in ("int", "str", "bool") and isinstance(value, str):
        resolved = resolve_definition(value)
        if isinstance(resolved, Definition):
            return _origin_arg(resolved, kind, resolve_code=resolve_code)
    return encode_pattern(value)


def decode_pattern(card: Card):
    card = _need(card, "pattern")
    if card.tag == "node" and len(card.fields) == 1:
        return decode_node(card.fields[0])
    if card.tag == "map" and len(card.fields) == 1:
        pairs = [_need(entry, "pattern", "entry", 2).fields for entry in items(card.fields[0])]
        if any(not isinstance(key, str) for key, _ in pairs) or len({key for key, _ in pairs}) != len(pairs):
            raise CodeError("invalid template mapping")
        return {key: decode_pattern(value) for key, value in pairs}
    if card.tag in ("tuple", "list") and len(card.fields) == 1:
        values = [decode_pattern(item) for item in items(card.fields[0])]
        return tuple(values) if card.tag == "tuple" else values
    if card.tag == "value" and len(card.fields) == 1:
        value = card.fields[0]
        if isinstance(value, bool) or not isinstance(value, (int, str, Card)):
            raise CodeError("invalid template value")
        if isinstance(value, Card) and value.sort == "literal":
            if value.tag == "bool_card" and value.fields in ((TRUE,), (FALSE,)):
                return value.fields[0]
            raise CodeError("invalid template value")
        return value
    if card.tag == "none" and not card.fields:
        return None
    if card.tag == "bool" and card.fields in ((TRUE,), (FALSE,)):
        return card.fields[0] == TRUE
    if card.tag == "bottom" and len(card.fields) == 1:
        return Bottom(_text(card.fields[0]))
    if card.tag == "definition" and len(card.fields) == 3:
        _text(card.fields[0])
        _text(card.fields[1])
        if not isinstance(card.fields[2], str) or not re.fullmatch(r"[0-9a-f]{64}", card.fields[2]):
            raise CodeError("invalid definition argument hash")
        return card.fields[0]
    raise CodeError("invalid template pattern")


def _template_body(pattern, fallback, params: Sequence[str]) -> Card:
    return Card("pattern", "template", (encode_pattern(pattern), encode_pattern(fallback)))


def _validate_template(sig: Card, body: Card) -> None:
    """Validate both pattern children and the produced spec before code entry (2.1)."""
    from opulse.atoms.spec import (
        BridgeSpec,
        CombinatorSpec,
        LawSpec,
        ObjectSpec,
        ObservationSpec,
        OperationSpec,
    )
    from opulse.atoms.templates import _encode_nodes, _replace

    pattern, fallback = (decode_pattern(field) for field in body.fields)
    if not isinstance(pattern, dict):
        raise CodeError("template pattern must describe a spec")
    kinds = {"operation": OperationSpec, "combinator": CombinatorSpec,
             "object": ObjectSpec, "observation": ObservationSpec,
             "law": LawSpec, "bridge": BridgeSpec}
    args = {pair.fields[0]: {"int": 1, "bool": True}.get(pair.fields[1], "sample")
            for pair in items(sig.fields[0])}
    try:
        candidate = _replace(pattern, args)
        candidate["name"] = "sample"
        kinds[sig.fields[1]].from_dict(_encode_nodes(candidate))
        if fallback is not None and not isinstance(fallback, n.NODE_TYPES):
            raise CodeError("template fallback must be a node")
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        raise CodeError("invalid produced template spec") from error


_SIG_KIND = {"op": "operation", "comb": "combinator", "obs": "observation", "const": "object",
             "law": "law", "bridge": "bridge", "template": "template"}


def signature_of(spec) -> tuple[str, Card, tuple[str, ...]]:
    """``(kind, sig, params)`` of an atoms-v2 spec record (operation, combinator, observation, constant)."""
    from opulse.atoms.spec import (
        BridgeSpec,
        CombinatorSpec,
        LawSpec,
        ObjectSpec,
        ObservationSpec,
        OperationSpec,
        TemplateSpec,
    )

    if isinstance(spec, OperationSpec):
        names = tuple(spec.extra.get("input_names", ()))
        params = names if len(names) == len(spec.inputs) else tuple(f"arg{i}" for i in range(len(spec.inputs)))
        return "operation", sig_op([(e.sort, e.enter) for e in spec.inputs], (spec.output.sort, spec.output.enter)), params
    if isinstance(spec, CombinatorSpec):
        return ("combinator", sig_comb(len(spec.params), [spec.params.index(p) for p in spec.op_params]),
                tuple(spec.params))
    if isinstance(spec, ObservationSpec):
        if spec.memory is not None:
            raise CodeError("observations with memory have no code form in atoms-meta/0.1")
        return "observation", sig_obs(spec.reads), ()
    if isinstance(spec, ObjectSpec) and spec.form == "constant":
        return "object", sig_const(), ()
    if isinstance(spec, LawSpec):
        return "law", sig_law(spec.vars), tuple(name for name, _ in spec.vars)
    if isinstance(spec, BridgeSpec):
        return "bridge", sig_bridge(spec.source, spec.target, spec.interface, spec.domain), ("x",)
    if isinstance(spec, TemplateSpec):
        return "template", sig_template(spec.params, spec.produces), ()
    raise CodeError(f"no code form for {type(spec).__name__} {getattr(spec, 'form', '')}".strip())


# ------------------------------------------------------------------ canonical form
def atom_digest(op_spec) -> str:
    """sha256 of an OperationSpec without its display-only members (spec 3.2)."""
    def strip(value):
        if isinstance(value, dict):
            return {k: strip(v) for k, v in value.items() if k not in DISPLAY_ONLY}
        if isinstance(value, list):
            return [strip(v) for v in value]
        return value

    data = strip(op_spec.to_dict())
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def code_hash(code: Card) -> str:
    _need(code, "code", "def", 5)
    data = json.dumps(encode(code), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256((HASH_PREFIX + data).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Resolved:
    """What a free call name means: an invented definition (its code), a given atom, or nothing."""

    code: Card | None = None
    digest: str | None = None


Resolver = Callable[[str], Resolved | None]


def _global_names(body, resolve: Resolver) -> frozenset[str]:
    names = set()

    def visit(node, local: frozenset[str]):
        if isinstance(node, n.Call) and node.fn not in local and resolve(node.fn) is not None:
            names.add(node.fn)
        if (isinstance(node, n.Lit) and isinstance(node.value, kernel.FnRef) and
                node.value.name not in local and resolve(node.value.name) is not None):
            names.add(node.value.name)
        if isinstance(node, n.Rec):
            for arg in node.args:
                visit(arg, local)
            if not isinstance(node.measure, str):
                visit(node.measure, local | {node.fn})
            visit(node.body, local | {node.fn})
        else:
            for child in n.children(node):
                visit(child, local)

    visit(body, frozenset())
    return frozenset(names)


def _lexical_names(body, params: Sequence[str]) -> set[str]:
    names = set(params)
    for node in n.walk(body):
        if isinstance(node, n.Let):
            names.add(node.name)
        elif isinstance(node, n.Rec):
            names.update((node.fn, *node.params))
        elif isinstance(node, n.Blocks):
            names.update(name for name, _ in node.vars)
            names.update(label for label, _ in node.blocks)
    return names


class _Canon:
    def __init__(self, resolve: Resolver, reserved: frozenset[str] = frozenset(),
                 canonical: bool = False):
        self.resolve = resolve
        self.reserved = reserved
        self.canonical = canonical
        self.counts = {"v": 0, "r": 0, "l": 0}
        self.deps: dict[str, Card] = {}
        self.atoms: dict[str, str] = {}
        self.local_calls: set[str] = set()

    def fresh(self, prefix: str) -> str:
        name = f"{prefix}{self.counts[prefix]}"
        self.counts[prefix] += 1
        if name in self.reserved:
            return self.fresh(prefix)
        return name

    def fn_name(self, name: str, env: Mapping[str, str], rec: Mapping[str, str]) -> str:
        if name in rec:
            return rec[name]
        resolved = self.resolve(name)
        if name in env:
            if resolved is not None:
                raise CodeError(f"ambiguous call name {name!r}")
            else:
                self.local_calls.add(env[name])
                return env[name]
        if resolved is None:
            raise CodeError(f"unbound name {name!r}")
        if resolved.code is not None and resolved.digest is not None:
            raise CodeError(f"ambiguous resolved entity {name!r}")
        if resolved.code is not None:
            self._dep(resolved.code)
            return "#" + code_hash(resolved.code)
        if re.fullmatch(r"#[0-9a-f]{64}", name):
            raise CodeError(f"given atom name has hash shape: {name}")
        self.atoms[name] = _text(resolved.digest)
        return name

    def _dep(self, code: Card) -> None:
        digest = code_hash(code)
        if digest in self.deps:
            return
        self.deps[digest] = code
        for dep in items(code.fields[4]):
            if isinstance(dep, Card) and dep.sort == "code":
                self.deps.setdefault(code_hash(dep), dep)
        for atom in items(code.fields[3]):
            self.atoms[atom.fields[0]] = atom.fields[1]

    def node(self, node, env: Mapping[str, str], rec: Mapping[str, str] | None = None):
        rec = rec or {}
        if isinstance(node, n.Var):
            return n.Var(env.get(node.name, node.name))  # free names (probe values) stay
        if isinstance(node, n.Lit):
            if isinstance(node.value, kernel.FnRef):
                return n.Lit(kernel.FnRef(self.fn_name(node.value.name, env, rec)))
            _lit_value(node.value)
            return node
        if isinstance(node, n.Call):
            fn = self.fn_name(node.fn, env, rec)
            return n.Call(fn, tuple(self.node(arg, env, rec) for arg in node.args))
        if isinstance(node, n.Let):
            name = self.fresh("v")
            value = self.node(node.value, env, rec)
            return n.Let(name, value, self.node(node.body, {**env, node.name: name}, rec))
        if isinstance(node, n.Case):
            arms = tuple((self.node(cond, env, rec), self.node(body, env, rec)) for cond, body in node.arms)
            return n.Case(arms, None if node.default is None else self.node(node.default, env, rec))
        if isinstance(node, n.Rec):
            fn = self.fresh("r")
            params = tuple(self.fresh("v") for _ in node.params)
            inner = {**env, node.fn: fn, **dict(zip(node.params, params))}
            inner_rec = {**rec, node.fn: fn}
            args = tuple(self.node(arg, env, rec) for arg in node.args)
            measure = node.measure if isinstance(node.measure, str) else self.node(node.measure, inner, inner_rec)
            return n.Rec(fn, params, self.node(node.body, inner, inner_rec), args, measure, node.memo)
        if isinstance(node, n.Blocks):
            names = {name: self.fresh("v") for name, _ in node.vars}
            order = [node.entry] + [label for label, _ in node.blocks if label != node.entry]
            labels = {label: self.fresh("l") for label in order}
            inner = {**env, **names}
            before = dict(env)
            variables = []
            for name, init in node.vars:
                variables.append((names[name], self.node(init, before, rec)))
                before[name] = names[name]
            variables = tuple(variables)
            blocks = []
            for label, block in node.blocks:
                assigns = tuple((inner.get(name, name), self.node(value, inner, rec)) for name, value in block.assigns)
                end = block.end
                if isinstance(end, n.Jump):
                    end = n.Jump(labels[end.target])
                elif isinstance(end, n.CondJump):
                    end = n.CondJump(self.node(end.cond, inner, rec), labels[end.then], labels[end.else_])
                else:
                    end = n.Halt(self.node(end.value, inner, rec))
                blocks.append((labels[label], n.Block(assigns, end)))
            return n.Blocks(variables, labels[node.entry], tuple(blocks))
        if isinstance(node, n.Test):
            return n.Test(self.node(node.expr, env, rec))
        if isinstance(node, (n.And, n.Or)):
            return type(node)(self.node(node.left, env, rec), self.node(node.right, env, rec))
        if isinstance(node, n.Not):
            return n.Not(self.node(node.operand, env, rec))
        if isinstance(node, n.Always):
            return node
        raise CodeError(f"no code form for {node!r}")


def make_code(kind: str, sig: Card, params: Sequence[str], body, resolve: Resolver,
              *, _canonical: bool = False) -> Card:
    """The canonical code value of a definition given as kind, signature, parameter names and body."""
    if _SIG_KIND.get(_need(sig, "sig").tag) != kind:
        raise CodeError(f"signature {sig.tag} does not match kind {kind}")
    if len(params) != sig_arity(sig) or len(set(params)) != len(params):
        raise CodeError("parameter names must be distinct and match the signature arity")
    if kind == "law":
        sig = sig_law([(f"x{index}", pair.fields[1]) for index, pair in enumerate(items(sig.fields[0]))])
    if kind == "template":
        body = _need(body, "pattern", "template", 2)
        pairs = items(sig.fields[0])
        names = tuple(pair.fields[0] for pair in pairs)
        if len(set(names)) != len(names):
            raise CodeError("duplicate template parameters")
        _validate_template(sig, body)
        original = {name: f"x{index}" for index, name in enumerate(names)}
        def renamed(value):
            if isinstance(value, str):
                return re.sub(r"\$([A-Za-z_][A-Za-z_0-9]*)",
                              lambda match: "$" + original.get(match[1], match[1]), value)
            if isinstance(value, Card):
                return Card(value.sort, value.tag, tuple(renamed(field) for field in value.fields))
            return value
        sig = sig_template([(f"x{index}", pair.fields[1]) for index, pair in enumerate(pairs)], sig.fields[1])
        return Card("code", "def", (kind, sig, renamed(body), lst(), lst()))
    if kind == "bridge":
        domain = sig.fields[3]
        reserved = _global_names(body, resolve)
        if domain.tag == "some":
            domain_node = decode_node(domain.fields[0])
            reserved |= _global_names(domain_node, resolve)
            domain_canon = _Canon(resolve, reserved, _canonical)
            domain = Card("opt", "some", (encode_node(domain_canon.node(domain_node, {params[0]: "x0"})),))
            sig = Card("sig", "bridge", (*sig.fields[:3], domain))
            domain_atoms = domain_canon.atoms
            domain_deps = domain_canon.deps
        else:
            domain_atoms, domain_deps = {}, {}
    else:
        reserved = _global_names(body, resolve)
    canon = _Canon(resolve, reserved, _canonical)
    env = {param: f"x{i}" for i, param in enumerate(params)}
    canonical = canon.node(body, env)
    if kind == "bridge":
        canon.atoms.update(domain_atoms)
        canon.deps.update(domain_deps)
    collision = canon.atoms.keys() & _lexical_names(canonical, tuple(env.values()))
    if collision:
        raise CodeError(f"ambiguous global and lexical name {min(collision)!r}")
    if canon.local_calls & canon.atoms.keys():
        raise CodeError(f"ambiguous call name {min(canon.local_calls & canon.atoms.keys())!r}")
    atoms = lst(Card("atom", "atom", (name, canon.atoms[name])) for name in sorted(canon.atoms))
    deps = lst(canon.deps[digest] for digest in sorted(canon.deps))
    return Card("code", "def", (kind, sig, encode_node(canonical), atoms, deps))


def canonicalize(code: Card) -> Card:
    """Entry rule of ``code``: re-derive the canonical form of a code value built from parts."""
    code = _need(code, "code", "def", 5)
    kind, sig, body, atoms, deps = code.fields
    if not isinstance(kind, str):
        raise CodeError("kind must be text")
    if kind == "template":
        result = make_code(kind, sig, (), body, lambda name: None, _canonical=True)
        if atoms != lst() or deps != lst() or result != code:
            raise CodeError("noncanonical template code")
        return result
    by_hash = {}
    origin = None
    for dep in items(deps):
        if isinstance(dep, Card) and dep.sort == "origin":
            if origin is not None:
                raise CodeError("duplicate template provenance")
            origin = _need(dep, "origin", "template", 2)
            canonicalize(origin.fields[0])
            if origin.fields[0].fields[0] != "template":
                raise CodeError("provenance must name a template")
            for arg in items(origin.fields[1]):
                decode_pattern(arg)
            continue
        dep = canonicalize(dep)
        by_hash[code_hash(dep)] = dep
    digests = {}
    for atom in items(atoms):
        atom = _need(atom, "atom", "atom", 2)
        digests[_text(atom.fields[0])] = _text(atom.fields[1])

    decoded_body = decode_node(body)
    if digests.keys() & _lexical_names(decoded_body, tuple(f"x{i}" for i in range(sig_arity(sig)))):
        raise CodeError("global name collides with a lexical name")

    def resolve(name: str) -> Resolved | None:
        if name in digests:
            return Resolved(digest=digests[name])
        return Resolved(code=by_hash[name[1:]]) if name.startswith("#") and name[1:] in by_hash else None

    params = tuple(f"x{i}" for i in range(sig_arity(sig)))
    result = make_code(kind, sig, params, decoded_body, resolve, _canonical=True)
    if origin is not None:
        arguments = items(origin.fields[1])
        template = origin.fields[0]
        names = tuple(pair.fields[0] for pair in items(template.fields[1].fields[0]))
        if len(arguments) != len(names):
            raise CodeError("invalid template provenance arguments")
        for argument, pair in zip(arguments, items(template.fields[1].fields[0])):
            if argument.tag == "definition" and (argument.fields[1] != pair.fields[1]
                                                     and pair.fields[1] != "sort"):
                raise CodeError("invalid template provenance kind")
            if argument.tag == "definition":
                matches = [dep for digest, dep in by_hash.items() if digest == argument.fields[2]
                           and dep.fields[0] == argument.fields[1]]
                if not matches and argument.fields[0] not in digests:
                    raise CodeError("definition argument is not a canonical dependency")
        try:
            expected = instantiate_code(template, tuple(decode_pattern(arg) for arg in arguments),
                                        resolve, _reference=result, _origin_arguments=arguments)
        except (CodeError, ValueError, TypeError, KeyError) as error:
            raise CodeError("invalid template provenance") from error
        if expected != Card("code", "def", (*result.fields[:4],
                                              lst((*items(result.fields[4]), origin)))):
            raise CodeError("template provenance does not match body")
        result = expected
    return result


def is_canonical(code: Card) -> bool:
    try:
        return canonicalize(code) == code
    except CodeError:
        return False


def _provenance_resolver(source_body, canonical_body, resolve: Resolver) -> Resolver:
    """Match template source references to their canonical dependency hashes (2.2.4)."""
    aliases: dict[str, Resolved] = {}
    source_nodes = tuple(n.walk(source_body))
    target_nodes = tuple(n.walk(canonical_body))
    if len(source_nodes) != len(target_nodes):
        raise CodeError("template provenance does not match body")
    for source, target in zip(source_nodes, target_nodes):
        if type(source) is not type(target):
            raise CodeError("template provenance does not match body")
        if isinstance(source, n.Call) and len(source.args) != len(target.args):
            raise CodeError("template provenance does not match body")
        if isinstance(source, n.Call):
            names = (source.fn, target.fn)
        elif (isinstance(source, n.Lit) and isinstance(source.value, kernel.FnRef)
              and isinstance(target.value, kernel.FnRef)):
            names = (source.value.name, target.value.name)
        else:
            continue
        original, canonical = names
        if original == canonical:
            continue
        if not canonical.startswith("#"):
            continue
        dependency = resolve(canonical)
        resolved_original = resolve(original)
        if dependency is None or dependency.code is None or (
                resolved_original is not None and resolved_original != dependency):
            raise CodeError("template provenance does not match body")
        if original in aliases and aliases[original] != dependency:
            raise CodeError("template provenance does not match body")
        aliases[original] = dependency
    return lambda name: resolve(name) or aliases.get(name)


# --------------------------------------------------------------------- quote
def quote(definition, resolve_definition: Callable[[str], object | None],
          atom_digests: Mapping[str, str]) -> Card:
    """Canonical code value of an atoms-v2 ``Definition`` (spec 2.4).

    ``resolve_definition(name)`` returns the invented ``Definition`` stored under ``name`` (or None);
    ``atom_digests`` maps every given atom name to its digest (``atom_digest``).
    """
    memo: dict[str, Card] = {}

    def quote_one(defn, active: frozenset) -> Card:
        if defn.name in memo:
            return memo[defn.name]
        if defn.name in active:
            raise CodeError(f"dependency cycle through {defn.name}")
        kind, sig, params = signature_of(defn.spec)
        if kind == "template":
            result = make_code(kind, sig, (), _template_body(defn.spec.pattern, defn.body,
                                                              tuple(name for name, _ in defn.spec.params)),
                               lambda name: None)
            memo[defn.name] = result
            return result
        if not isinstance(defn.body, n.NODE_TYPES):
            raise CodeError(f"{defn.name} has no kernel body")
        body = defn.spec.map if kind == "bridge" else defn.body
        provenance = defn.spec.extra.get("template", {})
        template_code = None
        if provenance:
            template_defn = resolve_definition(provenance["name"])
            if template_defn is None:
                raise CodeError("instantiation needs its template definition")
            template_code = quote_one(template_defn, active | {defn.name})
            if isinstance(body, n.Let) and body.name.startswith("_template_origin_"):
                body = body.body

        def resolve(name: str) -> Resolved | None:
            other = resolve_definition(name)
            if other is not None and getattr(other, "origin", "invented") == "invented":
                return Resolved(code=quote_one(other, active | {defn.name}))
            if name in atom_digests:
                return Resolved(digest=atom_digests[name])
            return None

        result = make_code(kind, sig, params, body, resolve)
        if template_code is not None:
            ordered = tuple(pair.fields[0] for pair in items(template_code.fields[1].fields[0]))
            source_names = tuple(pair[0] for pair in template_defn.spec.params)
            arguments = tuple(_origin_arg(provenance["args"][source_names[index]],
                                          items(template_code.fields[1].fields[0])[index].fields[1],
                                          resolve_definition, resolve)
                              for index, _ in enumerate(ordered))
            origin = Card("origin", "template", (template_code, lst(arguments)))
            result = Card("code", "def", (*result.fields[:4], lst((*items(result.fields[4]), origin))))
        memo[defn.name] = result
        return memo[defn.name]

    return quote_one(definition, frozenset())


def quote_from_library(library, name: str) -> Card:
    """``quote`` against an ``atoms.library.Library``: invented definitions and the world's atom digests."""
    world_ops = {op.name: op for op in library.world.operations}
    digests = {}
    for atom in library.atoms:
        op = world_ops.get(atom.name)
        digests[atom.name] = atom_digest(op) if op is not None else hashlib.sha256(
            f"atom:{atom.name}:{atom.arity}:{atom.cost}".encode()).hexdigest()
    definitions = library.definitions

    def resolve(other: str):
        defn = definitions.get(other)
        return defn if defn is not None and defn.origin == "invented" else None

    return quote(definitions[name], resolve, digests)


def quote_args(library, args: Sequence[object]) -> Card:
    """Encode invented operation references as code arguments (spec 2.5)."""
    encoded = []
    for arg in args:
        if isinstance(arg, kernel.FnRef):
            definition = library.definitions.get(arg.name)
            if definition is not None and definition.origin == "invented":
                if definition.kind != "operation":
                    raise CodeError(f"{arg.name!r} is not an operation")
                encoded.append(quote_from_library(library, arg.name))
            else:
                if arg.name not in {atom.name for atom in library.atoms}:
                    raise CodeError(f"unknown given atom {arg.name!r}")
                encoded.append(_expr("fn", arg.name))
        else:
            encoded.append(arg)
    return lst(encoded)


def instantiate_code(template_code: Card, args: Mapping[str, object] | Sequence[object],
                     resolve: Resolver | None = None, *, name: str = "instantiation",
                     _reference: Card | None = None,
                     _origin_arguments: tuple[Card, ...] | None = None) -> Card | tuple[Definition, Card]:
    """Instantiate with origin; return (Definition, origin) for unquotable objects (2.1)."""
    from opulse.atoms.spec import Definition, TemplateSpec
    from opulse.atoms.templates import instantiate

    if canonicalize(template_code) != template_code or template_code.fields[0] != "template":
        raise CodeError("instantiate_code requires canonical template code")
    sig, body = template_code.fields[1:3]
    names = tuple(pair.fields[0] for pair in items(sig.fields[0]))
    values = dict(args) if isinstance(args, Mapping) else dict(zip(names, args, strict=True))
    if set(values) != set(names):
        raise CodeError("template arguments do not match parameters")
    pattern, fallback = (decode_pattern(field) for field in body.fields)
    from opulse.atoms.templates import _encode_nodes
    spec = TemplateSpec("template_source", tuple((pair.fields[0], pair.fields[1])
                                                 for pair in items(sig.fields[0])), sig.fields[1],
                        _encode_nodes(pattern))
    source = Definition(spec.name, "template", "invented", 1, (), spec, fallback)
    produced = instantiate(source, values, name)
    resolver = resolve or (lambda _: None)
    supplied_resolver = resolver
    resolver = lambda ref: (Resolved(code=template_code) if ref == spec.name else supplied_resolver(ref))
    if _origin_arguments is None:
        origin_args = tuple(_origin_arg(values[param], pair.fields[1], resolve_code=resolver)
                            for param, pair in zip(names, items(sig.fields[0])))
    else:
        origin_args = _origin_arguments
    origin = Card("origin", "template", (template_code, lst(origin_args)))
    if produced.kind == "object" and produced.spec.form in ("refine", "compose"):
        return produced, origin
    generated_body = produced.body
    if isinstance(generated_body, n.Let) and generated_body.name.startswith("_template_origin_"):
        generated_body = generated_body.body
    kind, output_sig, params = signature_of(produced.spec)
    if not isinstance(generated_body, n.NODE_TYPES):
        raise CodeError("this instantiation has no callable code body")
    if kind == "bridge":
        generated_body = produced.spec.map
    if _reference is not None:
        resolver = _provenance_resolver(generated_body, decode_node(_reference.fields[2]), resolver)
        if kind == "bridge" and output_sig.fields[3].tag == "some":
            resolver = _provenance_resolver(produced.spec.domain,
                                            decode_node(_reference.fields[1].fields[3].fields[0]), resolver)
        for argument in origin_args:
            if argument.tag == "definition":
                dependency = resolver(argument.fields[0])
                if (dependency is None or
                        (dependency.code is not None and
                         (dependency.code.fields[0] != argument.fields[1] or
                          code_hash(dependency.code) != argument.fields[2])) or
                        (dependency.code is None and dependency.digest is None)):
                    raise CodeError("definition argument does not match resolved dependency")
    result = make_code(kind, output_sig, params, generated_body, resolver)
    return Card("code", "def", (*result.fields[:4], lst((*items(result.fields[4]), origin))))


# ---------------------------------------------------------------------- decode
@dataclass(frozen=True)
class Decoded:
    main: kernel.Defn
    deps: tuple[kernel.Defn, ...]
    atoms: tuple[tuple[str, str], ...]
    kind: str
    sig: Card


def decode(code: Card) -> Decoded:
    """Kernel definitions of a canonical code value: the main one and its deps, each named ``#<hash>``."""
    code = _need(code, "code", "def", 5)
    kind, sig, _, atoms, _ = code.fields
    defns: dict[str, kernel.Defn] = {}
    layers: dict[str, int] = {}

    def build(card: Card) -> kernel.Defn:
        digest = code_hash(card)
        name = "#" + digest
        if name in defns:
            return defns[name]
        k, s, b, _, ds = card.fields
        for dep in items(ds):
            if isinstance(dep, Card) and dep.sort == "code":
                build(dep)
        node = n.Lit(b) if k == "template" else decode_node(b)
        if k == "bridge" and s.fields[3].tag == "some":
            node = n.Case(((n.Test(decode_node(s.fields[3].fields[0])), node),),
                          n.Lit(Bottom("outside_domain")))
        called = {ref for ref in n.references(node) if ref.startswith("#")}
        layers[name] = 1 + max((layers[ref] for ref in called if ref in layers), default=0)
        defns[name] = kernel.Defn(name, tuple(f"x{i}" for i in range(sig_arity(s))), node, k, layers[name])
        return defns[name]

    main = build(code)
    atom_pairs = tuple((_text(a.fields[0]), a.fields[1]) for a in (_need(x, "atom", "atom", 2) for x in items(atoms)))
    return Decoded(main, tuple(d for name, d in defns.items() if name != main.name), atom_pairs, kind, sig)


# ----------------------------------------------------------------------- display
def show(code: Card) -> str:
    """Short ASCII display ``Code<op #ab12cd(x0, x1)>`` (the full tree is the value itself)."""
    kind, sig = code.fields[0], code.fields[1]
    word = {"operation": "op", "combinator": "comb", "observation": "obs", "object": "obj",
            "law": "law", "bridge": "bridge", "template": "template"}[kind]
    params = ", ".join(f"x{i}" for i in range(sig_arity(sig)))
    return f"Code<{word} #{code_hash(code)[:6]}({params})>"
