"""Short public strings, words, and indexed characters."""

from itertools import product

from opulse.atoms.values import Card
from opulse.gen_v2.worlds._catalogue import catalogue
from opulse.gen_v2.worlds._common import BOOL, world_tags
from opulse.worlds_v2.text import hosts, world

TAGS = world_tags("text", world.decl())


def gen_world():
    words = ["", "a", "b", "aa", "ab", "ba", "bb", "aba", "aab", "bab"]
    texts = [*words, *(left + " " + right for left, right in product(words[1:5], repeat=2))]
    characters = [Card("indexed_char", "at", (index, char))
                  for index, char in product(range(4), ("a", "b", " "))]
    sequences = [hosts.sequence(), *(hosts.sequence(text) for text in texts),
                 hosts.sequence("a", "b")]
    return catalogue("text", world,
                     {"int": tuple(range(10)), "str": texts, "bool": BOOL,
                      "any": (*characters, *words), "text": texts,
                      "indexed_char": characters, "List": sequences,
                      "Text": texts, "Char": ("a", "b", " "),
                      "Pair": [hosts.pair(0, 1), hosts.pair(1, 2)],
                      "Span": [hosts.span(0, 1, "a", 0), hosts.span(1, 2, "b", 1)]},
                     truth_states=texts, measures={"List": [("seq_tail", "seq_length")]},
                     bases={"List": ["seq_is_empty"]})
