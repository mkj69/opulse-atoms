"""Reference semantics for the sealed, partially observed action world.

Only front_wall/front_water inspect the sealed terrain. All planning uses Known.
Python functions named with a leading underscore are verifier internals, not learner APIs.
"""

from collections import deque
from dataclasses import dataclass
import json
from pathlib import Path


DIRS = ((0, -1), (1, 0), (0, 1), (-1, 0))
LETTERS = 'NESW'
MAPS = {
    'M1': (
        '############',
        '#..#....#..#',
        '#..#.#..#..#',
        '#....#.....#',
        '##.#...##..#',
        '#..#.#.....#',
        '#.~..#.#.#.#',
        '#.##...#...#',
        '#....#.....#',
        '############',
    ),
    'M2': (
        '############',
        '#..#....#..#',
        '#..#.#..#..#',
        '#....#.....#',
        '##.#...##..#',
        '#..#.#.....#',
        '#.~..#.#.#.#',
        '#....~.#...#',
        '#....#.....#',
        '############',
    ),
    'M3': (
        '############',
        '#..#....##.#',
        '#..#.#..####',
        '#....#.....#',
        '##.#...##..#',
        '#..#.#.....#',
        '#.~..#.#.#.#',
        '#.##...#...#',
        '#....#.....#',
        '############',
    ),
}
START = (1, 1, 1)


class Bottom(Exception):
    pass


@dataclass(frozen=True)
class Maze:
    token: str

    def __post_init__(self):
        if self.token not in MAPS:
            raise Bottom('unknown_maze')


@dataclass(frozen=True)
class Bot:
    maze: Maze
    x: int
    y: int
    direction: int
    steps: int = 0
    turns: int = 0

    @property
    def pos(self):
        return self.x, self.y


@dataclass(frozen=True)
class Scan:
    x: int
    y: int
    # N E S W, each entry is '.', '#', or '~'.
    faces: tuple


@dataclass(frozen=True)
class Known:
    start: tuple
    tiles: tuple  # canonical triples (x,y,tile), sorted by (y,x)
    scanned: tuple  # sorted coordinates (y,x)


@dataclass(frozen=True)
class Survey:
    bot: Bot
    known: Known
    scans: int


@dataclass(frozen=True)
class Atlas:
    survey: Survey


def _terrain(maze, x, y):
    rows = MAPS[maze.token]
    if not (0 <= x < 12 and 0 <= y < 10):
        return '#'
    return rows[y][x]


def start(maze):
    assert _terrain(maze, START[0], START[1]) == '.'
    return Bot(maze, *START)


def turn_right(bot):
    return Bot(bot.maze, bot.x, bot.y, (bot.direction + 1) % 4,
               bot.steps, bot.turns + 1)


def turn_left(bot):
    return Bot(bot.maze, bot.x, bot.y, (bot.direction - 1) % 4,
               bot.steps, bot.turns + 1)


def _ahead(bot):
    dx, dy = DIRS[bot.direction]
    return bot.x + dx, bot.y + dy


def front_wall(bot):
    return _terrain(bot.maze, *_ahead(bot)) == '#'


def front_water(bot):
    return _terrain(bot.maze, *_ahead(bot)) == '~'


def pose(bot):
    return bot.x, bot.y, LETTERS[bot.direction]


def _encode_bot(bot):
    return {'maze': bot.maze.token, 'x': bot.x, 'y': bot.y,
            'dir': LETTERS[bot.direction], 'steps': bot.steps, 'turns': bot.turns}


def odometer(bot):
    return bot.steps, bot.turns


def forward(bot):
    wall, water = front_wall(bot), front_water(bot)
    if wall or water:
        raise Bottom('blocked')
    x, y = _ahead(bot)
    return Bot(bot.maze, x, y, bot.direction, bot.steps + 1, bot.turns)


def seq(first, second, bot):
    return second(first(bot))


