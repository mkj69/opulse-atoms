"""Twelve invented definitions built from counted, given kernel atoms."""

import importlib.util
from dataclasses import replace
from functools import lru_cache
from pathlib import Path

from opulse.atoms import kernel, templates
from opulse.atoms import nodes as n
from opulse.atoms.library import VerifyRequest
from opulse.atoms.spec import (
    CombinatorSpec,
    Contract,
    Definition,
    Edge,
    ObjectSpec,
    ObservationSpec,
    OperationSpec,
    TemplateSpec,
    compute_layer,
)
from opulse.atoms.values import FALSE, TRUE, Bottom, Card, boolean

from . import hosts
from .world import new_library


@lru_cache(maxsize=1)
def reference():
    path = Path(__file__).resolve().parents[4] / "worlds/catalogue/depth/action.py"
    spec = importlib.util.spec_from_file_location("action_depth_reference", path)
    module = importlib.util.module_from_spec(spec)
    import sys
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def from_reference(value):
    ref = reference()
    if isinstance(value, ref.Maze):
        return hosts.maze(value.token)
    if isinstance(value, ref.Bot):
        return hosts.mint_bot(from_reference(value.maze), value.x, value.y,
                              value.direction, value.steps, value.turns)
    if isinstance(value, ref.Scan):
        return Card("Scan", "scan", (value.x, value.y, Card("List", "items", value.faces)))
    if isinstance(value, ref.Known):
        return Card("Known", "known", (Card("Pos", "pos", value.start),
            Card("List", "items", tuple(Card("Pair", "pair", (Card("Pos", "pos", (x, y)), tile))
                                        for x, y, tile in value.tiles)),
            Card("List", "items", tuple(Card("Pos", "pos", position) for position in value.scanned))))
    if isinstance(value, ref.Survey):
        return Card("Survey", "survey", (from_reference(value.bot), from_reference(value.known), value.scans))
    if isinstance(value, ref.Atlas):
        return Card("Atlas", "atlas", (from_reference(value.survey),))
    if type(value) is bool:
        return boolean(value)
    if isinstance(value, tuple):
        if len(value) == 2 and isinstance(value[0], ref.Bot) and isinstance(value[1], ref.Scan):
            return Card("Pair", "pair", tuple(from_reference(item) for item in value))
        if len(value) == 2 and all(type(item) is int for item in value):
            return Card("Pos", "pos", value)
        return Card("List", "items", tuple(from_reference(item) for item in value))
    return value


def to_reference(value):
    ref = reference()
    if value in (TRUE, FALSE):
        return value == TRUE
    if isinstance(value, Card):
        if value.sort == "Maze":
            return ref.Maze(value.fields[0])
        if value.sort == "Bot":
            maze, x, y, direction, steps, turns = value.fields
            return ref.Bot(to_reference(maze), x, y, direction, steps, turns)
        if value.sort == "Pos":
            return value.fields
        if value.sort == "Scan":
            return ref.Scan(value.fields[0], value.fields[1], value.fields[2].fields)
        if value.sort == "Known":
            origin, tiles, scanned = value.fields
            return ref.Known(origin.fields, tuple((*entry.fields[0].fields, entry.fields[1])
                                                  for entry in tiles.fields),
                             tuple(pos.fields for pos in scanned.fields))
        if value.sort == "Survey":
            return ref.Survey(to_reference(value.fields[0]), to_reference(value.fields[1]), value.fields[2])
        if value.sort == "Atlas":
            return ref.Atlas(to_reference(value.fields[0]))
        if value.sort == "List":
            return tuple(to_reference(item) for item in value.fields)
    return value


