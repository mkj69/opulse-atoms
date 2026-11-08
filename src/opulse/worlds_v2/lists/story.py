"""Twelve-layer list tower; every algorithm unfolds to counted kernel calls."""

from dataclasses import replace
from itertools import product

from opulse.atoms import kernel, values
from opulse.atoms import nodes as n
from opulse.atoms.check import check_definition
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
from opulse.worlds_v2.lists import hosts, oracle
from opulse.worlds_v2.lists.world import new_library

V = n.Var
L = n.Lit


def C(name, *args):
    return n.Call(name, args)


def choose(condition, yes, no):
    return n.Case(((n.Test(condition), yes),), no)


LAYERS = {}


def computed(references):
    return max((LAYERS.get(name.split(".")[0], 0) for name in references), default=0) + 1


def obj(name, layer, valid, base, interface):
    LAYERS[name] = 1
    refs = tuple(sorted(n.references(valid) | n.operation_literals(valid)))
    return Definition(name, "object", "invented", 1, refs,
                      ObjectSpec(name, "refine", base=base, valid=valid, sealed=True,
                                 interface=interface), None)


def comb(name, layer, body, params, op_params=()):
    refs = tuple(sorted((n.references(body) | n.operation_literals(body)) - set(op_params)))
    LAYERS[name] = computed(refs)
    return Definition(name, "combinator", "invented", LAYERS[name], refs,
                      CombinatorSpec(name, params, op_params, body), body)


def op(name, layer, body, params, sorts, output):
    refs = tuple(sorted(n.references(body) | n.operation_literals(body)))
    LAYERS[name] = computed(refs)
    return Definition(name, "operation", "invented", LAYERS[name], refs,
                      OperationSpec(name, "transform", tuple(Edge(sort, name=param) for sort, param in zip(sorts, params)),
                                    Edge(output), "Public recursive unfolding of " + name,
                                    extra={"input_names": list(params)}), body)


def obs(name, layer, body, params):
    refs = tuple(sorted(n.references(body) | n.operation_literals(body)))
    LAYERS[name] = computed(refs)
    return Definition(name, "observation", "invented", LAYERS[name], refs,
                      ObservationSpec(name, ("items", "length"), body), body)