def front_clear(bot):
    wall, water = front_wall(bot), front_water(bot)
    return not wall and not water


def safe_step(bot):
    if not front_clear(bot):
        raise Bottom('blocked')
    return forward(bot)


def _make_scan(x, y, faces):
    faces = tuple(faces)
    if len(faces) != 4 or any(tile not in '.#~' for tile in faces):
        raise Bottom('bad_scan')
    return Scan(x, y, faces)


def sense(bot):
    wall, water = front_wall(bot), front_water(bot)
    return '#' if wall else '~' if water else '.'


def scan(turn, probe, bot):
    current = bot
    faces = [None] * 4
    for _ in range(4):
        faces[current.direction] = probe(current)
        current = turn(current)
    assert current.pos == bot.pos and current.direction == bot.direction
    return current, _make_scan(bot.x, bot.y, faces)


def _sort_pos(positions):
    return tuple(sorted(positions, key=lambda p: (p[1], p[0])))


def make_known(origin):
    return Known(origin, ((origin[0], origin[1], '.'),), ())


def _tiles(known):
    return {(x, y): tile for x, y, tile in known.tiles}


def tiles(known):
    return known.tiles


def merge_scan(known, reading):
    tiles = _tiles(known)
    if tiles.get((reading.x, reading.y)) != '.':
        raise Bottom('unreachable_scan')
    if (reading.x, reading.y) in known.scanned:
        if any(tiles.get((reading.x + dx, reading.y + dy)) != reading.faces[index]
               for index, (dx, dy) in enumerate(DIRS)):
            raise Bottom('contradictory_scan')
        return known
    for index, (dx, dy) in enumerate(DIRS):
        pos = reading.x + dx, reading.y + dy
        tile = reading.faces[index]
        if pos in tiles and tiles[pos] != tile:
            raise Bottom('contradictory_scan')
        tiles[pos] = tile
    return Known(known.start,
                 tuple((x, y, tiles[x, y]) for x, y in _sort_pos(tiles)),
                 _sort_pos((*known.scanned, (reading.x, reading.y))))


def frontier(known):
    tiles = _tiles(known)
    return _sort_pos(pos for pos in tiles if tiles[pos] == '.' and pos not in known.scanned)


def route_known(known, source, target):
    tiles = _tiles(known)
    if tiles.get(source) != '.' or tiles.get(target) != '.':
        raise Bottom('unknown_or_blocked')
    parents = {source: None}
    queue = deque([source])
    while queue:
        pos = queue.popleft()
        if pos == target:
            break
        for dx, dy in DIRS:
            neighbor = pos[0] + dx, pos[1] + dy
            if tiles.get(neighbor) == '.' and neighbor not in parents:
                parents[neighbor] = pos
                queue.append(neighbor)
    if target not in parents:
        raise Bottom('no_route')
    route = []
    pos = target
    while pos != source:
        route.append(pos)
        pos = parents[pos]
    return tuple(reversed(route))


def _face(bot, direction):
    diff = (direction - bot.direction) % 4
    if diff == 3:
        return turn_left(bot)
    for _ in range(diff):
        bot = turn_right(bot)
    return bot


def follow(step, bot, route):
    for pos in route:
        for index, (dx, dy) in enumerate(DIRS):
            if (bot.x + dx, bot.y + dy) == pos:
                bot = step(_face(bot, index))
                break
        else:
            raise Bottom('nonadjacent_route')
    return bot


def _default_scan(bot):
    return scan(turn_right, sense, bot)


def explore(bot, scan_action=None, step=None, route=None):
    scan_action = _default_scan if scan_action is None else scan_action
    step = safe_step if step is None else step
    route = route_known if route is None else route
    known = make_known(bot.pos)
    scans = 0
    # At most 120 open cells; each scan marks a new one; no unknown-map access.
    for _ in range(120):
        remaining = frontier(known)
        if not remaining:
            return Survey(bot, known, scans)
        paths = [(len(route(known, bot.pos, target)), target[1], target[0], target)
                 for target in remaining]
        target = min(paths)[3]
        bot = follow(step, bot, route(known, bot.pos, target))
        bot, reading = scan_action(bot)
        known = merge_scan(known, reading)
        scans += 1
    raise Bottom('scan_bound_exceeded')