def reference_outcome(name, *args):
    ref = reference()
    try:
        if name == "front_clear":
            state = to_reference(args[0])
            return boolean(not ref.front_wall(state) and not ref.front_water(state))
        if name == "Scan":
            return Card("Scan", "scan", args)
        if name == "Known":
            return Card("Known", "known", args)
        if name == "Atlas":
            return Card("Atlas", "atlas", args)
        if name in ("scan", "scan_default"):
            bot = args[-1]
            turn = {"turn_right": ref.turn_right, "turn_left": ref.turn_left}[
                args[0].name if name == "scan" else "turn_right"]
            probe = {"sense": ref.sense}[args[1].name if name == "scan" else "sense"]
            return from_reference(ref.scan(turn, probe, to_reference(bot)))
        if name == "follow":
            return from_reference(ref.follow(ref.safe_step, to_reference(args[1]), to_reference(args[2])))
        if name == "explore":
            return from_reference(ref.explore(to_reference(args[-1])))
        function = {"safe_step": ref.safe_step, "sense": ref.sense,
                    "make_known": ref.make_known, "merge_scan": ref.merge_scan,
                    "frontier": ref.frontier, "route_known": ref.route_known,
                    "make_atlas": ref.make_atlas}[name]
        result = function(*(to_reference(arg) for arg in args))
        return Card("Atlas", "atlas", args) if name == "make_atlas" else from_reference(result)
    except ref.Bottom as error:
        return Bottom(str(error))


def var(name):
    return n.Var(name)


def lit(value):
    return n.Lit(value)


def call(name, *args):
    return n.Call(name, args)


def let(name, value, body):
    return n.Let(name, value, body)


def iff(condition, yes, no):
    return n.Case(((n.Test(condition), yes),), no)


def fail(reason):
    return call("fail", lit(reason))


def field(value, index):
    return call("field", value, lit(index))


def items(*members):
    result = call("empty")
    for member in members:
        result = call("push", result, member)
    return result


def record(sort, tag, *members):
    return call("card", lit(sort), lit(tag), items(*members))


def pos(x, y):
    return record("Pos", "pos", x, y)


def xpos(value):
    return field(value, 0)


def ypos(value):
    return field(value, 1)


def adjacent(value, direction):
    dx, dy = hosts.DIRS[direction]
    return pos(call("add", xpos(value), lit(dx)), call("add", ypos(value), lit(dy)))


def zero(value):
    return call("eq", value, lit(0))


def tile(known, position):
    return call("assoc_get", field(known, 1), position, lit("?"))


def current(bot):
    return let("seen_pose", call("pose", bot), pos(xpos(var("seen_pose")), ypos(var("seen_pose"))))


def fresh(name, kind, body, params, known, op_params=(), output="unknown"):
    dependencies = tuple(sorted(n.references(body) - set(op_params)))
    layer = compute_layer(set(dependencies) | n.operation_literals(body),
                          lambda dep: known[dep.split(".")[0]].layer
                          if dep.split(".")[0] in known else 0)
    if kind == "operation":
        spec = OperationSpec(name, "transform", tuple(Edge("unknown") for _ in params),
                             Edge(output), name, extra={"input_names": list(params)})
    elif kind == "combinator":
        spec = CombinatorSpec(name, tuple(params), tuple(op_params), body)
    elif kind == "observation":
        spec = ObservationSpec(name, tuple(params), body)
    else:
        fields = {"Scan": (("x", "int"), ("y", "int"), ("faces", "List")),
                  "Known": (("start", "Pos"), ("tiles", "List"), ("scanned", "List")),
                  "Atlas": (("survey", "Survey"),)}[name]
        interfaces = {"Scan": ("Scan.scan",), "Known": ("Known.known",),
                      "Atlas": ("Atlas.atlas",)}
        spec = ObjectSpec(name, "compose", tags={name.lower(): fields}, sealed=True,
                          interface=interfaces[name])
    definition = Definition(name, kind, "invented", layer, dependencies, spec, body)
    known[name] = definition
    return definition


