"""Given, sealed 12-by-10 maze actions and generic structural primitives."""

import hashlib
import hmac

from opulse.atoms.values import Bottom, Card, boolean

MAPS = {
    "M1": ("############", "#..#....#..#", "#..#.#..#..#", "#....#.....#",
           "##.#...##..#", "#..#.#.....#", "#.~..#.#.#.#", "#.##...#...#",
           "#....#.....#", "############"),
    "M2": ("############", "#..#....#..#", "#..#.#..#..#", "#....#.....#",
           "##.#...##..#", "#..#.#.....#", "#.~..#.#.#.#", "#....~.#...#",
           "#....#.....#", "############"),
    "M3": ("############", "#..#....##.#", "#..#.#..####", "#....#.....#",
           "##.#...##..#", "#..#.#.....#", "#.~..#.#.#.#", "#.##...#...#",
           "#....#.....#", "############"),
}
DIRS = ((0, -1), (1, 0), (0, 1), (-1, 0))
LETTERS = "NESW"
_probe_calls = []
_observed = {}
_seal_key = b"action-v2-sealed-cards"


def seal(kind, fields):
    return hmac.new(_seal_key, repr((kind, fields)).encode(), hashlib.sha256).hexdigest()


def probe_count(survey):
    if (not isinstance(survey, Card) or survey.sort != "Survey" or survey.tag != "survey"
            or len(survey.fields) != 5):
        return None
    bot, known, scans, count, signature = survey.fields
    if (not valid_state(bot) or not valid_known(known) or type(scans) is not int
            or scans < 0 or type(count) is not int or count < 0
            or signature != seal("survey", survey.fields[:4])):
        return None
    return count


def mint_bot(world, x, y, direction, steps, turns):
    fields = (world, x, y, direction, steps, turns)
    return Card("Bot", "bot:" + seal("bot", fields), fields)


def valid_known(known):
    if not isinstance(known, Card) or known.sort != "Known" or known.tag != "known" or len(known.fields) != 3:
        return False
    start, tiles, scanned = known.fields
    if not (isinstance(start, Card) and start.sort == "Pos" and start.tag == "pos"
            and isinstance(tiles, Card) and tiles.sort == "List" and tiles.tag == "items"
            and isinstance(scanned, Card) and scanned.sort == "List" and scanned.tag == "items"):
        return False
    def position(item):
        return (isinstance(item, Card) and item.sort == "Pos" and item.tag == "pos"
                and len(item.fields) == 2 and all(type(coord) is int for coord in item.fields)
                and 0 <= item.fields[0] < 12 and 0 <= item.fields[1] < 10)
    if not position(start):
        return False
    entries = tiles.fields
    if any(not isinstance(entry, Card) or entry.sort != "Pair" or entry.tag != "pair"
           or len(entry.fields) != 2 or not position(entry.fields[0])
           or entry.fields[1] not in ("#", ".", "~") for entry in entries):
        return False
    positions = [entry.fields[0].fields for entry in entries]
    scanned_positions = [item.fields for item in scanned.fields if position(item)]
    free = {entry.fields[0].fields for entry in entries if entry.fields[1] == "."}
    return (positions == sorted(set(positions), key=lambda pos: (pos[1], pos[0]))
            and len(scanned_positions) == len(scanned.fields)
            and scanned_positions == sorted(set(scanned_positions), key=lambda pos: (pos[1], pos[0]))
            and start.fields in free and set(scanned_positions) <= free)


def measured_scan(x, y, faces):
    return any(all(_observed.get((maze_id, x, y, direction)) == face
                       for direction, face in enumerate(faces)) for maze_id in MAPS)


def valid_learner_card(value):
    if not isinstance(value, Card):
        return True
    if value.sort == "Maze":
        return value.tag == "maze" and value.fields in tuple((name,) for name in MAPS)
    if value.sort == "Bot":
        return valid_state(value)
    if value.sort == "Survey":
        return probe_count(value) is not None
    if value.sort == "Scan":
        return (value.tag == "scan" and len(value.fields) == 3
                and type(value.fields[0]) is int and type(value.fields[1]) is int
                and isinstance(value.fields[2], Card) and value.fields[2].sort == "List"
                and value.fields[2].tag == "items" and len(value.fields[2].fields) == 4
                and all(face in ("#", ".", "~") for face in value.fields[2].fields)
                and measured_scan(*value.fields[:2], value.fields[2].fields))
    if value.sort == "Known":
        return valid_known(value)
    if value.sort == "Atlas":
        return value.tag == "atlas" and len(value.fields) == 1 and probe_count(value.fields[0]) is not None
    return all(valid_learner_card(item) for item in value.fields)


def maze(name):
    return Card("Maze", "maze", (name,)) if name in MAPS else Bottom("unknown_maze")


def valid_state(state):
    if not isinstance(state, Card) or state.sort != "Bot" or len(state.fields) != 6:
        return False
    world, x, y, direction, steps, turns = state.fields
    return (state.tag == "bot:" + seal("bot", state.fields)
            and isinstance(world, Card) and world.sort == "Maze" and world.tag == "maze"
            and len(world.fields) == 1 and type(world.fields[0]) is str
            and world.fields[0] in MAPS and type(x) is int and 0 <= x < 12
            and type(y) is int and 0 <= y < 10 and type(direction) is int and 0 <= direction < 4
            and type(steps) is int and steps >= 0 and type(turns) is int and turns >= 0
            and MAPS[world.fields[0]][y][x] == ".")


def to_card(state):
    if not valid_state(state):
        return Bottom("invalid")
    return state


def from_card(card):
    return to_card(card)


