"""Kernel-written finite expression parsing and its dependent inventions."""

import importlib.util
from dataclasses import replace
from itertools import product
from pathlib import Path

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
from opulse.atoms.values import Bottom, Card, boolean

from . import hosts
from .world import new_library


def v(name):
    return n.Var(name)


def lit(value):
    return n.Lit(value)


def call(name, *args):
    return n.Call(name, args)


def branch(test, yes, no):
    return n.Case(((n.Test(test), yes),), no)


def let(name, value, body):
    return n.Let(name, value, body)


def same(left, right):
    return call("eq", left, lit(right))


def fail(reason):
    return call("fail", lit(reason))


def plus(left, right):
    return call("add", left, right)


def minus(left, right):
    return call("sub", left, right)


def size(value):
    return call("length", value)


def index(value, position):
    return call("at", value, position)


def make(name, kind, spec, body, layer=None):
    if layer is None:
        raise ValueError("definition layer is required")
    if body is None:
        refs = set()
        for node in (spec.valid, spec.canon):
            if node is not None:
                refs.update(n.references(node))
    else:
        refs = n.references(body) - (set(spec.op_params) if kind == "combinator" else set())
    return Definition(name, kind, "invented", layer, tuple(sorted(refs)), spec, body)


def op(name, params, body, layer, output="any"):
    spec = OperationSpec(name, "transform", tuple(Edge("any", "bottom", param) for param in params),
                         Edge(output), f"Kernel-defined {name} over public grammar data.",
                         extra={"input_names": list(params)})
    return make(name, "operation", spec, body, layer)


def obs(name, body, layer):
    spec = ObservationSpec(name, (), body)
    return make(name, "observation", spec, body, layer)


def comb(name, params, op_params, body, layer):
    spec = CombinatorSpec(name, params, op_params, body)
    return make(name, "combinator", spec, body, layer)


