"""Executable reference semantics for the Opulse text world's 0–12 layers.

Strings are sequences of Unicode code points, not bytes or display columns.
None represents Option.none for unreachable minimums, and Bottom(index) for
invalid unranking (different result contracts). Invalid constructors and
out-of-domain layer-0 calls raise ValueError (Bottom(size/domain)).
"""

from dataclasses import dataclass
from itertools import product
import json
from pathlib import Path

MAX_TEXT = 64
ALPHABET = frozenset("ab ")


def text(value):
    if not isinstance(value, str) or len(value) > MAX_TEXT or any(c not in ALPHABET for c in value):
        raise ValueError("Bottom(text_domain_or_size)")
    return value


def concat(left, right):
    return text(text(left) + text(right))


def slice_text(value, start, end):
    text(value)
    if not (type(start) is int and type(end) is int and 0 <= start <= end <= len(value)):
        raise ValueError("Bottom(span)")
    return text(value[start:end])


def add(left, right):
    if type(left) is not int or type(right) is not int or left < 0 or right < 0:
        raise ValueError("Bottom(nat)")
    return left + right


def sub_nat(left, right):
    if type(left) is not int or type(right) is not int or not 0 <= right <= left:
        raise ValueError("Bottom(nat_subtraction)")
    return left - right


def length(value):
    return len(text(value))


def chars(value):
    return tuple(enumerate(text(value)))


def map_chars(transform, value):
    mapped = []
    for _, char in chars(value):
        replacement = transform(char)
        if not isinstance(replacement, str) or len(replacement) != 1 or replacement not in ALPHABET:
            raise ValueError("Bottom(char_step)")
        mapped.append(replacement)
    return text("".join(mapped))


@dataclass(frozen=True)
class Word:
    value: str

    def __post_init__(self):
        text(self.value)
        if not self.value or " " in self.value:
            raise ValueError("Bottom(word)")


def split(value):
    result = []
    current = ""
    for _, char in chars(value):
        if char == " ":
            if current:
                result.append(Word(current))
                current = ""
        else:
            current = concat(current, char)
    if current:
        result.append(Word(current))
    return tuple(result)


def rewrite(transform, words):
    result = ""
    for word in words:
        if not isinstance(word, Word):
            raise ValueError("Bottom(word)")
        replacement = transform(word)
        if not isinstance(replacement, Word):
            raise ValueError("Bottom(word_transform)")
        result = concat(concat(result, " " if result else ""), replacement.value)
    return result


def identity(word):
    return word


def starts(value):
    result = []
    inside = False
    for index, char in chars(value):
        if char != " " and not inside:
            result.append(index)
        inside = char != " "
    return tuple(result)


@dataclass(frozen=True)
class Lex:
    entries: tuple

    def __post_init__(self):
        entries = tuple(self.entries)
        if len(entries) > 16:
            raise ValueError("Bottom(lex_size)")
        for word, cost in entries:
            if not isinstance(word, Word) or len(word.value) > 8 or type(cost) is not int or not 1 <= cost <= 9:
                raise ValueError("Bottom(lex_entry)")
        ordered = sorted(entries, key=lambda entry: entry[0].value)
        if len({word.value for word, _ in ordered}) != len(ordered):
            raise ValueError("Bottom(duplicate_word)")
        object.__setattr__(self, "entries", tuple(ordered))

    def cost(self, word):
        for candidate, cost in self.entries:
            if candidate == word:
                return cost
        raise ValueError("Bottom(absent_word)")


@dataclass(frozen=True)
class Span:
    start: int
    end: int
    word: Word
    cost: int

    def __post_init__(self):
        if not (type(self.start) is int and type(self.end) is int and
                0 <= self.start < self.end <= MAX_TEXT and isinstance(self.word, Word) and
                type(self.cost) is int and self.cost >= 0):
            raise ValueError("Bottom(span)")


def edges(value, lexicon):
    text(value)
    if " " in value or not isinstance(lexicon, Lex):
        raise ValueError("Bottom(lattice_input)")
    found = []
    for start in range(len(value)):
        for word, cost in lexicon.entries:
            end = start + len(word.value)
            if end <= len(value) and slice_text(value, start, end) == word.value:
                found.append(Span(start, end, word, cost))
    return tuple(sorted(found, key=lambda edge: (edge.end, edge.start, edge.word.value)))


def routes(extend, merge, spans, length, zero, unit):
    if type(length) is not int or length < 0 or length > MAX_TEXT:
        raise ValueError("Bottom(length)")
    if any(not (0 <= edge.start < edge.end <= length) for edge in spans):
        raise ValueError("Bottom(span)")
    state = [zero for _ in range(length + 1)]
    state[0] = unit
    for edge in sorted(spans, key=lambda item: (item.end, item.start, item.word.value)):
        state[edge.end] = merge(state[edge.end], extend(state[edge.start], edge))
    return state[length]


def parses(value, lexicon):
    return routes(keep_count, add, edges(value, lexicon), length(value), 0, 1)