def make_atlas(survey):
    if frontier(survey.known) or len(survey.known.scanned) != survey.scans:
        raise Bottom('incomplete')
    return Atlas(survey)


def stats(survey):
    moves, turns = odometer(survey.bot)
    return {'scans': survey.scans, 'moves': moves,
            'turns': turns, 'probes': 8 * survey.scans + 4 * moves,
            'last_pose': list(pose(survey.bot))}


def known(atlas):
    return atlas.survey.known


def shortest(atlas, target):
    return route_known(known(atlas), known(atlas).start, target)


def _oracle_reachable(maze):
    # Verifier-only: never used by a learner-visible definition.
    found = {START[:2]}
    queue = deque(found)
    while queue:
        x, y = queue.popleft()
        for dx, dy in DIRS:
            neighbor = x + dx, y + dy
            if neighbor not in found and _terrain(maze, *neighbor) == '.':
                found.add(neighbor)
                queue.append(neighbor)
    return found


def _show_path(path):
    return ''.join(LETTERS[DIRS.index((next_pos[0] - last[0], next_pos[1] - last[1]))]
                   for last, next_pos in zip((START[:2], *path), path))


def _result(key):
    maze = Maze('M1')
    bot = start(maze)
    if key == 'clear':
        return front_clear(bot)
    if key == 'step':
        return list(pose(safe_step(bot)))
    if key == 'scan_object':
        reading = _make_scan(1, 1, ('#', '.', '.', '#'))
        return {'x': reading.x, 'y': reading.y, 'faces': list(reading.faces)}
    if key == 'sense':
        return sense(bot)
    if key == 'scan':
        turned, reading = scan(turn_right, sense, bot)
        assert reading.faces == ('#', '.', '.', '#') and turned.turns == 4
        return [_encode_bot(turned),
                {'x': reading.x, 'y': reading.y, 'faces': list(reading.faces)}]
    if key == 'known':
        return [list(make_known(bot.pos).tiles[0])]
    if key == 'merge':
        reading = scan(turn_right, sense, bot)[1]
        return [list(row) for row in merge_scan(make_known(bot.pos), reading).tiles]
    if key == 'frontier':
        reading = scan(turn_right, sense, bot)[1]
        return [list(p) for p in frontier(merge_scan(make_known(bot.pos), reading))]
    if key == 'route_known':
        reading = scan(turn_right, sense, bot)[1]
        return [list(p) for p in route_known(merge_scan(make_known(bot.pos), reading), bot.pos, (2, 1))]
    if key == 'follow':
        moved = follow(safe_step, bot, ((2, 1), (2, 2)))
        return _encode_bot(moved)
    if key in ('explore', 'atlas', 'compute', 'decide', 'invert'):
        survey = explore(bot)
        atlas = make_atlas(survey)
        if key == 'explore':
            return stats(survey)
        if key == 'atlas':
            return [list(pos) for pos in frontier(known(atlas))]
        if key == 'compute':
            destination = (10, 8)
            route = shortest(atlas, destination)
            return {'length': len(route), 'directions': _show_path(route),
                    'scans': survey.scans, 'moves': survey.bot.steps,
                    'wall': sum(tile == '#' for _, _, tile in survey.known.tiles),
                    'water': sum(tile == '~' for _, _, tile in survey.known.tiles)}
        if key == 'decide':
            destination = (10, 8)
            candidate = 'EWESSEESEESEEEESSS'
            current = START[:2]
            trace = []
            for letter in candidate:
                dx, dy = DIRS[LETTERS.index(letter)]
                current = current[0] + dx, current[1] + dy
                trace.append(current)
            legal = all(_tiles(known(atlas)).get(p) == '.' for p in trace)
            return {'legal': legal, 'reaches_goal': current == destination,
                    'optimal': legal and current == destination and len(trace) == len(shortest(atlas, destination)),
                    'shortest_length': len(shortest(atlas, destination))}
        # Find the lexicographically first reachable coordinate at the exact
        # distance. This is a genuine inverse of the shortest-path observation.
        if key == 'invert':
            desired = 14
            matches = [pos for pos in _sort_pos(known(atlas).scanned)
                       if len(shortest(atlas, pos)) == desired]
            return {'first': list(matches[0]) if matches else None, 'count': len(matches),
                    'directions': _show_path(shortest(atlas, matches[0])) if matches else None}
    raise KeyError(key)