def definitions():
    LAYERS.clear()
    xs, left, right = V("xs"), V("left"), V("right")
    empty = lambda val: C("eq", C("length", val), L(0))
    fold_body = choose(empty(xs), V("seed"), n.Rec("fold_loop", ("remaining", "acc"),
                      choose(empty(V("remaining")), V("acc"),
                             C("fold_loop", C("tail", V("remaining")),
                               C("f", C("head", V("remaining")), V("acc")))),
                      (C("NonEmpty.base", C("NonEmpty.make", xs)), V("seed")), C("length", V("remaining"))))
    yield obj("NonEmpty", 1, C("ne", C("length", V("x")), L(0)),
              "list", ("NonEmpty.make", "NonEmpty.base"))
    yield comb("fold", 2, fold_body, ("f", "xs", "seed"), ("f",))
    yield op("reverse", 3, C("fold", L(kernel.FnRef("cons")), xs, C("nil")), ("xs",), ("list",), "list")
    yield obs("palindrome", 4, C("same_list", C("items", xs), C("items", C("reverse", xs))), ("xs",))
    yield obj("Run", 5, choose(C("lt", C("key", V("x")), C("add", C("key", V("x")), L(1))),
                               C("lt", L(0), C("second", V("x"))), L(values.FALSE)),
              "pair", ("Run.make", "Run.base"))

    item, acc = V("item"), V("acc")
    new_run = C("Run.make", C("run", item, L(1)))
    run_step = choose(empty(acc), C("cons", new_run, acc),
                      choose(C("eq", C("key", C("Run.base", C("head_run", acc))), item),
                             C("cons", C("Run.make", C("run", item,
                                 C("add", C("count", C("Run.base", C("head_run", acc))), L(1)))), C("tail", acc)),
                             C("cons", new_run, acc)))
    yield op("rle_step", 6, run_step, ("item", "acc"), ("int", "list"), "list")
    yield op("rle", 6, C("fold", L(kernel.FnRef("rle_step")), C("reverse", xs), C("nil")),
             ("xs",), ("list",), "list")
    merge_step = choose(empty(left), right, choose(empty(right), left,
                  choose(C("compare", C("head", left), C("head", right)),
                         C("cons", C("head", left), C("merge_loop", C("tail", left), right)),
                         C("cons", C("head", right), C("merge_loop", left, C("tail", right))))))
    yield comb("stable_merge", 7,
               n.Rec("merge_loop", ("left", "right"), merge_step,
                     (C("items", V("left_input")), C("items", V("right_input"))),
                     C("add", C("length", left), C("length", right))),
               ("compare", "left_input", "right_input"), ("compare",))
    sort_step = choose(C("le", C("length", V("remaining")), L(1)), V("remaining"),
                n.Let("halves", C("split_at", V("remaining"), C("half_floor", C("length", V("remaining")))),
                      C("stable_merge", L(kernel.FnRef("le")), C("sort_loop", C("first", V("halves"))),
                        C("sort_loop", C("second_list", V("halves"))))))
    yield op("sort", 8, n.Rec("sort_loop", ("remaining",), sort_step, (xs,), C("length", V("remaining"))),
             ("xs",), ("list",), "list")
    count_step = choose(empty(left), L(0), choose(empty(right), L(0),
                 choose(C("compare", C("head", left), C("head", right)),
                        C("count_loop", C("tail", left), right),
                        C("add", C("length", left), C("count_loop", left, C("tail", right))))))
    count_body = n.Rec("count_loop", ("left", "right"), count_step,
                       (V("left_input"), V("right_input")), C("add", C("length", left), C("length", right)))
    merged = C("stable_merge", V("compare"), V("left_input"), V("right_input"))
    yield comb("merge_count", 9,
               C("pair", merged, count_body),
               ("compare", "left_input", "right_input"), ("compare",))
    inv_step = choose(C("le", C("length", V("remaining")), L(1)), L(0),
               n.Let("halves", C("split_at", V("remaining"), C("half_floor", C("length", V("remaining")))),
                 C("add", C("add", C("inv_loop", C("first", V("halves"))), C("inv_loop", C("second_list", V("halves")))),
                   C("second", C("merge_count", L(kernel.FnRef("le")), C("sort", C("first", V("halves"))),
                                   C("sort", C("second_list", V("halves"))))))))
    yield obs("inversions", 10, n.Rec("inv_loop", ("remaining",), inv_step, (xs,), C("length", V("remaining"))), ("xs",))

    seek_body = choose(C("eq", C("nth", V("working"), V("position")), V("wanted")), V("position"),
                       C("seek_loop", V("working"), C("add", V("position"), L(1)), V("wanted")))
    seek = n.Rec("seek_loop", ("working", "position", "wanted"), seek_body,
                 (V("working"), V("target_position"), C("nth", V("target"), V("target_position"))),
                 C("sub", C("length", V("working")), V("position")))
    swap = n.Let("first_value", C("nth", V("working"), C("sub", V("position"), L(1))),
           n.Let("second_value", C("nth", V("working"), V("position")),
                 C("replace_at", C("replace_at", V("working"), C("sub", V("position"), L(1)), V("second_value")), V("position"), V("first_value"))))
    move = n.Rec("move_loop", ("working", "position", "target_position", "steps"),
                 choose(C("eq", V("position"), V("target_position")), C("pair_lists", V("working"), V("steps")),
                        C("move_loop", swap, C("sub", V("position"), L(1)), V("target_position"),
                          C("append", V("steps"), C("cons", C("sub", V("position"), L(1)), C("nil"))))),
                 (V("working"), seek, V("target_position"), V("steps")),
                 C("sub", V("position"), V("target_position")))
    trace_loop = n.Rec("trace_loop", ("working", "target", "target_position", "steps"),
               choose(C("eq", V("target_position"), C("length", V("target"))), V("steps"),
                      n.Let("moved", move,
                            C("trace_loop", C("first", V("moved")), V("target"),
                              C("add", V("target_position"), L(1)), C("second_list", V("moved"))))),
               (xs, C("sort", xs), L(0), C("nil")),
               C("sub", C("length", V("target")), V("target_position")))
    yield op("trace", 11, n.Let("lower_bound", C("inversions", xs), trace_loop), ("xs",), ("list",), "list")

    replay_swap = n.Let("before", C("nth", V("working"), V("index")),
                  n.Let("after", C("nth", V("working"), C("add", V("index"), L(1))),
                     C("replace_at", C("replace_at", V("working"), V("index"), V("after")),
                       C("add", V("index"), L(1)), V("before"))))
    replay = n.Rec("replay_loop", ("working", "remaining"),
                    choose(empty(V("remaining")), V("working"),
                      n.Let("index", C("head", V("remaining")),
                        choose(C("lt", V("index"), L(0)), L(values.FALSE),
                          choose(C("le", C("length", V("working")), C("add", V("index"), L(1))), L(values.FALSE),
                            choose(C("le", C("nth", V("working"), V("index")),
                                        C("nth", V("working"), C("add", V("index"), L(1)))), L(values.FALSE),
                              C("replay_loop", replay_swap, C("tail", V("remaining")))))))),
                    (xs, V("steps")), C("length", V("remaining")))
    yield obs("certificate", 12,
              n.Let("replayed", replay,
                choose(C("eq_bool", V("replayed"), L(values.FALSE)), L(values.FALSE),
                  choose(C("ne", C("length", V("steps")), C("inversions", xs)), L(values.FALSE),
                    choose(C("same_list", V("replayed"), C("sort", xs)),
                      C("same_list", C("rle", V("replayed")), C("rle", C("sort", xs))), L(values.FALSE))))), ("xs", "steps"))


def reference(name, args):
    from opulse.worlds_v2.lists import oracle
    return oracle.expected(name, args)


