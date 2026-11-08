"""Small reproducible task worlds (docs/spec/atoms-v2.md, sections 7 and 12)."""

import json
from dataclasses import replace

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.library import Library
from opulse.atoms.spec import (
    CombinatorSpec,
    Definition,
    Edge,
    ObjectSpec,
    ObservationSpec,
    OperationSpec,
)
from opulse.atoms.world import WorldDecl
from opulse.tasks_v2.hooks import from_library, show


def toy_world(open_kinds=None):
    operations = tuple(OperationSpec(name, "transform", (Edge("int"),), Edge("int"), name)
                       for name in ("inc", "dec"))
    decl = WorldDecl("generic_toy", 1, "atoms-v2", {}, {}, (ObjectSpec("int", "given"),),
                     operations, {"nodes": list(n.NODE_NAMES), "recursion": "fuel"},
                     {"truth": "int", "probes": [{"name": "probe", "sort": "int"}]}, {},
                     {"open_kinds": open_kinds or ["object", "operation", "combinator", "observation"]})
    atoms = (kernel.Atom("inc", 1, lambda value: value + 1),
             kernel.Atom("dec", 1, lambda value: value - 1),
             kernel.Atom("absolute", 1, abs),
             kernel.Atom("nonnegative", 1, lambda value: max(0, value)),
             kernel.Atom("probe", 1, lambda state: state % 2, kind="observation"))
    library = Library(decl, atoms)
    definitions = (
        Definition("normalized", "object", "invented", 1, ("absolute",),
                   ObjectSpec("normalized", "refine", base="int", valid=n.Lit(True),
                              canon=n.Call("absolute", (n.Var("x"),)), params=("value",)),
                   n.Call("absolute", (n.Var("value"),)), status="callable"),
        Definition("clamped", "object", "invented", 1, ("nonnegative",),
                   ObjectSpec("clamped", "refine", base="int", valid=n.Lit(True),
                              canon=n.Call("nonnegative", (n.Var("x"),)), params=("value",)),
                   n.Call("nonnegative", (n.Var("value"),)), status="callable"),
        Definition("unchanged", "object", "invented", 1, (),
                   ObjectSpec("unchanged", "refine", base="int", valid=n.Lit(True),
                              canon=n.Var("x"), params=("value",)), n.Var("value"), status="callable"),
        Definition("plus_one", "operation", "invented", 1, ("inc",),
                   OperationSpec("plus_one", "transform", (Edge("int"),), Edge("int"), "increment"),
                   n.Call("inc", (n.Var("arg0"),)), status="callable"),
        Definition("minus_one", "operation", "invented", 1, ("dec",),
                   OperationSpec("minus_one", "transform", (Edge("int"),), Edge("int"), "decrement"),
                   n.Call("dec", (n.Var("arg0"),)), status="callable"),
        Definition("absolute_value", "operation", "invented", 1, ("absolute",),
                   OperationSpec("absolute_value", "transform", (Edge("int"),), Edge("int"), "absolute"),
                   n.Call("absolute", (n.Var("arg0"),)), status="callable"),
        Definition("twice", "combinator", "invented", 1, (),
                   CombinatorSpec("twice", ("f", "x"), ("f",),
                                  n.Call("f", (n.Call("f", (n.Var("x"),)),))),
                   n.Call("f", (n.Call("f", (n.Var("x"),)),)), status="callable"),
        Definition("once", "combinator", "invented", 1, (),
                   CombinatorSpec("once", ("f", "x"), ("f",), n.Call("f", (n.Var("x"),))),
                   n.Call("f", (n.Var("x"),)), status="callable"),
        Definition("thrice", "combinator", "invented", 1, (),
                   CombinatorSpec("thrice", ("f", "x"), ("f",),
                                  n.Call("f", (n.Call("f", (n.Call("f", (n.Var("x"),)),)),))),
                   n.Call("f", (n.Call("f", (n.Call("f", (n.Var("x"),)),)),)), status="callable"),
        Definition("parity", "observation", "invented", 1, (),
                   ObservationSpec("parity", ("probe",), n.Var("probe")), n.Var("probe"),
                   status="callable"),
        Definition("next_parity", "observation", "invented", 1, ("inc",),
                   ObservationSpec("next_parity", ("probe",), n.Call("inc", (n.Var("probe"),))),
                   n.Call("inc", (n.Var("probe"),)), status="callable"),
        Definition("twice_next_probe", "observation", "invented", 1, ("inc",),
                   ObservationSpec("twice_next_probe", ("probe",),
                                   n.Call("inc", (n.Call("inc", (n.Var("probe"),)),))),
                   n.Call("inc", (n.Call("inc", (n.Var("probe"),)),)),
                   status="callable"),
    )
    for definition in definitions:
        library._definitions[definition.name] = definition
    return from_library(library, domains={"int": (-2, 0, 1, 3)}, family={"f": ("inc", "dec")},
                        states=(-2, 0, 1, 3), modalities={"image": lambda state: f"image:{state}"})

