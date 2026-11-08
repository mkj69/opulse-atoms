"""Finite, exact C/O/H valence-graph world; no chemical stability claims."""

from collections import Counter, defaultdict
from dataclasses import dataclass
from functools import lru_cache
from itertools import combinations, permutations
import json
from pathlib import Path


VALENCE = {"C": 4, "O": 2}
MAX_HEAVY = 8
MAX_ATOMS = 32


@dataclass(frozen=True)
class Graph:
    atoms: tuple[str, ...]
    edges: tuple[tuple[int, int], ...]
    hydrogen: tuple[int, ...]

    def __post_init__(self):
        if not 1 <= len(self.atoms) <= MAX_HEAVY or len(self.hydrogen) != len(self.atoms):
            raise ValueError("size")
        if len(self.atoms) + sum(self.hydrogen) > MAX_ATOMS:
            raise ValueError("size")
        if any(atom not in VALENCE for atom in self.atoms):
            raise ValueError("element")
        if any(type(count) is not int or count < 0 for count in self.hydrogen):
            raise ValueError("hydrogen")
        if any(not (0 <= left < right < len(self.atoms)) for left, right in self.edges):
            raise ValueError("edge")
        if len(set(self.edges)) != len(self.edges) or tuple(sorted(self.edges)) != self.edges:
            raise ValueError("edge")
        if any(self.hydrogen[index] + sum(index in edge for edge in self.edges) > VALENCE[atom]
               for index, atom in enumerate(self.atoms)):
            raise ValueError("valence")


def attach(graph: Graph, atom: str, old: int) -> Graph:
    if not 0 <= old < len(graph.atoms):
        raise ValueError("index")
    if atom == "H":
        hydrogen = list(graph.hydrogen)
        hydrogen[old] += 1
        return Graph(graph.atoms, graph.edges, tuple(hydrogen))
    if atom not in VALENCE:
        raise ValueError("element")
    edge = (old, len(graph.atoms))
    return Graph(graph.atoms + (atom,), tuple(sorted(graph.edges + (edge,))), graph.hydrogen + (0,))


def link(graph: Graph, left: int, right: int) -> Graph:
    if not 0 <= left < len(graph.atoms) or not 0 <= right < len(graph.atoms) or left == right:
        raise ValueError("index")
    edge = tuple(sorted((left, right)))
    return Graph(graph.atoms, tuple(sorted(graph.edges + (edge,))), graph.hydrogen)


def chain(functions, graph):
    for function in functions:
        graph = function(graph)
    return graph


def identity(graph: Graph) -> Graph:
    return graph


def atoms(graph: Graph):
    return tuple((atom, graph.hydrogen[index],
                  VALENCE[atom] - graph.hydrogen[index] - sum(index in edge for edge in graph.edges))
                 for index, atom in enumerate(graph.atoms)), graph.edges


def connected(graph: Graph) -> bool:
    visited = {0}
    frontier = [0]
    while frontier:
        current = frontier.pop()
        for left, right in graph.edges:
            neighbor = right if current == left else left if current == right else None
            if neighbor is not None and neighbor not in visited:
                visited.add(neighbor)
                frontier.append(neighbor)
    return len(visited) == len(graph.atoms)


def canonical(graph: Graph) -> str:
    if not connected(graph):
        raise ValueError("disconnected")
    groups = [[index for index, atom in enumerate(graph.atoms) if atom == element]
              for element in sorted(set(graph.atoms))]
    orderings = [permutations(group) for group in groups]
    from itertools import product
    best = None
    for parts in product(*orderings):
        order = sum((tuple(part) for part in parts), ())
        old_to_new = {old: new for new, old in enumerate(order)}
        candidate = (tuple(graph.atoms[index] for index in order),
                     tuple(graph.hydrogen[index] for index in order),
                     tuple(sorted(tuple(sorted((old_to_new[left], old_to_new[right])))
                                  for left, right in graph.edges)))
        if best is None or candidate < best:
            best = candidate
    labels, hydrogen, edges = best
    return ("".join(labels) + "/" + ",".join(map(str, hydrogen)) + "/" +
            ",".join(f"{left}-{right}" for left, right in edges))


@dataclass(frozen=True, eq=False)
class Molecule:
    graph: Graph

    def __post_init__(self):
        if not connected(self.graph):
            raise ValueError("disconnected")

    @property
    def code(self):
        return canonical(self.graph)

    def __eq__(self, other):
        return isinstance(other, Molecule) and self.code == other.code

    def __hash__(self):
        return hash(self.code)


def saturate(graph: Graph) -> Molecule:
    if not connected(graph):
        raise ValueError("disconnected")
    for index in range(len(graph.atoms)):
        for _ in range(atoms(graph)[0][index][2]):
            graph = attach(graph, "H", index)
    return Molecule(graph)


def formula(molecule: Molecule) -> str:
    count = Counter(molecule.graph.atoms)
    return f"C{count['C']}H{sum(molecule.graph.hydrogen)}O{count['O']}"


def finish(function, graph: Graph) -> Molecule:
    return saturate(function(graph))


def cycle_rank(molecule: Molecule) -> int:
    return len(molecule.graph.edges) - len(molecule.graph.atoms) + 1


@lru_cache(maxsize=None)
def candidates(carbon: int, oxygen: int, edges: int) -> tuple[Molecule, ...]:
    size = carbon + oxygen
    if not (0 <= carbon and 0 <= oxygen and 2 <= size <= 6 and size - 1 <= edges <= size):
        raise ValueError("enumeration bound")
    labels = ("C",) * carbon + ("O",) * oxygen
    unique = {}
    for selected in combinations(combinations(range(size), 2), edges):
        try:
            molecule = finish(identity, Graph(labels, selected, (0,) * size))
        except ValueError:
            continue
        unique[molecule.code] = molecule
    return tuple(unique[code] for code in sorted(unique))


