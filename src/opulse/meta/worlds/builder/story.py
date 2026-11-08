"""A finite, executable creation story for builder@1 (atoms-meta section 7)."""

import hashlib
import json
import re
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
from itertools import product as cartesian

from opulse.atoms import bridges, kernel, laws, library
from opulse.atoms import nodes as n
from opulse.atoms.library import atoms_digest
from opulse.atoms.spec import (
    BridgeSpec,
    CombinatorSpec,
    Contract,
    Definition,
    Edge,
    Evidence,
    LawSpec,
    ObjectSpec,
    OperationSpec,
)
from opulse.atoms.values import Bottom, Card, Ok, Unknown, encode, outcome_equal
from opulse.meta import code as C
from opulse.meta import engine
from opulse.meta.builder import world_value as V
from opulse.meta.builder.instantiate import extend, instantiate
from opulse.meta.builder.wf import wf
from opulse.meta.cards import promote_output
from opulse.meta.code_world import MeteredLibrary
from opulse.meta.export_util import input_hash
from opulse.meta.identity import Ledger
from opulse.meta.worlds.builder import hosts, world


def z(number):
    return Card("z", f"z{number}")


def tags():
    return [V.tag("domain", "math"), V.tag("modalities", ["text"]),
            V.tag("open_kinds", ["operation", "object", "observation", "combinator"]),
            V.tag("star_kind", "operation"), V.tag("reasoning", ["compute"]),
            V.tag("state", "stateless"), V.tag("outcomes", "deterministic"),
            V.tag("visibility", "partial"), V.tag("agents", "1"),
            V.tag("scale", "five residues and 25 input pairs"),
            V.tag("difficulty", "five levels from tables to verified composition"),
            V.tag("uses", ["teaching"])]


@lru_cache(maxsize=1)
def z5():
    """Twenty-five rows each for addition and multiplication, plus a probe."""
    def table(name, fn):
        return V.table(name, "combine", ["z", "z"], "z", [],
                       [V.row((z(a), z(b)), V.val(z(fn(a, b) % 5)))
                        for a, b in cartesian(range(5), repeat=2)])

    operations = [table("add5", lambda a, b: a + b), table("mul5", lambda a, b: a * b),
                    V.table("eq5", "decide", ["z", "z"], "bool", [],
                            [V.row([z(a), z(b)], V.val(Card("bool", "true" if a == b else "false")))
                             for a, b in cartesian(range(5), repeat=2)]),
                    V.table("identity", "transform", ["z"], "z", [],
                            [V.row([z(i)], V.val(z(i))) for i in range(5)])]
    base = V.world("z5", 1, [V.enum("z", [f"z{i}" for i in range(5)])], operations,
                   ["Var", "Lit", "Call", "Let", "Case", "Rec"], "measure", ["identity"],
                   "full_state", ["operation", "object", "observation", "combinator"], tags())
    decl, _ = instantiate(base)
    digests = {op.name: C.atom_digest(op) for op in decl.operations}
    a, b, c = (n.Var(name) for name in ("a", "b", "c"))
    expressions = {
        "add5_assoc": call("eq5", call("add5", call("add5", a, b), c),
                           call("add5", a, call("add5", b, c))),
        "mul5_distributes": call("eq5", call("mul5", a, call("add5", b, c)),
                                 call("add5", call("mul5", a, b), call("mul5", a, c))),
    }
    laws_in_world = [V.law(name, C.make_code(
        "law", C.sig_law((("a", "z"), ("b", "z"), ("c", "z"))), ("a", "b", "c"),
        expression, lambda name: C.Resolved(digest=digests[name])))
        for name, expression in expressions.items()]
    return V.world(*base.fields[:2], C.items(base.fields[2]), C.items(base.fields[3]),
                   C.items(base.fields[4]), base.fields[5], C.items(base.fields[6]),
                   base.fields[7], C.items(base.fields[8]), C.items(base.fields[9]),
                   laws=laws_in_world)


