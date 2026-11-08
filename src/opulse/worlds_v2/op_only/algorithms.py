"""Finite bitset implementation for the public relation hosts."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class Rel:
    size: int
    rows: tuple[int, ...]

    def edges(self):
        for source, row in enumerate(self.rows):
            while row:
                bit = row & -row
                yield source, bit.bit_length() - 1
                row -= bit


def braid(levels: int, lanes: int, cycle: int, gates=()) -> Rel:
    assert levels >= 2 and lanes >= 1 and cycle >= 1
    assert tuple(sorted(set(gates))) == tuple(gates) and all(0 <= gate < levels - 1 for gate in gates)
    size = levels * lanes * cycle
    rows = [0] * size
    for level in range(levels):
        for lane in range(lanes):
            start = (level * lanes + lane) * cycle
            for offset in range(cycle):
                rows[start + offset] |= 1 << (start + (offset + 1) % cycle)
            if level < levels - 1:
                targets = (0,) if level in gates and lane == 0 else (range(lanes) if level not in gates else ())
                for target_lane in targets:
                    rows[start] |= 1 << ((level + 1) * lanes * cycle + target_lane * cycle)
    return Rel(size, tuple(rows))


def switch_net(levels: int, width: int, seed: int) -> Rel:
    if levels < 2 or width != 64 or not 0 <= seed < 16:
        raise ValueError('Switch requires levels >= 2, width = 64, and seed in 0..15')
    size = levels * width
    rows = [0] * size
    split = [16 + (17 * level + 7 * seed) % 33 for level in range(levels)]
    primary = [int((7 * level + 3 * seed) % 5 == 0) for level in range(levels)]
    for level in range(levels):
        for first, last in ((0, split[level]), (split[level], width)):
            for offset in range(first, last):
                rows[level * width + offset] |= 1 << (level * width + first + (offset - first + 1) % (last - first))
        if level == levels - 1:
            continue
        bottleneck = level in (9, 33, 54) or (13 * level + 7 * seed) % 23 in (4, 11)
        for source_lane in range(2):
            for target_lane in range(2):
                mandatory = (source_lane, target_lane) == (primary[level], primary[level + 1])
                optional = (37 * level + 11 * seed + 17 * source_lane + 23 * target_lane) % 7 in (0, 1, 3)
                if mandatory or (optional and not bottleneck):
                    source = level * width + (split[level] if source_lane else 0)
                    target = (level + 1) * width + (split[level + 1] if target_lane else 0)
                    rows[source] |= 1 << target
    return Rel(size, tuple(rows))


def identity(size: int) -> Rel:
    return Rel(size, tuple(1 << index for index in range(size)))


def union(left: Rel, right: Rel) -> Rel:
    assert left.size == right.size
    return Rel(left.size, tuple(a | b for a, b in zip(left.rows, right.rows)))


@lru_cache(maxsize=8)
def _shifts(rows):
    sources = {}
    for source, targets in enumerate(rows):
        while targets:
            bit = targets & -targets
            offset = bit.bit_length() - 1 - source
            sources[offset] = sources.get(offset, 0) | (1 << source)
            targets -= bit
    return tuple(sorted(sources.items(), key=lambda item: (item[0] != 1, -item[1].bit_count())))


def compose(left: Rel, right: Rel) -> Rel:
    assert left.size == right.size
    shifts = _shifts(right.rows)
    if len(shifts) <= 128:
        rows = []
        for row in left.rows:
            result = 0
            for offset, sources in shifts:
                active = row & sources
                if active:
                    result |= active << offset if offset >= 0 else active >> -offset
            rows.append(result)
        return Rel(left.size, tuple(rows))
    blocks = [right.rows[start:start + 16] for start in range(0, right.size, 16)]
    cached = [{} for _ in blocks]
    rows = []
    for row in left.rows:
        result = 0
        block_index = 0
        while row:
            mask = row & 0xffff
            if mask:
                table = cached[block_index]
                if mask not in table:
                    bits = mask
                    combined = 0
                    while bits:
                        bit = bits & -bits
                        combined |= blocks[block_index][bit.bit_length() - 1]
                        bits -= bit
                    table[mask] = combined
                result |= table[mask]
            row >>= 16
            block_index += 1
        rows.append(result)
    return Rel(left.size, tuple(rows))


def transpose(rel: Rel) -> Rel:
    rows = [0] * rel.size
    for source, target in rel.edges():
        rows[target] |= 1 << source
    return Rel(rel.size, tuple(rows))


def collapse(rel: Rel, equivalence: Rel) -> Rel:
    assert rel.size == equivalence.size
    representatives = [(row & -row).bit_length() - 1 for row in equivalence.rows]
    rows = [0] * rel.size
    for source, target in rel.edges():
        left, right = representatives[source], representatives[target]
        if left != right:
            rows[left] |= 1 << right
    return Rel(rel.size, tuple(rows))


@dataclass
class Profile:
    depth: list[int]
    ways: list[int]


def longest_count(result: Profile) -> int:
    longest = max(result.depth)
    return sum(ways for depth, ways in zip(result.depth, result.ways) if depth == longest)


def count(rel: Rel) -> int:
    return sum(row.bit_count() for row in rel.rows)
