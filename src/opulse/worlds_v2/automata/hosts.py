"""Layer-zero DFA step/probe and generic finite structural primitives."""

from functools import lru_cache

from opulse.atoms.values import Bottom, Card, boolean


def to_card(count, start, finals, rows):
    machine = Card("automaton", "dfa", (count, start, Card("states", "list", tuple(finals)),
                                         Card("rows", "list", tuple(Card("row", "pair", tuple(row)) for row in rows))))
    if not machine_valid(machine):
        raise ValueError("invalid")
    return machine


def from_card(machine):
    if not machine_valid(machine):
        raise ValueError("invalid")
    count, start, finals, rows = machine.fields
    return count, start, finals.fields, tuple(row.fields for row in rows.fields)


def machine_valid(machine):
    if not isinstance(machine, Card):
        return False
    try:
        return _machine_valid_cached(machine)
    except TypeError:
        return False


@lru_cache(maxsize=256)
def _machine_valid_cached(machine):
    if not isinstance(machine, Card) or (machine.sort, machine.tag) != ("automaton", "dfa") or len(machine.fields) != 4:
        return False
    count, start, finals, rows = machine.fields
    return (type(count) is int and 1 <= count <= 20000 and type(start) is int and 0 <= start < count
            and isinstance(finals, Card) and (finals.sort, finals.tag) == ("states", "list")
            and all(type(state) is int and 0 <= state < count for state in finals.fields)
            and tuple(sorted(set(finals.fields))) == finals.fields
            and isinstance(rows, Card) and (rows.sort, rows.tag) == ("rows", "list")
            and len(rows.fields) == count and all(
                isinstance(row, Card) and (row.sort, row.tag) == ("row", "pair")
                and len(row.fields) == 2 and all(type(state) is int and 0 <= state < count for state in row.fields)
                for row in rows.fields))


def word_valid(word):
    return isinstance(word, str) and all(char in "ab" for char in word)


def step(machine, state, char):
    if (not machine_valid(machine) or type(state) is not int or
            not 0 <= state < machine.fields[0] or type(char) is not str or char not in ("a", "b")):
        return Bottom("invalid")
    return machine.fields[3].fields[state].fields[0 if char == "a" else 1]


def accept(machine, word):
    if not machine_valid(machine) or not word_valid(word):
        return Bottom("invalid")
    state = machine.fields[1]
    for char in word:
        state = step(machine, state, char)
    return boolean(state in machine.fields[2].fields)


def count(machine):
    return machine.fields[0] if machine_valid(machine) else Bottom("invalid")


def start(machine):
    return machine.fields[1] if machine_valid(machine) else Bottom("invalid")


def final(machine, state):
    if not machine_valid(machine) or type(state) is not int or not 0 <= state < machine.fields[0]:
        return Bottom("invalid")
    return boolean(state in machine.fields[2].fields)


def make_machine(size, initial, accepted, transitions):
    if not (isinstance(accepted, Card) and (accepted.sort, accepted.tag) == ("states", "list")
            and isinstance(transitions, Card) and (transitions.sort, transitions.tag) == ("rows", "list")):
        return Bottom("invalid")
    machine = Card("automaton", "dfa", (size, initial, accepted, transitions))
    return machine if machine_valid(machine) else Bottom("invalid")


def make_row(left, right):
    return Card("row", "pair", (left, right)) if type(left) is type(right) is int else Bottom("invalid")


def char_head(word):
    return Bottom("invalid") if not word_valid(word) else word[0] if word else Bottom("empty")


def char_tail(word):
    return Bottom("invalid") if not word_valid(word) else word[1:] if word else Bottom("empty")


def word_length(word):
    return len(word) if word_valid(word) else Bottom("invalid")


def empty(sort):
    return Card(sort, "list", ()) if sort in ("states", "rows", "queue", "visited", "signatures") else Bottom("invalid")


def cons(value, sequence):
    if (not isinstance(sequence, Card) or sequence.tag != "list" or
            (sequence.sort in ("states", "visited") and type(value) is not int) or
            (sequence.sort == "queue" and type(value) is not int and
             not isinstance(value, Card))):
        return Bottom("invalid")
    return Card(sequence.sort, "list", (value, *sequence.fields))


def cons_row(value, sequence):
    if (not isinstance(sequence, Card) or (sequence.sort, sequence.tag) != ("rows", "list")
            or not isinstance(value, Card) or (value.sort, value.tag) != ("row", "pair")
            or len(value.fields) != 2 or any(type(state) is not int for state in value.fields)):
        return Bottom("invalid")
    return cons(value, sequence)


def head(sequence):
    if not isinstance(sequence, Card) or sequence.tag != "list":
        return Bottom("invalid")
    return sequence.fields[0] if sequence.fields else Bottom("empty")


def tail(sequence):
    if not isinstance(sequence, Card) or sequence.tag != "list":
        return Bottom("invalid")
    return Card(sequence.sort, "list", sequence.fields[1:]) if sequence.fields else Bottom("empty")


def length(sequence):
    return len(sequence.fields) if isinstance(sequence, Card) and sequence.tag == "list" else Bottom("invalid")


def contains(sequence, value):
    return boolean(value in sequence.fields) if isinstance(sequence, Card) and sequence.tag == "list" else Bottom("invalid")


