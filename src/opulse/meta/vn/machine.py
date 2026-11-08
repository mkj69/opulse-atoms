"""Card-based von Neumann world (docs/spec/atoms-meta.md, section 4)."""

from __future__ import annotations

import hashlib
import importlib
import inspect
import json
from types import CodeType

from opulse.atoms import nodes
from opulse.atoms.kernel import Atom, DictScope, Limits, evaluate
from opulse.atoms.library import atoms_digest
from opulse.atoms.spec import Edge, ObjectSpec, OperationSpec
from opulse.atoms.values import FALSE, TRUE, Bottom, Card, boolean, truth
from opulse.atoms.world import WorldDecl
from opulse.meta.export_util import host_rule as _source_host_rule
from opulse.meta.vn import reference


def _helpers_digest():
    """Commit full module sources and live functions/classes (meta 4.2, 9.I4)."""
    world = importlib.import_module("opulse.meta.worlds.vonneumann.world")
    modules = (reference, importlib.import_module(__name__), world)

    def code_bytes(code):
        constants = tuple(code_bytes(item) if isinstance(item, CodeType) else repr(item)
                          for item in code.co_consts)
        return (code.co_code.hex(), constants, code.co_names, code.co_varnames,
                code.co_freevars, code.co_cellvars, code.co_argcount, code.co_posonlyargcount,
                code.co_kwonlyargcount, code.co_flags)

    def live(value):
        if inspect.isfunction(value):
            return (value.__module__, value.__qualname__, code_bytes(value.__code__),
                    repr(value.__defaults__), repr(value.__kwdefaults__))
        if isinstance(value, (staticmethod, classmethod)):
            return live(value.__func__)
        if isinstance(value, (tuple, list)):
            return tuple(live(item) for item in value)
        if isinstance(value, dict):
            return tuple(sorted((repr(key), live(item)) for key, item in value.items()))
        if isinstance(value, (str, int, float, bool, type(None))):
            return value
        return type(value).__name__

    records = []
    for module in modules:
        members = []
        for name, value in vars(module).items():
            if inspect.isfunction(value) or name.isupper() or name in ("_OPERATIONS", "_PROBES"):
                members.append((name, live(value)))
            elif inspect.isclass(value) and value.__module__ == module.__name__:
                members.append((name, tuple(sorted((key, live(member)) for key, member in vars(value).items()
                                                   if inspect.isfunction(member) or
                                                   isinstance(member, (staticmethod, classmethod))))))
        records.append((module.__name__, inspect.getsource(module), tuple(sorted(members))))
    return hashlib.sha256(repr(records).encode("utf-8")).hexdigest()


def _host_rule(fn):
    rule = _source_host_rule(fn)
    rule["digest"] = hashlib.sha256(json.dumps(
        (rule["digest"], _helpers_digest()), separators=(",", ":")
    ).encode("ascii")).hexdigest()
    return rule


def atoms_hash(n: int) -> str:
    """Pin both atom wrappers/costs and the source of their transitive helpers."""
    return hashlib.sha256(json.dumps(
        (atoms_digest(atoms(n)), _helpers_digest()), separators=(",", ":")
    ).encode("ascii")).hexdigest()


def to_card(state: reference.State) -> Card:
    return Card("vn", "vn", (state.pc, state.a, Card("mem", "items", state.mem), boolean(state.halted)))


def from_card(card: Card) -> reference.State:
    if not isinstance(card, Card) or card.sort != "vn" or card.tag != "vn" or len(card.fields) != 4:
        raise ValueError("invalid vn state")
    pc, accumulator, memory, halted = card.fields
    if not isinstance(memory, Card) or memory.sort != "mem" or memory.tag != "items":
        raise ValueError("invalid vn memory")
    if halted not in (FALSE, TRUE):
        raise ValueError("invalid vn halted flag")
    return reference.State(pc, accumulator, memory.fields, truth(halted))


def _byte(value):
    return type(value) is int and 0 <= value < 256


def _address(state, address):
    return type(address) is int and 0 <= address < len(state.mem)


def step(state):
    try:
        return to_card(reference.step(from_card(state)))
    except reference.Illegal:
        return Bottom("illegal")


def is_halted(state):
    return boolean(from_card(state).halted)


def poke(state, address, value):
    current = from_card(state)
    if not _address(current, address) or not _byte(value):
        return Bottom("invalid")
    memory = current.mem[:address] + (value,) + current.mem[address + 1:]
    return to_card(reference.State(current.pc, current.a, memory, current.halted))


def peek(state, address):
    current = from_card(state)
    return current.mem[address] if _address(current, address) else Bottom("invalid")


def set_a(state, value):
    current = from_card(state)
    return (to_card(reference.State(current.pc, value, current.mem, current.halted))
            if _byte(value) else Bottom("invalid"))


