"""Exact, bounded voxel tomography with adaptive shadow experiments.

The world is 8 x 8 x 6. All coordinates are (x,y,z), zero-based.
Top and side are the initially authorized probes; the other three probes
must be explicitly authorized by a question. The reference checker holds a
secret fixture; learner-facing questions reveal only authorized projections.
"""

from dataclasses import dataclass
from functools import lru_cache
from itertools import product
from pathlib import Path
import json

WIDTH, HEIGHT, DEPTH = 8, 8, 6
LIMIT = 200000


def cell(x, y, z):
    if not (0 <= x < WIDTH and 0 <= y < HEIGHT and 0 <= z < DEPTH):
        raise ValueError("Bottom(range)")
    return (x, y, z)


@dataclass(frozen=True)
class Volume:
    cells: frozenset

    def __post_init__(self):
        for x, y, z in self.cells:
            cell(x, y, z)


def put(volume, x, y, z):
    return Volume(volume.cells | {cell(x, y, z)})


def erase(volume, x, y, z):
    return Volume(volume.cells - {cell(x, y, z)})


def pipe(first, second, value):
    return second(first(value))


def top(volume):
    return frozenset((x, y) for x, y, z in volume.cells)


def side(volume):
    return frozenset((y, z) for x, y, z in volume.cells)


def front(volume):
    return frozenset((x, z) for x, y, z in volume.cells)


def diag(volume):
    return frozenset((x + z, y) for x, y, z in volume.cells)


def anti(volume):
    return frozenset((x - z + DEPTH - 1, y) for x, y, z in volume.cells)


PROBES = {"front": front, "diag": diag, "anti": anti}


def ink(volume):
    return len(top(volume))


@dataclass(frozen=True)
class Views:
    top_cells: frozenset
    side_cells: frozenset
    area: int

    def __post_init__(self):
        if self.area != len(self.top_cells):
            raise ValueError("Bottom(invalid_area)")
        if any(not (0 <= x < WIDTH and 0 <= y < HEIGHT) for x, y in self.top_cells):
            raise ValueError("Bottom(top_range)")
        if any(not (0 <= y < HEIGHT and 0 <= z < DEPTH) for y, z in self.side_cells):
            raise ValueError("Bottom(side_range)")


def capture(volume):
    return Views(top(volume), side(volume), ink(volume))


def matches(volume, views):
    return capture(volume) == views


@dataclass(frozen=True)
class Mask:
    cells: frozenset

    def __post_init__(self):
        if len(self.cells) > 32:
            raise ValueError("Bottom(mask_limit)")
        Volume(self.cells)


@dataclass(frozen=True)
class Candidates:
    mask: Mask
    views: Views
    volumes: tuple


def candidates(mask, views):
    """Factor the constraint by y; exactly enumerate each local edge cover.

    All rays of the two authorized probes have fixed y, so the Cartesian
    product of the local solutions is exactly the global solution set.
    """
    parts = []
    for y in range(HEIGHT):
        possible = sorted(voxel for voxel in mask.cells if voxel[1] == y)
        required_top = frozenset(x for x, row in views.top_cells if row == y)
        required_side = frozenset(z for row, z in views.side_cells if row == y)
        local = []
        if len(possible) > 16:
            raise ValueError("Bottom(local_mask_limit)")
        for bits in range(1 << len(possible)):
            chosen = frozenset(voxel for index, voxel in enumerate(possible) if bits & (1 << index))
            if {x for x, _, _ in chosen} == required_top and {z for _, _, z in chosen} == required_side:
                local.append(chosen)
        parts.append(local)
    result = []
    for sections in product(*parts):
        result.append(Volume(frozenset().union(*sections)))
        if len(result) > LIMIT:
            raise ValueError("Bottom(candidate_limit)")
    result.sort(key=lambda volume: tuple(sorted(volume.cells)))
    assert all(matches(volume, views) for volume in result)
    return Candidates(mask, views, tuple(result))


def retain(predicate, pool):
    return Candidates(pool.mask, pool.views, tuple(volume for volume in pool.volumes if predicate(volume)))