def keep_count(count, edge):
    return count


def add_cost(cost, edge):
    return None if cost is None else add(cost, edge.cost)


def min_cost(left, right):
    if left is None:
        return right
    if right is None:
        return left
    return min(left, right)


def best(value, lexicon):
    return routes(add_cost, min_cost, edges(value, lexicon), length(value), None, 0)


def add_tally(tally, edge):
    return (None, 0) if tally[0] is None else (add(tally[0], edge.cost), tally[1])


def min_tally(left, right):
    if left[0] is None:
        return right
    if right[0] is None:
        return left
    if left[0] < right[0]:
        return left
    if right[0] < left[0]:
        return right
    return (left[0], add(left[1], right[1]))


def optimal_count(value, lexicon):
    cost, count = routes(add_tally, min_tally, edges(value, lexicon), length(value), (None, 0), (0, 1))
    assert cost == best(value, lexicon)
    return count


@dataclass(frozen=True)
class Parse:
    source: str
    lexicon: Lex
    words: tuple

    def __post_init__(self):
        text(self.source)
        if " " in self.source or not isinstance(self.lexicon, Lex) or not isinstance(self.words, tuple):
            raise ValueError("Bottom(parse_source)")
        assembled = ""
        for word in self.words:
            if not isinstance(word, Word):
                raise ValueError("Bottom(parse_word)")
            self.lexicon.cost(word)
            assembled = concat(assembled, word.value)
        if assembled != self.source:
            raise ValueError("Bottom(parse_cover)")


def kth_optimal(value, lexicon, index):
    text(value)
    if type(index) is not int or index < 0 or index >= optimal_count(value, lexicon):
        return None
    prefix = 0
    selected = []
    remaining_cost = best(value, lexicon)
    while prefix < len(value):
        choices = sorted((edge for edge in edges(value, lexicon) if edge.start == prefix),
                         key=lambda edge: (edge.end, edge.word.value))
        for edge in choices:
            suffix = slice_text(value, edge.end, len(value))
            suffix_cost = best(suffix, lexicon)
            if suffix_cost is None or add(edge.cost, suffix_cost) != remaining_cost:
                continue
            branch_size = optimal_count(suffix, lexicon)
            if index >= branch_size:
                index = sub_nat(index, branch_size)
                continue
            selected.append(edge.word)
            prefix = edge.end
            remaining_cost = sub_nat(remaining_cost, edge.cost)
            break
        else:
            raise AssertionError("inconsistent optimal path counts")
    result = Parse(value, lexicon, tuple(selected))
    assert sum(lexicon.cost(word) for word in result.words) == best(value, lexicon)
    return result


def lex(*pairs):
    return Lex(tuple((Word(word), cost) for word, cost in pairs))


def list_words(words):
    return "List<" + ", ".join(render_word(word) for word in words) + ">"


def render_word(word):
    return "Word<" + repr(word.value) + ">"


def render_text(value):
    return "Text<" + repr(value) + ">"


def list_int(values):
    return "List<" + ", ".join(map(str, values)) + ">"


def render_lex(lexicon):
    return "Lex<" + ", ".join("Pair<" + render_word(word) + ", " + str(cost) + ">"
                              for word, cost in lexicon.entries) + ">"


def render_parse(value):
    return ("Bottom(index)" if value is None else
            "Parse<" + render_text(value.source) + ", " + render_lex(value.lexicon) +
            ", " + list_words(value.words) + ">")


def render_edges(spans):
    return "List<" + ", ".join("Span<" + str(edge.start) + ", " + str(edge.end) +
                               ", " + render_word(edge.word) + ", " + str(edge.cost) + ">"
                               for edge in spans) + ">"


def examples():
    dictionary = lex(("a", 2), ("aa", 3), ("b", 3), ("ab", 4))
    return [
        render_word(Word("ab")),
        list_words(split("a  b")),
        render_text(rewrite(identity, split("a  b"))),
        list_int(starts(rewrite(identity, split("a  b")))),
        render_lex(lex(("b", 3), ("ab", 4), ("a", 2))),
        render_edges(edges("aab", dictionary)),
        routes(lambda count, edge: count, add, edges("aab", dictionary), 3, 0, 1),
        parses("aab", dictionary),
        best("aab", dictionary),
        optimal_count("aab", dictionary),
        render_parse(Parse("ab", lex(("ab", 4)), (Word("ab"),))),
        render_parse(kth_optimal("aab", dictionary, 0)),
    ]


