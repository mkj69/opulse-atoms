"""Atoms-v2 flagship integer world, using the catalogue when installed."""

import json
from dataclasses import replace
from math import gcd
from pathlib import Path

from opulse.atoms.kernel import Atom
from opulse.atoms.spec import Edge, ObjectSpec, OperationSpec
from opulse.atoms.values import Card
from opulse.atoms.world import WorldDecl
from opulse.gen_v2.worlds._common import build, world_tags
from opulse.gen_v2.worlds.classic import gen_world as classic_world

CATALOGUE_SOURCE = "worlds/decl/v2/integer@2.json"
_CATALOGUE_PATH = Path(__file__).resolve().parents[4] / CATALOGUE_SOURCE
TAGS = (world_tags("integer", WorldDecl.from_dict(json.loads(_CATALOGUE_PATH.read_text(encoding="utf-8"))))
        if _CATALOGUE_PATH.exists() else world_tags("integer"))


def gen_world():
    if _CATALOGUE_PATH.exists():
        from opulse.worlds_v2.integer import world

        declaration = world.decl()
        atoms = world.atoms()
        fractions = [Card("frac", "ratio", (numerator, denominator))
                     for numerator in (0, 1, -1, 2, -2, 3, -3, 4, -4, 5, -5, 6, -6)
                     for denominator in (1, 2, 3, 4, 5, 6)
                     if gcd(numerator, denominator) == 1]
        values = {"int": (-3, -2, 0, 1, 3), "bool": (False, True),
                  "str": ("add", "succ", "pred"),
                  "nat": [Card("nat", "number", (number,)) for number in range(7)],
                  "list": [Card("list", "items", values) for values in
                           ((), (0,), (1,), (1, 2), (2, 3, 4))],
                  "pair": [Card("pair", "items", (first, second))
                           for first, second in ((0, 1), (1, 2), (2, 3))],
                  "frac": fractions,
                  "cf": [Card("cf", "digits", (Card("list", "items", (index,)),))
                         for index in range(4)]}
        result = build("integer", declaration, atoms, values,
                       bases={"int": ["is_zero"]}, truth_states=tuple(range(-12, 13)))
        result.sorts["frac"].values = tuple(fractions[:32])
        return result

    classic = classic_world("integer")
    helpers = (
        ("gen_dec", lambda value: value - 1, "Subtract one from a nonnegative integer.", "int"),
        ("gen_size", abs, "Absolute value of an integer.", "int"),
        ("gen_zero", lambda value: value == 0, "Decide whether an integer is zero.", "bool"),
    )
    operations = tuple(OperationSpec(name, "decide" if output == "bool" else "transform",
                                     (Edge("int"),), Edge(output), rule)
                       for name, _, rule, output in helpers)
    decl = replace(classic.decl, version=2, dialect="atoms-v2",
                   objects=(*classic.decl.objects, ObjectSpec("bool", "given")),
                   operations=(*classic.decl.operations, *operations),
                   combinators={**classic.decl.combinators,
                                "nodes": ["Var", "Lit", "Call", "Let", "Case", "Rec"],
                                "recursion": "measure"},
                   observation={**classic.decl.observation, "truth": None, "probes": []},
                   extra={**classic.decl.extra,
                          "open_kinds": ["object", "operation", "combinator", "observation"],
                          "generator_source": "published-integer-fallback"})
    atoms = [*classic.atoms, *(Atom(name, 1, fn) for name, fn, _, _ in helpers)]
    return build("integer", decl, atoms,
                 {"int": tuple(range(10)), "bool": (False, True)},
                 measures={"int": [("gen_dec", "gen_size")]},
                 bases={"int": ["gen_zero"]}, max_scope=120)