def get_a(state):
    return from_card(state).a


def set_pc(state, address):
    current = from_card(state)
    return (to_card(reference.State(address, current.a, current.mem, current.halted))
            if _address(current, address) else Bottom("invalid"))


def get_pc(state):
    return from_card(state).pc


def cell(state, address):
    return peek(state, address)


def halted(state):
    return is_halted(state)


_OPERATIONS = (("step", step, 1, 1, "vn", "transform", ("illegal",)),
               ("is_halted", is_halted, 1, 0, "bool", "decide", ()),
               ("poke", poke, 3, 1, "vn", "act", ("invalid",)),
               ("peek", peek, 2, 1, "byte", "transform", ("invalid",)),
               ("set_a", set_a, 2, 1, "vn", "act", ("invalid",)),
               ("get_a", get_a, 1, 1, "byte", "transform", ()),
               ("set_pc", set_pc, 2, 1, "vn", "act", ("invalid",)),
               ("get_pc", get_pc, 1, 1, "int", "transform", ()))
_PROBES = (("pc", get_pc, 1, "int"), ("a", get_a, 1, "byte"),
           ("cell", cell, 2, "byte"), ("halted", halted, 1, "bool"))


class _CommittedHost:
    """Expose source-only commitments to core atoms_digest (meta 4.2, 9.I4)."""

    __slots__ = ("fn",)

    def __init__(self, fn):
        self.fn = fn

    def __call__(self, *args):
        return self.fn(*args)

    @property
    def __dict__(self):
        return {"fn": self.fn, "helpers_digest": _helpers_digest()}

    def __repr__(self):
        return f"{self.fn.__module__}.{self.fn.__qualname__}:{_helpers_digest()}"


def atoms(n: int) -> tuple[Atom, ...]:
    if n not in reference.SIZES:
        raise ValueError("invalid memory size")
    return tuple(Atom(name, arity, _CommittedHost(fn) if name == "step" else fn, cost)
                 for name, fn, arity, cost, _, _, _ in _OPERATIONS) + tuple(
        Atom(name, arity, fn, 0, "observation") for name, fn, arity, _ in _PROBES)


def exec_node(state_node: nodes.Node) -> nodes.Rec:
    """The @exec kernel combinator (section 4.2)."""
    state = nodes.Var("s")
    return nodes.Rec("r0", ("s",), nodes.Case(
        ((nodes.Test(nodes.Call("is_halted", (state,))), state),),
        nodes.Call("r0", (nodes.Call("step", (state,)),))), (state_node,), "fuel")


def run(state_card: Card, fuel: int):
    return evaluate(exec_node(nodes.Lit(state_card)), scope=DictScope(atoms(len(from_card(state_card).mem))),
                    limits=Limits(fuel=fuel))


def world_decl(n: int) -> WorldDecl:
    """Declare the layer-0 objects, operations, and probes (section 4.2)."""
    if n not in reference.SIZES:
        raise ValueError("invalid memory size")
    objects = (ObjectSpec("byte", "refine", base="int", valid=_host_rule(_byte)),
               ObjectSpec("mem", "compose", tags={"items": {"items": "byte"}}, params=("n:int",)),
               ObjectSpec("vn", "compose", tags={"vn": [["pc", "int"], ["a", "byte"],
                                                        ["mem", "mem"], ["halted", "bool"]]}))
    operations = []
    for name, fn, arity, cost, result, role, errors in _OPERATIONS:
        inputs = ("vn", "int", "byte") if name == "poke" else (
            ("vn", "byte") if name == "set_a" else
            ("vn", "int") if arity == 2 else ("vn",))
        operations.append(OperationSpec(name, role, tuple(Edge(sort, name=field) for sort, field in
                                                   zip(inputs, ("s", "k", "b"))), Edge(result),
                                        inspect.getdoc(fn) or f"vn/1 {name}", errors,
                                        _host_rule(fn), cost, extra={"input_names": ["s", "k", "b"][:arity]}))
    probes = [{"name": name, "sort": sort, "kind": "observation", "arity": arity,
               "impl": _host_rule(fn)} for name, fn, arity, sort in _PROBES]
    digests = {name: _host_rule(fn)["digest"] for name, fn, *_ in _OPERATIONS + _PROBES}
    digests["byte.valid"] = _host_rule(_byte)["digest"]
    return WorldDecl("vonneumann", 1, "atoms-v2", {"n": n}, {}, objects, tuple(operations),
                     {"nodes": ["Var", "Lit", "Call", "Let", "Case", "Rec"], "library": ["exec"],
                      "recursion": "fuel"},
                     {"truth": "vn", "probes": probes, "judge_view": "full_state"},
                     {"host_digests": digests})
