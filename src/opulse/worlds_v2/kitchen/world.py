"""Locked timed-kitchen declaration and its layer-zero atoms."""

import json
from pathlib import Path

from opulse.atoms import kernel, nodes
from opulse.atoms.kernel import Atom
from opulse.atoms.values import Bottom, Card
from opulse.atoms.world import WorldDecl

from . import depth_hosts
from .depth_adapter import KitchenLibrary


def example_expression(value):
    if isinstance(value, Card) and value.sort == "Plan":
        start, slots, _ = value.fields[0].fields
        return nodes.Call("make_plan", (nodes.Lit(start), nodes.Lit(slots)))
    if isinstance(value, tuple) and any(isinstance(item, Card) and item.sort == "Plan"
                                        for item in value):
        return nodes.Call("cons", (example_expression(value[0]),
                                   example_expression(value[1:])))
    return nodes.Lit(value)


class TimedKitchenLibrary(KitchenLibrary):
    def run(self, name, args, fuel=None, trace=False, expression=None):
        if not all(depth_hosts.valid_input(arg) for arg in args):
            return kernel.Run(Bottom("invalid"), 0, 0, None)
        if expression is not None:
            if (expression != nodes.Call(name, tuple(example_expression(arg) for arg in args)) or
                    any(isinstance(item, nodes.Call) and item.fn in self.sealed_names()
                        for item in nodes.walk(expression)) or
                    any(isinstance(item, nodes.Lit) and not depth_hosts.valid_input(item.value)
                        for item in nodes.walk(expression))):
                return kernel.Run(Bottom("invalid"), 0, 0, None)
            return kernel.evaluate(expression, scope=self.scope(),
                                   limits=kernel.Limits(fuel=fuel), trace=trace,
                                   dialect=self.dialect)
        return super().run(name, args, fuel=fuel, trace=trace)

    def scope(self):
        scope = super().scope()
        if "PlanData.record" in scope.atoms:
            scope.atoms["PlanData.record"] = Atom("PlanData.record", 3, plan_record,
                                                   kind="object")
        if "Plan._stored" in scope.atoms:
            scope.atoms["Plan._stored"] = Atom(
                "Plan._stored", 1,
                plan_stored,
                kind="object")
        return scope


def plan_record(start, slots, end):
    if (not depth_hosts.valid_state(start) or not depth_hosts.valid_state(end) or
            not isinstance(slots, tuple) or len(slots) > 12 or
            any(not isinstance(slot, tuple) or any(type(recipe) is not str or
                                                    recipe not in depth_hosts.RECIPES
                                                    for recipe in slot) for slot in slots)):
        return Bottom("invalid")
    return Card("PlanData", "record", (start, slots, end))


def plan_stored(value):
    if (not isinstance(value, Card) or value.sort != "Plan" or value.tag != "val" or
            len(value.fields) != 1):
        return Bottom("invalid")
    record = value.fields[0]
    if (not isinstance(record, Card) or record.sort != "PlanData" or
            record.tag != "record" or len(record.fields) != 3 or
            isinstance(plan_record(*record.fields), Bottom)):
        return Bottom("invalid")
    return record


def decl():
    path = Path(__file__).resolve().parents[4] / "worlds/decl/v2/kitchen@1.json"
    return WorldDecl.from_dict(json.loads(path.read_text(encoding="utf-8")))


def atoms():
    world = decl()
    return ([Atom(op.name, len(op.inputs), getattr(depth_hosts, op.name), op.cost,
                  strict=op.strict)
             for op in world.operations] +
            [Atom(probe["name"], 1, getattr(depth_hosts, probe["name"]), 1,
                  "observation") for probe in world.observation["probes"]])


def new_library():
    world = decl()
    return TimedKitchenLibrary(world, atoms())
