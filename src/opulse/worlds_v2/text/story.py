"""Twelve kernel-defined inventions over the public weighted text lattice."""

from functools import lru_cache
from itertools import product

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.library import VerifyRequest
from opulse.atoms.spec import (
    CombinatorSpec,
    Contract,
    Definition,
    Edge,
    ObjectSpec,
    ObservationSpec,
    OperationSpec,
)
from opulse.atoms.values import Bottom, Card

from .world import new_library

NONE = Card("Option", "none")


def call(name, *args):
    return n.Call(name, args)


def var(name):
    return n.Var(name)


def lit(value):
    return n.Lit(value)


def choose(condition, yes, no):
    return n.Case(((n.Test(condition), yes),), no)


def let(name, value, body):
    return n.Let(name, value, body)


def rec(name, params, body, args, measure, memo=False):
    return n.Rec(name, params, body, args, measure, memo)


def sequence(*items):
    result = call("seq_empty")
    for item in reversed(items):
        result = call("seq_cons", item, result)
    return result


def word(value):
    return Card("Word", "val", (value,))


def lex(*entries):
    pairs = (Card("Pair", "pair", (word(text), weight)) for text, weight in entries)
    return Card("Lex", "val", (Card("List", "list", tuple(sorted(pairs, key=repr))),))


def definition(name, kind, body, spec, layer):
    deps = tuple(sorted(n.references(body) - (set(spec.op_params) if kind == "combinator" else set()))) if body is not None else ()
    return Definition(name, kind, "invented", layer, deps, spec, body)


def operation(name, params, body, layer):
    spec = OperationSpec(name, "transform", tuple(Edge("any", name=param) for param in params), Edge("any"),
                         "Unfold the public weighted lattice over layer-zero primitives.",
                         extra={"input_names": list(params)})
    return definition(name, "operation", body, spec, layer)


def observation(name, params, body, layer):
    return definition(name, "observation", body, ObservationSpec(name, ("chars",), body), layer)