def definitions():
    tree = v("x")
    current = v("current")
    tree_tag = call("tag", current)
    binary = branch(call("check_tree", call("field", current, lit(0))),
                    call("check_tree", call("field", current, lit(1))), lit(False))
    leaf = branch(call("le", lit(1), call("field", current, lit(0))),
                  call("le", call("field", current, lit(0)), lit(9)), lit(False))
    valid_cell = branch(same(tree_tag, "E"), lit(False),
                        branch(same(tree_tag, "num"), leaf,
                               branch(same(tree_tag, "group"),
                                      call("check_tree", call("field", current, lit(0))),
                                      branch(same(tree_tag, "+"), binary,
                                             branch(same(tree_tag, "*"), binary, lit(False))))))
    valid_body = n.Rec("check_tree", ("current",), valid_cell, (tree,), size(current))
    # A finite structural bound is checked by the given expander on every legitimate draft.
    legal_tree = branch(valid_body,
                        branch(call("le", size(tree), lit(40)),
                               let("public_word", call("yield_probe", tree),
                                   call("le", size(v("public_word")), lit(48))), lit(False)), lit(False))
    expr = ObjectSpec("ExprTree", "refine", base="Draft", valid=legal_tree,
                      sealed=True, interface=("ExprTree.make",))
    yield make("ExprTree", "object", expr, None, 1)

    word = v("w")
    pos, depth, cuts = v("position"), v("depth"), v("cuts")
    token = index(word, pos)
    next_pos = plus(pos, lit(1))
    go = lambda new_depth, new_cuts: call("scan", next_pos, new_depth, new_cuts)
    scan_body = branch(call("eq", pos, size(word)), cuts,
        let("token", token,
            branch(same(v("token"), "("), go(plus(depth, lit(1)), cuts),
            branch(same(v("token"), ")"), go(minus(depth, lit(1)), cuts),
            branch(same(depth, 0),
                   branch(same(v("token"), "+"), go(depth, call("append", cuts, pos)),
                   branch(same(v("token"), "*"), go(depth, call("append", cuts, pos)),
                          go(depth, cuts))), go(depth, cuts))))))
    split_body = n.Rec("scan", ("position", "depth", "cuts"), scan_body,
                       (lit(0), lit(0), call("list0")), minus(size(word), pos))
    yield op("split", ("w",), split_body, 1, "List")

    span = v("span")
    cell_cuts = v("positions")
    cell_index = v("position")
    cell_result = v("result")
    split_pos = index(cell_cuts, cell_index)
    cell_left = call("recurse", call("slice_word", span, lit(0), split_pos))
    cell_right = call("recurse", call("slice_word", span, plus(split_pos, lit(1)), size(span)))
    cell_join = call("join", index(span, split_pos), cell_left, cell_right)
    loop = n.Rec("walk_splits", ("position", "result"),
                 branch(call("eq", cell_index, size(cell_cuts)), cell_result,
                        call("walk_splits", plus(cell_index, lit(1)),
                             call("merge", cell_result, cell_join))),
                 (lit(0), v("initial")), minus(size(cell_cuts), cell_index))
    group = branch(same(index(span, lit(0)), "("),
                   branch(same(index(span, minus(size(span), lit(1))), ")"),
                          call("merge", call("zero_slot"), call("wrap", call("recurse",
                               call("slice_word", span, lit(1), minus(size(span), lit(1)))))),
                          call("zero_slot")), call("zero_slot"))
    chart_cell = branch(same(size(span), 0), call("zero_slot"),
                        branch(same(size(span), 1),
                               branch(call("is_int", index(span, lit(0))),
                                      call("leaf", index(span, lit(0))), call("zero_slot")),
                               let("positions", call("split", span),
                                   let("initial", group, loop))))
    chart_body = n.Rec("recurse", ("span",), chart_cell, (word,), size(span), memo=True)
    yield op("one", ("number",), lit(1), 1, "int")
    yield op("identity", ("item",), v("item"), 1)
    yield op("multiply", ("operator", "left", "right"), call("mul", v("left"), v("right")), 1, "int")
    yield op("combine_count", ("left", "right"), plus(v("left"), v("right")), 1, "int")
    yield op("zero", (), lit(0), 1, "int")
    yield op("one_alt", ("number",), call("add", lit(1), lit(0)), 1, "int")
    yield op("identity_alt", ("item",), call("field", call("pair", v("item"), lit(0)), lit(0)), 1)
    yield op("multiply_alt", ("operator", "left", "right"),
             call("mul", v("right"), v("left")), 1, "int")
    yield op("combine_count_alt", ("left", "right"),
             call("add", v("right"), v("left")), 1, "int")
    yield op("zero_alt", (), call("sub", lit(1), lit(1)), 1, "int")
    yield comb("chart", ("leaf", "join", "wrap", "merge", "zero_slot", "w"),
               ("leaf", "join", "wrap", "merge", "zero_slot"), chart_body, 2)
    count = call("chart", lit(kernel.FnRef("one")), lit(kernel.FnRef("multiply")),
                 lit(kernel.FnRef("identity")), lit(kernel.FnRef("combine_count")),
                 lit(kernel.FnRef("zero")), word)
    yield obs("parse_count", count, 3)

    yield obs("ambiguous", call("lt", lit(1), call("parse_count", word)), 4)

    offset, cut_index, cuts = v("offset"), v("cut_index"), v("cuts")
    span, rank = v("span"), v("rank")
    cut = index(cuts, cut_index)
    left = call("slice_word", span, lit(0), cut)
    right = call("slice_word", span, plus(cut, lit(1)), size(span))
    left_count, right_count = v("left_count"), v("right_count")
    block = call("mul", left_count, right_count)
    chosen = call("make_draft", index(span, cut),
                  call("list2", call("unrank_local", left, call("div", offset, right_count)),
                       call("unrank_local", right, call("mod", offset, right_count))))
    find_cut = n.Rec("find_cut", ("cut_index", "offset"),
                     branch(call("eq", cut_index, size(cuts)), fail("rank"),
                            let("left", left, let("right", right,
                            let("left_count", call("parse_count", v("left")),
                            let("right_count", call("parse_count", v("right")),
                            branch(call("lt", offset, block), chosen,
                                   call("find_cut", plus(cut_index, lit(1)), minus(offset, block)))))))),
                     (lit(0), rank), minus(size(cuts), cut_index))
    leaf = call("make_draft", lit("num"), call("list1", index(span, lit(0))))
    group_node = call("make_draft", lit("group"), call("list1", call("unrank_local",
                           call("slice_word", span, lit(1), minus(size(span), lit(1))), rank)))
    unrank_cell = branch(call("eq", size(span), lit(1)), leaf,
                         let("cuts", call("split", span),
                             branch(call("eq", size(cuts), lit(0)),
                                    branch(same(index(span, lit(0)), "("), group_node,
                                           fail("rank")), find_cut)))
    unrank_body = branch(call("lt", rank, lit(0)), fail("rank"),
                         branch(call("le", call("parse_count", word), rank), fail("rank"),
                                call("ExprTree.make", n.Rec("unrank_local", ("span", "rank"),
                                    unrank_cell, (word, rank), size(span)))))
    yield op("unrank", ("w", "rank"), unrank_body, 4, "ExprTree")

    witness_word = v("w")
    a = call("unrank", witness_word, lit(0))
    b = call("unrank", witness_word, lit(1))
    first_tree = call("field", v("x"), lit(1))
    second_tree = call("field", v("x"), lit(2))
    witness_valid = let("w", call("field", v("x"), lit(0)), branch(call("ambiguous", v("w")),
        branch(call("eq", first_tree, a), call("eq", second_tree, b),
               branch(call("eq", first_tree, b), call("eq", second_tree, a), lit(False))),
        lit(False)))
    witness = ObjectSpec("Ambiguity", "refine", base="Witness", valid=witness_valid,
                         sealed=True, interface=("Ambiguity.make",))
    yield make("Ambiguity", "object", witness, None, 5)

    yield op("arithmetic", ("operator", "left", "right"),
             branch(same(v("operator"), "+"), plus(v("left"), v("right")),
                    call("mul", v("left"), v("right"))), 1, "int")
    yield op("arithmetic_alt", ("operator", "left", "right"),
             branch(same(v("operator"), "*"), call("mul", v("right"), v("left")),
                    plus(v("right"), v("left"))), 1, "int")
    fold_tree = call("ExprTree.base", v("t"))
    cell = v("cell")
    cell_tag = call("tag", cell)
    fold_cell = branch(same(cell_tag, "num"), call("leaf", call("field", cell, lit(0))),
        branch(same(cell_tag, "group"), call("wrap", call("fold_local", call("field", cell, lit(0)))),
               call("join", cell_tag, call("fold_local", call("field", cell, lit(0))),
                    call("fold_local", call("field", cell, lit(1))))))
    fold_body = n.Rec("fold_local", ("cell",), fold_cell, (fold_tree,), size(cell))
    yield comb("fold", ("leaf", "join", "wrap", "t"), ("leaf", "join", "wrap"), fold_body, 2)

    yield op("singleton_value", ("number",),
             call("list1", call("fold", lit(kernel.FnRef("identity")),
                  lit(kernel.FnRef("arithmetic")), lit(kernel.FnRef("identity")),
                  call("ExprTree.make", call("make_draft", lit("num"), call("list1", v("number")))))), 3, "List")
    yield op("empty_values", (), call("list0"), 1, "List")
    yield op("merge_values", ("left", "right"), call("concat", v("left"), v("right")), 1, "List")

    left_values, right_values = v("left"), v("right")
    outer_index, inner_index = v("outer_index"), v("inner_index")
    inner_result = v("result")
    joined_value = call("arithmetic", v("operator"), index(left_values, outer_index),
                        index(right_values, inner_index))
    inner_loop = n.Rec("inner", ("inner_index", "result"),
                       branch(call("eq", inner_index, size(right_values)), inner_result,
                              call("inner", plus(inner_index, lit(1)),
                                   call("append", inner_result, joined_value))),
                       (lit(0), v("result")), minus(size(right_values), inner_index))
    outer_loop = n.Rec("outer", ("outer_index", "result"),
                       branch(call("eq", outer_index, size(left_values)), inner_result,
                              call("outer", plus(outer_index, lit(1)), inner_loop)),
                       (lit(0), call("list0")), minus(size(left_values), outer_index))
    yield op("product_values", ("operator", "left", "right"), outer_loop, 2, "List")

    ordered = v("ordered")
    idx = v("position")
    current_value = v("value")
    count_value = v("count")
    collected = v("collected")
    pairs = n.Rec("group_values", ("position", "value", "count", "collected"),
                  branch(call("eq", idx, size(ordered)),
                         call("append", collected, call("pair", current_value, count_value)),
                         branch(call("eq", index(ordered, idx), current_value),
                                call("group_values", plus(idx, lit(1)), current_value,
                                     plus(count_value, lit(1)), collected),
                                call("group_values", plus(idx, lit(1)), index(ordered, idx), lit(1),
                                     call("append", collected, call("pair", current_value, count_value))))),
                  (lit(1), index(ordered, lit(0)), lit(1), call("list0")),
                  minus(size(ordered), idx))
    hist_body = let("ordered", call("sorted_items", v("items")),
                    branch(same(size(ordered), 0), call("hist", call("list0")), call("hist", pairs)))
    yield op("histogram", ("items",), hist_body, 1, "Hist")

    all_values = call("chart", lit(kernel.FnRef("singleton_value")),
                      lit(kernel.FnRef("product_values")), lit(kernel.FnRef("identity")),
                      lit(kernel.FnRef("merge_values")), lit(kernel.FnRef("empty_values")), word)
    yield obs("value_hist", call("histogram", all_values), 4)

    hist_items = v("hist_items")
    hist_index = v("position")
    extract = n.Rec("extract", ("position", "result"),
                    branch(call("eq", hist_index, size(hist_items)), v("result"),
                           call("extract", plus(hist_index, lit(1)),
                                call("append", v("result"),
                                     call("field", index(hist_items, hist_index), lit(0))))),
                    (lit(0), call("list0")), minus(size(hist_items), hist_index))
    yield op("hist_keys", ("hist_items",), extract, 1, "List")
    gap_body = let("keys", call("hist_keys", call("value_hist", word)),
                   branch(same(size(v("keys")), 0), fail("no_parse"),
                          minus(call("maximum", v("keys")), call("minimum", v("keys")))))
    yield op("gap", ("w",), gap_body, 5, "int")

    position, remaining, parts = v("position"), v("remaining"), v("parts")
    empty = call("list0")
    numeral = plus(lit(1), call("mod", position, lit(3)))
    next_parts = call("append", parts, numeral)
    candidate = call("word_new", next_parts)
    last = branch(same(remaining, 0),
                  let("candidate", candidate,
                      branch(call("ambiguous", v("candidate")),
                             branch(call("eq", call("gap", v("candidate")), v("target")),
                                    v("candidate"), empty), empty)), empty)
    plus_choice = call("search", plus(position, lit(1)), remaining,
                       call("append", next_parts, lit("+")))
    star_choice = call("search", plus(position, lit(1)), minus(remaining, lit(1)),
                       call("append", next_parts, lit("*")))
    search_cell = branch(call("eq", position, minus(v("n"), lit(1))), last,
                         branch(call("le", lit(1), remaining),
                                let("star_result", star_choice,
                                    branch(call("eq", v("star_result"), empty), plus_choice,
                                           v("star_result"))), plus_choice))
    search_body = n.Rec("search", ("position", "remaining", "parts"), search_cell,
                        (lit(0), v("stars"), empty), minus(v("n"), position))
    bounds = branch(call("lt", v("target"), lit(0)), fail("target"),
                    branch(call("lt", v("n"), lit(2)), fail("family"),
                           branch(call("lt", lit(12), v("n")), fail("family"),
                                  branch(call("lt", v("stars"), lit(0)), fail("family"),
                                         branch(call("le", v("n"), v("stars")),
                                                fail("family"),
                                                let("candidate", search_body,
                                                    branch(call("eq", v("candidate"), empty),
                                                           fail("none"), v("candidate"))))))))
    yield op("invert_gap", ("target", "n", "stars"), bounds, 6, "Word")