def forced(pool):
    if not pool.volumes:
        raise ValueError("Bottom(empty_candidates)")
    return frozenset.intersection(*(volume.cells for volume in pool.volumes))


@dataclass(frozen=True)
class Min:
    mass: int
    count: int


def least(pool):
    if not pool.volumes:
        raise ValueError("Bottom(empty_candidates)")
    lower_bound = len(forced(pool))
    mass = min(len(volume.cells) for volume in pool.volumes)
    assert mass >= lower_bound
    return Min(mass, sum(len(volume.cells) == mass for volume in pool.volumes))


def ambiguity(pool):
    return len(pool.volumes)


def invert(pool):
    if ambiguity(pool) != 1:
        raise ValueError("Bottom(nonunique)")
    volume = Volume(forced(pool))
    assert volume.cells <= pool.mask.cells and matches(volume, pool.views)
    return volume


def add_view(probe, pool, observed, authorized):
    if probe not in authorized or probe not in PROBES:
        raise ValueError("Bottom(permission)")
    return retain(lambda volume: PROBES[probe](volume) == observed, pool)


def partition(pool, probe):
    groups = {}
    for volume in pool.volumes:
        groups.setdefault(PROBES[probe](volume), []).append(volume)
    return tuple(Candidates(pool.mask, pool.views, tuple(group)) for group in groups.values())


@dataclass(frozen=True)
class Choice:
    probe: str
    worst: int
    groups: int


def best_probe(pool, authorized=("front", "diag", "anti")):
    if not pool.volumes or not authorized or any(probe not in PROBES for probe in authorized):
        raise ValueError("Bottom(probe_domain)")
    options = []
    for order, probe in enumerate(authorized):
        groups = partition(pool, probe)
        options.append((max(map(ambiguity, groups)), order, Choice(probe, max(map(ambiguity, groups)), len(groups))))
    return min(options, key=lambda option: option[:2])[2]


@dataclass(frozen=True)
class Plan:
    depth: int
    first: str
    worst_after_first: int


def plan(pool, authorized=("front", "diag", "anti")):
    """Exact worst-case adaptive decision tree, or depth=-1 if indistinguishable."""
    if not pool.volumes:
        raise ValueError("Bottom(empty_candidates)")
    if len(set(authorized)) != len(authorized) or any(probe not in PROBES for probe in authorized):
        raise ValueError("Bottom(probe_domain)")

    @lru_cache(None)
    def solve(volumes, remaining):
        if len(volumes) <= 1:
            return (0, "none", len(volumes))
        state = Candidates(pool.mask, pool.views, volumes)
        if not remaining:
            return (float("inf"), "none", len(volumes))
        greedy = best_probe(state, remaining).probe
        order = (greedy,) + tuple(probe for probe in remaining if probe != greedy)
        solutions = []
        for probe in order:
            groups = partition(state, probe)
            if len(groups) == 1:
                continue
            tail = tuple(name for name in remaining if name != probe)
            depth = 1 + max(solve(group.volumes, tail)[0] for group in groups)
            solutions.append((depth, remaining.index(probe), probe, max(map(ambiguity, groups))))
        if not solutions:
            return (float("inf"), "none", len(volumes))
        best = min(solutions)
        return (best[0], best[2], best[3])

    depth, first, worst = solve(pool.volumes, tuple(authorized))
    return Plan(-1 if depth == float("inf") else int(depth), first, worst)


def sample():
    mask = Mask(frozenset((x, y, z) for y in (0, 2, 4, 6) for x in (1, 2) for z in (1, 2)))
    secret = Volume(frozenset(((1, 0, 1), (2, 0, 2), (1, 2, 2), (2, 2, 1),
                               (1, 4, 1), (1, 4, 2), (2, 4, 2), (1, 6, 2), (2, 6, 1))))
    return mask, secret


