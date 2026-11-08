"""Given finite grammar atoms and generic, counted data primitives."""

from functools import lru_cache, wraps

from opulse.atoms.values import Bottom, Card, boolean


def valid_card(value):
    """Check complete card shapes and refinements, not their Python identities."""
    try:
        return _valid_card_cached(value)
    except (TypeError, RecursionError):
        return _valid_card_uncached(value)


@lru_cache(maxsize=8192)
def _valid_card_cached(value):
    return _valid_card_uncached(value)


def _valid_card_uncached(value):
    if not isinstance(value, Card):
        return False
    try:
        if value.sort == "Word":
            return value.tag == "tokens" and word(*value.fields) == value
        if value.sort == "Draft":
            surface = _surface(value, True)
            return (_nodes(value) <= 40 and len(surface) <= 48 and
                    sum(type(token) is int for token in surface) <= 12 and
                    max((sum(token == "(" for token in surface[:index + 1]) -
                         sum(token == ")" for token in surface[:index + 1])
                         for index in range(len(surface))), default=0) <= 8)
        if value.sort == "Rule":
            return (value.tag == "num" and len(value.fields) == 1 and
                    type(value.fields[0]) is int and 1 <= value.fields[0] <= 9 or
                    value.tag in ("+", "*", "group") and not value.fields)
        if value.sort == "ExprTree":
            return (value.tag == "val" and len(value.fields) == 1 and
                    valid_card(value.fields[0]) and value.fields[0].sort == "Draft" and
                    isinstance(yield_probe(value.fields[0]), Card))
        if value.sort == "Ambiguity":
            if value.tag != "val" or len(value.fields) != 1 or not valid_card(value.fields[0]):
                return False
            witness_word, first, second = value.fields[0].fields
            if not (isinstance(witness_word, Card) and witness_word.sort == "Word" and
                    isinstance(first, Card) and first.sort == "ExprTree" and
                    isinstance(second, Card) and second.sort == "ExprTree"):
                return False
            ranked = _first_two(witness_word.fields)
            return len(ranked) == 2 and (first.fields[0], second.fields[0]) in (
                ranked, ranked[::-1])
        if value.sort == "Witness":
            return (value.tag == "triple" and len(value.fields) == 3 and
                    all(valid_card(item) if isinstance(item, Card) else type(item) in (int, str)
                        for item in value.fields))
        if value.sort == "Hist":
            return (value.tag == "entries" and all(isinstance(item, Card) and
                    item.sort == "Pair" and valid_card(item) for item in value.fields))
        if value.sort == "Pair":
            return value.tag == "pair" and len(value.fields) == 2 and all(
                valid_card(item) if isinstance(item, Card) else type(item) in (int, str)
                for item in value.fields)
        if value.sort == "List":
            return value.tag == "items" and all(
                valid_card(item) if isinstance(item, Card) else type(item) in (int, str)
                for item in value.fields)
        if value.sort == "bool":
            return value.tag in ("true", "false") and not value.fields
    except (ValueError, TypeError, IndexError, AttributeError, RecursionError):
        return False
    return False


@lru_cache(maxsize=8192)
def _first_two(tokens):
    if len(tokens) == 1 and type(tokens[0]) is int and 1 <= tokens[0] <= 9:
        return (Card("Draft", "num", (tokens[0],)),)
    if len(tokens) >= 2 and tokens[0] == "(" and tokens[-1] == ")":
        inner = tokens[1:-1]
        if word(*inner) == Card("Word", "tokens", inner):
            return tuple(Card("Draft", "group", (tree,)) for tree in _first_two(inner))
    depth = 0
    result = []
    for position, token in enumerate(tokens):
        if token == "(":
            depth += 1
        elif token == ")":
            depth -= 1
        elif token in ("+", "*") and depth == 0:
            for left in _first_two(tokens[:position]):
                for right in _first_two(tokens[position + 1:]):
                    result.append(Card("Draft", token, (left, right)))
                    if len(result) == 2:
                        return tuple(result)
    return tuple(result)


