"""Finite expression grammar: exact chart counts, ranked proofs, and values.

The public Word alphabet is 1..9, +, *, (, ). Bounds: 48 tokens,
12 numeral occurrences, and parenthesis depth 8. All grammar work is finite.
"""

from collections import Counter
from functools import lru_cache
from itertools import combinations
import json
from pathlib import Path


def word(*tokens):
    """Layer 0 Word constructor: reject oversized or ill-formed token streams."""
    if len(tokens) > 48 or sum(isinstance(t, int) and not isinstance(t, bool) for t in tokens) > 12:
        raise ValueError("size")
    depth = 0
    for token in tokens:
        if token == "(":
            depth += 1
            if depth > 8:
                raise ValueError("depth")
        elif token == ")":
            depth -= 1
            if depth < 0:
                raise ValueError("parenthesis")
        elif token not in ("+", "*") and (type(token) is not int or not 1 <= token <= 9):
            raise ValueError("token")
    if depth:
        raise ValueError("parenthesis")
    return tuple(tokens)


def expand(tree, path, rule):
    """Layer 0: expand an unexpanded E leaf by a production.

    Rules: ('num',digit), ('+',), ('*',), ('group',). path is a tuple
    of child indices. Invalid paths/rules are errors; the size bound applies
    to every intermediate tree as well as to finished trees.
    """
    if not isinstance(rule, tuple) or not rule:
        raise ValueError("rule")
    if rule[0] == "num" and len(rule) == 2 and type(rule[1]) is int and 1 <= rule[1] <= 9:
        replacement = ("num", rule[1])
    elif rule in (("+",), ("*",)):
        replacement = (rule[0], "E", "E")
    elif rule == ("group",):
        replacement = ("group", "E")
    else:
        raise ValueError("rule")

    def replace(node, steps):
        if not steps:
            if node != "E":
                raise ValueError("not a leaf")
            return replacement
        if not isinstance(node, tuple) or steps[0] not in range(1, len(node)):
            raise ValueError("path")
        children = list(node)
        children[steps[0]] = replace(children[steps[0]], steps[1:])
        return tuple(children)

    result = replace(tree, tuple(path))
    surface = yield_tokens(result, partial=True)
    if (len(surface) > 48 or node_count(result) > 40 or
            sum(type(token) is int for token in surface) > 12 or
            max_depth(surface) > 8):
        raise ValueError("size")
    return result


def max_depth(tokens):
    depth = peak = 0
    for token in tokens:
        depth += (token == "(") - (token == ")")
        peak = max(peak, depth)
    return peak


def node_count(tree):
    return 0 if tree == "E" else 1 + sum(node_count(child) for child in tree[1:] if isinstance(child, tuple) or child == "E")


def yield_tokens(tree, partial=False):
    """Layer 0 observation ?yield: public surface, never the hidden proof."""
    if tree == "E":
        if partial:
            return ("E",)
        raise ValueError("unfinished")
    tag = tree[0]
    if tag == "num":
        return (tree[1],)
    if tag == "group":
        return ("(",) + yield_tokens(tree[1], partial) + (")",)
    if tag in ("+", "*"):
        return yield_tokens(tree[1], partial) + (tag,) + yield_tokens(tree[2], partial)
    raise ValueError("tree")


def expr_tree(tree):
    """L1 sealed ExprTree: legal finished proof, normalized by its AST."""
    def check(node):
        if not isinstance(node, tuple):
            raise ValueError("unfinished")
        if node[0] == "num" and len(node) == 2 and type(node[1]) is int and 1 <= node[1] <= 9:
            return
        if node[0] == "group" and len(node) == 2:
            check(node[1])
            return
        if node[0] in ("+", "*") and len(node) == 3:
            check(node[1])
            check(node[2])
            return
        raise ValueError("tree")

    check(tree)
    word(*yield_tokens(tree))
    if node_count(tree) > 40:
        raise ValueError("size")
    return tree


def split(tokens):
    """L2: positions of depth-zero binary production operators."""
    tokens = word(*tokens)
    depth = 0
    result = []
    for index, token in enumerate(tokens):
        if token == "(":
            depth += 1
        elif token == ")":
            depth -= 1
        elif depth == 0 and token in ("+", "*"):
            result.append(index)
    return tuple(result)


def outer_group(tokens):
    if len(tokens) < 3 or tokens[0] != "(" or tokens[-1] != ")":
        return False
    depth = 0
    for index, token in enumerate(tokens):
        depth += (token == "(") - (token == ")")
        if depth == 0 and index != len(tokens) - 1:
            return False
    return True


def seq(first, second, value):
    """Layer 0 sequential composition of two total operations."""
    return second(first(value))


def bounded_rec(step, tokens):
    """Layer 0 recursion: only strictly shorter spans; memoize exact spans."""
    tokens = word(*tokens)

    @lru_cache(None)
    def run(span):
        def smaller(child):
            if len(child) >= len(span):
                raise ValueError("not decreasing")
            return run(child)
        return step(span, smaller)

    return run(tokens)


