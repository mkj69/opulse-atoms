"""Kernel unfold rule for the world-given short-circuit composition."""

from opulse.atoms import nodes
from opulse.atoms.spec import CombinatorSpec


def chain_spec():
    return CombinatorSpec(
        "chain", ("first", "second", "value"), ("first", "second"),
        nodes.Call("second", (nodes.Call("first", (nodes.Var("value"),)),)),
    )
