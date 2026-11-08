"""Finite, typed generator domains for the Harvard-style byte computer."""

from dataclasses import replace
from itertools import product

from opulse.atoms import nodes
from opulse.atoms.spec import CombinatorSpec
from opulse.atoms.values import Card
from opulse.gen_v2.worlds import _common
from opulse.gen_v2.worlds._common import build, world_tags
from opulse.worlds_v2.computer2 import hosts, world

_common.WORLD_TAGS.setdefault("computer", ("program", ("compute", "search", "equivalence", "counting")))
TAGS = world_tags("computer", world.decl())


def gen_world():
    declaration = world.decl()
    sequence = CombinatorSpec("@seq", ("f", "g", "s"), ("f", "g"),
                              nodes.Call("g", (nodes.Call("f", (nodes.Var("s"),)),)))
    declaration = replace(declaration, combinators={**declaration.combinators,
                          "library": [sequence.to_dict()]})
    registers = [Card("Reg", name) for name in hosts.REGISTERS]
    addresses = (16, 17, 31, 47, 64, 65, 80, 91, 120, 121, 130, 131)
    bytes_ = (0, 1, 2, 3, 7, 15, 31, 63, 127, 128, 254, 255)
    states = [hosts.state((first, second, third, fourth),
                         {addresses[index % len(addresses)]: (index * 7) % 256},
                         pc=addresses[index % len(addresses)], z=index % 2)
              for index, (first, second, third, fourth) in enumerate(
                  product((0, 1, 127, 255), (0, 2), (1, 128), (0, 3)))]
    memory = [state.fields[1] for state in states]
    vectors = [hosts.vec(start, length) for start, length in
               product((16, 64, 120), (1, 2, 3))]
    wides = [hosts.wide(first, second, third) for first, second, third in
             product((0, 1, 255), (0, 128), (1, 254))]
    return build("computer", declaration, world.atoms(),
                 {"int": tuple(range(-2, 14)), "bool": (False, True),
                  "Byte": bytes_, "Addr": addresses, "Reg": registers,
                  "Bit": (0, 1), "Machine": states, "Mem256": memory,
                  "any": (0, 1, 2, "A", registers[0], states[0].fields[0]),
                  "pair": [hosts.pair(first, second) for first, second in
                           product((0, 1, 16), (0, 1, 64))],
                  "vec_base": vectors, "wide_base": wides,
                  "List": ((), (0,), (1, 2), (16, 64))},
                 truth_states=states, probe_inputs={"?mem": ("Addr",)},
                 finite_sorts=("Reg", "Bit", "bool"), max_steps=800)