def word(*tokens):
    if len(tokens) > 48 or sum(type(token) is int for token in tokens) > 12:
        return Bottom("size")
    depth = 0
    for token in tokens:
        if token == "(":
            depth += 1
            if depth > 8:
                return Bottom("depth")
        elif token == ")":
            depth -= 1
            if depth < 0:
                return Bottom("parenthesis")
        elif token not in ("+", "*") and (type(token) is not int or not 1 <= token <= 9):
            return Bottom("token")
    return Card("Word", "tokens", tokens) if depth == 0 else Bottom("parenthesis")


HOLE = Card("Draft", "E")


def _surface(tree, partial=False):
    if not isinstance(tree, Card) or tree.sort != "Draft":
        raise ValueError("tree")
    if tree.tag == "E" and not tree.fields:
        if partial:
            return ("E",)
        raise ValueError("unfinished")
    if tree.tag == "num" and len(tree.fields) == 1 and type(tree.fields[0]) is int and 1 <= tree.fields[0] <= 9:
        return tree.fields
    if tree.tag == "group" and len(tree.fields) == 1:
        return ("(",) + _surface(tree.fields[0], partial) + (")",)
    if tree.tag in ("+", "*") and len(tree.fields) == 2:
        return _surface(tree.fields[0], partial) + (tree.tag,) + _surface(tree.fields[1], partial)
    raise ValueError("tree")


def _nodes(tree):
    return 0 if tree.tag == "E" else 1 + sum(_nodes(child) for child in tree.fields if isinstance(child, Card))


def expand(tree, path, rule):
    if not isinstance(path, Card) or path.sort != "List" or path.tag != "items":
        return Bottom("path")
    if not isinstance(rule, Card) or rule.sort != "Rule":
        return Bottom("rule")
    if rule.tag == "num" and len(rule.fields) == 1 and type(rule.fields[0]) is int and 1 <= rule.fields[0] <= 9:
        replacement = Card("Draft", "num", rule.fields)
    elif rule.tag in ("+", "*") and not rule.fields:
        replacement = Card("Draft", rule.tag, (HOLE, HOLE))
    elif rule.tag == "group" and not rule.fields:
        replacement = Card("Draft", "group", (HOLE,))
    else:
        return Bottom("rule")

    def replace(node, steps):
        if not steps:
            if node != HOLE:
                raise ValueError("not_leaf")
            return replacement
        if not isinstance(node, Card) or node.sort != "Draft" or type(steps[0]) is not int or not 1 <= steps[0] <= len(node.fields):
            raise ValueError("path")
        fields = list(node.fields)
        fields[steps[0] - 1] = replace(fields[steps[0] - 1], steps[1:])
        return Card("Draft", node.tag, tuple(fields))

    try:
        result = replace(tree, path.fields)
        surface = _surface(result, True)
        if len(surface) > 48 or _nodes(result) > 40 or sum(type(token) is int for token in surface) > 12:
            return Bottom("size")
        if max((sum(token == "(" for token in surface[:index + 1]) -
                sum(token == ")" for token in surface[:index + 1]) for index in range(len(surface))), default=0) > 8:
            return Bottom("depth")
        return result
    except ValueError as error:
        return Bottom(str(error))


def yield_probe(tree):
    try:
        return word(*_surface(tree))
    except ValueError as error:
        return Bottom(str(error))


def list_new(*items):
    return Card("List", "items", items)


def list0():
    return list_new()


def list1(first):
    return list_new(first)


def list2(first, second):
    return list_new(first, second)


def list3(first, second, third):
    return list_new(first, second, third)


def word_new(items):
    return word(*items.fields) if isinstance(items, Card) and items.sort == "List" else Bottom("invalid")


def length(items):
    if isinstance(items, Card) and items.sort == "Draft":
        return 1 + sum(length(child) for child in items.fields if isinstance(child, Card))
    return len(items.fields) if isinstance(items, Card) and items.sort in ("Word", "List", "Hist") else Bottom("invalid")


def at(items, index):
    if not isinstance(items, Card) or items.sort not in ("Word", "List", "Hist") or type(index) is not int or not 0 <= index < len(items.fields):
        return Bottom("index")
    return items.fields[index]


def slice_word(items, start, stop):
    if not isinstance(items, Card) or items.sort != "Word" or type(start) is not int or type(stop) is not int or not 0 <= start <= stop <= len(items.fields):
        return Bottom("index")
    return Card("Word", "tokens", items.fields[start:stop])


