"""Finite task domains for the computer@2 library (spec sections 7 and 12)."""

from copy import copy

from opulse.atoms import nodes
from opulse.atoms.spec import (
    CombinatorSpec,
    Definition,
    Edge,
    ObjectSpec,
    ObservationSpec,
    OperationSpec,
)
from opulse.atoms.values import Card, boolean
from opulse.tasks_v2.hooks import from_library, show

from . import hosts
from .story import build_library, vector


def show_value(value):
    if isinstance(value, Card) and value.sort == "Machine":
        regs, memory, pc, flag = hosts.fields(hosts.from_card(value))
        cells = ",".join(f"{index}:{item}" for index, item in enumerate(memory) if item)
        return f"Machine<regs={regs},pc={pc},z={flag},mem={{{cells}}}>"
    return show(value)


def to_value(value):
    return boolean(value) if isinstance(value, bool) else hosts.to_card(value)


def from_value(value):
    if isinstance(value, Card) and value.sort == "bool":
        return value.tag == "true"
    return hosts.from_card(value)


def task_world():
    """Expose small varied byte states without exposing hidden state in grading."""
    library = copy(build_library())
    library._definitions = type(library._definitions)(library._definitions)
    for name, body in (("byte_identity", nodes.Var("value")),
                       ("byte_zero", nodes.Lit(0))):
        base = nodes.Var("x") if name == "byte_identity" else nodes.Lit(0)
        spec = ObjectSpec(name, "refine", base="int", valid=nodes.Lit(True), canon=base,
                          params=("value",))
        library._definitions[name] = Definition(name, "object", "invented", 1, (),
                                                 spec, body, status="callable")
    for name, body in (("byte_next", nodes.Call("inc", (nodes.Var("arg0"),))),
                       ("byte_next_twice", nodes.Call("inc", (
                           nodes.Call("inc", (nodes.Var("arg0"),)),)))):
        spec = OperationSpec(name, "transform", (Edge("int"),), Edge("int"),
                             "Advance a byte-machine scalar.")
        library._definitions[name] = Definition(name, "operation", "invented", 1, (),
                                                 spec, body, status="callable")
    for name, body in (("@byte_map", nodes.Call("f", (nodes.Var("x"),))),
                       ("@byte_map_twice", nodes.Call("f", (nodes.Call("inc", (nodes.Var("x"),)),)))):
        library._definitions[name] = Definition(name, "combinator", "invented", 1, (),
            CombinatorSpec(name, ("f", "x"), ("f",), body), body, status="callable")
    for name, body in (("?byte_out", nodes.Var("?out")),
                       ("?byte_out_next", nodes.Call("inc", (nodes.Var("?out"),)))):
        library._definitions[name] = Definition(name, "observation", "invented", 1, (),
            ObservationSpec(name, ("?out",), body), body, status="callable")
    library = _TaskLibrary(library)
    left = vector(16, 2)
    right = vector(64, 2)
    states = (hosts.state((0, 1, 127, 128), {
        **dict(enumerate((17, 29, 43, 61, 79, 101, 127, 149,
                          163, 181, 197, 211, 223, 229, 241, 253), 16)),
        **dict(enumerate((13, 23, 37, 41, 53, 67, 71, 83,
                          97, 103, 109, 113, 131, 137, 139, 151), 64))}),
              hosts.state((255, 2, 1, 0), {
                  **dict(enumerate((21, 33, 47, 58, 69, 72, 85, 96,
                                    107, 118, 129, 140), 80)),
                  **dict(enumerate((119, 108, 97, 86, 75, 64, 53, 42,
                                    31, 20, 9, 254), 120))}))
    return from_library(library, domains={
        "int": (0, 1, 127, 128, 255), "Byte": (0, 1, 127, 128, 255),
        "Addr": (16, 17, 64, 65), "Machine": states,
        "Vec": (left, right), "vec_base": (hosts.vec(16, 2), hosts.vec(64, 2)),
        "wide_base": (hosts.wide(0, 1, 255), hosts.wide(255, 128, 0)),
        "pair": (hosts.pair(states[0], Card("Wide", "val", (hosts.wide(0, 0, 0),))),),
    }, family={"body": ("mul_tick", "carry_tick"),
               "step": ("dot_step", "dot_step_again"),
               "f": ("inc", "is_vec_base")},
        states=states, show_value=show_value,
        to_value=to_value, from_value=from_value)


class _TaskLibrary:
    """Keep the complete executable scope while exposing task-compatible signatures."""

    TASK_NAMES = ("byte_identity", "byte_zero", "byte_next", "byte_next_twice",
                  "@byte_map", "@byte_map_twice", "?byte_out", "?byte_out_next")

    def __init__(self, library):
        self.library = library

    @property
    def definitions(self):
        return {name: self.library.get(name) for name in self.TASK_NAMES}

    def __getattr__(self, name):
        return getattr(self.library, name)
