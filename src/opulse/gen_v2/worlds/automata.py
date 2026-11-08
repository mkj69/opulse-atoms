"""Finite total automata over two-letter words."""

from itertools import product

from opulse.atoms import kernel
from opulse.atoms.values import FALSE, TRUE, Card
from opulse.gen_v2.worlds._common import build, world_tags
from opulse.worlds_v2.automata import hosts, world

TAGS = world_tags("automata", world.decl())


def gen_world():
    machines = list(hosts.examples().values())
    machines += [hosts.to_card(size, 0, finals, ((0, 0),) * size)
                 for size in (3, 4) for finals in ((), (0,))]
    machines += [hosts.to_card(4, start, (start,), ((0, 0),) * 4)
                 for start in (1, 2, 3)]
    machines += [hosts.to_card(2, 0, finals, rows)
                 for rows in product(product(range(2), repeat=2), repeat=2)
                 for finals in ((), (0,), (1,), (0, 1))]
    rows = [Card("row", "pair", pair) for pair in product(range(2), repeat=2)]
    fold = world.new_library().get("fold_word")
    values = {"int": tuple(range(9)), "str": ("", "a", "b", "aa", "ab", "ba", "bb",
                                             "states", "rows", "queue", "visited"),
              "bool": (FALSE, TRUE), "word": ("", "a", "b", "aa", "ab", "ba", "bb",
                                               "aaa", "abab"),
              "row": rows, "automaton": machines,
              "signature": [hosts.make_signature(index, 0, 1) for index in range(4)],
              "entry": [hosts.make_entry(index, word) for index, word in
                        product((0, 1), ("", "a", "b"))],
              "states": [Card("states", "list", items) for items in ((), (0,), (1,), (0, 1))],
              "rows": [Card("rows", "list", items) for items in ((), (rows[0],), tuple(rows[:2]))],
              "queue": [Card("queue", "list", items) for items in
                        ((), (0,), (1,), (2,), (3,), (0, 1), (1, 2, 3), (0, 1, 2, 3))],
              "visited": [Card("visited", "list", items) for items in
                          ((), (0,), (1,), (0, 1), (0, 1, 2), (0, 1, 2, 3))]}
    values["frontier"] = [hosts.make_frontier(queue, visited) for queue, visited in
                          zip(values["queue"][:6], values["visited"])]
    result = build("automata", world.decl(), world.atoms(), values,
                   truth_states=machines[:24], probe_inputs={"accept": ("word",)},
                   extra_scope=(kernel.Defn("fold_word", fold.spec.params, fold.body,
                                            "combinator", 0),),
                   measures={"word": [("char_tail", "word_length")],
                             "queue": [("tail", "length")]})
    result.sorts["automaton"].values = tuple(machines[:32])
    return result