def definitions():
    known = {}
    result = []

    def add(name, kind, body, params, op_params=(), output="unknown"):
        result.append(fresh(name, kind, body, params, known, op_params, output))

    bot, known_map, scan = var("bot"), var("known_map"), var("scan")
    add("front_clear", "observation", iff(call("front_wall", var("s")), lit(FALSE),
        iff(call("front_water", var("s")), lit(FALSE), lit(TRUE))),
        ("front_wall", "front_water"))

    clear = call("front_clear", bot)
    add("safe_step", "operation", iff(clear, call("forward", bot), fail("blocked")), ("bot",), output="Bot")
    add("Scan", "object", None, ())
    add("sense", "operation", iff(call("front_wall", bot), lit("#"),
        iff(call("front_water", bot), lit("~"), lit("."))), ("bot",), output="str")

    scan_body = let("seen_pose", call("pose", bot),
                    record("Pair", "pair", var("rot4"),
                           call("Scan.scan", xpos(var("seen_pose")), ypos(var("seen_pose")),
                                items(*(var(name) for name in ("north", "east", "south", "west"))))))
    for direction in reversed(range(4)):
        faces = ("first", "second", "third", "fourth")
        heading = hosts.LETTERS[direction]
        selected = lit("?")
        for turn_index in reversed(range(4)):
            source = bot if turn_index == 0 else var(f"rot{turn_index}")
            selected = iff(call("eq", field(call("pose", source), 2), lit(heading)),
                           var(faces[turn_index]), selected)
        scan_body = let(("north", "east", "south", "west")[direction], selected, scan_body)
    for turn_index in reversed(range(4)):
        source = bot if turn_index == 0 else var(f"rot{turn_index}")
        scan_body = let(f"rot{turn_index + 1}", call("turn", source), scan_body)
        scan_body = let(("first", "second", "third", "fourth")[turn_index], call("probe", source), scan_body)
    add("scan", "combinator", scan_body, ("turn", "probe", "bot"), ("turn", "probe"))
    add("scan_default", "operation", call("scan", lit(kernel.FnRef("turn_right")),
        lit(kernel.FnRef("sense")), bot), ("bot",))

    origin = var("origin")
    add("Known", "object", None, ())
    add("make_known", "operation", call("Known.known", origin,
        call("assoc_put", call("empty"), origin, lit(".")), call("empty")), ("origin",), output="Known")

    merged = call("Known.known", field(known_map, 0),
                    call("ordered", var("tiles4"), lit(1), lit(0)),
                    iff(call("contains", field(known_map, 2), var("scan_pos")),
                        field(known_map, 2), call("ordered", call("push", field(known_map, 2),
                            var("scan_pos")), lit(1), lit(0))))
    for direction in reversed(range(4)):
        neighbor = adjacent(var("scan_pos"), direction)
        label = call("at", field(scan, 2), lit(direction))
        old = var(f"old_{direction}")
        previous = var(f"tiles{direction}")
        merged = let(f"neighbor_{direction}", neighbor,
                     let(f"label_{direction}", label,
                         let(f"old_{direction}", call("assoc_get", previous,
                                                      var(f"neighbor_{direction}"), lit("?")),
                             let(f"tiles{direction + 1}",
                                 iff(call("eq", old, lit("?")),
                                     call("assoc_put", previous, var(f"neighbor_{direction}"),
                                          var(f"label_{direction}")),
                                     iff(call("eq", old, var(f"label_{direction}")), previous,
                                         fail("contradictory_scan"))), merged))))
    merge_body = let("scan_pos", pos(field(scan, 0), field(scan, 1)),
        iff(call("eq", tile(known_map, var("scan_pos")), lit(".")),
            let("tiles0", field(known_map, 1), merged),
            fail("unreachable_scan")))
    add("merge_scan", "operation", merge_body, ("known_map", "scan"), output="Known")

    rem = var("rem")
    frontier_body = n.Rec("frontier_loop", ("rem", "found"),
        iff(zero(call("length", rem)), call("ordered", var("found"), lit(1), lit(0)),
            let("entry", call("at", rem, lit(0)),
                let("place", field(var("entry"), 0),
                    call("frontier_loop", call("tail", rem),
                        iff(call("eq", field(var("entry"), 1), lit(".")),
                            iff(call("contains", field(known_map, 2), var("place")), var("found"),
                                call("push", var("found"), var("place"))), var("found")))))),
        (field(known_map, 1), call("empty")), call("length", rem))
    add("frontier", "observation", frontier_body, ("known_map",))

    queue, visited = var("queue"), var("visited")
    steps = record("Pair", "pair", call("tail", queue), visited)
    for direction in range(4):
        place_next = adjacent(var("place"), direction)
        state = var(f"state_{direction}")
        candidate = var(f"candidate_{direction}")
        steps = let(f"state_{direction}", steps,
            let(f"candidate_{direction}", place_next,
                iff(call("eq", tile(known_map, candidate), lit(".")),
                    iff(call("contains", field(state, 1), candidate), state,
                        record("Pair", "pair",
                               call("push", field(state, 0), record("Pair", "pair", candidate,
                                   call("push", var("path"), candidate))),
                               call("push", field(state, 1), candidate))), state)))
    expanded = let("entry", call("at", queue, lit(0)),
        let("place", field(var("entry"), 0),
        let("path", field(var("entry"), 1),
        iff(call("eq", var("place"), var("target")), var("path"),
            let("state", steps,
                call("bfs_loop", field(var("state"), 0), field(var("state"), 1)))))))
    bfs = n.Rec("bfs_loop", ("queue", "visited"),
        iff(zero(call("length", queue)), fail("no_route"), expanded),
        (items(record("Pair", "pair", var("source"), call("empty"))), items(var("source"))),
        "fuel")
    route_body = iff(call("eq", tile(known_map, var("source")), lit(".")),
        iff(call("eq", tile(known_map, var("target")), lit(".")), bfs,
            fail("unknown_or_blocked")), fail("unknown_or_blocked"))
    add("route_known", "operation", route_body, ("known_map", "source", "target"), output="List")

    next_pos = var("next_pos")
    position = var("position")
    direction_test = None
    for direction in reversed(range(4)):
        desired = adjacent(position, direction)
        direction_test = iff(call("eq", next_pos, desired), lit(hosts.LETTERS[direction]),
                             direction_test if direction_test is not None else fail("nonadjacent_route"))
    turn = call("turn_right", var("facing_bot"))
    for direction in reversed(range(4)):
        turning_left = hosts.LETTERS[(direction - 1) % 4]
        turn = iff(call("eq", var("orientation"), lit(hosts.LETTERS[direction])),
                   iff(call("eq", var("desired"), lit(turning_left)),
                       call("turn_left", var("facing_bot")), turn), turn)
    face_body = let("orientation", field(call("pose", var("facing_bot")), 2),
        iff(call("eq", var("orientation"), var("desired")), var("facing_bot"),
            iff(zero(var("turns_left")), fail("nonadjacent_route"),
                call("face_loop", turn, call("sub", var("turns_left"), lit(1))))))
    facing = n.Rec("face_loop", ("facing_bot", "turns_left"), face_body,
                   (bot, lit(4)), var("turns_left"))
    follow_body = n.Rec("follow_loop", ("bot", "path"),
        iff(zero(call("length", var("path"))), bot,
            let("next_pos", call("at", var("path"), lit(0)),
                let("position", current(bot),
                    let("desired", direction_test,
                        call("follow_loop", call("step", facing), call("tail", var("path"))))))),
        (bot, var("path")), call("length", var("path")))
    add("follow", "combinator", follow_body, ("step", "bot", "path"), ("step",))

    select_body = n.Rec("select_loop", ("remaining", "best", "best_length"),
        iff(zero(call("length", var("remaining"))), var("best"),
            let("candidate", call("at", var("remaining"), lit(0)),
                let("distance", call("length", call("route", known_map, position, var("candidate"))),
                    call("select_loop", call("tail", var("remaining")),
                        iff(call("lt", var("distance"), var("best_length")), var("candidate"), var("best")),
                        iff(call("lt", var("distance"), var("best_length")), var("distance"), var("best_length")))))),
        (var("remaining"), var("best"), var("best_length")), call("length", var("remaining")))
    explore_body = n.Rec("explore_loop", ("bot", "known_map", "scans"),
        let("remaining", call("frontier", known_map),
            iff(zero(call("length", var("remaining"))),
                call("survey", bot, known_map, var("scans")),
                iff(call("eq", var("scans"), lit(120)), fail("scan_bound_exceeded"),
                    let("position", current(bot),
                        let("best", call("at", var("remaining"), lit(0)),
                            let("best_length", call("length", call("route", known_map, var("position"), var("best"))),
                                let("target", select_body,
                                    let("path", call("route", known_map, var("position"), var("target")),
                                        let("moved", call("follow", var("step"), bot, var("path")),
                                            let("sensed", call("scan_action", var("moved")),
                                                call("explore_loop", field(var("sensed"), 0),
                                                     call("merge_scan", known_map, field(var("sensed"), 1)),
                                                     call("add", var("scans"), lit(1))))))))))))),
        (bot, call("make_known", current(bot)), lit(0)), call("sub", lit(121), var("scans")))
    add("explore", "combinator", explore_body,
        ("scan_action", "step", "route", "bot"), ("scan_action", "step", "route"))

    survey = var("survey")
    add("Atlas", "object", None, ())
    atlas_body = iff(zero(call("length", call("frontier", field(survey, 1)))),
        iff(call("eq", call("length", field(field(survey, 1), 2)), field(survey, 2)),
            call("Atlas.atlas", survey), fail("incomplete")), fail("incomplete"))
    add("make_atlas", "operation", atlas_body, ("survey",), output="Atlas")
    return tuple(result)