@lru_cache(maxsize=1)
def z5xbool():
    """Pair each residue with a bit; the zero-bit slice embeds Z5."""
    values = range(10)
    return V.world("z5xbool", 1, [V.enum("z", [f"z{i}" for i in range(5)]),
                                   V.range_sort("pair", 0, 9)],
                   [V.table("embed", "transform", ["z"], "pair", [],
                            [V.row([z(index)], V.val(2 * index)) for index in range(5)]),
                    V.table("add_pair", "combine", ["pair", "pair"], "pair", [],
                            [V.row([left, right], V.val(
                                2 * ((left // 2 + right // 2) % 5) + (left + right) % 2))
                             for left, right in cartesian(values, repeat=2)])],
                   ["Var", "Lit", "Call", "Let", "Case", "Rec"], "measure", [],
                   "full_state", ["operation", "object", "observation", "combinator"], tags())


def bridge_context():
    return bridges.BridgeContext(_DispatchWorld(z5()), _DispatchWorld(z5xbool()))


class _DispatchWorld(library.Library):
    """Bridge verification dispatches through the given call_in of each world."""

    def __init__(self, value):
        declaration, entries = instantiate(value)
        super().__init__(declaration, (*entries, *hosts.atoms()))
        self.value = value

    def run(self, name, args, fuel=None, trace=False):
        return engine.call("call_in", (self.value, name, C.lst(args)),
                           kernel.DictScope(hosts.atoms()), kernel.Limits(fuel=fuel or 1_000_000),
                           trace=trace)


def binary_world(outputs=(0, 1), *, name="binary", probe=True):
    return V.world(name, 1, [V.enum("z", ["z0", "z1"])],
                   [V.table("f", "transform", ["z"], "z", ["missing"],
                            [V.row([z(i)], V.val(z(output))) for i, output in enumerate(outputs)])],
                   ["Var", "Lit", "Call", "Let", "Case", "Rec"], "measure",
                   ["f"] if probe else [], "full_state",
                   ["operation", "object", "observation", "combinator"], tags())


def broken_world(missing):
    original = binary_world()
    operation = C.items(original.fields[3])[0]
    rows = [row for row in C.items(operation.fields[5]) if C.items(row.fields[0])[0] != z(missing)]
    return replace(original, fields=(*original.fields[:3], C.lst((replace(
        operation, fields=(*operation.fields[:5], C.lst(rows), operation.fields[6])),)),
                                     *original.fields[4:]))


def finite_world(size, offset=0, *, name="finite", binary=True, missing=None):
    """Recorded range-sort table family with both unary and binary cases."""
    inputs = ["digit", "digit"] if binary else ["digit"]
    rows = [V.row(values, V.val((sum(values) + offset) % size))
            for values in cartesian(range(size), repeat=len(inputs)) if values != missing]
    return V.world(name, 1, [V.range_sort("digit", 0, size - 1)],
                   [V.table("mix", "combine" if binary else "transform", inputs,
                            "digit", ["missing"], rows)],
                   ["Var", "Lit", "Call", "Let", "Case", "Rec"], "measure",
                   ["mix"] if not binary else [],
                   "full_state", ["operation", "object", "observation", "combinator"], tags())


def mixed_world(prefix, offset=0):
    """Two differently sized sorts, two operations, and an enumerated codomain."""
    small, large = prefix + "small", prefix + "large"
    symbols = tuple(Card(large, f"q{index}") for index in range(3))
    rows = [V.row([left, right], V.val(symbols[(left + index + offset) % 3]))
            for left, right_index in cartesian(range(2), range(3))
            for index, right in ((right_index, symbols[right_index]),)]
    return V.world(prefix, 1, [V.range_sort(small, 0, 1), V.enum(large, ["q0", "q1", "q2"])],
                   [V.table("mix", "combine", [small, large], large, [], rows),
                    V.table("fold", "transform", [large], small, [],
                            [V.row([symbol], V.val((index + offset) % 2))
                             for index, symbol in enumerate(symbols)])],
                   ["Var", "Lit", "Call", "Let", "Case", "Rec"], "measure", ["fold"],
                   "full_state", ["operation", "object", "observation", "combinator"], tags())


def boolean_world():
    false, true = Card("bool", "false"), Card("bool", "true")
    return V.world("boolean", 1, [], [V.table("flip", "transform", ["bool"], "bool", [],
                    [V.row([false], V.val(true)), V.row([true], V.val(false))])],
                   ["Var", "Lit", "Call", "Let", "Case", "Rec"], "measure", ["flip"],
                   "full_state", ["operation", "object", "observation", "combinator"], tags())


def three_way_world():
    return V.world("three_way", 1, [V.range_sort("digit", 0, 2)],
                   [V.table("flip", "transform", ["digit"], "digit", [],
                            [V.row([number], V.val((number + 1) % 3)) for number in range(3)])],
                   ["Var", "Lit", "Call", "Let", "Case", "Rec"], "measure", ["flip"],
                   "full_state", ["operation", "object", "observation", "combinator"], tags())


def call(name, *args):
    return n.Call(name, args)


def list_of(*values):
    result = n.Lit(C.lst(()))
    for value in values:
        result = call("list_append", result, value)
    return result


def product_body():
    """Enumerate component domains and construct every n-ary product row in kernel nodes."""
    def var(name):
        return n.Var(name)

    def get(value, index):
        return call("list_get", value, index)

    def fld(value, index):
        return call("field", value, n.Lit(index))

    def length(value):
        return call("list_len", value)

    def minus(value):
        return call("int_sub", value, n.Lit(1))

    def pair_name(left, right):
        return call("str_concat", call("str_concat", n.Lit("p"),
                                       call("int_text", call("str_len", left))),
                    call("str_concat", n.Lit("_"),
                         call("str_concat", left, call("str_concat", n.Lit("_"), right))))

    def pair_size(left, right):
        return call("int_mul", length(call("domain_values", var("arg0"), left)),
                    length(call("domain_values", var("arg1"), right)))

    def select(sort_names, index):
        return get(sort_names, index)

    def finite_sorts(world_name):
        operations = fld(var(world_name), 3)
        scan_index = var("scan_index")
        operation = get(operations, scan_index)
        uses_bool = n.Or(n.Test(call("list_contains", fld(operation, 2), n.Lit("bool"))),
                         n.Test(call("str_eq", fld(operation, 3), n.Lit("bool"))))
        found = n.Rec("scan_bool", ("scan_index",),
                      n.Case(((n.Test(call("int_eq", scan_index, length(operations))),
                                n.Lit(Card("bool", "false"))),
                               (uses_bool, n.Lit(Card("bool", "true")))),
                             call("scan_bool", call("int_add", scan_index, n.Lit(1)))),
                      (n.Lit(0),), call("int_sub", length(operations), scan_index))
        return n.Case(((n.Test(found), call("list_append", fld(var(world_name), 2),
                                                   n.Lit(V.enum("bool", ["false", "true"])))),),
                      fld(var(world_name), 2))

    left_sorts = finite_sorts("arg0")
    right_sorts = finite_sorts("arg1")
    left_op = var("left_op")
    right_op = var("right_op")
    left_inputs = fld(left_op, 2)
    right_inputs = fld(right_op, 2)

    sort_index = var("sort_index")
    left_sort = fld(get(left_sorts, call("int_div", sort_index, length(right_sorts))), 0)
    right_sort = fld(get(right_sorts, call("int_mod", sort_index, length(right_sorts))), 0)
    sort_card = call("mk", n.Lit("sort"), n.Lit("range"), list_of(
        pair_name(left_sort, right_sort), n.Lit(0), minus(pair_size(left_sort, right_sort))))
    sorts = n.Rec("gather_sorts", ("sort_index", "sorts"),
                  n.Case(((n.Test(call("int_eq", sort_index,
                                        call("int_mul", length(left_sorts), length(right_sorts)))),
                            var("sorts")),),
                         call("gather_sorts", call("int_add", sort_index, n.Lit(1)),
                              call("list_append", var("sorts"), sort_card))),
                  (n.Lit(0), n.Lit(C.lst(()))),
                  call("int_sub", call("int_mul", length(left_sorts), length(right_sorts)), sort_index))

    position = var("position")
    input_size = pair_size(select(left_inputs, position), select(right_inputs, position))
    row_count = n.Rec("count_inputs", ("position", "count"),
                      n.Case(((n.Test(call("int_eq", position, length(left_inputs))), var("count")),),
                             call("count_inputs", call("int_add", position, n.Lit(1)),
                                  call("int_mul", var("count"), input_size))),
                      (n.Lit(0), n.Lit(1)), call("int_sub", length(left_inputs), position))

    index = var("index")
    current = minus(index)
    left_sort_name = select(left_inputs, current)
    right_sort_name = select(right_inputs, current)
    right_domain = call("domain_values", var("arg1"), right_sort_name)
    pair_index = call("int_mod", var("remaining"), pair_size(left_sort_name, right_sort_name))
    left_value = get(call("domain_values", var("arg0"), left_sort_name),
                     call("int_div", pair_index, length(right_domain)))
    right_value = get(right_domain, call("int_mod", pair_index, length(right_domain)))
    unpack = n.Rec("unpack", ("index", "remaining", "left_args", "right_args", "pair_args"),
                   n.Case(((n.Test(call("int_eq", index, n.Lit(0))),
                             call("mk", n.Lit("tuple"), n.Lit("pair"),
                                  list_of(var("left_args"), var("right_args"), var("pair_args")))),),
                          call("unpack", minus(index),
                               call("int_div", var("remaining"), pair_size(left_sort_name, right_sort_name)),
                               call("list_concat", list_of(left_value), var("left_args")),
                               call("list_concat", list_of(right_value), var("right_args")),
                               call("list_concat", list_of(pair_index), var("pair_args")))),
                   (length(left_inputs), var("row_index"), n.Lit(C.lst(())), n.Lit(C.lst(())),
                    n.Lit(C.lst(()))), index)

    output_left = call("call_in", var("arg0"), fld(left_op, 0), fld(var("unpacked"), 0))
    output_right = call("call_in", var("arg1"), fld(right_op, 0), fld(var("unpacked"), 1))
    output_number = call("int_add", call("int_mul", call("list_index", call("domain_values", var("arg0"),
                                            fld(left_op, 3)), output_left),
                                            length(call("domain_values", var("arg1"), fld(right_op, 3)))),
                                call("list_index", call("domain_values", var("arg1"), fld(right_op, 3)),
                                     output_right))
    row = n.Let("unpacked", unpack, call("mk", n.Lit("row"), n.Lit("row"),
                                        list_of(fld(var("unpacked"), 2),
                                                call("mk", n.Lit("cell"), n.Lit("val"),
                                                     list_of(output_number)))))
    row_index = var("row_index")
    rows = n.Rec("gather_rows", ("row_index", "rows"),
                 n.Case(((n.Test(call("int_eq", row_index, var("total"))), var("rows")),),
                        call("gather_rows", call("int_add", row_index, n.Lit(1)),
                             call("list_append", var("rows"), row))),
                 (n.Lit(0), n.Lit(C.lst(()))), call("int_sub", var("total"), row_index))
    input_names = n.Rec("gather_names", ("position", "names"),
                        n.Case(((n.Test(call("int_eq", position, length(left_inputs))), var("names")),),
                               call("gather_names", call("int_add", position, n.Lit(1)),
                                    call("list_append", var("names"), pair_name(
                                        select(left_inputs, position), select(right_inputs, position))))),
                        (n.Lit(0), n.Lit(C.lst(()))), call("int_sub", length(left_inputs), position))
    output_name = pair_name(fld(left_op, 3), fld(right_op, 3))
    op_card = n.Let("total", row_count, call("mk", n.Lit("op"), n.Lit("table"),
                  list_of(fld(left_op, 0), fld(left_op, 1), input_names, output_name,
                          n.Lit(C.lst(())), rows, n.Lit(1))))
    op_index = var("op_index")
    operations = n.Rec("gather_ops", ("op_index", "operations"),
                       n.Case(((n.Test(call("int_eq", op_index, length(fld(var("arg0"), 3)))),
                                 var("operations")),),
                              call("gather_ops", call("int_add", op_index, n.Lit(1)),
                                   call("list_append", var("operations"),
                                        n.Let("left_op", get(fld(var("arg0"), 3), op_index),
                                              n.Let("right_op", get(fld(var("arg1"), 3), op_index), op_card))))),
                       (n.Lit(0), n.Lit(C.lst(()))),
                       call("int_sub", length(fld(var("arg0"), 3)), op_index))
    base = call("with_field", var("arg0"), n.Lit(0), n.Lit("product"))
    return call("with_field", call("with_field", base, n.Lit(2), sorts), n.Lit(3), operations)


def repair_body():
    first = call("list_get", call("field", n.Var("arg0"), n.Lit(3)), n.Lit(0))
    rows = call("field", first, n.Lit(5))
    seen = n.Rec("collect", ("position", "values"),
                 n.Case(((n.Test(call("int_eq", n.Var("position"), call("list_len", rows))),
                           n.Var("values")),),
                        call("collect", call("int_add", n.Var("position"), n.Lit(1)),
                             call("list_append", n.Var("values"),
                                  call("list_get", call("field", call("list_get", rows,
                                       n.Var("position")), n.Lit(0)), n.Lit(0))))),
                 (n.Lit(0), n.Lit(C.lst(()))),
                 call("int_sub", call("list_len", rows), n.Var("position")))
    domain = call("domain_values", n.Var("arg0"),
                  call("list_get", call("field", first, n.Lit(2)), n.Lit(0)))
    missing = n.Rec("find_missing", ("position",),
                    n.Case(((n.Test(call("list_contains", n.Var("seen"),
                                          call("list_get", domain, n.Var("position")))),
                              call("find_missing", call("int_add", n.Var("position"), n.Lit(1)))),),
                           call("list_get", domain, n.Var("position"))),
                    (n.Lit(0),), call("int_sub", call("list_len", domain), n.Var("position")))
    row = call("mk", n.Lit("row"), n.Lit("row"),
               list_of(list_of(missing), n.Lit(V.err("missing"))))
    repaired = call("with_field", first, n.Lit(5), call("list_append", rows, row))
    return n.Let("seen", seen, call("with_field", n.Var("arg0"), n.Lit(3), list_of(repaired)))


def definitions():
    base = n.Lit(z5())
    probes = call("field", n.Var("arg0"), n.Lit(6))
    probe_index = n.Var("probe_index")
    retained = n.Var("retained")
    probe = call("list_get", probes, probe_index)
    hide = call("with_field", n.Var("arg0"), n.Lit(6),
                n.Rec("filter_probes", ("probe_index", "retained"),
                      n.Case(((n.Test(call("int_eq", probe_index, call("list_len", probes))), retained),),
                             call("filter_probes", call("int_add", probe_index, n.Lit(1)),
                                  n.Case(((n.Test(call("list_contains", n.Var("arg1"), probe)), retained),),
                                         call("list_append", retained, probe)))),
                      (n.Lit(0), n.Lit(C.lst(()))),
                      call("int_sub", call("list_len", probes), probe_index)))
    verdict = call("eq", call("wf", n.Var("arg0")),
                   call("wf", call("hide", n.Var("arg0"), n.Var("arg1"))))
    count_row = call("int_add", n.Var("arg0"), n.Lit(1))
    fold = n.Let("rows", call("field", call("list_get", call("field", n.Var("arg0"), n.Lit(3)),
                                     n.Var("arg1")), n.Lit(5)),
                 n.Rec("walk_rows", ("position", "acc"),
                       n.Case(((n.Test(call("int_eq", n.Var("position"),
                                            call("list_len", n.Var("rows")))), n.Var("acc")),),
                              call("walk_rows", call("int_add", n.Var("position"), n.Lit(1)),
                                   call("f", n.Var("acc"),
                                        call("list_get", n.Var("rows"), n.Var("position"))))),
                       (n.Lit(0), n.Var("arg2")),
                       call("int_sub", call("list_len", n.Var("rows")), n.Var("position"))))
    full = call("int_eq", call("product_table_total", n.Var("arg0"), n.Var("arg1"), n.Var("arg2")),
                call("int_mul", call("list_len", call("field", call("list_get",
                     call("field", n.Var("arg0"), n.Lit(3)), n.Lit(0)), n.Lit(5))),
                     call("list_len", call("field", call("list_get",
                     call("field", n.Var("arg1"), n.Lit(3)), n.Lit(0)), n.Lit(5)))))
    a, b, c = (n.Var(name) for name in ("a", "b", "c"))
    assoc_left = call("add5", call("add5", a, b), c)
    assoc_right = call("add5", a, call("add5", b, c))
    distribute_left = call("mul5", a, call("add5", b, c))
    distribute_right = call("add5", call("mul5", a, b), call("mul5", a, c))
    law_vars = (("a", "z"), ("b", "z"), ("c", "z"))
    assoc = call("eq", assoc_left, assoc_right)
    distribute = call("eq", distribute_left, distribute_right)
    embed = call("call_in", n.Lit(z5xbool()), n.Lit("embed"), list_of(n.Var("x")))
    entries = [
        ("base_z5", "object", ObjectSpec("base_z5", "constant", body=base), base),
        ("add5_assoc", "law", LawSpec("add5_assoc", law_vars, assoc), assoc),
        ("mul5_distributes", "law", LawSpec("mul5_distributes", law_vars, distribute), distribute),
        ("embed_z5", "bridge", BridgeSpec("embed_z5", "z5@1:z", "z5xbool@1:int", embed,
                                           interface=(("add5", "add_pair"),)), embed),
        ("hide", "operation", OperationSpec("hide", "transform", (Edge("world"), Edge("list")),
                                            Edge("world"), "Remove all selected probes"), hide),
        ("repair", "operation", OperationSpec("repair", "transform", (Edge("world"),),
                                              Edge("world"), "Fill the missing unary table row with err(missing)"),
         repair_body()),
        ("product", "operation", OperationSpec("product", "combine", (Edge("world"), Edge("world")),
                                               Edge("world"), "Componentwise finite n-ary table product"),
         product_body()),
        ("count_row", "operation", OperationSpec("count_row", "transform", (Edge("int"), Edge("row")),
                                                  Edge("int"), "Count one visited row"), count_row),
        ("for_each_tuple", "combinator", CombinatorSpec("for_each_tuple", ("f", "arg0", "arg1", "arg2"),
                                                         ("f",), fold), fold),
        ("table_total", "operation", OperationSpec("table_total", "transform",
              (Edge("world"), Edge("int"), Edge("code")), Edge("int"),
              "Count the rows of a table using a supplied folding operation"),
         call("for_each_tuple", n.Var("arg2"), n.Var("arg0"), n.Var("arg1"), n.Lit(0))),
        ("product_table_total", "operation", OperationSpec("product_table_total", "transform",
              (Edge("world"), Edge("world"), Edge("code")), Edge("int"),
              "Count rows of a constructed product"),
         call("table_total", call("product", n.Var("arg0"), n.Var("arg1")), n.Lit(0), n.Var("arg2"))),
        ("audit_product", "operation", OperationSpec("audit_product", "decide",
              (Edge("world"), Edge("world"), Edge("code")), Edge("bool"),
              "Audit product table cardinality"), full),
        ("same_verdict", "operation", OperationSpec("same_verdict", "decide",
                                                      (Edge("world"), Edge("list")), Edge("bool"),
                                                      "Compare complete wf reports after hiding a probe"), verdict),
        ("audit_hidden_product", "operation", OperationSpec("audit_hidden_product", "decide",
              (Edge("world"), Edge("world"), Edge("code")), Edge("bool"),
              "Audit cardinality and the hidden product's full-state verdict"),
         n.Case(((n.Test(call("audit_product", n.Var("arg0"), n.Var("arg1"), n.Var("arg2"))),
                   call("same_verdict", call("product", n.Var("arg0"), n.Var("arg1")),
                        call("list_concat", call("field", n.Var("arg0"), n.Lit(6)),
                             n.Lit(C.lst(()))))),), n.Lit(Card("bool", "false")))),
    ]
    result = []
    layers = {"base_z5": 1, "add5_assoc": 1, "mul5_distributes": 1, "embed_z5": 1, "hide": 1,
              "repair": 1, "product": 1, "count_row": 1, "for_each_tuple": 1,
              "table_total": 2, "product_table_total": 3, "audit_product": 4,
              "same_verdict": 2, "audit_hidden_product": 5}
    for name, kind, spec, body in entries:
        depends = tuple(sorted(n.references(body) - ({"f"} if kind == "combinator" else set())))
        result.append(Definition(name, kind, "invented", layers[name], depends, spec, body))
    return result


def reference(name, *args):
    """Tooling oracle, never an invented definition or a given atom."""
    if name == "base_z5":
        return z5()
    if name in ("add5_assoc", "mul5_distributes"):
        return Card("bool", "true")
    if name == "embed_z5":
        return 2 * int(args[0].tag[1:])
    if name == "hide":
        value, selected = args
        return replace(value, fields=(*value.fields[:6], C.lst(
            probe for probe in C.items(value.fields[6]) if probe not in C.items(selected)),
                                      *value.fields[7:]))
    if name == "repair":
        value, = args
        operation = C.items(value.fields[3])[0]
        rows = C.items(operation.fields[5])
        sorts = {item.fields[0]: item for item in C.items(value.fields[2])}
        from opulse.meta.builder.instantiate import domain
        missing = next(item for item in domain(C.items(operation.fields[2])[0], sorts) if all(
            C.items(row.fields[0])[0] != item for row in rows))
        repaired = replace(operation, fields=(*operation.fields[:5], C.lst(
            (*rows, V.row([missing], V.err("missing")))), operation.fields[6]))
        return replace(value, fields=(*value.fields[:3], C.lst((repaired,)), *value.fields[4:]))
    if name == "product":
        left, right = args
        from opulse.meta.builder.instantiate import domain
        left_sorts = {item.fields[0]: item for item in C.items(left.fields[2])}
        right_sorts = {item.fields[0]: item for item in C.items(right.fields[2])}
        def values(side, sort):
            return domain(sort, left_sorts if side == 0 else right_sorts)

        left_names = (*left_sorts, "bool") if any(
            "bool" in (*C.items(op.fields[2]), op.fields[3])
            for op in C.items(left.fields[3])) else tuple(left_sorts)
        right_names = (*right_sorts, "bool") if any(
            "bool" in (*C.items(op.fields[2]), op.fields[3])
            for op in C.items(right.fields[3])) else tuple(right_sorts)
        sorts = [V.range_sort(f"p{len(left_sort)}_{left_sort}_{right_sort}", 0,
                              len(values(0, left_sort)) * len(values(1, right_sort)) - 1)
                 for left_sort in left_names for right_sort in right_names]
        operations = []
        for first, second in zip(C.items(left.fields[3]), C.items(right.fields[3])):
            inputs_a, inputs_b = C.items(first.fields[2]), C.items(second.fields[2])
            combined = [f"p{len(sort_a)}_{sort_a}_{sort_b}"
                        for sort_a, sort_b in zip(inputs_a, inputs_b)]
            outputs = []
            left_rows = {tuple(C.items(row.fields[0])): row.fields[1].fields[0]
                         for row in C.items(first.fields[5])}
            right_rows = {tuple(C.items(row.fields[0])): row.fields[1].fields[0]
                          for row in C.items(second.fields[5])}
            for numbers in cartesian(*(range(len(values(0, a)) * len(values(1, b)))
                                       for a, b in zip(inputs_a, inputs_b))):
                lhs = tuple(values(0, sort)[number // len(values(1, other))]
                            for number, sort, other in zip(numbers, inputs_a, inputs_b))
                rhs = tuple(values(1, other)[number % len(values(1, other))]
                            for number, other in zip(numbers, inputs_b))
                output = (values(0, first.fields[3]).index(left_rows[lhs]) *
                          len(values(1, second.fields[3])) +
                          values(1, second.fields[3]).index(right_rows[rhs]))
                outputs.append(V.row(numbers, V.val(output)))
            operations.append(V.table(first.fields[0], first.fields[1], combined,
                                      f"p{len(first.fields[3])}_{first.fields[3]}_{second.fields[3]}",
                                      [], outputs))
        return replace(left, fields=("product", left.fields[1], C.lst(sorts), C.lst(operations),
                                     *left.fields[4:]))
    if name == "count_row":
        return args[0] + 1
    if name == "for_each_tuple":
        _, value, index, seed = args
        return seed + len(C.items(C.items(value.fields[3])[index].fields[5]))
    if name == "table_total":
        return reference("for_each_tuple", args[2], args[0], args[1], 0)
    if name == "product_table_total":
        return reference("table_total", reference("product", *args[:2]), 0, args[2])
    if name == "audit_product":
        lhs = len(C.items(C.items(args[0].fields[3])[0].fields[5]))
        rhs = len(C.items(C.items(args[1].fields[3])[0].fields[5]))
        return Card("bool", "true" if reference("product_table_total", *args) == lhs * rhs else "false")
    if name == "audit_hidden_product":
        value = reference("product", *args[:2])
        verdict = reference("same_verdict", value, args[0].fields[6])
        return Card("bool", "true" if reference("audit_product", *args).tag == "true"
                    and verdict.tag == "true" else "false")
    if name == "same_verdict":
        return Card("bool", "true" if wf(args[0]) == wf(reference("hide", *args)) else "false")
    raise KeyError(name)


class BuilderLibrary(MeteredLibrary):
    """Local metered adapter until Library exposes an evaluator hook."""

    @property
    def definitions(self):
        return deepcopy(super().definitions)

    def get(self, name):
        return deepcopy(super().get(name))

    def write(self, defn, replace=False):
        return deepcopy(super().write(deepcopy(defn), replace))

    def verify(self, name, request):
        if self.get(name).kind == "template":
            request = deepcopy(request)
            family = request.extra.get("family", ())
            request = replace(request, domain=tuple(() for _ in family),
                              scope={**request.scope, "size": len(family)})
            return deepcopy(super().verify(name, request))
        request = deepcopy(request)
        if request.reference is None or not callable(request.reference):
            raise library.PipelineError("reference oracle required")
        if not request.domain:
            raise library.PipelineError("verification domain must be nonempty")
        if request.method == "bounded" and not re.search(
                r"\d|\b(?:one|two|three|four|five|six|seven|eight|nine|ten)\b",
                request.scope.get("domain", "")):
            raise library.PipelineError("bounded domain needs an explicit finite bound")
        domain = [[{"fn": arg.name} if isinstance(arg, kernel.FnRef) else encode(arg)
                   for arg in args] for args in request.domain]
        count = len(domain)
        hashes = [input_hash(args) for args in request.domain]
        if request.scope.get("enumerated_count", count) != count or request.scope.get(
                "input_hashes", hashes) != hashes:
            raise library.PipelineError("declared domain enumeration differs")
        request.scope["enumerated_count"] = count
        request.scope["input_hashes"] = hashes
        fingerprint = hashlib.sha256(json.dumps(
            domain, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if "domain_hash" in request.scope and request.scope["domain_hash"] != fingerprint:
            raise library.PipelineError("enumerated domain fingerprint differs")
        request.scope["domain_hash"] = fingerprint
        return deepcopy(super().verify(name, request))

    def check(self, name):
        from opulse.atoms.check import check_definition
        definition = self.get(name)
        problems = check_definition(definition, self.world, self._definitions.get)
        problems = [problem for problem in problems if "expected any, got " not in problem
                    and not problem.endswith(", got any")]
        if definition.kind in ("law", "bridge"):
            problems.extend(laws.check_law(definition, self) if definition.kind == "law"
                            else bridges.check_bridge(definition, bridge_context()))
        if problems:
            raise library.PipelineError(problems)
        return self._advance(name, "checked")

    def make_callable(self, name, sample):
        definition = self.get(name)
        if definition.kind in ("law", "template"):
            return deepcopy(super().make_callable(name, sample))
        if definition.status != "checked" or not sample:
            raise library.PipelineError("checked definition and nonempty sample required")
        scope = self.scope().extend([kernel.Defn(name, self._params(definition), definition.body,
                                                definition.kind, definition.layer)])
        runs = [engine.call(name, args, scope, kernel.Limits(fuel=100_000)) for args in sample]
        if any(isinstance(run.outcome, Unknown) for run in runs):
            raise library.PipelineError(f"sample failed: {runs!r}")
        self._steps[name] = [run.steps for run in runs]
        return self._advance(name, "callable")


def _verify(defn, lib, request):
    if request.reference is None:
        return library.VerifyResult(False, (), ["reference oracle required"], [])
    problems, steps = [], []
    for args in request.domain:
        actual = lib.run(defn.name, args, trace=True)
        unfolded = engine.evaluate(kernel.inline(call(defn.name, *(n.Lit(arg) for arg in args)), lib.scope()),
                                   scope=lib.scope(), trace=True)
        expected = request.reference(*args)
        if not isinstance(expected, (Ok, Bottom, Unknown)):
            expected = Ok(expected)
        if not outcome_equal(actual.outcome, unfolded.outcome) or actual.steps != unfolded.steps:
            problems.append(f"unfold mismatch for {args!r}")
        if actual.outcome != expected:
            problems.append(f"reference mismatch for {args!r}")
        steps.append(actual.steps)
        if problems:
            break
    checks = ("unfold_equivalence", "reference") if not problems else ()
    return library.VerifyResult(not problems, checks, problems, steps)


def _verify_object(defn, lib, request):
    if not isinstance(defn.spec, ObjectSpec) or defn.spec.form != "constant" or request.reference is None:
        return library.VerifyResult(False, (), ["object needs a constant and a reference"], [])
    result = _verify(defn, lib, request)
    if not result.ok:
        return result
    for args in request.domain:
        value = lib.run(defn.name, args).outcome
        if not isinstance(value, Ok) or not isinstance(value.value, Card) or value.value.sort != "world" \
                or wf(value.value) != Card("report", "ok"):
            return library.VerifyResult(False, (), ["object world interface failed"], result.steps)
    return library.VerifyResult(True, (*result.checks, "constant", "world_interface"), [], result.steps)


def _verify_combinator(defn, lib, request):
    family = request.extra.get("op_family", ())
    if not isinstance(defn.spec, CombinatorSpec) or not family or not set(family) <= set(
            request.scope.get("op_family", ())) or not all(
            isinstance(lib.get(name).spec, OperationSpec) and lib.get(name).status == "promoted"
            for name in family):
        return library.VerifyResult(False, (), ["combinator needs a declared callable operation family"], [])
    if any(not isinstance(args[0], kernel.FnRef) or args[0].name not in family
           for args in request.domain):
        return library.VerifyResult(False, (), ["combinator input outside operation family"], [])
    result = _verify(defn, lib, request)
    return library.VerifyResult(result.ok, (*result.checks, "operation_family") if result.ok else (),
                                result.problems, result.steps)


def _verify_law(defn, lib, request):
    return laws.verify_law(defn, lib, request)


def _verify_bridge(defn, lib, request):
    checked = bridges.verify_bridge(defn, bridge_context(), request)
    unfolded = _verify(defn, lib.source_lib, request) if checked.ok else checked
    return library.VerifyResult(checked.ok and unfolded.ok,
                                (*checked.checks, *unfolded.checks) if unfolded.ok else (),
                                (*checked.problems, *unfolded.problems), unfolded.steps)


def cancellation_near_miss(lib):
    """Reject cancellation at zero with a core law counterexample (atoms-v2 19.1)."""
    a, b, c = (n.Var(name) for name in ("a", "b", "c"))
    statement = call("eq", call("eq", call("mul5", a, b), call("mul5", a, c)),
                     call("eq", b, c))
    definition = Definition("mul5_cancels", "law", "invented", 1,
                            ("eq", "mul5"),
                            LawSpec("mul5_cancels", (("a", "z"), ("b", "z"), ("c", "z")), statement),
                            statement)
    witness = (z(0), z(0), z(1))
    lib.write(definition)
    lib.check(definition.name)
    lib.make_callable(definition.name, [witness])
    request = library.VerifyRequest("bounded", [witness],
                                    {"domain": "one zero-divisor witness", "size": 1})
    result = laws.verify_law(lib.get(definition.name), lib, request)
    if result.ok:
        raise ValueError("false cancellation law passed verification")
    return lib.get(definition.name), witness, result


def creation():
    """Return independent copies of the fully checked builder story."""
    lib, families = deepcopy(_creation())
    lib._metered_atoms_key = tuple(id(atom) for atom in lib.atoms
                                   if atom.name not in ("eval", "run"))
    return lib, families


@lru_cache(maxsize=1)
def _creation():
    """Write, check, sample, verify, account, and promote every story member."""
    import opulse.atoms.library as module

    original = dict(module._VERIFIERS)
    original_checkers = dict(module._CHECKERS)
    module.register_kind("operation", verifier=_verify)
    module.register_kind("object", verifier=_verify_object)
    module.register_kind("combinator", verifier=_verify_combinator)
    module.register_kind("law", verifier=_verify_law)
    module.register_kind("bridge", verifier=_verify_bridge)
    result = BuilderLibrary(world.declaration(), hosts.atoms())
    result.attach_world("z5xbool@1", _DispatchWorld(z5xbool()))
    unary = [finite_world(size, offset, binary=False, name=f"u{size}_{offset}")
             for size in (2, 3) for offset in range(size)]
    binary = [finite_world(size, offset, name=f"b{size}_{offset}")
              for size in (2, 3) for offset in range(size)]
    pairs = list(cartesian(unary[:2], repeat=2)) + list(cartesian(binary[:2], repeat=2))
    pairs += list(cartesian(binary[2:4], repeat=2))
    pairs.append((mixed_world("left", 1), mixed_world("right", 2)))
    pairs.append((boolean_world(), three_way_world()))
    damaged = [(finite_world(size, offset, name=f"bad{size}_{offset}_{missing}",
                             binary=False, missing=(missing,)),)
               for size in (2, 3, 4, 5) for offset in range(size) for missing in range(size)]
    families = {
        "base_z5": [()],
        "add5_assoc": [tuple(z(value) for value in triple)
                       for triple in cartesian(range(5), repeat=3)],
        "mul5_distributes": [tuple(z(value) for value in triple)
                             for triple in cartesian(range(5), repeat=3)],
        "embed_z5": [(z(index),) for index in range(5)],
        "hide": [(z5(), C.lst(("identity",))), (binary_world(), C.lst(("f",)))],
        "repair": damaged[:20], "product": pairs,
        "count_row": [(0, V.row([0], V.val(1))), (7, V.row([1], V.val(0)))],
        "for_each_tuple": [(kernel.FnRef("count_row"), binary[0], 0, 0)],
        "table_total": [(binary[0], 0, kernel.FnRef("count_row")),
                        (binary[2], 0, kernel.FnRef("count_row"))],
        "product_table_total": [(*pairs[1], kernel.FnRef("count_row"))],
        "audit_product": [(*pairs[2], kernel.FnRef("count_row"))],
        "same_verdict": [(broken_world(0), C.lst(("f",)))],
        "audit_hidden_product": [(*pairs[3], kernel.FnRef("count_row"))],
    }
    try:
        for definition in definitions():
            name = definition.name
            domain = families[name]
            result.write(definition)
            result.check(name)
            result.make_callable(name, domain)
            request = library.VerifyRequest("bounded", domain,
                                            {"domain": f"recorded {name} family up to {len(domain)} cases",
                                             "size": len(domain),
                                             **({"op_family": ["count_row"]}
                                                if definition.kind == "combinator" else {})},
                                            reference=lambda *args, name=name: reference(name, *args),
                                            extra={"op_family": ("count_row",)}
                                            if definition.kind == "combinator" else {})
            result.verify(name, request)
            result.account(name)
            result.promote(name, Contract(f"Exact results on the recorded {name} family", keeps=("world",)))
    finally:
        module._VERIFIERS.clear()
        module._VERIFIERS.update(original)
        module._CHECKERS.clear()
        module._CHECKERS.update(original_checkers)
    return result, families


def promoted_mul5(value=None):
    """Repeat add5 under a decreasing rank measure; extend only with bound evidence."""
    value = value or z5()
    rank = V.table("rank", "transform", ["z"], "int", [],
                   [V.row([z(index)], V.val(index)) for index in range(5)])
    fields = list(value.fields)
    fields[3] = C.lst((*C.items(fields[3]), rank))
    value = Card("world", "world", tuple(fields))
    declaration, entries = instantiate(value)
    digests = {op.name: C.atom_digest(op) for op in declaration.operations}
    body = n.Rec("repeat", ("counter", "total"),
                 n.Case(((n.Test(call("eq5", n.Var("counter"), n.Lit(z(0)))), n.Var("total")),),
                        call("repeat", call("add5", n.Var("counter"), n.Lit(z(4))),
                             call("add5", n.Var("total"), n.Var("left")))),
                 (n.Var("right"), n.Lit(z(0))), call("rank", n.Var("counter")))
    generated = C.make_code("operation", C.sig_op([("z", "bottom"), ("z", "bottom")],
                                                    ("z", "bottom")), ("left", "right"), body,
                            lambda name: C.Resolved(digest=digests[name]) if name in digests else None)
    decoded = C.decode(generated)
    scope = kernel.DictScope([entry for entry in entries if isinstance(entry, kernel.Atom)],
                             [decoded.main])
    for left, right in cartesian(range(5), repeat=2):
        actual = kernel.call(decoded.main.name, (z(left), z(right)), scope)
        expected = kernel.call("mul5", (z(left), z(right)), scope)
        if actual.outcome != expected.outcome or actual.outcome != Ok(z(left * right % 5)):
            raise ValueError(f"mul5 reference mismatch: {left}, {right}")
        unfolded = kernel.evaluate(kernel.inline(call(decoded.main.name, n.Lit(z(left)),
                                                       n.Lit(z(right))), scope), scope=scope)
        if unfolded.outcome != actual.outcome or unfolded.steps != actual.steps:
            raise ValueError(f"mul5 unfold mismatch: {left}, {right}")
    ledger = Ledger()
    digest = ledger.add(generated, V.world_hash(value), "mul_by_add")
    evidence = Evidence("exhaustive", {"domain": "all 25 pairs of z5", "size": 25},
                        checks=("reference", "unfold_equivalence"), world_hash=V.world_hash(value),
                        content_hash=digest, atoms_hash=atoms_digest(tuple(
                            entry for entry in entries if isinstance(entry, kernel.Atom))))
    ledger.attach_evidence(digest, V.world_hash(value), evidence)
    promote_output(ledger, digest, V.world_hash(value),
                   tuple(entry for entry in entries if isinstance(entry, kernel.Atom)),
                   Contract("All 25 products match mul5", keeps=("z",)))
    return value, generated, ledger, extend(value, generated, ledger)


def promoted_power5():
    """Promote measured multiplication, then measured exponentiation over that body."""
    value, times_code, times_ledger, times_world = promoted_mul5()
    if len(times_world.promoted) != 1 or times_ledger.status(
            C.code_hash(times_code), V.world_hash(value)) != "promoted":
        raise ValueError("times5 was not promoted")
    times_name = "derived_" + C.code_hash(times_code)[:12]
    with_times = replace(value, fields=(*value.fields[:3],
                     C.lst((*C.items(value.fields[3]), V.body(times_name, times_code))),
                     *value.fields[4:]))
    declaration, entries = instantiate(with_times)
    digests = {op.name: C.atom_digest(op) for op in declaration.operations}
    body = n.Rec("exponent", ("counter", "total"),
                 n.Case(((n.Test(call("eq5", n.Var("counter"), n.Lit(z(0)))), n.Var("total")),),
                        call("exponent", call("add5", n.Var("counter"), n.Lit(z(4))),
                             call(times_name, n.Var("total"), n.Var("left")))),
                 (n.Var("right"), n.Lit(z(1))), call("rank", n.Var("counter")))
    generated = C.make_code("operation", C.sig_op([("z", "bottom"), ("z", "bottom")],
                                                    ("z", "bottom")), ("left", "right"), body,
                            lambda name: C.Resolved(digest=digests[name]) if name in digests else None)
    decoded = C.decode(generated)
    scope = kernel.DictScope([entry for entry in entries if isinstance(entry, kernel.Atom)],
                             [entry for entry in entries if isinstance(entry, kernel.Defn)] + [decoded.main])
    table_scope = kernel.DictScope([entry for entry in entries if isinstance(entry, kernel.Atom)])
    measurements = {}
    for left, right in cartesian(range(5), repeat=2):
        args = (z(left), z(right))
        observed = kernel.call(decoded.main.name, args, scope)
        expected = z(pow(left, right, 5))
        if observed.outcome != Ok(expected):
            raise ValueError(f"power5 reference mismatch: {left}, {right}")
        unfolded = kernel.evaluate(kernel.inline(call(decoded.main.name,
                                                       n.Lit(args[0]), n.Lit(args[1])), scope),
                                   scope=scope)
        if unfolded.outcome != observed.outcome or unfolded.steps != observed.steps:
            raise ValueError(f"power5 unfold mismatch: {left}, {right}")
        measurements[left, right] = observed.steps
        if kernel.call("mul5", args, table_scope).outcome != Ok(z(left * right % 5)):
            raise ValueError(f"mul5 reference mismatch: {left}, {right}")
    ledger = Ledger()
    identity = V.world_hash(with_times)
    digest = ledger.add(generated, identity, "power_by_times")
    ledger.attach_evidence(digest, identity, Evidence(
        "exhaustive", {"domain": "all 25 base-exponent pairs of z5", "size": 25},
        checks=("reference", "unfold_equivalence"), world_hash=identity,
        content_hash=digest, atoms_hash=atoms_digest(tuple(
            entry for entry in entries if isinstance(entry, kernel.Atom)))))
    promote_output(ledger, digest, identity,
                   tuple(entry for entry in entries if isinstance(entry, kernel.Atom)),
                   Contract("All 25 powers agree with pow5", keeps=("z",)))
    return with_times, generated, ledger, extend(with_times, generated, ledger), measurements