def screen(probe, target, molecules):
    return tuple(molecule for molecule in molecules if probe(molecule) == target)


def oh_count(molecule: Molecule) -> int:
    graph = molecule.graph
    return sum(graph.hydrogen[index] > 0 and
               any(graph.atoms[other] == "C" for left, right in graph.edges
                   for other in ([right] if left == index else [left] if right == index else []))
               for index, atom in enumerate(graph.atoms) if atom == "O")


@dataclass(frozen=True, order=True)
class Profile:
    formula: str
    cycles: int
    oh: int
    carbon_branches: int


def profile(molecule: Molecule) -> Profile:
    graph = molecule.graph
    branches = sum(atom == "C" and sum(index in edge for edge in graph.edges) >= 3
                   for index, atom in enumerate(graph.atoms))
    return Profile(formula(molecule), cycle_rank(molecule), oh_count(molecule), branches)


def partition(probe, molecules):
    groups = defaultdict(list)
    for molecule in molecules:
        groups[probe(molecule)].append(molecule.code)
    return {key: tuple(sorted(values)) for key, values in sorted(groups.items())}


def ambiguity(groups):
    if not groups:
        raise ValueError("empty")
    maximum = max(len(values) for values in groups.values())
    key = min(key for key, values in groups.items() if len(values) == maximum)
    return {"profile": list(key.__dict__.values()), "count": maximum,
            "witness": list(groups[key][:2])}


def count(values):
    return len(values)


def group_sizes(groups):
    return [[display(key), len(members)] for key, members in groups.items()]


def display(value):
    if isinstance(value, Molecule):
        return value.code
    if isinstance(value, Profile):
        return list(value.__dict__.values())
    if isinstance(value, dict) and value and all(isinstance(key, Profile) for key in value):
        return [[display(key), len(members)] for key, members in value.items()]
    if isinstance(value, (tuple, list)) and value and all(isinstance(item, Molecule) for item in value):
        return [item.code for item in value]
    return value


def evaluate():
    base = Graph(("C",), (), (0,))
    ethanol = finish(identity, attach(attach(base, "C", 0), "O", 1))
    tree_isomers = candidates(5, 1, 5)
    alcohols = screen(oh_count, 1, tree_isomers)
    profiles = partition(profile, tree_isomers)
    return [Molecule(base), saturate(base), ethanol, formula(ethanol),
            cycle_rank(ethanol), count(tree_isomers), oh_count(ethanol), count(alcohols),
            Profile("C5H12O1", 0, 1, 1), profile(ethanol), group_sizes(profiles),
            ambiguity(profiles)]


def showcase():
    tree_isomers = candidates(5, 1, 5)
    groups = partition(profile, screen(formula, "C5H12O1", tree_isomers))
    inverse_profile = Profile("C5H12O1", 0, 1, 1)
    inverse = groups[inverse_profile][0]
    ring_isomers = candidates(4, 1, 5)
    ring_ethers = screen(oh_count, 0, ring_isomers)
    return [ambiguity(groups), {"code": inverse, "multiplicity": len(groups[inverse_profile])},
            {"exists": bool(ring_ethers), "count": len(ring_ethers),
             "witness": ring_ethers[0].code if ring_ethers else None}]


def tests():
    source = json.loads(Path(__file__).with_suffix(".json").read_text(encoding="utf-8"))
    assert source["id"] == "molecules" and len(source["tower"]) == 12
    assert {layer["kind"] for layer in source["tower"]} == {
        "object", "operation", "combinator", "observation"}
    assert [layer["layer"] for layer in source["tower"]] == list(range(1, 13))
    for layer, actual in zip(source["tower"], evaluate()):
        assert layer["value"] == display(actual), (layer["layer"], display(actual))
    for task, actual in zip(source["showcase"], showcase()):
        assert task["answer"] == actual, (task["angle"], actual)
    base = Graph(("C",), (), (0,))
    assert atoms(base) == ((('C', 0, 4),), ())
    assert chain([lambda graph: attach(graph, "O", 0),
                  lambda graph: attach(graph, "H", 1)], base).hydrogen == (0, 1)
    assert identity(base) == base and count((1, 2)) == 2
    assert Molecule(Graph(("O", "C"), ((0, 1),), (1, 3))) == Molecule(
        Graph(("C", "O"), ((0, 1),), (3, 1)))
    triangle = link(Graph(("C", "C", "C"), ((0, 1), (1, 2)), (0, 0, 0)), 0, 2)
    assert cycle_rank(saturate(triangle)) == 1
    for bad in [lambda: attach(Graph(("O",), (), (2,)), "H", 0),
                lambda: link(Graph(("C", "C"), ((0, 1),), (0, 0)), 1, 0),
                lambda: Molecule(Graph(("C", "C"), (), (0, 0)))]:
        try:
            bad()
        except ValueError:
            pass
        else:
            raise AssertionError("invalid graph accepted")
    assert all(formula(item) == "C5H12O1" for item in candidates(5, 1, 5))
    assert len({item.code for item in candidates(5, 1, 5)}) == len(candidates(5, 1, 5))
    assert count(candidates(5, 1, 5)) == 14
    assert count(screen(oh_count, 1, candidates(5, 1, 5))) == 8
    assert ambiguity(partition(profile, candidates(5, 1, 5)))["count"] == 6
    assert count(screen(oh_count, 0, candidates(4, 1, 5))) == 7
    assert all(formula(item) == "C4H8O1" and cycle_rank(item) == 1
               for item in candidates(4, 1, 5))


if __name__ == "__main__":
    tests()
    print("OK")