def add(left, right):
    return left + right if type(left) is type(right) is int else Bottom("invalid")


def sub(left, right):
    return left - right if type(left) is type(right) is int else Bottom("invalid")


def mul(left, right):
    return left * right if type(left) is type(right) is int else Bottom("invalid")


def div(left, right):
    return left // right if type(left) is type(right) is int and right else Bottom("invalid")


def mod(left, right):
    return left % right if type(left) is type(right) is int and right else Bottom("invalid")


def less(left, right):
    return boolean(left < right) if type(left) is type(right) is int else Bottom("invalid")


def equal(left, right):
    return boolean(left == right)


def count_a(size):
    if type(size) is not int or not 1 <= size <= 20000:
        return Bottom("invalid")
    return Card("rows", "list", tuple(Card("row", "pair", ((state + 1) % size, state))
                                      for state in range(size)))


def count_b(size):
    if type(size) is not int or not 1 <= size <= 20000:
        return Bottom("invalid")
    return Card("rows", "list", tuple(Card("row", "pair", (state, (state + 1) % size))
                                      for state in range(size)))


def distinct_count(blocks):
    if not isinstance(blocks, Card) or blocks.tag != "list" or any(type(item) is not int for item in blocks.fields):
        return Bottom("invalid")
    return len(set(blocks.fields))


def at(sequence, index):
    if not isinstance(sequence, Card) or sequence.tag != "list" or type(index) is not int or not 0 <= index < len(sequence.fields):
        return Bottom("invalid")
    return sequence.fields[index]


def sorted_unique(sequence):
    if not isinstance(sequence, Card) or sequence.tag != "list":
        return Bottom("invalid")
    def key(value):
        if isinstance(value, Card):
            return (value.sort, value.tag, tuple(key(field) for field in value.fields))
        return (type(value).__name__, value)
    return Card(sequence.sort, "list", tuple(sorted(set(sequence.fields), key=key)))


def row_first(row):
    return row.fields[0] if isinstance(row, Card) and (row.sort, row.tag) == ("row", "pair") else Bottom("invalid")


def row_second(row):
    return row.fields[1] if isinstance(row, Card) and (row.sort, row.tag) == ("row", "pair") else Bottom("invalid")


def make_signature(current, on_a, on_b):
    if any(type(value) is not int for value in (current, on_a, on_b)):
        return Bottom("invalid")
    return Card("signature", "triple", (current, on_a, on_b))


def make_entry(state, word):
    return Card("entry", "pair", (state, word)) if type(state) is int and word_valid(word) else Bottom("invalid")


def entry_state(entry):
    return entry.fields[0] if isinstance(entry, Card) and (entry.sort, entry.tag) == ("entry", "pair") else Bottom("invalid")


def entry_word(entry):
    return entry.fields[1] if isinstance(entry, Card) and (entry.sort, entry.tag) == ("entry", "pair") else Bottom("invalid")


def make_frontier(queue, seen):
    return Card("frontier", "pair", (queue, seen)) if all(isinstance(item, Card) and item.tag == "list" for item in (queue, seen)) else Bottom("invalid")


def frontier_queue(frontier):
    return frontier.fields[0] if isinstance(frontier, Card) and (frontier.sort, frontier.tag) == ("frontier", "pair") else Bottom("invalid")


def frontier_seen(frontier):
    return frontier.fields[1] if isinstance(frontier, Card) and (frontier.sort, frontier.tag) == ("frontier", "pair") else Bottom("invalid")


def machine_valid_atom(machine):
    return boolean(machine_valid(machine))


def index_of(sequence, item):
    if not isinstance(sequence, Card) or sequence.tag != "list":
        return Bottom("invalid")
    try:
        return sequence.fields.index(item)
    except ValueError:
        return Bottom("missing")


def append(sequence, item):
    if not isinstance(sequence, Card) or sequence.tag != "list":
        return Bottom("invalid")
    return Card(sequence.sort, "list", (*sequence.fields, item))


def less_equal(left, right):
    return boolean(left <= right) if type(left) is type(right) is int else Bottom("invalid")


def join_word(word, char):
    return word + char if word_valid(word) and char in ("a", "b") else Bottom("invalid")


def examples():
    return {

        "ends_a": to_card(2, 0, (1,), ((1, 0), (1, 0))),
        "even_len": to_card(2, 0, (0,), ((1, 1), (0, 0))),
        "never_accept": to_card(1, 0, (), ((0, 0),)),
    }


def depth_examples():
    return {
        "mod7_a": to_card(7, 0, (0,), tuple(((state + 1) % 7, state) for state in range(7))),
        "mod5_a": to_card(5, 0, (0,), tuple(((state + 1) % 5, state) for state in range(5))),
        "mod35_a": to_card(35, 0, (0,), tuple(((state + 1) % 35, state) for state in range(35))),
        "mod5_b": to_card(5, 0, (0,), tuple((state, (state + 1) % 5) for state in range(5))),
        "no_bb": to_card(3, 0, (0, 1), ((0, 1), (0, 2), (2, 2))),
        "seen_b": to_card(2, 0, (1,), ((0, 1), (1, 1))),
        **examples(),
    }
