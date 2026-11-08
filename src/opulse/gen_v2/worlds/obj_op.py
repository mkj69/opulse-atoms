"""Finite schedule values for object and operation invention."""

from dataclasses import replace

from opulse.gen_v2.worlds._common import BOOL, build, world_tags
from opulse.worlds_v2.obj_op import hosts, world

TAGS = world_tags("obj_op", world.decl())


def gen_world():
    cycles = [hosts.cycle_raw(index, period) for index in range(4) for period in (2, 3)]
    plans = [hosts.plan_raw((cycle,)) for cycle in cycles]
    windows = [hosts.window_raw(plan, 0, 10, None) for plan in plans]
    bands = [hosts.band(index, index + 1) for index in range(4)]
    blackouts = [hosts.blackout_raw(window, (bands[0],)) for window in windows]
    declaration = world.decl()
    observation = dict(declaration.observation)
    observation["probes"] = [dict(probe, reads="Band") if probe["name"] == "range"
                             else probe for probe in observation["probes"]]
    declaration = replace(declaration, observation=observation)
    return build("obj_op", declaration, world.atoms(),
                 {"int": tuple(range(-3, 13)), "bool": BOOL,
                  "Int": tuple(range(-3, 13)), "Bool": BOOL,
                  "Text": ("", "Cycle", "Plan", "Window", "Blackout"),
                  "List": ((), (0,), (1,), (0, 1), tuple(cycles[:2])),
                  "Band": bands, "Outcome": (0, 1),
                  "CycleRaw": cycles, "PlanRaw": plans,
                  "WindowRaw": windows, "BlackoutRaw": blackouts,
                  "unknown": (0, 1, None, (), *cycles[:2], *plans[:2],
                              *windows[:2], *blackouts[:2])},
                 truth_states=tuple(range(24)), max_steps=1200)