def chart(leaf, join, wrap, merge, zero, tokens):
    """L3 higher-order memoized chart, with explicit algebraic slots.

    Every legal top-level split is a distinct derivation; merge must combine
    alternatives without erasing multiplicity. Empty spans contribute zero().
    Slots must be pure on the given finite inputs for memoization to be sound.
    """
    def cell(span, smaller):
        if len(span) == 1 and type(span[0]) is int:
            return leaf(span[0])
        result = zero()
        if outer_group(span):
            result = merge(result, wrap(smaller(span[1:-1])))
        for index in split(span):
            if index == 0 or index == len(span) - 1:
                continue
            left = smaller(span[:index])
            right = smaller(span[index + 1:])
            result = merge(result, join(span[index], left, right))
        return result

    return bounded_rec(cell, tokens)


def parse_count(tokens):
    """L4 public observation, a finite count of proofs, not their yields."""
    return chart(lambda _: 1, lambda _op, left, right: left * right,
                 lambda inner: inner, lambda left, right: left + right,
                 lambda: 0, tokens)


def unrank(tokens, rank):
    """L5: unique zero-based proof in increasing split, left-major order."""
    tokens = word(*tokens)
    if type(rank) is not int or not 0 <= rank < parse_count(tokens):
        raise ValueError("rank")

    def build(span, offset):
        if len(span) == 1 and type(span[0]) is int:
            return ("num", span[0])
        if outer_group(span):
            return ("group", build(span[1:-1], offset))
        for index in split(span):
            left, right = span[:index], span[index + 1:]
            left_count, right_count = parse_count(left), parse_count(right)
            block = left_count * right_count
            if offset < block:
                return (span[index], build(left, offset // right_count),
                        build(right, offset % right_count))
            offset -= block
        raise AssertionError("inconsistent chart")

    return expr_tree(build(tokens, rank))


def ambiguous(tokens):
    """L6 observation: strictly more than one proof."""
    return parse_count(tokens) > 1


def ambiguity(tokens):
    """L7 sealed witness: same public yield, distinct canonical proof trees."""
    tokens = word(*tokens)
    if not ambiguous(tokens):
        raise ValueError("not ambiguous")
    first, second = unrank(tokens, 0), unrank(tokens, 1)
    assert first != second and yield_tokens(first) == yield_tokens(second) == tokens
    return (tokens, first, second)


def fold(leaf, join, wrap, tree):
    """L8 higher-order structural interpreter of a checked proof tree."""
    expr_tree(tree)

    def visit(node):
        if node[0] == "num":
            return leaf(node[1])
        if node[0] == "group":
            return wrap(visit(node[1]))
        return join(node[0], visit(node[1]), visit(node[2]))

    return visit(tree)


def eval_tree(tree):
    """One interpretation of L8: arithmetic denotation."""
    return fold(lambda value: value,
                lambda op, left, right: left + right if op == "+" else left * right,
                lambda inner: inner, tree)


def value_hist(tokens):
    """L9 observation: map result to exact number of derivations."""
    def combine(op, left, right):
        result = Counter()
        for left_value, left_count in left.items():
            for right_value, right_count in right.items():
                result[left_value + right_value if op == "+" else left_value * right_value] += left_count * right_count
        return result

    histogram = chart(lambda value: Counter({value: 1}), combine, lambda inner: inner,
                      lambda left, right: left + right, Counter, tokens)
    assert sum(histogram.values()) == parse_count(tokens)
    return dict(sorted(histogram.items()))


def gap(tokens):
    """L10: exact semantic disagreement range; no parse => Bottom(domain)."""
    histogram = value_hist(tokens)
    if not histogram:
        raise ValueError("no parse")
    return max(histogram) - min(histogram)


def patterned_words(numerals, stars):
    """Public finite candidate family for inversion.

    Numerals cycle 1,2,3; + precedes * lexically; combinations are ordered
    by increasing indices of * (not by host-language tuple comparison).
    """
    if type(numerals) is not int or type(stars) is not int or not 2 <= numerals <= 12 or not 0 <= stars <= numerals - 1:
        raise ValueError("family")
    for positions in combinations(range(numerals - 1), stars):
        pieces = []
        for index in range(numerals):
            pieces.append(1 + index % 3)
            if index < numerals - 1:
                pieces.append("*" if index in positions else "+")
        yield word(*pieces)


def invert_gap(target, numerals, stars):
    """L11: first candidate in the declared order with specified gap."""
    if type(target) is not int or target < 0:
        raise ValueError("target")
    for candidate in patterned_words(numerals, stars):
        if ambiguous(candidate) and gap(candidate) == target:
            return candidate
    return None


def format_word(tokens):
    return "Word<" + ",".join(map(str, tokens)) + ">"


def format_tree(tree):
    if tree[0] == "num":
        return f"Num<{tree[1]}>"
    if tree[0] == "group":
        return "Group<" + format_tree(tree[1]) + ">"
    return ("Add<" if tree[0] == "+" else "Mul<") + format_tree(tree[1]) + "," + format_tree(tree[2]) + ">"


def format_hist(histogram):
    return "Hist<" + ",".join(f"({key},{count})" for key, count in sorted(histogram.items())) + ">"


def run_checks(data):
    assert data['id'] == 'grammar'
    assert len(data['tower']) == 11 and len(data['showcase']) == 3
    assert {entry['kind'] for entry in data['tower']} == {'object', 'operation', 'combinator', 'observation'}
    proof = expand(expand(expand('E', (), ('+',)), (1,), ('num', 2)), (2,), ('num', 3))
    assert yield_tokens(proof) == word(2, '+', 3)
    assert seq(lambda tree: expand(tree, (), ('+',)),
               lambda tree: expand(tree, (1,), ('num', 2)), 'E') == ('+', ('num', 2), 'E')
    try:
        bounded_rec(lambda span, recurse: recurse(span), word(1))
    except ValueError:
        pass
    else:
        raise AssertionError('unguarded recursion')
    assert word(*yield_tokens(expr_tree(proof))) == word(2, '+', 3)
    assert split(word(2, '+', '(', 3, '*', 2, ')')) == (1,)
    assert parse_count(word(1, '+', 2, '*', 3, '+', 1)) == 5
    assert parse_count(word('(', 1, '+', 2, ')', '*', 3)) == 1
    assert len(set(unrank(word(*sum(([1, '+'] for _ in range(7)), []) + [1]), index)
                   for index in range(429))) == 429
    assert ambiguous(word(1, '+', 2, '*', 3))
    assert ambiguity(word(1, '+', 2, '*', 3))[1] != ambiguity(word(1, '+', 2, '*', 3))[2]
    assert eval_tree(unrank(word(1, '+', 2, '*', 3), 0)) == 7
    assert value_hist(word(1, '+', 2, '*', 3)) == {7: 1, 9: 1}
    assert gap(word(1, '+', 2, '*', 3)) == 2
    computed_tower = tower_values()
    for layer, entry in enumerate(data['tower'], 1):
        assert entry['layer'] == layer
        assert entry['value'] == computed_tower[layer - 1], entry
    for task, computed in zip(data['showcase'], showcase_values()):
        assert task['answer'] == computed, task
    assert invert_gap(999999, 4, 2) is None
    for candidate in patterned_words(5, 2):
        histogram = value_hist(candidate)
        assert sum(histogram.values()) == 14
        assert all(yield_tokens(unrank(candidate, rank)) == candidate for rank in range(14))
        assert Counter(eval_tree(unrank(candidate, rank)) for rank in range(14)) == histogram
    for invalid in [(1, '+', '('), (0,), tuple(range(13))]:
        try:
            word(*invalid)
        except ValueError:
            pass
        else:
            raise AssertionError('accepted invalid word')


def tower_values():
    sample = word(1, '+', 2, '*', 3)
    counted = word(1, '+', 1, '+', 1, '+', 1, '+', 1, '+', 1, '+', 1, '+', 1)
    witness = ambiguity(sample)
    return [format_tree(expr_tree(('num', 7))),
            'List<' + ','.join(map(str, split(word(2, '+', '(', 3, '*', 2, ')')))) + '>',
            str(chart(lambda _: 1, lambda _op, left, right: left * right,
                      lambda inner: inner, lambda left, right: left + right,
                      lambda: 0, word(1, '+', 2, '*', 3, '+', 1))),
            str(parse_count(counted)), format_tree(unrank(sample, 1)),
            str(ambiguous(sample)).lower(),
            'Ambiguity<' + format_word(witness[0]) + ',' +
            format_tree(witness[1]) + ',' + format_tree(witness[2]) + '>',
            str(fold(lambda number: number,
                     lambda op, left, right: left + right if op == '+' else left * right,
                     lambda inner: inner, unrank(sample, 0))),
            format_hist(value_hist(sample)), str(gap(sample)),
            format_word(invert_gap(37, 7, 3))]


def showcase_values():
    long_word = word(2, '+', 2, '*', 2, '+', 2, '*', 2, '+', 2, '*', 2, '+', 2, '*', 2)
    inverse = invert_gap(94, 7, 3)
    decision = word(1, '+', 2, '*', 3, '+', 1, '*', 2, '+', 3, '*', 1)
    histogram = value_hist(long_word)
    return [f"Count<{parse_count(long_word)}>;Range<{min(histogram)},{max(histogram)}>;Gap<{gap(long_word)}>",
            format_word(inverse) if inverse is not None else 'Bottom<none>',
            f"{str(ambiguous(decision) and gap(decision) > 20).lower()};Count<{parse_count(decision)}>;Gap<{gap(decision)}>;{format_hist(value_hist(decision))}"]


if __name__ == '__main__':
    content = json.loads(Path(__file__).with_suffix('.json').read_text(encoding='utf-8'))
    run_checks(content)
    print('OK')