def example_inputs():
    bot = hosts.start(hosts.maze("M1"))
    for direction in range(4):
        hosts.front_wall(hosts.mint_bot(bot.fields[0], 1, 1, direction, 0, 0))
    position = Card("Pos", "pos", (1, 1))
    scan = Card("Scan", "scan", (1, 1, Card("List", "items", ("#", ".", ".", "#"))))
    known_map = Card("Known", "known", (position,
        Card("List", "items", (Card("Pair", "pair", (position, ".")),)), Card("List", "items")))
    scan_args = (kernel.FnRef("turn_right"), kernel.FnRef("sense"), bot)
    explored = (kernel.FnRef("scan_default"), kernel.FnRef("safe_step"), kernel.FnRef("route_known"), bot)
    return {
        "front_clear": (bot,), "safe_step": (hosts.start(hosts.maze("M2")),),
        "Scan": (1, 1, Card("List", "items", ("#", ".", ".", "#"))),
        "sense": (hosts.start(hosts.maze("M3")),),
        "scan": scan_args, "make_known": (position,),
        "scan_default": (bot,),
        "Known": (position, known_map.fields[1], known_map.fields[2]),
        "merge_scan": (known_map, scan), "frontier": (known_map,),
        "route_known": (known_map, position, position),
        "follow": (kernel.FnRef("safe_step"), bot, Card("List", "items", (Card("Pos", "pos", (2, 1)),))),
        "explore": explored,
        "Atlas": (Card("Survey", "survey", (bot, known_map, 0)),),
        "make_atlas": (Card("Survey", "survey", (bot,
            Card("Known", "known", (position, known_map.fields[1], Card("List", "items", (position,)))), 1)),),
    }


