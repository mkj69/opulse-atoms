"""Leap-year and weekday probes over bounded valid dates."""

from opulse.gen_v2.worlds._catalogue import catalogue
from opulse.gen_v2.worlds._common import BOOL, world_tags
from opulse.worlds_v2.calendar import hosts, world

TAGS = world_tags("calendar", world.decl())


def gen_world():
    dates = [hosts.to_card(year, month, day)
             for year in (2000, 2001, 2004, 2024, 2099)
             for month in (1, 2, 3, 12)
             for day in (1, 2, 27, 28, 29)
             if day <= hosts.month_length(year, month)]
    return catalogue("calendar", world,
                     {"int": tuple(range(-2, 10)) + (28, 29, 30, 31, 2000, 2001, 2004, 2024, 2099),
                      "bool": BOOL, "str": ("invalid", "range"), "date": dates,
                      "pair": [hosts.pair(dates[0], dates[1]), hosts.pair(dates[1], dates[2])],
                      "maybe_date": [hosts.some(dates[0]), hosts.some(dates[1])]},
                     truth_states=dates, max_steps=1200)
