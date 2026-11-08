from dataclasses import dataclass


@dataclass(frozen=True)
class Var:
    name: str

    def to_json(self):
        return {"type": "var", "name": self.name}


@dataclass(frozen=True)
class Lit:
    value: int

    def to_json(self):
        return {"type": "lit", "value": self.value}


@dataclass(frozen=True)
class Call:
    name: str
    args: tuple

    def to_json(self):
        return {"type": "call", "name": self.name, "args": [arg.to_json() for arg in self.args]}


@dataclass(frozen=True)
class Let:
    name: str
    bound: object
    body: object

    def to_json(self):
        return {"type": "let", "name": self.name, "bound": self.bound.to_json(), "body": self.body.to_json()}


@dataclass(frozen=True)
class If:
    cond: object
    then: object
    other: object

    def to_json(self):
        return {"type": "if", "cond": self.cond.to_json(), "then": self.then.to_json(), "other": self.other.to_json()}


@dataclass(frozen=True)
class Def:
    name: str
    params: tuple[str, ...]
    body: object
    param_sorts: tuple[str, ...] = ()
    result_sort: str = "Nat"

    def __post_init__(self):
        if not self.param_sorts:
            object.__setattr__(self, "param_sorts", ("Nat",) * len(self.params))

    def to_json(self):
        return {"type": "def", "name": self.name, "params": list(self.params), "body": self.body.to_json(),
                "param_sorts": list(self.param_sorts), "result_sort": self.result_sort}


@dataclass(frozen=True)
class Program:
    defs: tuple[Def, ...]
    saves: tuple[str, ...]

    def to_json(self):
        return {"type": "program", "defs": [definition.to_json() for definition in self.defs], "saves": list(self.saves)}


def node_from_json(data):
    kind = data["type"]
    if kind == "var":
        return Var(data["name"])
    if kind == "lit":
        return Lit(data["value"])
    if kind == "call":
        return Call(data["name"], tuple(node_from_json(arg) for arg in data["args"]))
    if kind == "let":
        return Let(data["name"], node_from_json(data["bound"]), node_from_json(data["body"]))
    if kind == "if":
        return If(node_from_json(data["cond"]), node_from_json(data["then"]), node_from_json(data["other"]))
    if kind == "def":
        return Def(data["name"], tuple(data["params"]), node_from_json(data["body"]),
                   tuple(data.get("param_sorts", ("Nat",) * len(data["params"]))), data.get("result_sort", "Nat"))
    if kind == "program":
        return Program(tuple(node_from_json(item) for item in data["defs"]), tuple(data["saves"]))
    raise ValueError(f"unknown node type {kind}")


def _format_expr(node):
    if isinstance(node, Var):
        return node.name
    if isinstance(node, Lit):
        return str(node.value)
    if isinstance(node, Call):
        return f"{node.name}({', '.join(_format_expr(arg) for arg in node.args)})"
    if isinstance(node, Let):
        return f"let {node.name} = {_format_expr(node.bound)} in {_format_expr(node.body)}"
    if isinstance(node, If):
        return f"if {_format_expr(node.cond)} then {_format_expr(node.then)} else {_format_expr(node.other)}"
    raise TypeError(f"not an expression: {node!r}")


def format_def(definition):
    sorts = definition.param_sorts or ("Nat",) * len(definition.params)
    params = ", ".join(f"{name}: {sort}" for name, sort in zip(definition.params, sorts))
    return f"op {definition.name}({params}) -> {definition.result_sort} = {_format_expr(definition.body)}"


def size(definition):
    def count(node):
        if isinstance(node, (Lit, Var)):
            return 1
        if isinstance(node, Call):
            return 1 + sum(count(arg) for arg in node.args)
        if isinstance(node, Let):
            return 1 + count(node.bound) + count(node.body)
        if isinstance(node, If):
            return 1 + count(node.cond) + count(node.then) + count(node.other)
        raise TypeError(f"not an expression: {node!r}")

    return 1 + len(definition.params) + count(definition.body)
