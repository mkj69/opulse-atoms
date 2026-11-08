"""Exact finite-alphabet automata world; run with ``python3 out/automata.py``.

States are dense integers, transitions are total, and the alphabet is (a,b).
Breadth-first traversal in alphabet order is both the canonical naming rule and
the shortest-then-lexicographic witness rule. None of the checks sample words.
"""

from collections import deque
from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path


ALPHABET = "ab"


@dataclass(frozen=True)
class DFA:
    transitions: tuple[tuple[int, int], ...]
    initial: int
    finals: frozenset[int]

    def __post_init__(self):
        size = len(self.transitions)
        assert size > 0 and 0 <= self.initial < size
        assert all(len(row) == 2 and all(0 <= target < size for target in row)
                   for row in self.transitions)
        assert all(0 <= state < size for state in self.finals)


def count_a(divisor):
    assert divisor > 0
    return tuple(((state + 1) % divisor, state) for state in range(divisor))


def count_b(divisor):
    assert divisor > 0
    return tuple((state, (state + 1) % divisor) for state in range(divisor))


mod7_a = DFA(count_a(7), 0, frozenset({0}))
mod5_a = DFA(count_a(5), 0, frozenset({0}))
mod35_a = DFA(count_a(35), 0, frozenset({0}))
mod5_b = DFA(count_b(5), 0, frozenset({0}))
seen_b = DFA(((0, 1), (1, 1)), 0, frozenset({1}))
no_bb = DFA(((0, 1), (0, 2), (2, 2)), 0, frozenset({0, 1}))
ends_a = DFA(((1, 0), (1, 0)), 0, frozenset({1}))
even_len = DFA(((1, 1), (0, 0)), 0, frozenset({0}))
never_accept = DFA(((0, 0),), 0, frozenset())


# Layer 0: operation, fold combinator, and observations.
def step(automaton, state, symbol):
    assert symbol in ALPHABET
    return automaton.transitions[state][ALPHABET.index(symbol)]


def fold(move, initial, word):
    state = initial
    for symbol in word:
        assert symbol in ALPHABET
        state = move(state, symbol)
    return state


def accept(automaton, word):
    return fold(lambda state, symbol: step(automaton, state, symbol),
                automaton.initial, word) in automaton.finals


def size(automaton):
    return len(automaton.transitions)


def distinct_count(blocks):
    return len(set(blocks))


# L1: a product object is a pair of machines, not yet a chosen final predicate.
@dataclass(frozen=True)
class Pair:
    left: DFA
    right: DFA

    @property
    def initial(self):
        return self.left.initial, self.right.initial

    @property
    def capacity(self):
        return size(self.left) * size(self.right)


# L2: a typed combinator; both slots consume exactly the same input symbol.
def sync(move_left, move_right, pair, states, symbol):
    return (move_left(pair.left, states[0], symbol),
            move_right(pair.right, states[1], symbol))


MODES = {
    "and": lambda left, right: left and right,
    "or": lambda left, right: left or right,
    "xor": lambda left, right: left != right,
    "left_not_right": lambda left, right: left and not right,
}


# L3: preserve all pairs, even if unreachable, until the explicit Trim layer.
def combine(left, right, mode):
    assert mode in MODES
    pair = Pair(left, right)
    width = size(right)
    transitions = []
    finals = set()
    for left_state in range(size(left)):
        for right_state in range(width):
            index = left_state * width + right_state
            if MODES[mode](left_state in left.finals, right_state in right.finals):
                finals.add(index)
            transitions.append(tuple(
                next_left * width + next_right
                for next_left, next_right in (
                    sync(step, step, pair, (left_state, right_state), symbol)
                    for symbol in ALPHABET
                )))
    return DFA(tuple(transitions), left.initial * width + right.initial,
               frozenset(finals))


def reachable(automaton):
    order = [automaton.initial]
    paths = {automaton.initial: ""}
    queue = deque(order)
    while queue:
        state = queue.popleft()
        for symbol in ALPHABET:
            target = step(automaton, state, symbol)
            if target not in paths:
                paths[target] = paths[state] + symbol
                order.append(target)
                queue.append(target)
    return order, paths


# L4: exhaustive reachability, including the empty word.
def empty(automaton):
    order, _ = reachable(automaton)
    return not any(state in automaton.finals for state in order)


# L5: keep precisely reachable states and rename them BFS/alphabet order.
def trim(automaton):
    order, _ = reachable(automaton)
    numbers = {old: new for new, old in enumerate(order)}
    return DFA(tuple(tuple(numbers[step(automaton, state, symbol)]
                           for symbol in ALPHABET) for state in order),
               0, frozenset(numbers[state] for state in order
                            if state in automaton.finals))


