"""Dice declaration and counted layer-zero atoms."""

import importlib
import json
from copy import copy
from pathlib import Path

from opulse.atoms import kernel, nodes
from opulse.atoms.library import Library, PipelineError
from opulse.atoms.spec import CombinatorSpec, Definition
from opulse.atoms.values import Bottom
from opulse.atoms.world import WorldDecl

DECL_PATH = Path(__file__).resolve().parents[4] / "worlds/decl/v2/dice@1.json"


def decl():
    return WorldDecl.from_dict(json.loads(DECL_PATH.read_text(encoding="utf-8")))


def atoms():
    from . import hosts

    world = decl()
    specs = [(op.name, len(op.inputs), op.impl, op.cost, "operation") for op in world.operations]
    specs = [(name, arity, impl, cost, "observation" if name == "mass" else kind)
             for name, arity, impl, cost, kind in specs]
    result = []
    for name, arity, impl, cost, kind in specs:
        module_name, function_name = impl["host"].split(":")
        host = getattr(importlib.import_module(module_name), function_name)

        def guarded(*args, host=host):
            return host(*args) if hosts.valid_world_value(args) else Bottom("invalid")

        result.append(kernel.Atom(name, arity, guarded, cost, kind))
    return result


class DiceLibrary(Library):
    def run(self, name, args, fuel=None, trace=False):
        from . import hosts

        if not hosts.valid_world_value(args):
            return kernel.Run(Bottom("invalid"), 0, 0, None)
        return super().run(name, args, fuel=fuel, trace=trace)

    def run_example(self, expression):
        from . import hosts

        if any(isinstance(item, nodes.Lit) and not hosts.valid_world_value(item.value)
               for item in nodes.walk(expression)):
            return kernel.Run(Bottom("invalid"), 0, 0, None)
        references = nodes.references(expression) | {
            item.value.name for item in nodes.walk(expression)
            if isinstance(item, nodes.Lit) and isinstance(item.value, kernel.FnRef)
        }
        if references & self.sealed_names():
            raise PipelineError("sealed object private name in example")
        learner = copy(self)
        learner._definitions = copy(self._definitions)
        learner._cache = {}
        name = "dice_example_expression"
        learner._definitions[name] = Definition(
            name, "combinator", "given", 0, (), CombinatorSpec(name, (), (), expression),
            expression, status="promoted",
        )
        result = learner.run(name, (), trace=True)
        trace = copy(result.trace)
        trace.children = result.trace.children[0].children
        return kernel.Run(result.outcome, result.steps, result.jumps, trace, result.work)

    def _params(self, defn):
        if defn.kind == "observation":
            return {"mean": ("dist",), "hit_prob": ("arg0", "arg1"), "hitting": ("arg0",)}.get(defn.name, ())
        return super()._params(defn)

    def scope(self):
        from .story import continuation_defns

        return super().scope().extend(continuation_defns())

def new_library():
    return DiceLibrary(decl(), atoms())
