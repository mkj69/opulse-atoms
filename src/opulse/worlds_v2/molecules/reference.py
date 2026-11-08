"""Independent depth-design oracle, used only when checking bounded evidence."""

import importlib.util
from functools import lru_cache
from itertools import permutations
from pathlib import Path

from opulse.atoms.values import Bottom, Card, boolean

from . import hosts


@lru_cache(maxsize=1)
def design():
    path = Path(__file__).resolve().parents[4] / "worlds/catalogue/depth/molecules.py"
    spec = importlib.util.spec_from_file_location("molecules_depth_oracle", path)
    module = importlib.util.module_from_spec(spec)
    import sys

    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def to_design(value):
    oracle = design()
    if isinstance(value, Card) and value.sort == "Graph":
        return oracle.Graph(*hosts.from_card(value))
    if isinstance(value, Card) and value.sort == "Molecule":
        return oracle.Molecule(to_design(value.fields[0]))
    return value


def canonical_card(code):
    labels, hydrogens, edges = code.split("/")
    return hosts.to_card(labels, (tuple(int(item) for item in pair.split("-"))
                                  for pair in edges.split(",") if pair),
                         (int(item) for item in hydrogens.split(",")))


def operation(name):
    oracle = design()

    def compare(*args):
        try:
            if name == "connected":
                return boolean(oracle.connected(to_design(args[0])))
            if name == "normalize":
                labels, edges, hydrogens = hosts.from_card(args[0])
                candidates = []
                for order in permutations(range(len(labels))):
                    inverse = {old: new for new, old in enumerate(order)}
                    renamed = hosts.to_card((labels[old] for old in order),
                                            sorted(tuple(sorted((inverse[left], inverse[right])))
                                                   for left, right in edges),
                                            (hydrogens[old] for old in order))
                    candidates.append(renamed)
                return min(candidates, key=lambda graph: (
                    hosts.from_card(graph)[0], hosts.from_card(graph)[2], hosts.from_card(graph)[1]))
            if name == "relabel":
                labels, edges, hydrogens = hosts.from_card(args[0])
                ordering = args[1].fields
                inverse = {old: new for new, old in enumerate(ordering)}
                return hosts.to_card((labels[old] for old in ordering),
                                     sorted(tuple(sorted((inverse[left], inverse[right])))
                                            for left, right in edges),
                                     (hydrogens[old] for old in ordering))
            if name == "saturate":
                return Card("Molecule", "val", (canonical_card(oracle.saturate(to_design(args[0])).code),))
            if name == "all_pairs":
                size = args[0]
                if size > 8:
                    return Bottom("size")
                return hosts.list_make(*(hosts.pair_make(left, right)
                                         for left in range(size) for right in range(left + 1, size)))
            if name == "candidates":
                return hosts.list_make(*(Card("Molecule", "val", (canonical_card(molecule.code),))
                                         for molecule in oracle.candidates(*args)))
            if name == "carbon_branches":
                return oracle.profile(to_design(args[0])).carbon_branches
            if name == "profile":
                result = oracle.profile(to_design(args[0]))
                return Card("Profile", "profile", (result.formula, result.cycles,
                                                   result.oh, result.carbon_branches))
        except ValueError:
            return Bottom("enumeration_bound" if name == "candidates" else "invalid")
        raise ValueError(name)

    return compare


def observe(name):
    oracle = design()

    def compare(value):
        if name in ("formula", "cycle_rank", "oh_count"):
            return getattr(oracle, name)(to_design(value))
        if name == "ambiguity":
            groups = {oracle.Profile(*pair.fields[0].fields): tuple(pair.fields[1].fields)
                      for pair in value.fields}
            result = oracle.ambiguity(groups)
            return Card("Record", "ambiguity", (
                Card("Profile", "profile", tuple(result["profile"])), result["count"],
                hosts.list_make(*result["witness"])))
        raise ValueError(name)

    return compare


def combine(name):
    oracle = design()

    def compare(operations, inputs):
        probe = operations.get("probe", operations.get("f"))
        if name == "finish":
            try:
                graph = to_design(inputs[0])
                return Card("Molecule", "val", (canonical_card(oracle.saturate(graph).code),))
            except ValueError:
                return Bottom("invalid")
        if probe not in {"formula", "oh_count", "cycle_rank", "profile"}:
            raise ValueError(probe)
        fn = getattr(oracle, probe)
        if name == "screen":
            target, molecules = inputs
            return hosts.list_make(*(item for item in molecules.fields
                                     if fn(to_design(item)) == target))
        if name == "partition":
            (molecules,) = inputs
            groups = oracle.partition(fn, tuple(to_design(item) for item in molecules.fields))
            return hosts.list_make(*(hosts.pair_make(
                Card("Profile", "profile", (key.formula, key.cycles, key.oh, key.carbon_branches))
                if isinstance(key, oracle.Profile) else key, hosts.list_make(*codes))
                for key, codes in groups.items()))
        raise ValueError(name)

    return compare
