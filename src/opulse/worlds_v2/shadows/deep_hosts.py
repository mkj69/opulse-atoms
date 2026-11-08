"""Given voxel actions, probes, generic primitives and declared finite-search accelerators."""

from contextvars import ContextVar
from functools import lru_cache

from opulse.atoms.values import Bottom, Card, boolean

WIDTH, HEIGHT, DEPTH = 8, 8, 6
validated_run = ContextVar("shadows_validated_run", default=False)


def cell(x, y, z):
    if any(type(value) is not int for value in (x, y, z)) or not (0 <= x < WIDTH and 0 <= y < HEIGHT and 0 <= z < DEPTH):
        return Bottom("range")
    return Card("Cell", "cell", (x, y, z))


def pair(first, second):
    return Card("Pair", "pair", (first, second))


def _cells(value):
    if not isinstance(value, Card) or value.sort not in ("Volume", "Mask"):
        return None
    if value.sort == "Volume" and value.tag == "bits" and len(value.fields) == 1:
        bits = value.fields[0]
        if type(bits) is not int or not 0 <= bits < 1 << (WIDTH * HEIGHT * DEPTH):
            return None
        result = []
        while bits:
            index = (bits & -bits).bit_length() - 1
            result.append(cell(index // 48, (index // 6) % 8, index % 6))
            bits &= bits - 1
        return tuple(result)
    if value.tag != "cells":
        return None
    if any(not isinstance(item, Card) or item.sort != "Cell" or item.tag != "cell" or
           len(item.fields) != 3 or isinstance(cell(*item.fields), Bottom) for item in value.fields):
        return None
    return tuple(sorted(set(value.fields), key=lambda item: item.fields))


def volume(*cells):
    result = Card("Volume", "cells", tuple(cells))
    normalized = _cells(result)
    if normalized is None:
        return Bottom("range")
    bits = sum(1 << (item.fields[0] * 48 + item.fields[1] * 6 + item.fields[2]) for item in normalized)
    return Card("Volume", "bits", (bits,))


def to_card(cells):
    if not isinstance(cells, (tuple, frozenset)):
        return Bottom("invalid")
    encoded = tuple(cell(*position) if isinstance(position, tuple) else position for position in cells)
    return volume(*encoded)


def from_card(value):
    decoded = _cells(value)
    return (tuple(item.fields for item in decoded) if decoded is not None and
            isinstance(value, Card) and value.sort == "Volume" else Bottom("invalid"))


def mask(*cells):
    result = Card("Mask", "cells", tuple(cells))
    normalized = _cells(result)
    if normalized is None:
        return Bottom("range")
    if len(normalized) > 32:
        return Bottom("mask_limit")
    if any(sum(item.fields[1] == row for item in normalized) > 16 for row in range(HEIGHT)):
        return Bottom("local_mask_limit")
    return Card("Mask", "cells", normalized)


def put(value, x, y, z):
    if _cells(value) is None or value.sort != "Volume":
        return Bottom("invalid")
    item = cell(x, y, z)
    return item if isinstance(item, Bottom) else volume(*_cells(value), item)


def erase(value, x, y, z):
    if _cells(value) is None or value.sort != "Volume":
        return Bottom("invalid")
    item = cell(x, y, z)
    return item if isinstance(item, Bottom) else volume(*(part for part in _cells(value) if part != item))


@lru_cache(maxsize=10000)
def projection(value, name):
    cells = _cells(value)
    if cells is None or value.sort != "Volume":
        return Bottom("invalid")
    def project(item):
        x, y, z = item.fields
        return {"top": (x, y), "side": (y, z), "front": (x, z),
                "diag": (x + z, y), "anti": (x - z + DEPTH - 1, y)}[name]
    return Card("Set", "items", tuple(pair(*position) for position in sorted({project(item) for item in cells})))


def top(value):
    return projection(value, "top")


def side(value):
    return projection(value, "side")


def front(value):
    return projection(value, "front")


def diag(value):
    return projection(value, "diag")


def anti(value):
    return projection(value, "anti")


def size(value):
    if not safe_value(value):
        return Bottom("invalid")
    return len(value.fields) if isinstance(value, Card) and value.tag in ("items", "cells") else Bottom("invalid")


def same(left, right):
    if not safe_value(left) or not safe_value(right):
        return Bottom("invalid")
    return boolean(left == right)


def add(left, right):
    return left + right if type(left) is type(right) is int else Bottom("invalid")


def less(left, right):
    return boolean(left < right) if type(left) is type(right) is int else Bottom("invalid")


def items(value):
    if not safe_value(value):
        return Bottom("invalid")
    return value.fields if isinstance(value, Card) and value.tag in ("cells", "items") else Bottom("invalid")


def list_items(*values):
    return Card("List", "items", tuple(values))


def first(value):
    if not safe_value(value):
        return Bottom("invalid")
    return value.fields[0] if isinstance(value, Card) and value.tag == "items" and value.fields else Bottom("empty")


def rest(value):
    if not safe_value(value):
        return Bottom("invalid")
    return Card(value.sort, "items", value.fields[1:]) if isinstance(value, Card) and value.tag == "items" and value.fields else Bottom("empty")


def cons(value, values):
    if not safe_value(value) or not safe_value(values):
        return Bottom("invalid")
    return Card(values.sort, "items", (value, *values.fields)) if isinstance(values, Card) and values.tag == "items" else Bottom("invalid")


def empty(values):
    if not safe_value(values):
        return Bottom("invalid")
    return boolean(not values.fields) if isinstance(values, Card) and values.tag == "items" else Bottom("invalid")


def mask_cells(value):
    return Card("List", "items", value.fields) if _cells(value) is not None and value.sort == "Mask" else Bottom("invalid")


def volume_cells(value):
    return Card("List", "items", _cells(value)) if _cells(value) is not None and value.sort == "Volume" else Bottom("invalid")


def views_record(top_cells, side_cells, area):
    if not all(isinstance(value, Card) and value.sort == "Set" for value in (top_cells, side_cells)):
        return Bottom("invalid")
    return Card("ViewsRaw", "record", (top_cells, side_cells, area))


def views_top(value):
    return value.fields[0] if isinstance(value, Card) and value.sort == "ViewsRaw" else Bottom("invalid")


def views_side(value):
    return value.fields[1] if isinstance(value, Card) and value.sort == "ViewsRaw" else Bottom("invalid")


def views_area(value):
    return value.fields[2] if isinstance(value, Card) and value.sort == "ViewsRaw" else Bottom("invalid")


def valid_views_raw(value):
    if not isinstance(value, Card) or value.sort != "ViewsRaw" or value.tag != "record" or len(value.fields) != 3:
        return boolean(False)
    top_cells, side_cells, area = value.fields
    if any(not isinstance(shadow, Card) or shadow.sort != "Set" or shadow.tag != "items"
           for shadow in (top_cells, side_cells)) or type(area) is not int:
        return boolean(False)
    def valid_pairs(shadow, x_limit, y_limit):
        return all(isinstance(item, Card) and item.sort == "Pair" and item.tag == "pair" and
                   len(item.fields) == 2 and type(item.fields[0]) is type(item.fields[1]) is int and
                   0 <= item.fields[0] < x_limit and 0 <= item.fields[1] < y_limit for item in shadow.fields)
    return boolean(valid_pairs(top_cells, WIDTH, HEIGHT) and valid_pairs(side_cells, HEIGHT, DEPTH))


def _valid_views(value):
    if not isinstance(value, Card) or value.sort != "Views" or value.tag != "val" or len(value.fields) != 1:
        return False
    raw = value.fields[0]
    if valid_views_raw(raw) != boolean(True):
        return False
    top_cells, side_cells, area = raw.fields
    return (top_cells.fields == tuple(sorted(set(top_cells.fields), key=lambda item: item.fields)) and
            side_cells.fields == tuple(sorted(set(side_cells.fields), key=lambda item: item.fields)) and
            area == len(top_cells.fields))


@lru_cache(maxsize=512)
def _valid_candidates(value):
    if not isinstance(value, Card) or value.sort != "Candidates" or value.tag != "val" or len(value.fields) != 1:
        return False
    raw = value.fields[0]
    if not isinstance(raw, Card) or raw.sort != "CandidatesRaw" or raw.tag != "pool" or len(raw.fields) != 3:
        return False
    public_mask, views, volumes = raw.fields
    mask_items = _cells(public_mask)
    if (mask_items is None or public_mask.sort != "Mask" or public_mask.tag != "cells" or
            public_mask.fields != mask_items or len(mask_items) > 32 or
            any(sum(item.fields[1] == row for item in mask_items) > 16 for row in range(HEIGHT)) or
            not _valid_views(views) or not isinstance(volumes, Card) or
            volumes.sort != "List" or volumes.tag != "items"):
        return False
    previous = None
    allowed = set(mask_items)
    top_cells, side_cells, _ = views.fields[0].fields
    for item in volumes.fields:
        cells = _cells(item)
        if cells is None or item.sort != "Volume" or not set(cells) <= allowed:
            return False
        positions = tuple(cell_value.fields for cell_value in cells)
        if previous is not None and positions <= previous:
            return False
        if projection(item, "top") != top_cells or projection(item, "side") != side_cells:
            return False
        previous = positions
    return True


def valid_invented(value):
    if not isinstance(value, Card):
        return False
    if validated_run.get():
        return (value.sort == "Views" and value.tag == "val" and len(value.fields) == 1 or
                value.sort == "Candidates" and value.tag == "val" and len(value.fields) == 1)
    try:
        return _valid_views(value) if value.sort == "Views" else _valid_candidates(value)
    except (TypeError, ValueError, RecursionError):
        return False


@lru_cache(maxsize=4096)
def _safe_value(value):
    if isinstance(value, Card):
        if value.sort in ("Views", "Candidates"):
            return valid_invented(value)
        return all(safe_value(field) for field in value.fields)
    if isinstance(value, (tuple, list)):
        return all(safe_value(item) for item in value)
    return True


def safe_value(value):
    if validated_run.get():
        return True
    try:
        return _safe_value(value)
    except (TypeError, ValueError, RecursionError):
        return False


def normalize_views(value):
    if valid_views_raw(value) != boolean(True):
        return Bottom("invalid")
    top_cells, side_cells, area = value.fields
    def normalize(shadow):
        return Card("Set", "items", tuple(sorted(set(shadow.fields), key=lambda item: item.fields)))
    return Card("ViewsRaw", "record", (normalize(top_cells), normalize(side_cells), area))


def unwrap_views(value):
    return value.fields[0] if valid_invented(value) and value.sort == "Views" else Bottom("invalid")


@lru_cache(maxsize=256)
def enumerate_raw(public_mask, views):
    raw = unwrap_views(views)
    if _cells(public_mask) is None or public_mask.sort != "Mask" or isinstance(raw, Bottom):
        return Bottom("invalid")
    from itertools import product

    sections = []
    for row in range(HEIGHT):
        possible = tuple(item for item in public_mask.fields if item.fields[1] == row)
        if len(possible) > 16:
            return Bottom("local_mask_limit")
        required_top = {item.fields[0] for item in raw.fields[0].fields if item.fields[1] == row}
        required_side = {item.fields[1] for item in raw.fields[1].fields if item.fields[0] == row}
        local = []
        for bits in range(1 << len(possible)):
            chosen = tuple(item for index, item in enumerate(possible) if bits & (1 << index))
            if {item.fields[0] for item in chosen} == required_top and {item.fields[2] for item in chosen} == required_side:
                local.append(chosen)
        sections.append(local)
    from math import prod
    if prod(map(len, sections)) > 200000:
        return Bottom("candidate_limit")
    volumes = []
    for parts in product(*sections):
        volumes.append(volume(*(item for part in parts for item in part)))
        if len(volumes) > 200000:
            return Bottom("candidate_limit")
    volumes.sort(key=lambda item: tuple(part.fields for part in _cells(item)))
    return Card("CandidatesRaw", "pool", (public_mask, views, Card("List", "items", tuple(volumes))))


def slice_extend(public_mask, views, partials, row):
    raw = unwrap_views(views)
    if (_cells(public_mask) is None or public_mask.sort != "Mask" or isinstance(raw, Bottom) or
            not isinstance(partials, Card) or partials.sort != "List" or partials.tag != "items" or
            type(row) is not int or not 0 <= row < HEIGHT):
        return Bottom("invalid")
    possible = tuple(item for item in public_mask.fields if item.fields[1] == row)
    required_top = {item.fields[0] for item in raw.fields[0].fields if item.fields[1] == row}
    required_side = {item.fields[1] for item in raw.fields[1].fields if item.fields[0] == row}
    local = []
    for bits in range(1 << len(possible)):
        chosen = tuple(item for index, item in enumerate(possible) if bits & (1 << index))
        if {item.fields[0] for item in chosen} == required_top and {item.fields[2] for item in chosen} == required_side:
            local.append(chosen)
    if len(partials.fields) * len(local) > 200000:
        return Bottom("candidate_limit")
    return list_items(*(volume(*_cells(partial), *section) for partial in partials.fields for section in local))


def pack_enumerated(public_mask, views, partials):
    if not isinstance(partials, Card) or partials.sort != "List" or partials.tag != "items":
        return Bottom("invalid")
    ordered = tuple(sorted(partials.fields, key=lambda item: tuple(part.fields for part in _cells(item))))
    return Card("CandidatesRaw", "pool", (public_mask, views, list_items(*ordered)))


def pool_raw(value):
    return value.fields[0] if valid_invented(value) and value.sort == "Candidates" else Bottom("invalid")


def pool_volumes(value):
    return value.fields[2] if isinstance(value, Card) and value.sort == "CandidatesRaw" and value.tag == "pool" else Bottom("invalid")


def pool_mask(value):
    return value.fields[0] if isinstance(value, Card) and value.sort == "CandidatesRaw" and value.tag == "pool" else Bottom("invalid")


def pool_views(value):
    return value.fields[1] if isinstance(value, Card) and value.sort == "CandidatesRaw" and value.tag == "pool" else Bottom("invalid")


@lru_cache(maxsize=256)
def valid_pool(value):
    if not isinstance(value, Card) or value.sort != "CandidatesRaw" or value.tag != "pool" or len(value.fields) != 3:
        return boolean(False)
    public_mask, views, volumes = value.fields
    raw_views = unwrap_views(views)
    if (_cells(public_mask) is None or public_mask.sort != "Mask" or isinstance(raw_views, Bottom) or
            not isinstance(volumes, Card) or volumes.sort != "List" or volumes.tag != "items"):
        return boolean(False)
    return boolean(True)


def ordered_volumes(volumes):
    if not isinstance(volumes, Card) or volumes.sort != "List" or volumes.tag != "items":
        return boolean(False)
    if any(_cells(item) is None or item.sort != "Volume" for item in volumes.fields):
        return boolean(False)
    ordered = tuple(sorted(set(volumes.fields), key=lambda item: tuple(part.fields for part in _cells(item))))
    return boolean(volumes.fields == ordered)


def within_mask(volume_value, mask_value):
    volume_cells = _cells(volume_value)
    mask_cells = _cells(mask_value)
    return boolean(volume_cells is not None and mask_cells is not None and
                   volume_value.sort == "Volume" and mask_value.sort == "Mask" and
                   set(volume_cells) <= set(mask_cells))


def retain_raw(value, probe_name, observed):
    raw = pool_raw(value)
    if isinstance(raw, Bottom) or probe_name not in ("top", "side", "front", "diag", "anti"):
        return Bottom("permission")
    remaining = tuple(item for item in pool_volumes(raw).fields if projection(item, probe_name) == observed)
    return Card("CandidatesRaw", "pool", (pool_mask(raw), pool_views(raw), list_items(*remaining)))


def forced_cells(value):
    raw = pool_raw(value)
    if isinstance(raw, Bottom):
        return raw
    volumes = pool_volumes(raw).fields
    if not volumes:
        return Bottom("empty_candidates")
    common = set(_cells(volumes[0]))
    for item in volumes[1:]:
        common.intersection_update(_cells(item))
    return Card("Set", "items", tuple(sorted(common, key=lambda item: item.fields)))


def minimum_raw(value, lower_bound):
    raw = pool_raw(value)
    if isinstance(raw, Bottom) or isinstance(lower_bound, Bottom):
        return Bottom("invalid")
    masses = [len(_cells(item)) for item in pool_volumes(raw).fields]
    if not masses:
        return Bottom("empty_candidates")
    minimum = min(masses)
    return Card("Min", "min", (minimum, masses.count(minimum))) if minimum >= len(lower_bound.fields) else Bottom("invalid")


@lru_cache(maxsize=256)
def best_raw(value, available):
    raw = pool_raw(value)
    if isinstance(raw, Bottom) or not isinstance(available, Card) or not available.fields:
        return Bottom("probe_domain")
    names = available.fields
    if len(set(names)) != len(names) or any(name not in ("front", "diag", "anti") for name in names):
        return Bottom("probe_domain")
    volumes = pool_volumes(raw).fields
    if not volumes:
        return Bottom("probe_domain")
    from collections import Counter
    options = []
    for order, name in enumerate(names):
        groups = Counter(projection(item, name) for item in volumes)
        options.append((max(groups.values()), order, name, len(groups)))
    worst, _, name, count = min(options)
    return Card("Choice", "choice", (name, worst, count))


def probe_score(value, name):
    raw = value if isinstance(value, Card) and value.sort == "CandidatesRaw" else pool_raw(value)
    if isinstance(raw, Bottom) or name not in ("front", "diag", "anti"):
        return Bottom("probe_domain")
    volumes = pool_volumes(raw).fields
    if not volumes:
        return Bottom("probe_domain")
    from collections import Counter

    groups = Counter(projection(item, name) for item in volumes)
    return Card("Choice", "choice", (name, max(groups.values()), len(groups)))


def choice_worst(value):
    return value.fields[1] if isinstance(value, Card) and value.sort == "Choice" and value.tag == "choice" else Bottom("invalid")


@lru_cache(maxsize=256)
def plan_raw(value, available):
    raw = pool_raw(value)
    if isinstance(raw, Bottom) or not isinstance(available, Card):
        return Bottom("probe_domain")
    names = tuple(getattr(item, "name", item) for item in available.fields)
    if len(set(names)) != len(names) or any(name not in ("front", "diag", "anti") for name in names):
        return Bottom("probe_domain")
    volumes = pool_volumes(raw).fields
    if not volumes:
        return Bottom("empty_candidates")
    from functools import lru_cache

    @lru_cache(None)
    def solve(indices, remaining):
        if len(indices) <= 1:
            return 0, "none", len(indices)
        if not remaining:
            return float("inf"), "none", len(indices)
        answers = []
        for order, name in enumerate(remaining):
            groups = {}
            for index in indices:
                groups.setdefault(projection(volumes[index], name), []).append(index)
            if len(groups) == 1:
                continue
            tail = tuple(item for item in remaining if item != name)
            depth = 1 + max(solve(tuple(group), tail)[0] for group in groups.values())
            answers.append((depth, order, name, max(map(len, groups.values()))))
        if not answers:
            return float("inf"), "none", len(indices)
        best = min(answers)
        return best[0], best[2], best[3]

    depth, first_probe, worst = solve(tuple(range(len(volumes))), tuple(names))
    return Card("Plan", "plan", (-1 if depth == float("inf") else depth, first_probe, worst))


def probe_groups(value, name):
    raw = value if isinstance(value, Card) and value.sort == "CandidatesRaw" else pool_raw(value)
    if isinstance(raw, Bottom) or name not in ("front", "diag", "anti"):
        return Bottom("probe_domain")
    groups = {}
    for item in pool_volumes(raw).fields:
        groups.setdefault(projection(item, name), []).append(item)
    return list_items(*(pack_raw(pool_mask(raw), pool_views(raw), list_items(*items))
                        for items in groups.values()))


def without_probe(available, name):
    return list_items(*(item for item in available.fields if item != name))


def first_probe(available):
    return available.fields[0] if available.fields else Bottom("probe_domain")


def plan_depth(value):
    return value.fields[0] if isinstance(value, Card) and value.sort == "Plan" and value.tag == "plan" else Bottom("invalid")


def make_plan(depth, name, worst):
    return Card("Plan", "plan", (depth, name, worst))


def choose_plan(previous, candidate):
    if previous.fields[0] < 0 or (candidate.fields[0] >= 0 and candidate.fields[0] < previous.fields[0]):
        return candidate
    return previous


def pack_raw(public_mask, views, volumes):
    if _cells(public_mask) is None or not isinstance(views, Card) or not isinstance(volumes, Card):
        return Bottom("invalid")
    return Card("CandidatesRaw", "pool", (public_mask, views, volumes))


def snoc(values, value):
    return Card("List", "items", (*values.fields, value)) if isinstance(values, Card) and values.tag == "items" else Bottom("invalid")
