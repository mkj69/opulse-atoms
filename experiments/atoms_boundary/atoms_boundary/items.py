"""Frozen inputs and boundary-independent kernel answers."""

import csv
import random
from itertools import product
from pathlib import Path

from opulse.atoms.values import Ok

ITEMS = Path(__file__).resolve().parents[1] / "items" / "frozen.csv"
SEED = 20261104


def generate_inputs():
    triples = list(product(range(4), repeat=3))
    random.Random(SEED).shuffle(triples)
    return triples[:48]


def frozen_inputs():
    with ITEMS.open(newline="", encoding="ascii") as source:
        rows = [tuple(int(value) for value in row) for row in csv.reader(source)]
    if rows != generate_inputs():
        raise ValueError("frozen inputs differ from preregistered generator")
    return rows


def items(library):
    result = []
    for index, args in enumerate(frozen_inputs()):
        run = library.run("score", args, trace=True)
        if not isinstance(run.outcome, Ok):
            raise TypeError(f"item {index} has no exact answer")
        def leaves(node):
            if node.given:
                yield node
            for child in node.children:
                yield from leaves(child)

        result.append({"id": index, "args": args, "value": run.outcome.value,
                       "adds": sum(node.name == "add" for node in leaves(run.trace)),
                       "steps": run.steps, "trace": run.trace})
    return result