def fixtures():
    mask, secret = sample()
    views = capture(secret)
    pool = candidates(mask, views)
    diag_pool = add_view("diag", pool, diag(secret), ("diag",))
    front_pool = add_view("front", pool, front(secret), ("front",))
    both = add_view("front", diag_pool, front(secret), ("front",))
    return [
        ink(secret), views, views, matches(secret, views),
        pool, retain(lambda volume: matches(volume, views), pool),
        forced(pool), least(pool), ambiguity(pool), ambiguity(diag_pool),
        best_probe(pool), plan(pool),
    ], [
        (ambiguity(pool), least(pool)),
        invert(add_view("anti", pool, anti(secret), ("anti",))),
        (best_probe(pool), plan(pool), ambiguity(front_pool), ambiguity(both), best_probe(pool).worst == 1),
    ]


def render(value):
    if isinstance(value, Views):
        return "Views<Top<" + ",".join(f"({x},{y})" for x, y in sorted(value.top_cells)) + ">,Side<" + ",".join(f"({y},{z})" for y, z in sorted(value.side_cells)) + f">,{value.area}>"
    if isinstance(value, Mask):
        return "Mask<" + ",".join(f"({x},{y},{z})" for x, y, z in sorted(value.cells)) + ">"
    if isinstance(value, Candidates):
        return f"Candidates<{len(value.volumes)}>"
    if isinstance(value, Volume):
        return "Volume<" + ",".join(f"({x},{y},{z})" for x, y, z in sorted(value.cells)) + ">"
    if isinstance(value, frozenset):
        return "Set<" + ",".join(f"({x},{y},{z})" for x, y, z in sorted(value)) + ">"
    if isinstance(value, Min):
        return f"Min<{value.mass},{value.count}>"
    if isinstance(value, Choice):
        return f"Choice<{value.probe},{value.worst},{value.groups}>"
    if isinstance(value, Plan):
        return f"Plan<{value.depth},{value.first},{value.worst_after_first}>"
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, tuple):
        return "Tuple<" + ",".join(map(render, value)) + ">"
    return str(value)


if __name__ == "__main__":
    mask, secret = sample()
    assert len(mask.cells) == 16 and len(secret.cells) == 9
    assert erase(put(Volume(frozenset()), 1, 0, 1), 1, 0, 1) == Volume(frozenset())
    assert pipe(lambda value: put(value, 1, 0, 1), lambda value: put(value, 2, 0, 2), Volume(frozenset())).cells == {(1, 0, 1), (2, 0, 2)}
    assert top(secret) and side(secret) and front(secret) and diag(secret) and anti(secret)
    assert all(matches(volume, capture(secret)) for volume in candidates(mask, capture(secret)).volumes)
    assert all(volume.cells <= mask.cells for volume in candidates(mask, capture(secret)).volumes)
    assert sample()[1] in candidates(mask, capture(secret)).volumes
    ordered = sorted(mask.cells)
    brute_force = {
        Volume(frozenset(voxel for index, voxel in enumerate(ordered) if bits & (1 << index)))
        for bits in range(1 << len(ordered))
    }
    assert {volume for volume in brute_force if matches(volume, capture(secret))} == set(candidates(mask, capture(secret)).volumes)
    recovered = add_view("anti", candidates(mask, capture(secret)), anti(secret), ("anti",))
    assert ambiguity(recovered) == 1 and invert(recovered) == secret
    try:
        add_view("front", candidates(mask, capture(secret)), front(secret), ("diag",))
    except ValueError as error:
        assert str(error) == "Bottom(permission)"
    else:
        raise AssertionError("probe permission was bypassed")
    document = json.loads(Path(__file__).with_suffix(".json").read_text(encoding="utf-8"))
    tower, showcase = fixtures()
    assert len(document["tower"]) == len(tower)
    assert len(document["showcase"]) == len(showcase)
    for layer, actual in zip(document["tower"], tower):
        assert layer["value"] == render(actual), (layer["layer"], layer["value"], render(actual))
    for task, actual in zip(document["showcase"], showcase):
        assert task["answer"] == render(actual), (task["angle"], task["answer"], render(actual))
    print("OK")