def definitions():
    current = var("x")
    visible = var("visible")
    is_space = call("equal", call("second", call("seq_head", visible)), lit(" "))
    has_space = rec("scan_space", ("visible",),
                    choose(call("seq_is_empty", visible), lit(False),
                           choose(is_space, lit(True), call("scan_space", call("seq_tail", visible)))),
                    (call("chars", current),), call("seq_length", visible))
    word_valid = choose(call("is_text", current),
                        choose(call("equal", current, lit("")), lit(False),
                               choose(has_space, lit(False), lit(True))), lit(False))
    word_def = Definition("Word", "object", "invented", 1, tuple(sorted(n.references(word_valid))),
                          ObjectSpec("Word", "refine", base="host_text", valid=word_valid,
                                     sealed=True, interface=("Word.make", "Word.base")), None)
    space_def = operation("contains_space", ("text",),
                          rec("find_space", ("visible",),
                              choose(call("seq_is_empty", visible), lit(False),
                                     choose(is_space, lit(True), call("find_space", call("seq_tail", visible)))),
                              (call("chars", var("text")),), call("seq_length", visible)), 1)

    remaining, fragment = var("remaining"), var("fragment")
    char = call("second", call("seq_head", remaining))
    advance = call("scan_split", call("seq_tail", remaining), call("concat", fragment, char))
    flush = call("seq_cons", call("Word.make", fragment), call("scan_split", call("seq_tail", remaining), lit("")))
    split_body = rec("scan_split", ("remaining", "fragment"),
                     choose(call("seq_is_empty", remaining),
                            choose(call("equal", fragment, lit("")), sequence(), sequence(call("Word.make", fragment))),
                            choose(call("equal", char, lit(" ")),
                                   choose(call("equal", fragment, lit("")),
                                          call("scan_split", call("seq_tail", remaining), fragment), flush), advance)),
                     (call("chars", var("text")), lit("")), call("seq_length", remaining))
    split_def = operation("split", ("text",), split_body, 2)

    visible = var("visible")
    public_body = rec("collect_chars", ("visible",),
                      choose(call("seq_is_empty", visible), lit(""),
                             call("concat", call("second", call("seq_head", visible)),
                                  call("collect_chars", call("seq_tail", visible)))),
                      (call("chars", var("text")),), call("seq_length", visible))
    public_def = operation("public_text", ("text",), public_body, 1)

    words = var("words")
    translated = call("Word.base", call("transform", call("seq_head", words)))
    rewrite_body = rec("rewrite_local", ("words",),
                       choose(call("seq_is_empty", words), lit(""),
                              let("next", call("seq_tail", words),
                                  choose(call("seq_is_empty", var("next")), translated,
                                         call("concat", translated,
                                              call("concat", lit(" "), call("rewrite_local", var("next"))))))),
                       (words,), call("seq_length", words))
    rewrite_def = definition("rewrite", "combinator", rewrite_body,
                             CombinatorSpec("rewrite", ("transform", "words"), ("transform",), rewrite_body), 2)

    remaining, inside = var("remaining"), var("inside")
    entry = call("seq_head", remaining)
    starts_body = rec("scan_starts", ("remaining", "inside"),
                      choose(call("seq_is_empty", remaining), sequence(),
                             choose(call("equal", call("second", entry), lit(" ")),
                                    call("scan_starts", call("seq_tail", remaining), lit(False)),
                                    choose(inside, call("scan_starts", call("seq_tail", remaining), lit(True)),
                                           call("seq_cons", call("first", entry),
                                                call("scan_starts", call("seq_tail", remaining), lit(True)))))),
                      (call("chars", var("text")), lit(False)), call("seq_length", remaining))
    starts_def = observation("starts", ("text",), starts_body, 1)

    entries = var("entries")
    item = call("seq_head", entries)
    label = call("first", item)
    cost = call("second", item)
    valid_label = choose(call("card_is", label, lit("Word"), lit("val")),
                         choose(call("is_text", call("Word.base", label)),
                                choose(call("equal", call("Word.base", label), lit("")), lit(False),
                                       choose(call("contains_space", call("Word.base", label)), lit(False), lit(True))),
                                lit(False)), lit(False))
    entry_valid = choose(valid_label,
                         choose(call("le", call("length", call("Word.base", label)), lit(8)),
                                choose(call("le", lit(1), cost), call("le", cost, lit(9)), lit(False)), lit(False)), lit(False))
    lex_valid = choose(call("seq_is_empty", entries), lit(True),
                       choose(entry_valid,
                              let("tail", call("seq_tail", entries),
                                  choose(call("seq_is_empty", var("tail")), lit(True),
                                         choose(call("equal", label, call("first", call("seq_head", var("tail")))),
                                                lit(False), call("lex_valid", var("tail"))))), lit(False)))
    lex_check = choose(call("seq_valid", current),
                       choose(call("le", call("seq_length", current), lit(16)),
                              rec("lex_valid", ("entries",), lex_valid,
                                  (call("seq_sort", current),), call("seq_length", entries)), lit(False)), lit(False))
    lex_def = Definition("Lex", "object", "invented", 2,
                         tuple(sorted(n.references(lex_check) | n.references(call("seq_sort", current)))),
                         ObjectSpec("Lex", "refine", base="host_list", valid=lex_check,
                                    canon=call("seq_sort", current), sealed=True,
                                    interface=("Lex.make", "Lex.base")), None)

    position, entries = var("position"), var("entries")
    pair = call("seq_head", entries)
    word_text = call("Word.base", call("first", pair))
    end = call("add", position, call("length", word_text))
    edge = call("span", position, end, call("first", pair), call("second", pair))
    matching = choose(call("le", end, call("length", var("text"))),
                      choose(call("equal", call("slice_text", var("text"), position, end), word_text),
                             call("seq_cons", edge, call("scan_entries", call("seq_tail", entries), position)),
                             call("scan_entries", call("seq_tail", entries), position)),
                      call("scan_entries", call("seq_tail", entries), position))
    scan_entries = rec("scan_entries", ("entries", "position"),
                       choose(call("seq_is_empty", entries), sequence(), matching),
                       (call("Lex.base", var("dictionary")), position), call("seq_length", entries))
    rest, sorted_edges = var("rest"), var("sorted_edges")
    current_edge = call("seq_head", rest)
    next_edge = call("seq_head", sorted_edges)
    before = choose(call("less", call("span_end", current_edge), call("span_end", next_edge)), lit(True),
                    choose(call("equal", call("span_end", current_edge), call("span_end", next_edge)),
                           call("less", call("span_start", current_edge), call("span_start", next_edge)), lit(False)))
    insert = rec("insert_edge", ("sorted_edges",),
                 choose(call("seq_is_empty", sorted_edges), sequence(current_edge),
                        choose(before, call("seq_cons", current_edge, sorted_edges),
                               call("seq_cons", next_edge, call("insert_edge", call("seq_tail", sorted_edges))))),
                 (var("acc"),), call("seq_length", sorted_edges))
    sort_edges = rec("sort_edges", ("rest", "acc"),
                     choose(call("seq_is_empty", rest), var("acc"),
                            call("sort_edges", call("seq_tail", rest), insert)),
                     (var("edges"), sequence()), call("seq_length", rest))
    sorted_def = operation("sort_edges", ("edges",), sort_edges, 1)
    edges_body = choose(call("contains_space", var("text")), lit(Bottom("lattice_input")),
                        call("sort_edges", rec("scan_positions", ("position",),
                            choose(call("equal", position, call("length", var("text"))), sequence(),
                                   call("seq_merge", scan_entries, call("scan_positions", call("add", position, lit(1))))),
                            (lit(0),), call("sub_nat", call("length", var("text")), position))))
    edges_def = operation("edges", ("text", "dictionary"), edges_body, 3)

    spans, state = var("spans"), var("state")
    edge = call("seq_head", spans)
    routes_body = let("spans", call("sort_edges", var("spans")),
                  let("state", call("seq_set", call("seq_repeat", var("zero"), call("add", var("size"), lit(1))), lit(0), var("unit")),
                      rec("fold_routes", ("spans", "state"),
                          choose(call("seq_is_empty", spans), call("seq_get", state, var("size")),
                                 choose(call("le", call("span_end", edge), var("size")),
                                        call("fold_routes", call("seq_tail", spans),
                                      call("seq_set", state, call("span_end", edge),
                                           call("merge", call("seq_get", state, call("span_end", edge)),
                                                call("extend", call("seq_get", state, call("span_start", edge)), edge)))),
                                        lit(Bottom("span")))),
                          (var("spans"), var("state")), call("seq_length", spans))))
    routes_def = definition("routes", "combinator", routes_body,
                            CombinatorSpec("routes", ("extend", "merge", "spans", "size", "zero", "unit"),
                                           ("extend", "merge"), routes_body), 2)

    identity_copy_def = operation("identity_copy", ("item",), call("identity", var("item")), 1)
    count_def = operation("keep_count", ("count", "edge"), var("count"), 1)
    count_copy_def = operation("keep_count_copy", ("count", "edge"), call("keep_count", var("count"), var("edge")), 2)
    add_copy_def = operation("add_copy", ("left", "right"), call("add", var("left"), var("right")), 1)
    parses_body = call("routes", lit(kernel.FnRef("keep_count")), lit(kernel.FnRef("add")),
                       call("edges", call("public_text", var("text")), var("dictionary")),
                       call("length", call("public_text", var("text"))), lit(0), lit(1))
    parses_def = observation("parses", ("text", "dictionary"), parses_body, 4)

    cost_def = operation("add_cost", ("value", "edge"),
                         choose(call("equal", var("value"), lit(NONE)), lit(NONE),
                                call("add", var("value"), call("span_cost", var("edge")))), 1)
    minimum = choose(call("equal", var("left"), lit(NONE)), var("right"),
                     choose(call("equal", var("right"), lit(NONE)), var("left"),
                            choose(call("less", var("left"), var("right")), var("left"), var("right"))))
    minimum_def = operation("min_cost", ("left", "right"), minimum, 1)
    best_body = call("routes", lit(kernel.FnRef("add_cost")), lit(kernel.FnRef("min_cost")),
                     call("edges", call("public_text", var("text")), var("dictionary")),
                     call("length", call("public_text", var("text"))), lit(NONE), lit(0))
    best_def = observation("best", ("text", "dictionary"), best_body, 4)

    tally_cost = call("first", var("value"))
    tally_def = operation("add_tally", ("value", "edge"),
                          choose(call("equal", tally_cost, lit(NONE)), call("pair", lit(NONE), lit(0)),
                                 call("pair", call("add", tally_cost, call("span_cost", var("edge"))),
                                      call("second", var("value")))), 1)
    left_cost, right_cost = call("first", var("left")), call("first", var("right"))
    min_tally_def = operation("min_tally", ("left", "right"),
                              choose(call("equal", left_cost, lit(NONE)), var("right"),
                                     choose(call("equal", right_cost, lit(NONE)), var("left"),
                                            choose(call("less", left_cost, right_cost), var("left"),
                                                   choose(call("less", right_cost, left_cost), var("right"),
                                                          call("pair", left_cost, call("add", call("second", var("left")),
                                                                                      call("second", var("right")))))))), 1)
    optimal_body = call("second", call("routes", lit(kernel.FnRef("add_tally")),
                                       lit(kernel.FnRef("min_tally")),
                                       call("edges", call("public_text", var("text")), var("dictionary")),
                                       call("length", call("public_text", var("text"))),
                                       call("pair", lit(NONE), lit(0)), call("pair", lit(0), lit(1))))
    optimal_def = observation("optimal_count", ("text", "dictionary"), optimal_body, 4)

    parse_source = call("first", current)
    parse_pair = call("second", current)
    parse_lex, parse_words = call("first", parse_pair), call("second", parse_pair)
    pieces = var("pieces")
    concat_words = rec("join_parse", ("pieces",),
                       choose(call("seq_is_empty", pieces), lit(""),
                              call("concat", call("Word.base", call("seq_head", pieces)),
                                   call("join_parse", call("seq_tail", pieces)))),
                       (parse_words,), call("seq_length", pieces))
    candidate = var("candidate")
    entries = var("entries")
    contains_word = rec("lookup", ("entries",),
                        choose(call("seq_is_empty", entries), lit(False),
                               choose(call("equal", candidate, call("first", call("seq_head", entries))), lit(True),
                                      call("lookup", call("seq_tail", entries)))),
                        (call("Lex.base", parse_lex),), call("seq_length", entries))
    remaining = var("remaining")
    words_in_lex = rec("check_words", ("remaining",),
                       choose(call("seq_is_empty", remaining), lit(True),
                              let("candidate", call("seq_head", remaining),
                                  choose(call("card_is", candidate, lit("Word"), lit("val")),
                                         choose(let("x", call("Word.base", candidate), word_valid),
                                                choose(contains_word, call("check_words", call("seq_tail", remaining)),
                                                       lit(False)), lit(False)), lit(False)))),
                       (parse_words,), call("seq_length", remaining))
    parse_valid = choose(call("card_is", current, lit("Pair"), lit("pair")),
                         choose(call("card_is", parse_pair, lit("Pair"), lit("pair")),
                                choose(call("is_text", parse_source),
                                       choose(call("seq_valid", parse_words),
                                              choose(call("card_is", parse_lex, lit("Lex"), lit("val")),
                                                     choose(let("x", call("Lex.base", parse_lex), lex_check),
                                                            choose(call("equal", call("seq_sort", call("Lex.base", parse_lex)),
                                                                        call("Lex.base", parse_lex)),
                                                                   choose(call("equal", parse_source, concat_words),
                                                                          words_in_lex, lit(False)), lit(False)),
                                                            lit(False)),
                                                     lit(False)), lit(False)), lit(False)), lit(False)), lit(False))
    parse_def = Definition("Parse", "object", "invented", 3, tuple(sorted(n.references(parse_valid))),
                           ObjectSpec("Parse", "refine", base="host_pair", valid=parse_valid,
                                      sealed=True, interface=("Parse.make", "Parse.base")), None)

    position, index, selected = var("position"), var("index"), var("selected")
    remaining = var("remaining")
    edge = call("seq_head", remaining)
    suffix = call("slice_text", var("text"), call("span_end", edge), call("length", var("text")))
    prefix = call("slice_text", var("text"), position, call("length", var("text")))
    candidate = call("best", suffix, var("dictionary"))
    count = call("optimal_count", suffix, var("dictionary"))
    best_now = call("best", prefix, var("dictionary"))
    edge_good = choose(call("equal", candidate, lit(NONE)), lit(False),
                       call("equal", call("add", call("span_cost", edge), candidate), best_now))
    move = call("unrank", call("span_end", edge), index,
                call("seq_append", selected, call("span_word", edge)))
    scan = rec("scan_outgoing", ("remaining", "index"),
               choose(call("seq_is_empty", remaining), lit(Bottom("index")),
                      choose(call("equal", call("span_start", edge), position),
                             choose(edge_good, choose(call("less", index, count), move,
                                                      call("scan_outgoing", call("seq_tail", remaining),
                                                           call("sub_nat", index, count))),
                                    call("scan_outgoing", call("seq_tail", remaining), index)),
                             call("scan_outgoing", call("seq_tail", remaining), index))),
               (call("edges", var("text"), var("dictionary")), var("index")),
               call("seq_length", remaining))
    kth_body = choose(call("is_nat", var("rank")),
                      choose(call("less", var("rank"), call("optimal_count", var("text"), var("dictionary"))),
                      rec("unrank", ("position", "index", "selected"),
                          choose(call("equal", position, call("length", var("text"))),
                                 call("Parse.make", call("pair", var("text"), call("pair", var("dictionary"), selected))),
                                 scan),
                          (lit(0), var("rank"), sequence()),
                          call("sub_nat", call("length", var("text")), position)), lit(Bottom("index"))),
                      lit(Bottom("index")))
    kth_def = operation("kth_optimal", ("text", "dictionary", "rank"), kth_body, 5)

    return (word_def, space_def, split_def, public_def, identity_copy_def, rewrite_def, starts_def,
            lex_def, sorted_def, edges_def,
            count_def, count_copy_def, add_copy_def, routes_def,
            parses_def, cost_def, minimum_def, best_def, tally_def, min_tally_def,
            optimal_def, parse_def, kth_def)


