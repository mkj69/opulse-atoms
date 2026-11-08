"""Short melodies with pitch, duration, and event-list probes."""

from itertools import product

from opulse.atoms.values import Card
from opulse.gen_v2.worlds._catalogue import catalogue
from opulse.gen_v2.worlds._common import BOOL, world_tags
from opulse.worlds_v2.melody import hosts, world

TAGS = world_tags("melody", world.decl())


def gen_world():
    notes = list(product(range(60, 67), (1, 2)))
    melodies = [hosts.melody(notes[index], notes[(index + offset) % len(notes)])
                 for index in range(12) for offset in (1, 2, 4)]
    events = [Card("List", "items", melody.fields) for melody in melodies]
    scores = []
    for source in melodies:
        first, second = source.fields
        motif = Card("Motif", "val", (((0, first[1]), (second[0] - first[0], second[1])),))
        scores.append(Card("Score", "val", ((source, (motif,)),)))
    result = catalogue("melody", world,
                     {"int": tuple(range(-2, 15)) + tuple(range(60, 73)), "str": ("up", "level", "down"),
                      "bool": BOOL, "Event": notes, "Melody": melodies,
                      "List": [Card("List", "items", ()), *events],
                      "Nat": tuple(range(9)),
                      "public": [*melodies[:16], *scores[:16]]},
                     truth_states=[*melodies[:24], *scores[:24]])
    result.sorts["public"].values = tuple(value for pair in zip(melodies[:16], scores[:16])
                                           for value in pair)
    return result