# L6: generic stable-refinement combinator and the plugged-in signature.
def block_signature(move, automaton, state, blocks):
    return (blocks[state],
            tuple(blocks[move(automaton, state, symbol)] for symbol in ALPHABET))


def refine(move, automaton):
    blocks = tuple(int(state in automaton.finals) for state in range(size(automaton)))
    while True:
        signatures = [block_signature(move, automaton, state, blocks)
                      for state in range(size(automaton))]
        ids = {key: index for index, key in enumerate(sorted(set(signatures)))}
        updated = tuple(ids[key] for key in signatures)
        if distinct_count(updated) == distinct_count(blocks):
            return updated
        assert distinct_count(updated) > distinct_count(blocks)
        blocks = updated


# L7: one quotient state per stable block, then canonically BFS-rename it.
@lru_cache(maxsize=64)
def minimize(automaton):
    cleaned = trim(automaton)
    blocks = refine(step, cleaned)
    representatives = {}
    for state, block in enumerate(blocks):
        representatives.setdefault(block, state)
    labels = sorted(representatives)
    number = {block: index for index, block in enumerate(labels)}
    quotient = DFA(tuple(tuple(number[blocks[step(cleaned, representatives[block], symbol)]]
                               for symbol in ALPHABET) for block in labels),
                   number[blocks[0]],
                   frozenset(number[block] for block in labels
                             if representatives[block] in cleaned.finals))
    return trim(quotient)


# L8: canonical minimized complete DFAs decide equality for ALL finite words.
def equivalent(left, right):
    return minimize(left) == minimize(right)


# L9: first accepting state of the XOR product is a shortest/lex witness.
def separate(left, right):
    if equivalent(left, right):
        return None
    difference = combine(left, right, "xor")
    order, paths = reachable(difference)
    return next(paths[state] for state in order if state in difference.finals)


# L10: inclusion is emptiness of the directional difference; same graph proof.
def included(left, right):
    if equivalent(left, right):
        return True
    return empty(combine(left, right, "left_not_right"))


def as_text(result):
    if isinstance(result, bool):
        return "true" if result else "false"
    if result is None:
        return "none"
    return str(result)


def tower_results():
    product = Pair(mod7_a, no_bb)
    large = combine(combine(mod7_a, mod5_a, "and"), no_bb, "and")
    target = combine(combine(mod7_a, no_bb, "and"),
                     combine(mod5_a, ends_a, "or"), "left_not_right")
    return [
        f"Pair<{size(product.left)},{size(product.right)}>",
        str(sync(step, step, product, (6, 0), "a")).replace(" ", ""),
        as_text(accept(combine(mod7_a, no_bb, "and"), "aaaaaaa")),
        as_text(empty(combine(mod7_a, never_accept, "and"))),
        as_text(size(trim(combine(mod7_a, no_bb, "and")))),
        as_text(distinct_count(refine(step,
                                      trim(combine(mod7_a, no_bb, "and"))))),
        as_text(size(minimize(combine(mod7_a, no_bb, "and")))),
        as_text(equivalent(combine(mod7_a, mod5_a, "and"), mod35_a)),
        as_text(separate(target, never_accept)),
        as_text(included(large, mod35_a)),
    ]


def challenge():
    return combine(combine(combine(mod7_a, mod5_b, "and"),
                           seen_b, "and"),
                   combine(no_bb, ends_a, "and"), "and")


def showcase_results():
    large = combine(combine(mod7_a, mod5_a, "and"), no_bb, "and")
    return [
        as_text(size(minimize(large))),
        as_text(separate(challenge(), never_accept)),
        as_text(equivalent(minimize(combine(mod7_a, mod5_a, "and")), mod35_a)),
    ]


def main():
    tower = tower_results()
    showcase = showcase_results()
    assert tower == ["Pair<7,3>", "(0,0)", "true", "true", "21",
                     "15", "15", "true", "aaaaaaab", "true"], tower
    assert showcase == ["71", "aabababababa", "true"], showcase
    assert size(combine(combine(mod7_a, mod5_a, "and"), no_bb, "and")) == 105
    assert size(trim(combine(combine(mod7_a, mod5_a, "and"), no_bb, "and"))) == 105
    assert not included(mod35_a,
                        combine(combine(mod7_a, mod5_a, "and"), no_bb, "and"))
    assert separate(mod35_a, mod35_a) is None
    assert separate(mod35_a, never_accept) == ""
    assert empty(combine(mod7_a, never_accept, "and"))
    card = json.loads(Path(__file__).with_suffix(".json").read_text(encoding="utf-8"))
    assert card["id"] == "automata"
    assert [item["value"] for item in card["tower"]] == tower
    assert [item["answer"] for item in card["showcase"]] == showcase
    print("OK")


if __name__ == "__main__":
    main()
