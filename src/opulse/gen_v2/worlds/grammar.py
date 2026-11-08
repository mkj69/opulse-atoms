"""Small public-word grammars and bounded parse trees."""

from opulse.atoms.values import Card
from opulse.gen_v2.worlds._common import BOOL, build, world_tags
from opulse.worlds_v2.grammar import hosts, world

TAGS = world_tags("grammar", world.decl())


def gen_world():
    finished = [hosts.word(1), hosts.word(2), hosts.word(1, "+", 2)]
    tree_lists = [Card("List", "items", ()), Card("List", "items", (1,)),
                  Card("List", "items", (1, 2)), Card("List", "items", (1, 2, 3))]
    complete_drafts = [Card("Draft", "num", (index,)) for index in range(1, 10)]
    complete_drafts += [Card("Draft", "+", (left, right))
                        for left in complete_drafts[:6] for right in complete_drafts[:6]]
    return build("grammar", world.decl(), world.atoms(),
                 {"int": tuple(range(8)), "str": ("", "a", "aa", "aaa", "aaaa", "ss", "b"),
                  "bool": BOOL,
                  "Word": finished, "Draft": [hosts.HOLE, *complete_drafts],
                  "Rule": [Card("Rule", "num", (index,)) for index in range(1, 10)],
                  "List": tree_lists,
                  "Pair": [hosts.pair(1, 2), hosts.pair(2, 3)],
                  "Hist": [hosts.hist(items) for items in tree_lists],
                  "Witness": [hosts.witness(Card("List", "items", items))
                              for items in ((1, 2, 3), (2, 3, 4))]},
                 truth_states=complete_drafts[:32],
                 bases={"List": ["is_empty"]})