@lru_cache(maxsize=1)
def evidence_bots():
    ref = reference()
    poses = []
    for maze_id in ("M1", "M2", "M3"):
        for y, row in enumerate(hosts.MAPS[maze_id]):
            for x, tile_label in enumerate(row):
                if tile_label == ".":
                    for direction in range(4):
                        poses.append(hosts.mint_bot(hosts.maze(maze_id), x, y,
                                                    direction, 0, 0))
    for mask in range(128):
        if mask.bit_count() > 3:
            continue
        name = f"E{mask:03d}"
        cells = ["."] + ["." if mask & (1 << index) else "#" for index in range(7)]
        rows = ("############", "#" + "".join(cells[:4]) + "#######",
                "#" + "".join(cells[4:]) + "#######") + ("############",) * 7
        hosts.MAPS[name] = rows
        ref.MAPS[name] = rows
    return tuple(poses)


def evidence_domain(lib, name, samples):
    poses = evidence_bots()
    if name == "front_clear":
        water_facing = hosts.mint_bot(hosts.maze("M1"), 2, 5, 2, 0, 0)
        return tuple((bot,) for bot in (*poses[:51], water_facing))
    if name in ("safe_step", "sense", "scan_default"):
        return tuple((bot,) for bot in poses[:52])
    if name == "Scan":
        selected = tuple(bot for bot in poses if bot.fields[3] == 0 and bot.fields[0].fields[0] == "M1")[:52]
        for bot in selected:
            for direction in range(4):
                hosts.front_wall(hosts.mint_bot(bot.fields[0], bot.fields[1], bot.fields[2], direction, 0, 0))
        return tuple((bot.fields[1], bot.fields[2], Card("List", "items", tuple(
            hosts.terrain(bot, bot.fields[1] + dx, bot.fields[2] + dy) for dx, dy in hosts.DIRS)))
            for bot in selected)
    if name == "scan":
        return tuple((kernel.FnRef("turn_right" if index % 2 else "turn_left"),
                      kernel.FnRef("sense"), bot) for index, bot in enumerate(poses[:52]))
    if name in ("Known", "make_known"):
        positions = tuple(Card("Pos", "pos", (bot.fields[1], bot.fields[2]))
                          for bot in poses if bot.fields[3] == 0 and bot.fields[0].fields[0] == "M1")[:52]
        if name == "make_known":
            return tuple((position,) for position in positions)
        return tuple((position, Card("List", "items", (Card("Pair", "pair", (position, ".")),)),
                      Card("List", "items")) for position in positions)
    if name in ("merge_scan", "frontier", "route_known", "follow"):
        result = []
        selected = (tuple(bot for bot in poses if bot.fields[3] == 0 and
                          bot.fields[0].fields[0] == "M1")[:52]
                    if name != "follow" else tuple(bot for bot in poses if
                                                      isinstance(hosts.forward(bot), Card))[:52])
        for bot in selected:
            origin = Card("Pos", "pos", bot.fields[1:3])
            if name == "follow":
                forward = hosts.forward(bot)
                path = (Card("Pos", "pos", forward.fields[1:3]),) if isinstance(forward, Card) else ()
                result.append((kernel.FnRef("safe_step" if len(result) % 2 else "forward"), bot,
                               Card("List", "items", path)))
                continue
            known = lib.run("make_known", (origin,)).outcome.value
            scanned = lib.run("scan", (kernel.FnRef("turn_right"), kernel.FnRef("sense"), bot)).outcome.value.fields[1]
            if name == "merge_scan":
                result.append((known, scanned))
            else:
                merged = lib.run("merge_scan", (known, scanned)).outcome.value
                if name == "frontier":
                    result.append((merged,))
                else:
                    neighbors = [entry.fields[0] for entry in merged.fields[1].fields
                                 if entry.fields[1] == "." and entry.fields[0] != origin]
                    result.append((merged, origin, neighbors[0] if neighbors else origin))
        return tuple(result)
    if name in ("explore", "Atlas", "make_atlas"):
        result = []
        for maze_id in list(hosts.MAPS):
            if not maze_id.startswith("E"):
                continue
            bot = hosts.start(hosts.maze(maze_id))
            if name == "explore":
                result.append((kernel.FnRef("scan_default"),
                               kernel.FnRef("safe_step" if len(result) % 2 else "forward"),
                               kernel.FnRef("route_known"), bot))
            else:
                survey = lib.run("explore", (kernel.FnRef("scan_default"), kernel.FnRef("safe_step"),
                                             kernel.FnRef("route_known"), bot), fuel=2_000_000).outcome.value
                result.append((survey,))
        return tuple(result)
    raise KeyError(name)