TOWER = ("Word", "split", "rewrite", "starts", "Lex", "edges", "routes", "parses", "best",
         "optimal_count", "Parse", "kth_optimal")


@lru_cache(maxsize=1)
def reference_module():
    import importlib.util
    import sys
    from pathlib import Path

    path = Path(__file__).resolve().parents[4] / "worlds/catalogue/depth/text.py"
    spec = importlib.util.spec_from_file_location("opulse_text_depth_reference", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def oracle_value(value):
    reference = reference_module()
    if isinstance(value, reference.Word):
        return word(value.value)
    if isinstance(value, reference.Lex):
        return lex(*((item.value, weight) for item, weight in value.entries))
    if isinstance(value, reference.Span):
        return Card("Span", "span", (value.start, value.end, word(value.word.value), value.cost))
    if isinstance(value, reference.Parse):
        return Card("Parse", "val", (Card("Pair", "pair", (value.source,
                    Card("Pair", "pair", (oracle_value(value.lexicon),
                         Card("List", "list", tuple(oracle_value(item) for item in value.words)))))),))
    if isinstance(value, (tuple, list)):
        return Card("List", "list", tuple(oracle_value(item) for item in value))
    return NONE if value is None else value


def oracle_lex(dictionary):
    return reference_module().lex(*((item.fields[0].fields[0], item.fields[1])
                                    for item in dictionary.fields[0].fields))


def oracle_edges(edges):
    reference = reference_module()
    return tuple(reference.Span(item.fields[0], item.fields[1],
                                reference.Word(item.fields[2].fields[0]), item.fields[3]) for item in edges.fields)


def corpus():
    return tuple("".join(chars) for size in range(4) for chars in product("ab ", repeat=size)) + \
        tuple("".join(chars) for chars in list(product("ab ", repeat=4))[:16])


def dictionaries():
    names = ("a", "aa", "ab", "b", "ba", "bb")
    return tuple(lex(*((name, 1 + (position + offset) % 4)
                       for offset, name in enumerate(names) if (position >> offset) & 1))
                 for position in range(1, 51))


def verification_request(name, lib):
    reference = reference_module()
    texts = corpus()
    dictionaries_ = dictionaries()
    examples = tuple((text, dictionaries_[position % len(dictionaries_)])
                     for position, text in enumerate("".join(chars) for size in range(4)
                                                        for chars in product("ab", repeat=size)))
    examples += tuple(("".join(chars), dictionaries_[position]) for position, chars in
                      enumerate(list(product("ab", repeat=6))[:40]))
    edge = Card("Span", "span", (0, 1, word("a"), 1))
    if name == "Word":
        rows, callback = tuple((text,) for text in texts), None
    elif name == "contains_space":
        rows, callback = tuple((text,) for text in texts), lambda text: " " in text
    elif name == "split":
        rows, callback = tuple((text,) for text in texts), lambda text: oracle_value(reference.split(text))
    elif name == "public_text":
        rows, callback = tuple((text,) for text in texts), lambda text: text
    elif name == "identity_copy":
        rows, callback = tuple((position,) for position in range(50)), lambda item: item
    elif name == "rewrite":
        rows = tuple((oracle_value(reference.split(text)),) for text in texts)
        callback = lambda assignment, args: reference.rewrite(reference.identity, tuple(
            reference.Word(item.fields[0]) for item in args[0].fields))
    elif name == "starts":
        rows, callback = tuple((text,) for text in texts), lambda text: oracle_value(reference.starts(text))
    elif name == "Lex":
        rows = tuple((Card("List", "list", tuple(reversed(item.fields[0].fields)))
                      if position % 2 else item.fields[0],)
                     for position, item in enumerate(dictionaries_))
        rows += tuple((Card("List", "list", (Card("Pair", "pair", (word("a"), weight)),
                                           Card("Pair", "pair", (word("a"), weight + 1)))),)
                      for weight in range(1, 6))
        callback = None
    elif name == "sort_edges":
        rows = tuple((oracle_value(tuple(reversed(reference.edges(text, oracle_lex(dictionary))))
                      if position % 2 else reference.edges(text, oracle_lex(dictionary))),)
                     for position, (text, dictionary) in enumerate(examples))
        callback = lambda spans: oracle_value(sorted(oracle_edges(spans),
                                                    key=lambda item: (item.end, item.start, item.word.value)))
    elif name == "edges":
        rows, callback = examples, lambda text, dictionary: oracle_value(reference.edges(text, oracle_lex(dictionary)))
    elif name in ("keep_count", "keep_count_copy"):
        rows, callback = tuple((position, edge) for position in range(50)), lambda count, _: count
    elif name == "add_copy":
        rows, callback = tuple((position, position + 1) for position in range(50)), lambda left, right: left + right
    elif name == "routes":
        rows = tuple((oracle_value(tuple(reversed(reference.edges(text, oracle_lex(dictionary))))
                      if position % 2 else reference.edges(text, oracle_lex(dictionary))), len(text), 0, 1)
                     for position, (text, dictionary) in enumerate(examples))
        callback = lambda assignment, args: reference.routes(reference.keep_count, reference.add,
                                                               oracle_edges(args[0]), args[1], args[2], args[3])
    elif name == "parses":
        rows, callback = examples, lambda text, dictionary: reference.parses(text, oracle_lex(dictionary))
    elif name == "add_cost":
        rows = tuple((position, edge) for position in range(50))
        callback = lambda value, _: value + 1
    elif name == "min_cost":
        rows = tuple((position, 50 - position) for position in range(50))
        callback = min
    elif name == "best":
        rows, callback = examples, lambda text, dictionary: oracle_value(reference.best(text, oracle_lex(dictionary)))
    elif name == "add_tally":
        rows = tuple((Card("Pair", "pair", (position, position + 1)), edge) for position in range(50))
        callback = lambda value, _: Card("Pair", "pair", (value.fields[0] + 1, value.fields[1]))
    elif name == "min_tally":
        rows = tuple((Card("Pair", "pair", (position % 4, position + 1)),
                      Card("Pair", "pair", (position % 4, 2))) for position in range(50))
        callback = lambda left, right: Card("Pair", "pair", (left.fields[0], left.fields[1] + right.fields[1]))
    elif name == "optimal_count":
        rows, callback = examples, lambda text, dictionary: reference.optimal_count(text, oracle_lex(dictionary))
    elif name == "Parse":
        parse_lex = lex(("a", 2), ("b", 3), ("ab", 4), ("ba", 4), ("aa", 3))
        reference_lex = oracle_lex(parse_lex)
        rows = tuple((Card("Pair", "pair", (text, Card("Pair", "pair", (parse_lex,
                      oracle_value(reference.kth_optimal(text, reference_lex, 0).words))))),)
                     for size in range(6) for chars in product("ab", repeat=size)
                     for text in ("".join(chars),))
        rows += tuple((Card("Pair", "pair", (text, Card("Pair", "pair", (parse_lex,
                       Card("List", "list", (word("b"),)))))),)
                      for text in ("aa", "ab", "aab", "baa", "aba"))
        callback = None
    elif name == "kth_optimal":
        rows = tuple((text, dictionary, 0) for text, dictionary in examples)
        callback = lambda text, dictionary, rank: (oracle_value(reference.kth_optimal(text, oracle_lex(dictionary), rank))
                                                    if reference.kth_optimal(text, oracle_lex(dictionary), rank) is not None
                                                    else Bottom("index"))
    if name in ("Word", "split", "public_text", "starts"):
        scope_family = "all 40 strings of length <= 3 over a,b,space and first 16 length-4 strings"
    elif name == "rewrite":
        scope_family = "56 split-word lists from all length <= 3 and first 16 length-4 strings"
    elif name == "identity_copy":
        scope_family = "all integers 0..49"
    elif name == "Lex":
        scope_family = "50 dictionary masks 1..50 on six words (alternately reversed), plus five duplicate-word lists"
    elif name in ("sort_edges", "routes"):
        scope_family = ("55 edge lists from all binary strings length <= 3 and first 40 length-6 strings "
                        "with dictionary masks 1..50 by index; alternate lists reversed")
    elif name in ("keep_count", "keep_count_copy", "add_cost"):
        scope_family = "all integers 0..49 paired with the fixed span (0,1,Word<'a'>,1)"
    elif name == "add_copy":
        scope_family = "all integer pairs (n,n+1) for n=0..49"
    elif name == "min_cost":
        scope_family = "all integer pairs (n,50-n) for n=0..49"
    elif name == "add_tally":
        scope_family = "all tally pairs (n,n+1) for n=0..49 and fixed span (0,1,Word<'a'>,1)"
    elif name == "min_tally":
        scope_family = "all pairs ((n mod 4,n+1),(n mod 4,2)) for n=0..49"
    elif name == "Parse":
        scope_family = "all 63 binary strings length <= 5 with optimal certificates under one five-word lexicon, plus five invalid certificates"
    else:
        scope_family = ("55 paired inputs: all 15 binary strings length <= 3 and first 40 "
                        "length-6 binary strings, with dictionary masks 1..50 by index")
    description = f"bounded: {scope_family} ({len(rows)} evaluations)"
    request = VerifyRequest("bounded", rows, {"domain": description, "description": description,
                                            "size": len(rows)}, reference=callback)
    if name == "rewrite":
        request.scope["op_family"] = ["identity", "identity_copy"]
        request.extra["op_family"] = ("identity", "identity_copy")
    elif name == "routes":
        family = {"extend": ("keep_count", "keep_count_copy"), "merge": ("add", "add_copy")}
        request.scope["op_family"] = {key: list(values) for key, values in family.items()}
        request.extra["op_family"] = family
    return request


def build_library_until(stop_after):
    lib = new_library()
    for definition_ in definitions():
        name = definition_.name
        lib.write(definition_)
        lib.check(name)
        request = verification_request(name, lib)
        if definition_.kind == "object":
            lib.make_callable(name, request.domain[:1])
        elif name == "rewrite":
            lib.make_callable(name, ((kernel.FnRef("identity"), request.domain[0][0]),))
        elif name == "routes":
            lib.make_callable(name, ((kernel.FnRef("keep_count"), kernel.FnRef("add"), *request.domain[0]),))
        else:
            lib.make_callable(name, request.domain[:1])
        lib.verify(name, request)
        lib.account(name)
        lib.promote(name, Contract(f"Equal to independent finite reference over {len(request.domain)} public inputs."))
        if name == stop_after:
            break
    return lib


@lru_cache(maxsize=1)
def build_library():
    return build_library_until(None)
