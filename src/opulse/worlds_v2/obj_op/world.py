"""Locked open-object/open-operation world and its counted host primitives."""

import json
from pathlib import Path

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.library import Library
from opulse.atoms.spec import CombinatorSpec
from opulse.atoms.world import WorldDecl

from . import hosts

DECL_PATH = Path(__file__).resolve().parents[4] / "worlds/decl/v2/obj_op@1.json"
ACCESSORS = {"Cycle.residue": hosts.cycle_residue, "Cycle.period": hosts.cycle_period,
             "Plan.cycles": hosts.plan_cycles, "Window.plan": hosts.window_plan,
             "Window.lo": hosts.window_lo, "Window.hi": hosts.window_hi,
             "Window.compiled": hosts.window_compiled, "Blackout.window": hosts.blackout_window,
             "Blackout.bands": hosts.blackout_bands}

def until_spec():
    value = n.Var("value")
    remaining = n.Var("remaining")
    body = n.Case(((n.Test(n.Call("pred", (value,))), value),),
                  n.Case(((n.Test(n.Call("le", (remaining, n.Lit(0)))),
                           n.Call("resource_unknown", ())),),
                         n.Call("until_local", (n.Call("step", (value,)),
                                                 n.Call("sub", (remaining, n.Lit(1)))))))
    return CombinatorSpec("until", ("pred", "step", "seed", "limit"), ("pred", "step"),
                          n.Rec("until_local", ("value", "remaining"), body,
                                (n.Var("seed"), n.Var("limit")), remaining))


def fold_spec():
    remaining = n.Var("remaining")
    accumulator = n.Var("accumulator")
    body = n.Case(((n.Test(n.Call("is_empty", (remaining,))), accumulator),),
                  n.Call("fold_local", (n.Call("tail", (remaining,)),
                                        n.Call("step", (accumulator, n.Call("head", (remaining,)))))))
    return CombinatorSpec("fold", ("step", "seed", "items"), ("step",),
                          n.Rec("fold_local", ("remaining", "accumulator"), body,
                                (n.Var("items"), n.Var("seed")), n.Call("list_length", (remaining,))))


def decl():
    data = json.loads(DECL_PATH.read_text(encoding="utf-8"))
    return WorldDecl.from_dict(data)


def atoms():
    operations = [kernel.Atom(operation.name, len(operation.inputs),
                              ACCESSORS.get(operation.name) or getattr(hosts, operation.name),
                              cost=egcd_cost if operation.name == "egcd" else 1,
                              strict=operation.strict)
                  for operation in decl().operations]
    return operations + [kernel.Atom("value", 1, hosts.value, kind="observation", strict=False),
                         kernel.Atom("status", 1, hosts.status, kind="observation", strict=False),
                         kernel.Atom("range", 1, hosts.range_probe, kind="observation")]


def egcd_cost(left, right):
    if not hosts.bounded_pair(left, right):
        return 1
    count = 1
    while right:
        left, right = right, left % right
        count += 1
    return count


def new_library():
    return Library(decl(), atoms())