def build_library():
    lib = new_library()
    samples = example_inputs()
    completed_sample = None
    for defn in definitions():
        if defn.name in ("Atlas", "make_atlas") and completed_sample is None:
            tiny_bot = hosts.start(hosts.maze("E000"))
            completed_sample = lib.run("explore", (kernel.FnRef("scan_default"),
                kernel.FnRef("safe_step"), kernel.FnRef("route_known"), tiny_bot),
                fuel=2_000_000).outcome.value
        if defn.name in ("Atlas", "make_atlas"):
            samples[defn.name] = (completed_sample,)
        lib.write(defn)
        lib.check(defn.name)
        lib.make_callable(defn.name, (samples[defn.name],))
        domain = evidence_domain(lib, defn.name, samples)
        scope_by_name = {
            "front_clear": "52 reachable M1 robot poses measured through granted front probes",
            "safe_step": "52 reachable M1 robot poses",
            "sense": "52 reachable M1 robot poses",
            "scan_default": "52 reachable M1 robot poses with right turn and sense",
            "Scan": "52 M1 coordinates with four measured faces",
            "scan": "52 reachable M1 robot poses with left/right turn and sense slots",
            "Known": "52 M1 origins with a single known tile and no scanned cells",
            "make_known": "52 M1 origins",
            "merge_scan": "52 M1 known maps and scans of reachable poses",
            "frontier": "52 M1 known maps after merging one reachable scan",
            "route_known": "52 M1 known maps, origins and reachable neighbor targets",
            "follow": "52 M1 poses with a legal one-step path and forward/safe_step slots",
            "explore": "64 registered E000-E112 masks with at most three optional free cells; scan_default, forward/safe_step and route_known slots; 120-scan bound",
            "Atlas": "64 surveys from registered E000-E112 masks with scan_default, safe_step and route_known slots",
            "make_atlas": "64 surveys from registered E000-E112 masks with scan_default, safe_step and route_known slots",
        }
        description = scope_by_name[defn.name]
        request = VerifyRequest("bounded", domain,
                                {"domain": description, "size": len(domain), "bound": 120},
                                reference=lambda *args, name=defn.name: reference_outcome(name, *args))
        lib.verify(defn.name, request)
        lib.account(defn.name)
        lib.promote(defn.name, Contract(f"Verified on {request.scope['domain']}"))
    count_template = Definition("Count", "template", "invented", 1, (),
        TemplateSpec("Count", (("probe", "str"),), "observation", {
            "reads": ["$probe"], "body": n.to_json(n.Let("_zero", n.Call("add", (n.Lit(0), n.Lit(0))), n.Var("memory"))),
            "memory": {"init": n.to_json(n.Lit(0)), "step": n.to_json(n.Call("add", (
                n.Var("memory"), n.Case(((n.Test(n.Var("$probe")), n.Lit(1)),), n.Lit(0)))))},
            "definition_body": n.to_json(n.Let("_zero", n.Call("add", (n.Lit(0), n.Lit(0))), n.Var("memory")))},
            extra={"family": [{"probe": "front_wall"}, {"probe": "front_water"}]}),
        n.Lit(0))
    lib.write(count_template)
    history = tuple((bot,) for bot in evidence_bots()[:4])
    for probe in ("front_wall", "front_water"):
        instance = templates.instantiate(lib.get("Count"), {"probe": probe},
                                         "count_" + probe, lib=lib)
        body = n.Let("_template_origin", n.Lit(kernel.FnRef("Count")), n.Var("memory"))
        memory = {"init": n.Lit(0), "step": n.Call("add", (
            n.Var("memory"), n.Case(((n.Test(n.Call(probe, (n.Var("s"),))), n.Lit(1)),), n.Lit(0))))}
        instance = replace(instance, body=body,
                           spec=replace(instance.spec, body=body, memory=memory),
                           depends_on=("Count", probe, "add"))
        lib.write(instance)
        lib.check(instance.name)
        lib.make_callable(instance.name, history)
        lib.verify(instance.name, VerifyRequest("bounded", history,
            {"domain": f"four reachable M1 poses with {probe} probe history", "size": len(history)},
            reference=lambda state, probe=probe: sum(
                (reference().front_wall(to_reference(bot)) if probe == "front_wall"
                 else reference().front_water(to_reference(bot)))
                for bot in (row[0] for row in history)
                if (bot.fields[3] <= state.fields[3])),
            extra={"states": (tuple(row[0] for row in history),)}))
        lib.account(instance.name)
        lib.promote(instance.name, Contract(f"Four reachable M1 poses with {probe} probe history"))
    return lib