def build_library(limit=None):
    lib = new_library()
    rows = tuple(hosts.to_card(row) for size in range(5) for row in product((-1, 0, 1), repeat=size))
    certificate_rows = (*rows[:13], *(hosts.to_card(row) for row in
                          ((1, 0, -1), (1, 1, 0), (0, -1, 1), (1, 0, 1, -1), (0, 0, -1, 1), (1, 1, 0, -1))))
    sorted_rows = tuple(hosts.to_card(row) for size in range(4) for row in product((-1, 0, 1), repeat=size)
                        if tuple(sorted(row)) == row)
    for index, definition in enumerate(definitions()):
        if limit is not None and index >= limit:
            break
        name = definition.name
        lib.write(definition)
        if definition.kind == "observation":
            problems = check_definition(definition, lib.world,
                                        lambda ref: lib.definitions.get(ref) or lib.scope().resolve(ref))
            if problems:
                raise ValueError(problems)
            lib._advance(name, "checked")
        else:
            lib.check(name)
        if name == "NonEmpty":
            domain = tuple((row,) for row in rows)
        elif name == "Run":
            domain = tuple((hosts.pair(key, count),) for key in (-1, 0, 1) for count in (0, 1, 2))
        elif name in ("stable_merge", "merge_count"):
            domain = tuple((left, right) for left in sorted_rows for right in sorted_rows)
        elif name == "fold":
            domain = tuple((row, hosts.NIL) for row in rows)
        elif name == "rle_step":
            domain = tuple((item, hosts.to_card(tuple(values.Card("Run", "val", (hosts.run(*run),))
                                               for run in runs))) for item in (-1, 0, 1)
                           for runs in ((), ((-1, 1),), ((0, 2),), ((-1, 2), (1, 1))))
        elif name == "certificate":
            domain = tuple((row, hosts.to_card(steps)) for row in certificate_rows
                           for steps in ((), (0,), (0, 1),
                                         hosts.from_card(oracle.expected("trace", (row,)))))
        else:
            domain = tuple((row,) for row in rows)
        if definition.kind == "observation":
            run = kernel.call(name, domain[0], lib.scope().extend((kernel.Defn(name, ("xs", "steps") if name == "certificate" else ("xs",), definition.body, "observation", definition.layer),)))
            if isinstance(run.outcome, values.Unknown):
                raise ValueError((name, run.outcome))
            lib._advance(name, "callable")
        else:
            sample = domain[1:2] if name in ("NonEmpty", "Run") else domain[:1]
            if definition.kind == "combinator":
                sample = tuple((kernel.FnRef("cons" if name == "fold" else "le"), *entry) for entry in sample)
            lib.make_callable(name, sample)
        description = ("all keys -1..1 and counts 0..2 as pair bases" if name == "Run" else
                       "all ordered pairs of 20 sorted lists of length <=3 over -1..1; le/ge family (bound 3)" if name in ("stable_merge", "merge_count") else
                       "19 lists: all 13 of length <=2 over -1..1 plus (1,0,-1), (1,1,0), (0,-1,1), (1,0,1,-1), (0,0,-1,1), (1,1,0,-1); step lists (), (0), (0,1), and the reference trace for each" if name == "certificate" else
                       "items -1..1 with four empty/valid reversed-run accumulators" if name == "rle_step" else
                       "all 121 lists of length <=4 over -1..1; nil seed; cons/snoc family (bound 4)" if name == "fold" else
                       "all 121 lists of length <=4 over -1..1")
        scope = {"domain": description,
                 "size": len(domain)}
        if definition.kind == "combinator":
            family = ("cons", "snoc") if name == "fold" else ("le", "ge")
            scope["op_family"] = list(family)
            request = VerifyRequest("bounded", domain, scope,
                                    reference=lambda assignment, inputs, name=name: reference(name, (kernel.FnRef(next(iter(assignment.values()))), *inputs)),
                                    extra={"op_family": family})
            verified = lib.verify(name, request)
            if verified.evidence.scope.get("fixed_ops") == []:
                scope = {key: value for key, value in verified.evidence.scope.items() if key != "fixed_ops"}
                lib._definitions[name] = replace(verified, evidence=replace(verified.evidence, scope=scope))
        elif definition.kind == "operation":
            request = VerifyRequest("exhaustive", domain, scope,
                                    reference=lambda *args, name=name: (oracle.rle_step(*args) if name == "rle_step"
                                                                         else reference(name, args)))
            lib.verify(name, request)
        elif definition.kind == "object":
            lib.verify(name, VerifyRequest("exhaustive", domain, scope,
                                           extra={"interface_ops": {name + ".base": [0]}}))
        else:
            from opulse.worlds_v2.lists import adapter
            adapter.verify_public_observation(lib, name, VerifyRequest("exhaustive", domain, scope), reference)
        lib.account(name)
        lib.promote(name, Contract(guarantees="Exact outcomes and kernel cost over the stated finite scope."))
    return lib