def sensor_counter_world():
    base = toy_world().library()
    declaration = replace(base.world, world="sensor_counter", version=2,
                          observation={"truth": "counter_state",
                                       "probes": [{"name": "probe", "sort": "int"}]})
    atoms = tuple(atom for atom in base.atoms if atom.name != "probe") + (
        kernel.Atom("probe", 1, lambda state: state[0] % 2, kind="observation"),)
    library = Library(declaration, atoms)
    library._definitions.update(base.definitions)
    thrice = library.get("thrice")
    library._definitions["thrice_alternative"] = replace(
        thrice, name="thrice_alternative", body=n.Let("held", thrice.body, n.Var("held")))
    states = ((-3, "quiet"), (-1, "busy"), (0, "quiet"), (2, "busy"), (4, "quiet"))
    return from_library(library, domains={"int": (-3, -1, 0, 2, 4)},
                        family={"f": ("inc", "dec")}, states=states,
                        show_value=lambda value: f"Sensor<{value[0]}, {value[1]}>"
                        if isinstance(value, tuple) and len(value) == 2 else show(value))
def computer_world():
    from opulse.worlds_v2.computer import machine, runner
    from opulse.worlds_v2.computer.verify import ARTIFACT, DECLARATION, mul_program

    declaration = WorldDecl.from_dict(json.loads(DECLARATION.read_text()))
    library = Library(declaration, [kernel.Atom(name, arity, function, cost)
                                    for name, (arity, function, cost) in runner.atoms().items()])
    artifact = json.loads(ARTIFACT.read_text())
    program = mul_program()
    program = replace(program, blocks=tuple((label, replace(block, end=replace(
        block.end, cond=block.end.cond if isinstance(block.end.cond, n.Test) else n.Test(block.end.cond)))
        if isinstance(block.end, n.CondJump) else block)
        for label, block in program.blocks))
    program = replace(program, blocks=tuple(("test_block" if label == "test" else label,
        replace(block, end=replace(block.end, **{
            key: "test_block" if getattr(block.end, key) == "test" else getattr(block.end, key)
            for key in ("target", "then", "else_") if hasattr(block.end, key)})))
        for label, block in program.blocks))
    specification = replace(OperationSpec.from_dict(artifact["spec"]), name="mul")
    specification = replace(specification, extra={**specification.extra, "input_names": ("s",)})
    library._definitions["mul"] = Definition("mul", "operation", "invented", 1,
        tuple(artifact["depends_on"]), specification, program, status="callable")
    states = (machine.State((0, 3, 0, 0)), machine.State((0, 7, 2, 0)),
              machine.State((0, 255, 1, 0)))
    return from_library(library, domains={"machine_state": states},
                        to_value=lambda state: machine.to_card(state) if isinstance(state, machine.State) else state,
                        from_value=lambda value: machine.from_card(value)
                        if getattr(value, "sort", None) == "machine_state" else value)
