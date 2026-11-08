"""Executable reference for the operations-only relation world (Python 3 stdlib)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


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


def step(rel: Rel) -> Rel:
    return Rel(rel.size, tuple(row & ~(1 << index) for index, row in enumerate(rel.rows)))


def union(left: Rel, right: Rel) -> Rel:
    assert left.size == right.size
    return Rel(left.size, tuple(a | b for a, b in zip(left.rows, right.rows)))


def compose(left: Rel, right: Rel) -> Rel:
    assert left.size == right.size
    rows = []
    for row in left.rows:
        result = 0
        while row:
            bit = row & -row
            result |= right.rows[bit.bit_length() - 1]
            row -= bit
        rows.append(result)
    return Rel(left.size, tuple(rows))


def expand(current: Rel, base: Rel) -> Rel:
    return union(current, compose(current, step(base)))


def reach(rel: Rel) -> Rel:
    rows = list(identity(rel.size).rows)
    for source, row in enumerate(rel.rows):
        rows[source] |= row
    for pivot in range(rel.size):
        pivot_bit = 1 << pivot
        pivot_row = rows[pivot]
        for source in range(rel.size):
            if rows[source] & pivot_bit:
                rows[source] |= pivot_row
    return Rel(rel.size, tuple(rows))


def transpose(rel: Rel) -> Rel:
    rows = [0] * rel.size
    for source, target in rel.edges():
        rows[target] |= 1 << source
    return Rel(rel.size, tuple(rows))


def mutual(rel: Rel) -> Rel:
    visited = set()
    finish = []
    adjacency = [[] for _ in rel.rows]
    reverse = [[] for _ in rel.rows]
    for source, target in rel.edges():
        adjacency[source].append(target)
        reverse[target].append(source)
    for vertex in range(rel.size):
        if vertex in visited:
            continue
        visited.add(vertex)
        stack = [(vertex, iter(adjacency[vertex]))]
        while stack:
            source, targets = stack[-1]
            target = next(targets, None)
            if target is None:
                finish.append(source)
                stack.pop()
            elif target not in visited:
                visited.add(target)
                stack.append((target, iter(adjacency[target])))
    assigned = set()
    rows = [0] * rel.size
    for vertex in reversed(finish):
        if vertex in assigned:
            continue
        component = []
        stack = [vertex]
        assigned.add(vertex)
        while stack:
            source = stack.pop()
            component.append(source)
            for target in reverse[source]:
                if target not in assigned:
                    assigned.add(target)
                    stack.append(target)
        mask = sum(1 << member for member in component)
        for member in component:
            rows[member] = mask
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


def condense(rel: Rel) -> Rel:
    return collapse(step(rel), mutual(rel))


@dataclass
class Profile:
    depth: list[int]
    ways: list[int]


def advance(profile: Profile, source: int, target: int) -> None:
    candidate = profile.depth[source] + 1
    if candidate > profile.depth[target]:
        profile.depth[target] = candidate
        profile.ways[target] = profile.ways[source]
    elif candidate == profile.depth[target]:
        profile.ways[target] += profile.ways[source]


def profile(dag: Rel) -> Profile:
    incoming = [0] * dag.size
    for _, target in dag.edges():
        incoming[target] += 1
    queue = [index for index, degree in enumerate(incoming) if degree == 0]
    result = Profile([0] * dag.size, [1] * dag.size)
    offset = 0
    while offset < len(queue):
        source = queue[offset]
        offset += 1
        row = dag.rows[source]
        while row:
            bit = row & -row
            target = bit.bit_length() - 1
            advance(result, source, target)
            incoming[target] -= 1
            if incoming[target] == 0:
                queue.append(target)
            row -= bit
    if offset != dag.size:
        raise ValueError("@dag_fold requires an acyclic relation")
    return result


def longest_count(result: Profile) -> int:
    longest = max(result.depth)
    return sum(ways for depth, ways in zip(result.depth, result.ways) if depth == longest)


def critical(dag: Rel) -> Rel:
    forward, backward = profile(dag), profile(transpose(dag))
    longest, ways = max(forward.depth), longest_count(forward)
    rows = [0] * dag.size
    for source, target in dag.edges():
        if (forward.depth[source] + 1 + backward.depth[target] == longest
                and forward.ways[source] * backward.ways[target] == ways):
            rows[source] |= 1 << target
    return Rel(dag.size, tuple(rows))


def backbone(rel: Rel) -> Rel:
    return critical(condense(rel))


def count(rel: Rel) -> int:
    return sum(row.bit_count() for row in rel.rows)


def evaluate(expression: str):
    """Closed, typed test notation; not Python eval and not a general Opulse parser."""
    import re

    match = re.fullmatch(r'Rel<(\d+), (\d+), (\d+), Gates<([\d, ]*)>>', expression)
    if match:
        levels, lanes, cycle = map(int, match.group(1, 2, 3))
        gates = tuple(map(int, match.group(4).split(', '))) if match.group(4) else ()
        return braid(levels, lanes, cycle, gates)
    match = re.fullmatch(r'Rel<(\d+), (\d+), Switch<(\d+)>>', expression)
    if match:
        return switch_net(*map(int, match.groups()))
    match = re.fullmatch(r'(step|expand|reach|mutual|condense|profile|critical|backbone|transpose|id)\((.*)\)', expression)
    if match:
        name, contents = match.groups()
        if name == 'expand':
            assert contents.startswith('id(')
            split = contents.index('), ') + 1
            return expand(evaluate(contents[:split]), evaluate(contents[split + 2:]))
        argument = evaluate(contents)
        if name == 'id':
            return identity(argument.size)
        return globals()[name](argument)
    match = re.fullmatch(r'advance\(Profile<List<([\d, ]+)>, List<([\d, ]+)>>, (\d+), (\d+)\)', expression)
    if match:
        result = Profile([int(value) for value in match.group(1).split(', ')],
                         [int(value) for value in match.group(2).split(', ')])
        advance(result, int(match.group(3)), int(match.group(4)))
        return result
    match = re.fullmatch(r'\?(count|maxdepth|longest_count|has)\{(.*)\}', expression)
    if match:
        observation, content = match.groups()
        if observation == 'has':
            relation, pair = content.rsplit(', (', 1)
            source, target = map(int, pair[:-1].split(', '))
            return bool(evaluate(relation).rows[source] & (1 << target))
        value = evaluate(content)
        return {'count': lambda: count(value), 'maxdepth': lambda: max(value.depth),
                'longest_count': lambda: longest_count(value)}[observation]()
    raise ValueError(expression)


def formatted(value):
    if isinstance(value, Profile):
        return f"Profile<List<{', '.join(map(str, value.depth))}>, List<{', '.join(map(str, value.ways))}>>"
    return str(value).lower() if isinstance(value, bool) else str(value)


def verify_showcase(specification):
    compute, decide, inverse = specification['showcase']
    certificate = decide['certificate']
    graph = switch_net(64, 64, certificate['seed'])
    dag = condense(graph)
    sizes = certificate['first_scc_sizes']
    assert len(sizes) == 64 and all(16 <= size <= 48 for size in sizes)
    assert len(certificate['edge_masks']) == 63
    assert len(certificate['forward']) == len(certificate['backward']) == 64
    assert certificate['forward'][0] == certificate['backward'][-1] == [1, 1]
    actual_equivalence = mutual(graph)
    for level, size in enumerate(sizes):
        for first, last in ((0, size), (size, 64)):
            mask = sum(1 << (64 * level + offset) for offset in range(first, last))
            for offset in range(first, last):
                assert actual_equivalence.rows[64 * level + offset] == mask
    assert max(profile(dag).depth) == 63
    assert count(dag) == 132
    total = sum(certificate['forward'][-1])
    assert total == sum(certificate['backward'][0]) == longest_count(profile(dag))
    certified_edges = []
    for level, digit in enumerate(certificate['edge_masks']):
        bits = int(digit, 16)
        next_forward = [0, 0]
        current_backward = [0, 0]
        for source_lane in range(2):
            for target_lane in range(2):
                source = 64 * level + (sizes[level] if source_lane else 0)
                target = 64 * (level + 1) + (sizes[level + 1] if target_lane else 0)
                present = bool(dag.rows[source] & (1 << target))
                assert present == bool(bits & (1 << (2 * source_lane + target_lane)))
                if present:
                    next_forward[target_lane] += certificate['forward'][level][source_lane]
                    current_backward[source_lane] += certificate['backward'][level + 1][target_lane]
                    if certificate['forward'][level][source_lane] * certificate['backward'][level + 1][target_lane] == total:
                        certified_edges.append([source, target])
        assert next_forward == certificate['forward'][level + 1]
        assert current_backward == certificate['backward'][level]
    assert count(dag) == sum(int(digit, 16).bit_count() for digit in certificate['edge_masks'])
    assert certified_edges == certificate['backbone_edges']
    assert sorted(certified_edges) == [list(edge) for edge in backbone(graph).edges()]
    assert compute['answer'] == str(total)
    assert decide['answer'] == f'{len(certified_edges)} edges, listed in certificate.backbone_edges'

    candidate_rows = []
    for seed in range(16):
        candidate = switch_net(64, 64, seed)
        candidate_rows.append([seed, longest_count(profile(condense(candidate))), count(backbone(candidate))])
    assert candidate_rows == inverse['candidate_certificate']
    matches = [seed for seed, routes, edges in candidate_rows if routes == 4608 and edges == 38]
    assert matches == [int(inverse['answer'])] == [9]


def main():
    specification = json.loads((Path(__file__).resolve().parents[4] /
                                'worlds/catalogue/depth/op_only.json').read_text(encoding='utf-8'))
    for layer in specification['tower']:
        assert formatted(evaluate(layer['example'])) == layer['value'], layer['layer']
    for task in specification['showcase']:
        for expression, expected in task['check']:
            assert formatted(evaluate(expression)) == expected, task['angle']
    verify_showcase(specification)
    assert count(backbone(braid(64, 2, 32, (17, 41)))) == 2
    assert longest_count(profile(condense(braid(64, 2, 32, (17, 41))))) == 2 ** 60
    assert [gate for gate in range(63) if evaluate(
        f'?has{{backbone(Rel<64, 2, 32, Gates<{gate}>>), (1984, 2048)}}')] == [31]
    for levels, lanes, cycle, gates in [(4, 2, 3, (1,)), (5, 3, 2, (0, 3))]:
        relation = braid(levels, lanes, cycle, gates)
        paths = reach(relation)
        backwards = transpose(paths)
        expected = Rel(relation.size, tuple(a & b for a, b in zip(paths.rows, backwards.rows)))
        assert mutual(relation) == expected
    print('OK')


if __name__ == '__main__':
    main()
