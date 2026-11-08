"""Independent subset-DP oracle for exact finite scheduling certificates."""

from functools import cache

from .hosts import adjacent, vertices, weight


def independent_oracle(plan):
    remaining = set(range(plan.blocks * plan.width))
    groups = []
    while remaining:
        frontier = {min(remaining)}
        component = set()
        while frontier:
            vertex = frontier.pop()
            if vertex in component:
                continue
            component.add(vertex)
            frontier.update(set(vertices(adjacent(plan, vertex))) - component)
        remaining.difference_update(component)
        groups.append(component)

    @cache
    def solve(mask):
        if not mask:
            return 0, ()
        vertex = (mask & -mask).bit_length() - 1
        rejected = solve(mask & ~(1 << vertex))
        tail = solve(mask & ~((1 << vertex) | adjacent(plan, vertex)))
        accepted = (tail[0] + weight(plan, vertex), tuple(sorted((vertex, *tail[1]))))
        if accepted[0] > rejected[0] or accepted[0] == rejected[0] and accepted[1] < rejected[1]:
            return accepted
        return rejected

    total = 0
    chosen = ()
    for group in groups:
        score, selection = solve(sum(1 << vertex for vertex in group))
        total += score
        chosen = tuple(sorted((*chosen, *selection)))
    return total, chosen