def checks():
    expected = ["Word<'ab'>", "List<Word<'a'>, Word<'b'>>", "Text<'a b'>",
                "List<0, 2>", "Lex<Pair<Word<'a'>, 2>, Pair<Word<'ab'>, 4>, Pair<Word<'b'>, 3>>",
                "List<Span<0, 1, Word<'a'>, 2>, Span<0, 2, Word<'aa'>, 3>, Span<1, 2, Word<'a'>, 2>, Span<1, 3, Word<'ab'>, 4>, Span<2, 3, Word<'b'>, 3>>",
                3, 3, 6, 2,
                "Parse<Text<'ab'>, Lex<Pair<Word<'ab'>, 4>>, List<Word<'ab'>>>",
                "Parse<Text<'aab'>, Lex<Pair<Word<'a'>, 2>, Pair<Word<'aa'>, 3>, Pair<Word<'ab'>, 4>, Pair<Word<'b'>, 3>>, List<Word<'a'>, Word<'ab'>>>"]
    actual = examples()
    assert actual == expected, (actual, expected)
    assert chars("a b") == ((0, "a"), (1, " "), (2, "b"))
    assert concat("ab", " a") == "ab a"
    assert map_chars(lambda char: char, "a b") == "a b"
    assert split("    ") == ()
    assert parses("", lex(("a", 1))) == optimal_count("", lex(("a", 1))) == 1
    assert best("", lex(("a", 1))) == 0
    assert best("b", lex(("a", 1))) is None
    assert optimal_count("b", lex(("a", 1))) == 0
    assert kth_optimal("b", lex(("a", 1)), 0) is None
    for invalid in (lambda: Word(""), lambda: Word("a b"), lambda: text("a" * 65),
                    lambda: lex(("a", 2), ("a", 3)),
                    lambda: Parse("ab", lex(("a", 2)), (Word("a"),))):
        try:
            invalid()
        except ValueError:
            pass
        else:
            raise AssertionError("invalid representation accepted")

    small_lex = lex(("a", 2), ("aa", 3), ("b", 3), ("ab", 4), ("ba", 4))
    for length in range(7):
        for letters in product("ab", repeat=length):
            source = "".join(letters)
            def enumerate_paths(at):
                if at == length:
                    yield ()
                for edge in edges(source, small_lex):
                    if edge.start == at:
                        for rest in enumerate_paths(edge.end):
                            yield (edge.word,) + rest
            paths = list(enumerate_paths(0))
            assert parses(source, small_lex) == len(paths)
            costs = [sum(small_lex.cost(word) for word in path) for path in paths]
            minimum = min(costs, default=None)
            assert best(source, small_lex) == minimum
            optimal = [path for path, cost in zip(paths, costs) if cost == minimum]
            assert optimal_count(source, small_lex) == len(optimal)
            for rank, path in enumerate(optimal):
                assert kth_optimal(source, small_lex, rank).words == path
            assert kth_optimal(source, small_lex, len(optimal)) is None

    source = "abababababababababababab"
    dictionary = lex(("a", 2), ("aa", 3), ("aaa", 4), ("b", 2),
                     ("ab", 4), ("aba", 6), ("ba", 4), ("bab", 6))
    compute = (parses(source, dictionary), best(source, dictionary),
               optimal_count(source, dictionary), render_parse(kth_optimal(source, dictionary, 30)))

    inverse_source = "abababababab"
    def inverse_at(weight):
        candidate = lex(("a", 2), ("b", 3), ("ab", weight), ("aba", 4), ("bab", 5))
        return best(inverse_source, candidate), optimal_count(inverse_source, candidate)
    inverse_table = {weight: inverse_at(weight) for weight in range(1, 10)}

    decide_source = "abababababababab"
    base = lex(("a", 2), ("b", 3), ("ab", 4), ("aba", 4), ("bab", 5))
    enhanced = lex(*[(word.value, cost) for word, cost in base.entries], ("abab", 7))
    decide = (best(decide_source, base), optimal_count(decide_source, base),
              best(decide_source, enhanced), optimal_count(decide_source, enhanced))
    assert compute[:3] == (1389537, 48, 1389537)
    assert compute[3] == render_parse(kth_optimal(source, dictionary, 30))
    assert inverse_table == {1: (6, 1), 2: (12, 1), 3: (18, 6),
                             **{weight: (18, 1) for weight in range(4, 10)}}
    assert [weight for weight, result in inverse_table.items() if result == (18, 6)] == [3]
    assert decide == (25, 6, 25, 9)
    return actual, compute, inverse_table, decide


if __name__ == "__main__":
    example_values, compute_values, inverse_values, decide_values = checks()
    if __import__("sys").argv[1:] == ["--values"]:
        print("examples:", example_values)
        print("compute:", compute_values)
        print("inverse:", inverse_values)
        print("decide:", decide_values)
    else:
        path = Path(__file__).with_suffix(".json")
        if path.exists():
            card = json.loads(path.read_text(encoding="utf-8"))
            assert [layer["value"] for layer in card["tower"]] == example_values
            assert card["showcase"][0]["answer"] == dict(zip(
                ("parses", "best", "optimal_count"), compute_values[:3]))
            assert card["showcase"][1]["answer"] == "List<3>"
            assert card["showcase"][2]["answer"] == {
                "best_before": decide_values[0], "optimal_before": decide_values[1],
                "best_after": decide_values[2], "optimal_after": decide_values[3],
                "changes_optimal_count": decide_values[1] != decide_values[3]}
        print("OK")
