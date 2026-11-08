"""A finite sealed-register world with indistinguishable hidden states."""

from __future__ import annotations

from math import isqrt

from opulse.atoms import kernel
from opulse.atoms.spec import Edge, ObjectSpec, OperationSpec
from opulse.atoms.values import Card
from opulse.atoms.world import WorldDecl
from opulse.gen_v2.base import GenWorld, Signature, Sort


def _read(index):
    return lambda truth: truth.fields[index]


def _zigzag(value):
    return value * 2 if value >= 0 else -2 * value - 1


def _pack(previous, change):
    first, second = _zigzag(previous), _zigzag(change)
    return (first + second) * (first + second + 1) // 2 + second


def _unpack(value):
    if value < 0:
        return (0, 0)
    diagonal = (isqrt(8 * value + 1) - 1) // 2
    offset = value - diagonal * (diagonal + 1) // 2
    first, second = diagonal - offset, offset
    return ((first // 2 if first % 2 == 0 else -(first + 1) // 2),
            (second // 2 if second % 2 == 0 else -(second + 1) // 2))


def _remember(memory, value):
    previous, _ = _unpack(memory)
    return _pack(value, abs(value - previous))


_OPS = {
    "add": (("int", "int"), "int", lambda left, right: left + right),
    "sub": (("int", "int"), "int", lambda left, right: left - right),
    "inc": (("int",), "int", lambda value: value + 1),
    "dec": (("int",), "int", lambda value: value - 1),
    "neg": (("int",), "int", lambda value: -value),
    "absv": (("int",), "int", abs),
    "maxv": (("int", "int"), "int", max),
    "lt": (("int", "int"), "bool", lambda left, right: left < right),
    "eq": (("int", "int"), "bool", lambda left, right: left == right),
    "is_pos": (("int",), "bool", lambda value: value > 0),
    "is_zero": (("int",), "bool", lambda value: value == 0),
    "is_even": (("int",), "bool", lambda value: value % 2 == 0),
    "remember": (("int", "int"), "int", _remember),
    "change": (("int",), "int", lambda memory: _unpack(memory)[1]),
    "act": (("truth",), "truth", lambda truth: truth),
    "hidden": (("truth",), "int", _read(3)),
}
_PROBES = {"read_x": _read(0), "read_y": _read(1), "read_z": _read(2),
           "read_sum": lambda truth: sum(truth.fields[:3])}


def gen_world(open_kinds=("observation",)) -> GenWorld:
    operations = [OperationSpec(name, "act" if name == "act" else "decide" if output == "bool"
                                else "combine" if len(inputs) == 2 else "transform",
                                tuple(Edge(sort) for sort in inputs), Edge(output), name)
                  for name, (inputs, output, _) in _OPS.items()]
    operations.extend(OperationSpec(name, "decide", (Edge("truth"),), Edge("int"), name)
                      for name in _PROBES)
    decl = WorldDecl("toy_truth", 1, "atoms-v2", {}, {},
                     (ObjectSpec("int", "given"), ObjectSpec("bool", "given"),
                      ObjectSpec("truth", "given", sealed=True, interface=tuple(_PROBES))), tuple(operations),
                     {"nodes": ["Var", "Lit", "Call", "Let", "Case"], "library": [],
                      "recursion": "none"},
                     {"truth": "truth", "probes": list(_PROBES), "show": {},
                      "judge_view": "full_state"}, {}, {"open_kinds": list(open_kinds)},
                     open_kinds=tuple(open_kinds))
    atoms = [kernel.Atom(name, len(inputs), fn) for name, (inputs, _, fn) in _OPS.items()]
    atoms.extend(kernel.Atom(name, 1, fn, kind="observation") for name, fn in _PROBES.items())
    signatures = {name: Signature(inputs, output) for name, (inputs, output, _) in _OPS.items()}
    signatures.update({name: Signature(("truth",), "int") for name in _PROBES})
    truth_states = tuple(Card("truth", "registers", (x, y, z, hidden))
                         for x in range(4) for y in range(4) for z in range(4) for hidden in range(2))
    sorts = {"int": Sort("int", tuple(range(-4, 13))),
             "bool": Sort("bool", (False, True)),
             "truth": Sort("truth", truth_states, sealed=True, interface=tuple(_PROBES))}
    return GenWorld("toy_truth", decl, atoms, signatures, sorts,
                    frozenset(open_kinds), "truth", truth_states, tuple(_PROBES),
                    max_steps=150, max_scope=96, title="Sealed registers")
