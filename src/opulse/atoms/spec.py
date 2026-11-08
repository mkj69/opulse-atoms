"""Definition records (docs/spec/atoms-v2.md, sections 4, 5, 7, 8 and 9).

A library invalidates evidence without a recorded ``scope.checked``
(``Evidence.checked_recorded``); the record itself stays a plain value.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import Enum

from opulse.atoms import KINDS, nodes

_HOST = re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*:[A-Za-z_][\w.]*")


def is_host_rule(value) -> bool:
    """A layer-0 host rule ``{"host": "module:qualname", "digest": sha256}`` (spec 5, 13)."""
    return (isinstance(value, dict) and set(value) == {"host", "digest"} and isinstance(value["host"], str)
            and bool(_HOST.fullmatch(value["host"])) and bool(re.fullmatch(r"[0-9a-f]{64}", str(value["digest"]))))


def _node(value):
    if value is None or is_host_rule(value):
        return value
    return nodes.to_json(value)


def _read_node(value):
    if value is None or is_host_rule(value):
        return value
    return nodes.from_json(value)


def _free_vars(node, bound=frozenset()):
    if isinstance(node, nodes.Var):
        return set() if node.name in bound else {node.name}
    if isinstance(node, nodes.Let):
        return _free_vars(node.value, bound) | _free_vars(node.body, bound | {node.name})
    if isinstance(node, nodes.Rec):
        local = bound | {node.fn, *node.params}
        result = set().union(*(_free_vars(arg, bound) for arg in node.args)) if node.args else set()
        if not isinstance(node.measure, str):
            result |= _free_vars(node.measure, local)
        return result | _free_vars(node.body, local)
    if isinstance(node, nodes.Blocks):
        local = bound | {name for name, _ in node.vars}
        return set().union(*(_free_vars(child, local) for child in nodes.children(node)))
    result = set()
    for child in nodes.children(node):
        result.update(_free_vars(child, bound))
    return result


@dataclass(frozen=True)
class Edge:
    sort: str
    enter: str = "bottom"
    name: str | None = None  # parameter name (display)

    def __post_init__(self):
        match = re.fullmatch(r"saturate\((-?\d+),\s*(-?\d+)\)", self.enter)
        if match and int(match[1]) > int(match[2]):
            raise ValueError("saturate lower bound exceeds upper bound")
        if self.enter not in ("bottom", "normalize") and not match and not re.fullmatch(r"fold\([\w.-]+\)", self.enter):
            raise ValueError(f"invalid entry rule: {self.enter}")

    def to_dict(self):
        data = {"sort": self.sort, "enter": self.enter}
        if self.name is not None:
            data["name"] = self.name
        return data

    @classmethod
    def from_dict(cls, data):
        return cls(**data)


@dataclass(frozen=True)
class ObjectSpec:
    name: str
    form: str
    base: str | None = None
    tags: dict | None = None
    group: tuple[str, ...] = ()
    valid: object = None
    canon: object = None
    sealed: bool = False
    interface: tuple[str, ...] = ()
    params: tuple[str, ...] = ()
    equality: str = "canonical"
    canon_cost: str = "counted"
    body: object = None
    extra: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.form not in ("given", "compose", "refine", "constant"):
            raise ValueError("invalid object form")
        if self.equality not in ("canonical", "none") or self.canon_cost not in ("counted", "free"):
            raise ValueError("invalid equality or canon cost")
        if self.form == "compose":
            if not isinstance(self.tags, dict) or not self.tags:
                raise ValueError("compose needs tags")
            for tag, fields in self.tags.items():
                if not isinstance(tag, str) or not tag:
                    raise ValueError("tag needs a name")
                # Fields: [[name, sort], ...] or {name: sort, ...}; {"items": sort} is a variable-length tag.
                if not isinstance(fields, (list, tuple, dict)):
                    raise TypeError("tag fields must be pairs or a name -> sort mapping")
                if isinstance(fields, dict) and not all(isinstance(key, str) and key and isinstance(value, str)
                                                        and value for key, value in fields.items()):
                    raise ValueError("tag fields must map names to sorts")
                if isinstance(fields, (list, tuple)) and any(
                    not isinstance(pair, (list, tuple)) or len(pair) != 2 or
                    not all(isinstance(value, str) and value for value in pair) for pair in fields
                ):
                    raise ValueError("tag fields must be named sort pairs")
            object.__setattr__(self, "tags", {tag: [list(pair) for pair in fields]
                                               if isinstance(fields, (list, tuple)) else dict(fields)
                                               for tag, fields in self.tags.items()})
            if self.group == (self.name,) or self.group == ():  # a lone sort; groups are checked as a whole
                group = {self.name}
                if not any(all(sort not in group for sort in (fields.values() if isinstance(fields, dict) else (pair[1] for pair in fields))) for fields in self.tags.values()):
                    raise ValueError("recursive group needs a base tag")
        if self.form == "refine" and (not self.base or self.valid is None):
            raise ValueError("refine needs base and valid")
        if self.form == "constant" and (self.tags is not None or self.body is None or _free_vars(self.body)):
            raise ValueError("constant needs a closed body and no tags")
        if self.sealed and not self.interface:
            raise ValueError("sealed object needs an interface")
        if any(not re.fullmatch(r"[A-Za-z_][\w]*(?::(?:int|str))?", param) for param in self.params):
            raise ValueError("invalid static parameter")

    def to_dict(self):
        return {**self.extra, "name": self.name, "form": self.form, "base": self.base, "tags": self.tags,
                "group": list(self.group), "valid": _node(self.valid), "canon": _node(self.canon),
                "sealed": self.sealed, "interface": list(self.interface), "params": list(self.params),
                "equality": self.equality, "canon_cost": self.canon_cost, "body": _node(self.body)}

    @classmethod
    def from_dict(cls, data):
        data = dict(data)
        known = cls.__dataclass_fields__.keys() - {"extra"}
        extra = {name: data.pop(name) for name in tuple(data) if name not in known}
        for name in ("valid", "canon", "body"):
            data[name] = _read_node(data.get(name))
        for name in ("group", "interface", "params"):
            data[name] = tuple(data.get(name, ()))
        return cls(**data, extra=extra)


@dataclass(frozen=True)
class OperationSpec:
    name: str
    role: str
    inputs: tuple[Edge, ...]
    output: Edge
    rule: str
    errors: tuple[str, ...] = ()
    impl: dict | None = None
    cost: int = 1
    strict: bool = True
    reads_params: tuple[str, ...] = ()
    extra: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.role not in ("transform", "combine", "decide", "relate", "act") or not self.rule.strip():
            raise ValueError("invalid role or empty operation rule")
        if self.impl is not None:
            if len(self.impl) != 1 and set(self.impl) != {"host", "digest"}:
                raise ValueError("invalid operation implementation")
            if "host" in self.impl and (not isinstance(self.impl.get("host"), str) or
                                        not _HOST.fullmatch(self.impl["host"]) or
                                        not re.fullmatch(r"[0-9a-f]{64}", self.impl.get("digest", ""))):
                raise ValueError("host implementation requires a sha256 digest")
            if not set(self.impl).intersection({"host", "table", "body"}):
                raise ValueError("invalid operation implementation")

    def to_dict(self):
        impl = dict(self.impl) if self.impl is not None else None
        if impl is not None and "body" in impl:
            impl["body"] = _node(impl["body"])
        return {**self.extra, "name": self.name, "role": self.role, "inputs": [edge.to_dict() for edge in self.inputs],
                "output": self.output.to_dict(), "rule": self.rule, "errors": list(self.errors),
                "impl": impl, "cost": self.cost, "strict": self.strict, "reads_params": list(self.reads_params)}

    @classmethod
    def from_dict(cls, data):
        data = dict(data)
        known = cls.__dataclass_fields__.keys() - {"extra"}
        extra = {name: data.pop(name) for name in tuple(data) if name not in known}
        data["inputs"] = tuple(Edge.from_dict(edge) for edge in data["inputs"])
        data["output"] = Edge.from_dict(data["output"])
        if data.get("impl") is not None and "body" in data["impl"]:
            data["impl"] = {**data["impl"], "body": _read_node(data["impl"]["body"])}
        for name in ("errors", "reads_params"):
            data[name] = tuple(data.get(name, ()))
        return cls(**data, extra=extra)


@dataclass(frozen=True)
class CombinatorSpec:
    name: str
    params: tuple[str, ...]
    op_params: tuple[str, ...]
    body: object
    unfold_rule: str = "substitute"
    extra: dict = field(default_factory=dict)

    def to_dict(self):
        return {**self.extra, "name": self.name, "params": list(self.params), "op_params": list(self.op_params),
                "body": _node(self.body), "unfold_rule": self.unfold_rule}

    @classmethod
    def from_dict(cls, data):
        known = {"name", "params", "op_params", "body", "unfold_rule"}
        return cls(data["name"], tuple(data["params"]), tuple(data["op_params"]),
                   _read_node(data["body"]), data.get("unfold_rule", "substitute"),
                   {key: value for key, value in data.items() if key not in known})


@dataclass(frozen=True)
class ObservationSpec:
    name: str
    reads: tuple[str, ...]
    body: object
    memory: dict | None = None
    extra: dict = field(default_factory=dict)  # e.g. "subject": the name of the observed value (default s)

    @property
    def subject(self) -> str:
        return self.extra.get("subject", "s")

    def to_dict(self):
        memory = None if self.memory is None else {**self.memory, "init": _node(self.memory["init"]),
                                                    "step": _node(self.memory["step"])}
        return {**self.extra, "name": self.name, "reads": list(self.reads), "body": _node(self.body),
                "memory": memory}

    @classmethod
    def from_dict(cls, data):
        memory = data.get("memory")
        if memory is not None:
            memory = {**memory, "init": _read_node(memory["init"]), "step": _read_node(memory["step"])}
        known = {"name", "reads", "body", "memory"}
        return cls(data["name"], tuple(data["reads"]), _read_node(data["body"]), memory,
                   {key: value for key, value in data.items() if key not in known})


def _pairs(items) -> tuple[tuple[str, str], ...]:
    return tuple((str(name), str(sort)) for name, sort in items)


@dataclass(frozen=True)
class LawSpec:
    """A statement that holds in a world (spec 0.4, kind law, sigil #): a boolean node over
    typed variables. ``eq(lhs, rhs)`` statements are equations and can serve as rewrite steps."""

    name: str
    vars: tuple[tuple[str, str], ...]
    statement: object
    extra: dict = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, "vars", _pairs(self.vars))
        if len({name for name, _ in self.vars}) != len(self.vars):
            raise ValueError("law variables must be distinct")

    @property
    def equation(self):
        """(lhs, rhs) when the statement is eq(lhs, rhs), else None."""
        body = self.statement
        if isinstance(body, nodes.Call) and body.fn == "eq" and len(body.args) == 2:
            return body.args
        return None

    def to_dict(self):
        return {**self.extra, "name": self.name, "vars": [list(pair) for pair in self.vars],
                "statement": _node(self.statement)}

    @classmethod
    def from_dict(cls, data):
        known = {"name", "vars", "statement"}
        return cls(data["name"], _pairs(data["vars"]), _read_node(data["statement"]),
                   {key: value for key, value in data.items() if key not in known})


@dataclass(frozen=True)
class BridgeSpec:
    """A translation between objects or worlds (spec 0.4, kind bridge, sigil ~). ``map`` is a node
    over the variable ``x``; ``domain`` (optional) a boolean node over ``x`` for partial bridges;
    ``interface`` pairs (source operation, target operation) whose diagram must commute."""

    name: str
    source: str
    target: str
    map: object
    domain: object = None
    interface: tuple[tuple[str, str], ...] = ()
    extra: dict = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, "interface", _pairs(self.interface))

    def to_dict(self):
        return {**self.extra, "name": self.name, "source": self.source, "target": self.target,
                "map": _node(self.map), "domain": _node(self.domain),
                "interface": [list(pair) for pair in self.interface]}

    @classmethod
    def from_dict(cls, data):
        known = {"name", "source", "target", "map", "domain", "interface"}
        return cls(data["name"], data["source"], data["target"], _read_node(data["map"]),
                   _read_node(data.get("domain")), _pairs(data.get("interface", ())),
                   {key: value for key, value in data.items() if key not in known})


@dataclass(frozen=True)
class TemplateSpec:
    """A definition with kind and value parameters (spec 0.4): ``params`` are (name, kind) pairs
    where kind is one of the six kinds or a sort; ``produces`` the kind of every instantiation;
    ``pattern`` the produced spec as a dict whose strings and nodes may mention ``$param``."""

    name: str
    params: tuple[tuple[str, str], ...]
    produces: str
    pattern: dict
    extra: dict = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, "params", _pairs(self.params))
        if self.produces not in KINDS:
            raise ValueError(f"template produces an unknown kind: {self.produces}")

    def to_dict(self):
        return {**self.extra, "name": self.name, "params": [list(pair) for pair in self.params],
                "produces": self.produces, "pattern": self.pattern}

    @classmethod
    def from_dict(cls, data):
        known = {"name", "params", "produces", "pattern"}
        return cls(data["name"], _pairs(data["params"]), data["produces"], data["pattern"],
                   {key: value for key, value in data.items() if key not in known})


@dataclass(frozen=True)
class Evidence:
    method: str
    scope: dict
    seed: int | None = None
    checks: tuple[str, ...] = ()
    world_hash: str = ""
    deps_hash: str = ""
    content_hash: str = ""
    atoms_hash: str = ""

    def __post_init__(self):
        if self.method not in ("exhaustive", "bounded", "sampled") or not {"domain", "size"} <= self.scope.keys():
            raise ValueError("invalid evidence method or scope")
        if self.method == "sampled" and self.seed is None:
            raise ValueError("sampled evidence needs a seed")

    def checked_recorded(self) -> bool:
        checked = self.scope.get("checked")
        return (isinstance(checked, dict) and type(checked.get("size")) is int and
                checked["size"] == self.scope.get("size") and
                isinstance(checked.get("sha256"), str) and
                re.fullmatch(r"[0-9a-f]{64}", checked["sha256"]) is not None and
                isinstance(checked.get("bounds"), dict))

    def to_dict(self):
        return {"method": self.method, "scope": self.scope, "seed": self.seed,
                "checks": list(self.checks), "world_hash": self.world_hash, "deps_hash": self.deps_hash,
                "content_hash": self.content_hash, "atoms_hash": self.atoms_hash}

    @classmethod
    def from_dict(cls, data):
        return cls(**{**data, "checks": tuple(data.get("checks", ()))})


@dataclass(frozen=True)
class Contract:
    guarantees: str = ""
    may_change: tuple[str, ...] = ()
    keeps: tuple[str, ...] = ()

    def to_dict(self):
        return {"guarantees": self.guarantees, "may_change": list(self.may_change), "keeps": list(self.keeps)}

    @classmethod
    def from_dict(cls, data):
        return cls(data.get("guarantees", ""), tuple(data.get("may_change", ())), tuple(data.get("keeps", ())))


@dataclass(frozen=True)
class Cost:
    length: int = 0
    steps: dict | None = None
    reuse: int = 0

    def to_dict(self):
        return {"length": self.length, "steps": self.steps, "reuse": self.reuse}

    @classmethod
    def from_dict(cls, data):
        return cls(**data)


class Status(str, Enum):
    WRITTEN = "written"
    CHECKED = "checked"
    CALLABLE = "callable"
    VERIFIED = "verified"
    PROMOTED = "promoted"


def advance(current: str, target: str) -> str:
    order = tuple(status.value for status in Status)
    if current not in order or target not in order or order.index(target) != order.index(current) + 1:
        raise ValueError(f"invalid status transition: {current} -> {target}")
    return target


def reset(status: str) -> str:
    if status not in Status._value2member_map_:
        raise ValueError(f"invalid status: {status}")
    return "callable"


_SPEC_CLASSES = {"object": ObjectSpec, "operation": OperationSpec,
                 "combinator": CombinatorSpec, "observation": ObservationSpec,
                 "law": LawSpec, "bridge": BridgeSpec, "template": TemplateSpec}


@dataclass(frozen=True)
class Definition:
    name: str
    kind: str
    origin: str
    layer: int
    depends_on: tuple[str, ...]
    spec: ObjectSpec | OperationSpec | CombinatorSpec | ObservationSpec
    body: object
    evidence: Evidence | None = None
    contract: Contract | None = None
    cost: Cost = field(default_factory=Cost)
    status: str = "written"
    id: str | None = None

    def content_hash(self, dependencies: dict[str, str] | None = None) -> str:
        body = _node(self.body) if isinstance(self.body, nodes.NODE_TYPES) else self.body
        spec = self.spec.to_dict()
        # Parameter names bind the body's variables (their order is semantic), so input_names stays in.
        display_only = {"title", "title_zh", "doc", "source", "symbol"}

        return content_hash({"kind": self.kind, "spec": {key: value for key, value in spec.items()
                                                          if key not in display_only}, "body": body,
                             "dependencies": {name: dependencies[name] for name in sorted(self.depends_on)}
                             if dependencies is not None else {}})

    def validate(self) -> list[str]:
        problems = []
        if self.kind not in _SPEC_CLASSES or not isinstance(self.spec, _SPEC_CLASSES.get(self.kind, ())):
            problems.append("kind must match spec")
        if self.origin not in ("given", "invented"):
            problems.append("invalid origin")
        elif self.origin == "given" and self.layer != 0 or self.origin == "invented" and self.layer < 1:
            problems.append("invalid layer for origin")
        if self.origin == "invented" and isinstance(self.spec, ObjectSpec) and any(
                is_host_rule(rule) for rule in (self.spec.valid, self.spec.canon)):
            problems.append("host rules are allowed only for given layer-0 objects")
        if self.status not in Status._value2member_map_:
            problems.append("invalid status")
        if isinstance(self.body, nodes.NODE_TYPES):
            excluded = set(self.spec.op_params) if isinstance(self.spec, CombinatorSpec) else set()
            memory = getattr(self.spec, "memory", None) or {}
            template = getattr(self.spec, "extra", {}).get("template")
            provenance = ({value for value in (template.get("name"), *template.get("args", {}).values())
                           if isinstance(value, str)}
                          if isinstance(template, dict) and isinstance(template.get("args"), dict)
                          and self.kind in ("law", "bridge") else set())
            referenced = nodes.references(self.body) | set().union(
                *(nodes.references(node) for node in (memory.get("init"), memory.get("step"))
                  if isinstance(node, nodes.NODE_TYPES)))
            provenance -= referenced
            if (len(set(self.depends_on)) != len(self.depends_on) or
                    not nodes.dependencies_match(tuple(name for name in self.depends_on if name not in provenance),
                                                 self.body, excluded, (memory.get("init"), memory.get("step")))):
                problems.append("depends_on does not match body references")
        if self.status == "promoted" and self.origin != "given":
            if self.evidence is None or self.evidence.method not in ("exhaustive", "bounded"):
                problems.append("promotion needs exhaustive or bounded evidence")
            if self.contract is None:
                problems.append("promotion needs a contract")
        if (self.status == "verified" or self.status == "promoted" and self.origin != "given") and self.evidence is None:
            problems.append("verification needs evidence")
        return problems

    def to_dict(self):
        body = _node(self.body) if isinstance(self.body, nodes.NODE_TYPES) else self.body
        return {"schema": "opulse.definition/2", "id": self.id, "name": self.name, "kind": self.kind,
                "origin": self.origin, "layer": self.layer, "depends_on": list(self.depends_on),
                "spec": self.spec.to_dict(), "body": body,
                "evidence": self.evidence.to_dict() if self.evidence else None,
                "contract": self.contract.to_dict() if self.contract else None,
                "cost": self.cost.to_dict(), "status": self.status}

    @classmethod
    def from_dict(cls, data):
        if data.get("schema") != "opulse.definition/2":
            raise ValueError("invalid definition schema")
        body = data["body"]
        if isinstance(body, dict) and "node" in body:
            body = _read_node(body)
        return cls(data["name"], data["kind"], data["origin"], data["layer"], tuple(data["depends_on"]),
                   _SPEC_CLASSES[data["kind"]].from_dict(data["spec"]), body,
                   Evidence.from_dict(data["evidence"]) if data.get("evidence") else None,
                   Contract.from_dict(data["contract"]) if data.get("contract") else None,
                   Cost.from_dict(data.get("cost", {})), data.get("status", "written"), data.get("id"))


def compute_layer(depends_on, layer_of) -> int:
    return 1 + max((layer_of[name] if not callable(layer_of) else layer_of(name) for name in depends_on), default=0)


def content_hash(obj) -> str:
    data = obj.to_dict() if hasattr(obj, "to_dict") else obj
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