def terrain(state, x, y):
    if not 0 <= x < 12 or not 0 <= y < 10:
        return "#"
    return MAPS[state.fields[0].fields[0]][y][x]


def start(world):
    if not isinstance(world, Card) or not valid_learner_card(world):
        return Bottom("invalid")
    return mint_bot(world, 1, 1, 1, 0, 0)


def turn_right(bot):
    if not valid_state(bot):
        return Bottom("invalid")
    world, x, y, direction, steps, turns = bot.fields
    return mint_bot(world, x, y, (direction + 1) % 4, steps, turns + 1)


def turn_left(bot):
    if not valid_state(bot):
        return Bottom("invalid")
    world, x, y, direction, steps, turns = bot.fields
    return mint_bot(world, x, y, (direction - 1) % 4, steps, turns + 1)


def ahead(bot):
    dx, dy = DIRS[bot.fields[3]]
    return bot.fields[1] + dx, bot.fields[2] + dy


def front_wall(bot):
    if not valid_state(bot):
        return Bottom("invalid")
    label = terrain(bot, *ahead(bot))
    _observed[(bot.fields[0].fields[0], bot.fields[1], bot.fields[2], bot.fields[3])] = label
    if _probe_calls:
        _probe_calls[-1][0] += 1
    return boolean(label == "#")


def front_water(bot):
    if not valid_state(bot):
        return Bottom("invalid")
    label = terrain(bot, *ahead(bot))
    _observed[(bot.fields[0].fields[0], bot.fields[1], bot.fields[2], bot.fields[3])] = label
    if _probe_calls:
        _probe_calls[-1][0] += 1
    return boolean(label == "~")


def pose(bot):
    return Card("Pose", "pose", (bot.fields[1], bot.fields[2], LETTERS[bot.fields[3]])) if valid_state(bot) else Bottom("invalid")


def odometer(bot):
    return Card("Pair", "pair", bot.fields[4:6]) if valid_state(bot) else Bottom("invalid")


def forward(bot):
    if not valid_state(bot):
        return Bottom("invalid")
    x, y = ahead(bot)
    if terrain(bot, x, y) != ".":
        return Bottom("blocked")
    world, _, _, direction, steps, turns = bot.fields
    return mint_bot(world, x, y, direction, steps + 1, turns)


def stats(survey):
    probes = probe_count(survey)
    if probes is None:
        return Bottom("invalid")
    bot, _, scans = survey.fields[:3]
    return Card("Stats", "stats", (scans, bot.fields[4], bot.fields[5],
                                    probes, pose(bot)))


def field(value, index):
    if (not isinstance(value, Card) or type(index) is not int
            or not 0 <= index < len(value.fields)
            or value.sort in ("Bot", "Scan", "Known", "Survey", "Atlas")
            and not valid_learner_card(value)
            or not valid_learner_card(value.fields[index])):
        return Bottom("invalid")
    return value.fields[index]


def card(sort, tag, fields):
    if (not isinstance(fields, Card) or fields.sort != "List"
            or sort in ("Maze", "Bot", "Survey", "Scan", "Known", "Atlas")):
        return Bottom("invalid")
    return Card(sort, tag, fields.fields)


def survey(bot, known, scans):
    if (not _probe_calls or not valid_state(bot) or not valid_known(known)
            or type(scans) is not int or scans < 0):
        return Bottom("invalid")
    fields = (bot, known, scans, _probe_calls[-1][0])
    return Card("Survey", "survey", (*fields, seal("survey", fields)))


def empty():
    return Card("List", "items")


def push(items, item):
    return Card("List", "items", (*items.fields, item)) if isinstance(items, Card) and items.sort == "List" else Bottom("invalid")


def length(items):
    return len(items.fields) if isinstance(items, Card) and items.sort == "List" else Bottom("invalid")


def at(items, index):
    if not isinstance(items, Card) or items.sort != "List" or type(index) is not int or not 0 <= index < len(items.fields):
        return Bottom("invalid")
    return items.fields[index]


def tail(items):
    return Card("List", "items", items.fields[1:]) if isinstance(items, Card) and items.sort == "List" and items.fields else Bottom("invalid")


def contains(items, item):
    return boolean(item in items.fields) if isinstance(items, Card) and items.sort == "List" else Bottom("invalid")


def ordered(items, first, second):
    if not isinstance(items, Card) or items.sort != "List":
        return Bottom("invalid")
    def key(entry):
        target = entry.fields[0] if entry.sort == "Pair" else entry
        return target.fields[first], target.fields[second]
    return Card("List", "items", tuple(sorted(items.fields, key=key)))


def assoc_get(items, key, fallback):
    if not isinstance(items, Card) or items.sort != "List":
        return Bottom("invalid")
    for entry in items.fields:
        if entry.fields[0] == key:
            return entry.fields[1]
    return fallback


def assoc_put(items, key, value):
    if not isinstance(items, Card) or items.sort != "List":
        return Bottom("invalid")
    entries = [entry for entry in items.fields if entry.fields[0] != key]
    entries.append(Card("Pair", "pair", (key, value)))
    return Card("List", "items", tuple(entries))


def eq(left, right):
    return boolean(left == right)


def lt(left, right):
    return boolean(left < right)


def add(left, right):
    return left + right if type(left) is type(right) is int else Bottom("invalid")


def sub(left, right):
    return left - right if type(left) is type(right) is int else Bottom("invalid")


def fail(reason):
    if reason not in ("blocked", "invalid", "no_route", "unknown_or_blocked",
                      "contradictory_scan", "unreachable_scan", "nonadjacent_route",
                      "scan_bound_exceeded", "incomplete"):
        return Bottom("invalid")
    return Bottom(reason)
