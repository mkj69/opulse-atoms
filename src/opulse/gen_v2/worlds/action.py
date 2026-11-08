"""Generator probes for the sealed twelve-by-ten maze robot."""

from itertools import product

from opulse.atoms.values import Card, truth
from opulse.gen_v2.worlds._common import BOOL, build, world_tags
from opulse.worlds_v2.action import hosts, world

TAGS = world_tags("action", world.decl())


def gen_world():
    mazes = [hosts.maze(name) for name in hosts.MAPS]
    states = [hosts.mint_bot(maze, x, y, direction, 0, 0)
              for maze in mazes for x, y, direction in product(range(1, 11), range(1, 9), range(4))
              if hosts.MAPS[maze.fields[0]][y][x] == "."]
    wall_states = [state for state in states if truth(hosts.front_wall(state))]
    water_states = [state for state in states if truth(hosts.front_water(state))]
    clear_states = [state for state in states if not truth(hosts.front_wall(state))
                    and not truth(hosts.front_water(state))]
    samples = [hosts.mint_bot(*state.fields[:4], index % 5, (index // 2) % 5)
               for index in range(32) for state in
               (wall_states[index % len(wall_states)], water_states[index % len(water_states)],
                clear_states[index % len(clear_states)])]
    poses = [hosts.pose(state) for state in samples]
    scans = []
    for pose, state in zip(poses[:8], samples[:8]):
        faces = []
        for direction in range(4):
            facing = hosts.mint_bot(state.fields[0], pose.fields[0], pose.fields[1],
                                    direction, 0, 0)
            hosts.front_wall(facing)
            faces.append(hosts.terrain(facing, *hosts.ahead(facing)))
        scans.append(Card("Scan", "scan", (pose.fields[0], pose.fields[1],
                                           Card("List", "items", tuple(faces)))))
    known = [Card("Known", "known", (
             Card("Pos", "pos", pose.fields[:2]),
             Card("List", "items", (Card("Pair", "pair", (
                 Card("Pos", "pos", pose.fields[:2]), ".")),)),
             Card("List", "items", (Card("Pos", "pos", pose.fields[:2]),))))
             for pose in poses[:8]]
    surveys = []
    for index, state in enumerate(samples[:8]):
        fields = (state, known[index], index, index)
        surveys.append(Card("Survey", "survey", (*fields, hosts.seal("survey", fields))))
    return build("action", world.decl(), world.atoms(),
                 {"int": tuple(range(13)), "str": (*hosts.MAPS, *hosts.LETTERS, "#", ".", "~"),
                  "bool": BOOL, "Maze": mazes, "Bot": samples[:32], "Pose": poses,
                  "Pos": [Card("Pos", "pos", (x, y)) for x, y in ((1, 1), (2, 1))],
                  "Pair": [Card("Pair", "pair", (0, 0)), Card("Pair", "pair", (1, 0))],
                  "List": [Card("List", "items", ()), Card("List", "items", (1,))],
                  "unknown": [*scans, *known, 0, 1],
                  "Survey": surveys, "Stats": [hosts.stats(survey) for survey in surveys]},
                 truth_states=samples, finite_sorts=("Maze",), max_scope=150)