def main():
    assert all(len(rows) == 10 and all(len(row) == 12 for row in rows)
               for rows in MAPS.values())
    assert all(all(tile in '.#~' for row in rows for tile in row) for rows in MAPS.values())
    for maze_id in MAPS:
        atlas = make_atlas(explore(start(Maze(maze_id))))
        assert set(atlas.survey.known.scanned) == _oracle_reachable(Maze(maze_id))
        assert not frontier(known(atlas))
        assert stats(atlas.survey)['probes'] == 8 * len(atlas.survey.known.scanned) + 4 * atlas.survey.bot.steps
        assert all(_terrain(Maze(maze_id), x, y) == tile
                   for x, y, tile in known(atlas).tiles)
        for pos in atlas.survey.known.scanned:
            # Independent full-state BFS is verifier-only, never used for planning.
            distances = {START[:2]: 0}
            queue = deque([START[:2]])
            while queue:
                x, y = queue.popleft()
                for dx, dy in DIRS:
                    neighbor = x + dx, y + dy
                    if neighbor not in distances and _terrain(Maze(maze_id), *neighbor) == '.':
                        distances[neighbor] = distances[x, y] + 1
                        queue.append(neighbor)
            assert len(shortest(atlas, pos)) == distances[pos]
    assert _terrain(Maze('M3'), 10, 1) == '.'
    assert (10, 1) not in _oracle_reachable(Maze('M3'))
    assert _tiles(known(make_atlas(explore(start(Maze('M3')))))).get((10, 1)) != '.'
    original_wall, original_water = front_wall, front_water
    calls = {'wall': 0, 'water': 0}

    def counted_wall(bot):
        calls['wall'] += 1
        return original_wall(bot)

    def counted_water(bot):
        calls['water'] += 1
        return original_water(bot)

    globals()['front_wall'], globals()['front_water'] = counted_wall, counted_water
    try:
        measured = explore(start(Maze('M1')))
    finally:
        globals()['front_wall'], globals()['front_water'] = original_wall, original_water
    assert calls == {'wall': 380, 'water': 380}
    assert sum(calls.values()) == stats(measured)['probes']
    try:
        forward(_face(start(Maze('M1')), 0))
    except Bottom as error:
        assert str(error) == 'blocked'
    else:
        raise AssertionError('blocked move must fail, not silently stay put')
    data = json.loads(Path(__file__).with_suffix('.json').read_text(encoding='utf-8'))
    assert data['id'] == 'action' and len(data['tower']) == 12 and len(data['showcase']) == 3
    for layer, key in zip(data['tower'],
                          ('clear', 'step', 'scan_object', 'sense', 'scan', 'known',
                           'merge', 'frontier', 'route_known', 'follow', 'explore', 'atlas')):
        assert layer['value'] == _result(key), (layer['layer'], layer['value'], _result(key))
    for task, key in zip(data['showcase'], ('compute', 'invert', 'decide')):
        assert task['answer'] == _result(key), (key, task['answer'], _result(key))
    print('OK')


if __name__ == '__main__':
    main()
