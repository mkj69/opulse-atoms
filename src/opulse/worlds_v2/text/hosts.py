"""Only layer-zero text, numeric, and generic structural primitives."""

from opulse.atoms.values import Bottom, Card, boolean


def text_valid(value):
    return type(value) is str and len(value) <= 64 and set(value) <= {"a", "b", " "}


def concat(left, right):
    if not text_valid(left) or not text_valid(right) or len(left) + len(right) > 64:
        return Bottom("text_domain_or_size")
    return left + right


def slice_text(text, start, end):
    if not text_valid(text) or not all(type(item) is int for item in (start, end)) or not 0 <= start <= end <= len(text):
        return Bottom("span")
    return text[start:end]


def add(left, right):
    return left + right if all(type(item) is int and item >= 0 for item in (left, right)) else Bottom("nat")


def sub_nat(left, right):
    return left - right if all(type(item) is int for item in (left, right)) and 0 <= right <= left else Bottom("nat_subtraction")


def length(text):
    return len(text) if text_valid(text) else Bottom("text_domain_or_size")


def chars(text):
    return sequence(*(Card("Pair", "pair", (index, char)) for index, char in enumerate(text))) if text_valid(text) else Bottom("text_domain_or_size")


def sequence(*items):
    return Card("List", "list", items)


def seq_empty():
    return sequence()


def seq_is_empty(value):
    return boolean(not value.fields) if is_sequence(value) else Bottom("list")


def seq_head(value):
    return value.fields[0] if is_sequence(value) and value.fields else Bottom("empty")


def seq_tail(value):
    return sequence(*value.fields[1:]) if is_sequence(value) and value.fields else Bottom("empty")


def seq_cons(head, tail):
    return sequence(head, *tail.fields) if is_sequence(tail) else Bottom("list")


def seq_length(value):
    return len(value.fields) if is_sequence(value) else Bottom("list")


def seq_get(value, index):
    return value.fields[index] if is_sequence(value) and type(index) is int and 0 <= index < len(value.fields) else Bottom("index")


def seq_set(value, index, item):
    if not is_sequence(value) or type(index) is not int or not 0 <= index < len(value.fields):
        return Bottom("index")
    fields = list(value.fields)
    fields[index] = item
    return sequence(*fields)


def seq_append(value, item):
    return sequence(*value.fields, item) if is_sequence(value) else Bottom("list")


def seq_repeat(value, count):
    return sequence(*(value for _ in range(count))) if type(count) is int and 0 <= count <= 65 else Bottom("size")


def seq_sort(value):
    return sequence(*sorted(value.fields, key=repr)) if is_sequence(value) else Bottom("list")


def seq_reverse(value):
    return sequence(*reversed(value.fields)) if is_sequence(value) else Bottom("list")


def seq_merge(left, right):
    return sequence(*left.fields, *right.fields) if is_sequence(left) and is_sequence(right) else Bottom("list")


def seq_valid(value):
    return boolean(isinstance(value, Card) and value.sort == "List" and value.tag == "list")


def is_sequence(value):
    return isinstance(value, Card) and value.sort == "List" and value.tag == "list"


def pair(left, right):
    return Card("Pair", "pair", (left, right))


def first(value):
    return value.fields[0] if isinstance(value, Card) and value.sort == "Pair" and value.tag == "pair" and len(value.fields) == 2 else Bottom("pair")


def second(value):
    return value.fields[1] if isinstance(value, Card) and value.sort == "Pair" and value.tag == "pair" and len(value.fields) == 2 else Bottom("pair")


def span(start, end, item, cost):
    return Card("Span", "span", (start, end, item, cost)) if all(type(number) is int and number >= 0 for number in (start, end, cost)) and start < end else Bottom("span")


def span_start(value):
    return value.fields[0] if isinstance(value, Card) and value.sort == "Span" and value.tag == "span" else Bottom("span")


def span_end(value):
    return value.fields[1] if isinstance(value, Card) and value.sort == "Span" and value.tag == "span" else Bottom("span")


def span_word(value):
    return value.fields[2] if isinstance(value, Card) and value.sort == "Span" and value.tag == "span" else Bottom("span")


def span_cost(value):
    return value.fields[3] if isinstance(value, Card) and value.sort == "Span" and value.tag == "span" else Bottom("span")


def equal(left, right):
    return boolean(left == right)


def less(left, right):
    return boolean(type(left) is type(right) and left < right)


def le(left, right):
    return boolean(type(left) is type(right) and left <= right)


def not_equal(left, right):
    return boolean(left != right)


def is_nat(value):
    return boolean(type(value) is int and value >= 0)


def is_text(value):
    return boolean(text_valid(value))


def card_is(value, sort, tag):
    return boolean(isinstance(value, Card) and value.sort == sort and value.tag == tag)


def identity(value):
    return value