def oracle():
    path = Path(__file__).resolve().parents[4] / "worlds/catalogue/depth/grammar.py"
    spec = importlib.util.spec_from_file_location("grammar_depth_reference", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def word_from(tokens):
    return hosts.word(*tokens)


def hist_from(values):
    return Card("Hist", "entries", tuple(Card("Pair", "pair", item)
                                           for item in sorted(values.items())))


def list_from(values):
    return Card("List", "items", tuple(values))


def _reference(name, reference, lib):
    def run(*args):
        if name == "split":
            return list_from(reference.split(args[0].fields))
        if name == "parse_count":
            return reference.parse_count(args[0].fields)
        if name == "ambiguous":
            return boolean(reference.ambiguous(args[0].fields))
        if name == "unrank":
            try:
                return Card("ExprTree", "val", (hosts.to_card(reference.unrank(args[0].fields, args[1])),))
            except ValueError:
                return Bottom("rank")
        if name == "value_hist":
            return hist_from(reference.value_hist(args[0].fields))
        if name == "gap":
            return reference.gap(args[0].fields)
        if name == "invert_gap":
            result = reference.invert_gap(*args)
            return word_from(result) if result is not None else Bottom("none")
        if name in ("one", "one_alt"):
            return 1
        if name in ("zero", "zero_alt"):
            return 0
        if name in ("identity", "identity_alt"):
            return args[0]
        if name in ("multiply", "multiply_alt"):
            return args[1] * args[2]
        if name in ("combine_count", "combine_count_alt"):
            return args[0] + args[1]
        if name in ("arithmetic", "arithmetic_alt"):
            return args[1] + args[2] if args[0] == "+" else args[1] * args[2]
        if name == "singleton_value":
            return list_from((args[0],))
        if name == "empty_values":
            return list_from(())
        if name == "merge_values":
            return list_from(args[0].fields + args[1].fields)
        if name == "product_values":
            return list_from((a + b if args[0] == "+" else a * b)
                             for a in args[1].fields for b in args[2].fields)
        if name == "histogram":
            from collections import Counter

            return hist_from(Counter(args[0].fields))
        if name == "hist_keys":
            return list_from(pair.fields[0] for pair in args[0].fields)
        raise ValueError(f"no independent reference for {name}")

    return run


def _families(name):
    if name == "chart":
        slots = (("one", "one_alt"), ("multiply", "multiply_alt"),
                 ("identity", "identity_alt"), ("combine_count", "combine_count_alt"),
                 ("zero", "zero_alt"))
        names = ("leaf", "join", "wrap", "merge", "zero_slot")
    else:
        slots = (("identity", "identity_alt"), ("arithmetic", "arithmetic_alt"),
                 ("identity", "identity_alt"))
        names = ("leaf", "join", "wrap")
    return [dict(zip(names, choice)) for choice in product(*slots)]


def _sample(definition, lib):
    name = definition.name
    sample = word_from((1, "+", 2, "*", 3))
    if name == "ExprTree":
        return (hosts.to_card(("num", 7)),)
    if name == "Ambiguity":
        return (Card("Witness", "triple", (sample,
                      lib.run("unrank", (sample, 0)).outcome.value,
                      lib.run("unrank", (sample, 1)).outcome.value)),)
    if name == "chart":
        return tuple(kernel.FnRef(item) for item in ("one", "multiply", "identity",
                                                      "combine_count", "zero")) + (sample,)
    if name == "fold":
        return tuple(kernel.FnRef(item) for item in ("identity", "arithmetic", "identity")) + (
            lib.run("unrank", (sample, 0)).outcome.value,)
    if name == "unrank":
        return sample, 1
    if name == "invert_gap":
        return 0, 2, 0
    if name in ("split", "parse_count", "ambiguous", "value_hist", "gap"):
        return (sample,)
    if name in ("one", "one_alt", "identity", "identity_alt", "singleton_value"):
        return (2,)
    if name in ("multiply", "multiply_alt", "arithmetic", "arithmetic_alt"):
        return ("+", 2, 3)
    if name == "product_values":
        return ("+", list_from((1, 2)), list_from((3,)))
    if name == "merge_values":
        return list_from((1,)), list_from((2,))
    if name == "combine_count" or name == "combine_count_alt":
        return 2, 3
    if name == "histogram":
        return (list_from((1, 1, 2)),)
    if name == "hist_keys":
        return (hist_from({2: 3, 4: 1}),)
    return ()


def _domains(reference, lib):
    words = tuple(word_from((a, operator, b, "+", c))
                  for a, operator, b, c in product(range(1, 4), ("+", "*"), range(1, 4), range(1, 4)))[:54]
    words += tuple(word_from(("(", a, "+", b, ")", "*", c))
                   for a, b, c in product(range(1, 4), repeat=3))
    tiny = words[:50]
    return words, tiny


def build_library(*, stop_after=None):
    reference = oracle()
    lib = new_library()
    words, tiny = _domains(reference, lib)
    for definition in definitions():
        name = definition.name
        lib.write(definition)
        lib.check(name)
        lib.make_callable(name, [_sample(definition, lib)])
        if definition.kind == "object":
            if name == "ExprTree":
                domain = tuple((hosts.to_card(reference.unrank(word.fields, rank)),)
                               for word in tiny for rank in (0, 1))
                domain += ((hosts.HOLE,),)
            else:
                domain = tuple((Card("Witness", "triple", (word,
                                 lib.run("unrank", (word, 0)).outcome.value,
                                 lib.run("unrank", (word, 1)).outcome.value)),) for word in tiny)
            description = ("100 finished trees from 50 three-numeral words and one unfinished draft"
                           if name == "ExprTree" else "50 ranked witness triples from three-numeral words")
            request = VerifyRequest("bounded", domain,
                                    {"domain": description, "size": len(domain),
                                     "description": "bounded to three numerals"})
            lib.verify(name, request)
        elif definition.kind == "combinator":
            family = _families(name)
            if name == "chart":
                inputs = tuple((word,) for word in tiny)
                expected = lambda assignment, args: reference.parse_count(args[0].fields)
            else:
                inputs = tuple((lib.run("unrank", (word, 0)).outcome.value,) for word in tiny)
                expected = lambda assignment, args: reference.eval_tree(hosts.from_card(args[0].fields[0]))
            op_family = {slot: sorted({assignment[slot] for assignment in family})
                         for slot in definition.spec.op_params}
            request = VerifyRequest("bounded", inputs,
                                    {"domain": f"50 public three-numeral inputs and {len(family)} algebra assignments (two operations per slot)",
                                     "size": len(inputs), "description": "bounded to three numerals",
                                     "op_family": op_family}, reference=expected,
                                    extra={"op_family": op_family})
            if name == "chart":
                operands = _sample(definition, lib)
                plain = kernel.Defn("chart_plain", definition.spec.params,
                                    replace(definition.body, memo=False), "combinator", definition.layer)
                memo_run = lib.run(name, operands)
                request.scope["memo_steps"] = memo_run.steps
                request.scope["memo_work"] = memo_run.work
                plain_run = kernel.call("chart_plain", operands, lib.scope().extend((plain,)))
                if plain_run.outcome != lib.run(name, operands).outcome:
                    raise ValueError("memo/plain recursion changed the chart result")
                request.scope["plain_steps"] = plain_run.steps
                request.scope["plain_work"] = plain_run.work
            lib.verify(name, request)
        else:
            if name == "invert_gap":
                domain = tuple((target, number, stars) for number, stars, target in
                               product(range(2, 5), range(4), range(9)) if stars < number)[:60]
            elif name == "unrank":
                domain = tuple((word, rank) for word in tiny for rank in (0, 1))
            elif name == "split" or name in ("parse_count", "ambiguous", "value_hist", "gap"):
                domain = tuple((word,) for word in words)
                if definition.kind == "observation":
                    domain += ((Card("Word", "tokens", tuple(words[0].fields)),),)
            elif name in ("one", "one_alt", "identity", "identity_alt", "singleton_value"):
                domain = tuple((number,) for number in range(1, 10))
            elif name in ("zero", "zero_alt", "empty_values"):
                domain = ((),)
            elif name in ("multiply", "multiply_alt", "arithmetic", "arithmetic_alt"):
                domain = tuple((operator, left, right) for operator, left, right in
                               product(("+", "*"), range(1, 8), range(1, 8)))
            elif name in ("combine_count", "combine_count_alt"):
                domain = tuple(product(range(1, 9), range(1, 9)))
            elif name == "merge_values":
                domain = tuple((list_from((left,)), list_from((right,))) for left, right in
                               product(range(1, 9), repeat=2))
            elif name == "product_values":
                domain = tuple((operator, list_from((left,)), list_from((right,)))
                               for operator, left, right in product(("+", "*"), range(1, 7), range(1, 7)))
            elif name == "histogram":
                domain = tuple((list_from((first, second, third)),) for first, second, third in
                               product(range(1, 5), repeat=3))
            elif name == "hist_keys":
                domain = tuple((hist_from({first: 1, second: 2}),) for first, second in
                               product(range(1, 9), repeat=2))
            else:
                raise ValueError(f"missing verification domain for {name}")
            descriptions = {
                "invert_gap": "60 target/number/star requests, with at most four numerals and target 0..8",
                "unrank": "50 three-numeral public words at each of ranks 0 and 1",
                "split": "54 plain and 27 grouped three-numeral words",
                "parse_count": "54 plain and 27 grouped three-numeral public words, plus an equal-view copy",
                "ambiguous": "54 plain and 27 grouped three-numeral public words, plus an equal-view copy",
                "value_hist": "54 plain and 27 grouped three-numeral public words, plus an equal-view copy",
                "gap": "54 plain and 27 grouped three-numeral public words",
                "one": "all nine digits 1..9", "one_alt": "all nine digits 1..9",
                "identity": "all nine digits 1..9", "identity_alt": "all nine digits 1..9",
                "singleton_value": "all nine digits 1..9",
                "zero": "one complete nullary evaluation", "zero_alt": "one complete nullary evaluation",
                "empty_values": "one complete nullary evaluation",
                "multiply": "98 operator and two-value inputs, values 1..7",
                "multiply_alt": "98 operator and two-value inputs, values 1..7",
                "arithmetic": "98 operator and two-value inputs, values 1..7",
                "arithmetic_alt": "98 operator and two-value inputs, values 1..7",
                "combine_count": "all 64 ordered pairs of values 1..8",
                "combine_count_alt": "all 64 ordered pairs of values 1..8",
                "merge_values": "all 64 singleton-list pairs of values 1..8",
                "product_values": "72 operator and singleton-list pairs of values 1..6",
                "histogram": "all 64 ordered length-three lists of values 1..4",
                "hist_keys": "all 64 distinct-key-map requests from values 1..8",
            }
            request = VerifyRequest("bounded", domain,
                                    {"domain": descriptions[name], "size": len(domain),
                                     "description": "bounded by the explicitly listed inputs"},
                                    reference=_reference(name, reference, lib))
            lib.verify(name, request)
        lib.account(name)
        lib.promote(name, Contract(guarantees="Exact kernel outcome for the stated finite verification family."))
        if name == stop_after:
            break
    return lib