def append(items, item):
    if not isinstance(items, Card) or items.sort != "List":
        return Bottom("invalid")
    return Card("List", "items", items.fields + (item,))


def concat(left, right):
    if not isinstance(left, Card) or not isinstance(right, Card) or left.sort != right.sort or left.tag != right.tag:
        return Bottom("invalid")
    return Card(left.sort, left.tag, left.fields + right.fields)


def make_draft(tag, fields):
    if tag not in ("num", "+", "*", "group") or not isinstance(fields, Card) or fields.sort != "List":
        return Bottom("invalid")
    result = Card("Draft", tag, fields.fields)
    try:
        surface = _surface(result)
        if (_nodes(result) > 40 or len(surface) > 48 or sum(type(token) is int for token in surface) > 12 or
                isinstance(word(*surface), Bottom)):
            return Bottom("invalid")
    except ValueError:
        return Bottom("invalid")
    return result


def tag(value):
    return value.tag if isinstance(value, Card) else Bottom("invalid")


def field(value, index):
    if isinstance(value, Card) and value.sort in ("ExprTree", "Ambiguity"):
        return Bottom("permission")
    return value.fields[index] if isinstance(value, Card) and type(index) is int and 0 <= index < len(value.fields) else Bottom("index")


def add(left, right):
    return left + right


def sub(left, right):
    return left - right


def mul(left, right):
    return left * right


def eq(left, right):
    return boolean(left == right)


def is_int(item):
    return boolean(type(item) is int)


def fail(reason):
    return Bottom(reason)


def lt(left, right):
    return boolean(left < right)


def le(left, right):
    return boolean(left <= right)


def mod(left, right):
    return left % right if right else Bottom("zero")


def div(left, right):
    return left // right if right else Bottom("zero")


def sorted_items(items):
    return Card("List", "items", tuple(sorted(items.fields))) if isinstance(items, Card) and items.sort == "List" else Bottom("invalid")


def pair(first, second):
    return Card("Pair", "pair", (first, second))


def hist(items):
    return Card("Hist", "entries", items.fields) if isinstance(items, Card) and items.sort == "List" else Bottom("invalid")


def witness(items):
    return Card("Witness", "triple", items.fields) if isinstance(items, Card) and items.sort == "List" and len(items.fields) == 3 else Bottom("invalid")


def minimum(items):
    return min(items.fields) if isinstance(items, Card) and items.fields else Bottom("empty")


def maximum(items):
    return max(items.fields) if isinstance(items, Card) and items.fields else Bottom("empty")


def to_card(tree):
    """Convert a valid reference AST into the given draft representation."""
    if tree == "E":
        return HOLE
    if tree[0] == "num":
        return Card("Draft", "num", (tree[1],))
    return Card("Draft", tree[0], tuple(to_card(child) for child in tree[1:]))


def from_card(tree):
    """Convert a draft into the reference representation without losing order."""
    if tree == HOLE:
        return "E"
    return (tree.tag, *(from_card(child) if isinstance(child, Card) else child for child in tree.fields))


_original_host_functions = {}


def _reject_invalid_cards(name):
    @wraps(_original_host_functions[name])
    def checked(*args):
        if any(_invalid_argument(arg) for arg in args):
            return Bottom("invalid")
        return _original_host_functions[name](*args)

    return checked


def _invalid_argument(value):
    if isinstance(value, Card):
        return not valid_card(value)
    if isinstance(value, (tuple, list)):
        return any(_invalid_argument(item) for item in value)
    if isinstance(value, dict):
        return any(_invalid_argument(item) for pair in value.items() for item in pair)
    if isinstance(value, (set, frozenset)):
        return any(_invalid_argument(item) for item in value)
    return False


for _name in ("word", "expand", "yield_probe", "list_new", "list1", "list2", "list3",
              "word_new", "length", "at", "slice_word", "append", "concat", "make_draft",
              "tag", "field", "add", "sub", "mul", "eq", "is_int", "fail", "lt", "le",
              "mod", "div", "sorted_items", "pair", "hist", "witness", "minimum",
              "maximum"):
    _original_host_functions[_name] = globals()[_name]
    globals()[_name] = _reject_invalid_cards(_name)
