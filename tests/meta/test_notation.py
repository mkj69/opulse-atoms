"""ASCII notation round trips and exact printed strings (atoms-meta 2, 4, 6)."""

import random

import pytest
from test_builder_instantiate import body_world, z5
from test_builder_wf import base

from opulse.atoms import nodes as n
from opulse.atoms.values import Card
from opulse.meta import code as C
from opulse.meta import gen_code
from opulse.meta.builder import world_value as W
from opulse.meta.notation import (
    NotationError,
    parse_code,
    parse_vn,
    parse_world,
    show_code,
    show_vn,
    show_world,
)
from opulse.meta.vn import machine, reference


def _code(kind, signature, params, body, digests=None):
    return C.make_code(kind, signature, params, body,
                       lambda name: C.Resolved(digest=(digests or {})[name])
                       if name in (digests or {}) else None)


def test_six_ascii_golden_strings():
    operation = _code("operation", C.sig_op([("int", "bottom")], ("int", "bottom")),
                      ("arg",), n.Call("add", (n.Var("arg"), n.Lit(3))), {"add": "aabb"})
    combinator = _code("combinator", C.sig_comb(2, [0]), ("fn", "arg"),
                       n.Call("fn", (n.Var("arg"),)))
    observation = _code("observation", C.sig_obs(["front_wall", "front_water"]), (),
                        n.Var("front_wall"))
    constant = _code("object", C.sig_const(), (), n.Lit(Card("z", "z0")))
    assert show_code(operation, signature=True, deps=True, exact=True) == (
        'Code<op (x0: int) -> int = add(x0, 3)>\nwhere atom add = "aabb"')
    assert show_code(combinator, signature=True, deps=True, exact=True) == (
        "Code<comb [x0] (x1) = x0(x1)>")
    assert show_code(observation, signature=True, deps=True, exact=True) == (
        "Code<obs {front_wall, front_water} = front_wall>")
    assert show_code(constant, signature=True, deps=True, exact=True) == "Code<obj = z.z0<>>"
    for program in (operation, combinator, observation, constant):
        assert parse_code(show_code(program, signature=True, deps=True, exact=True)) == program

    state = machine.to_card(reference.State(0, 3, (1, 0, 4) + (0,) * 13))
    expected = "VN<pc=0, a=3, halted=false, mem=Mem<16: 1, 0, 4>>"
    assert show_vn(state, compact=True) == expected
    assert parse_vn(expected) == state

    world = W.world("small", 1, [W.range_sort("digit", 0, 1)], [], ["Lit"],
                    "none", [], "full_state", ["operation"], [W.tag("domain", "math")])
    expected = ("World<small@1\n  sort digit = range(0, 1);\n  nodes {Lit};\n"
                "  probes {};\n  open_kinds {operation};\n  recursion none;\n"
                "  judge_view full_state;\n  tag domain = \"math\";\n>")
    assert show_world(world) == expected
    assert parse_world(expected) == world


def test_new_kinds_golden_round_trip():
    law = _code("law", C.sig_law((("a", "int"), ("b", "int"))), ("a", "b"),
                n.Call("eq", (n.Var("a"), n.Var("b"))), {"eq": "e"})
    bridge = _code("bridge", C.sig_bridge("A", "B", (("left", "right"),),
                                         n.Call("positive", (n.Var("x"),))), ("x",),
                   n.Call("convert", (n.Var("x"),)), {"positive": "p", "convert": "c"})
    template = C.make_code("template", C.sig_template((("T", "object"), ("canon", "operation")), "object"),
                           (), C._template_body({"name": "$T", "form": "constant",
                                                 "body": n.Lit("$canon")}, None, ("T", "canon")),
                           lambda _: None)
    assert show_code(law) == "Code<law #? (x0: int, x1: int) = eq(x0, x1)>"
    assert show_code(bridge) == (
        "Code<bridge ~? A -> B interface {left: right} domain positive(x0) = convert(x0)>")
    assert show_code(template).startswith("Code<template [x0: object, x1: operation] -> object = pattern<template:")
    for value in (law, bridge, template):
        exact = show_code(value, signature=True, deps=True, exact=True)
        assert parse_code(exact) == value
        assert exact.isascii()


def test_seeded_new_kind_round_trips():
    from opulse.atoms.notation import print_expr

    rng = random.Random(714023)
    for index in range(60):
        name = f"arg{index}"
        offset = rng.randrange(20)
        law = _code("law", C.sig_law(((name, "int"),)), (name,),
                    n.Call("eq", (n.Var(name), n.Lit(offset))), {"eq": "e"})
        bridge = _code("bridge", C.sig_bridge("Int", "Int"), (name,),
                       n.Call("add", (n.Var(name), n.Lit(offset))), {"add": "a"})
        for value in (law, bridge):
            text = show_code(value, signature=True, deps=True, exact=True)
            assert parse_code(text) == value
            expression = print_expr(C.decode_node(value.fields[2]))
            assert " = " + expression + ">" in text


def test_all_code_expression_kinds_use_core_printer():
    from opulse.atoms.notation import print_expr

    body = n.Case(((n.Test(n.Lit(True)), n.Lit(1)),), n.Lit(0))
    for kind, sig, params in (("operation", C.sig_op((), ("int", "bottom")), ()),
                              ("object", C.sig_const(), ())):
        code = C.make_code(kind, sig, params, body, lambda _: None)
        text = show_code(code, signature=True, deps=True, exact=True)
        assert " = " + print_expr(C.decode_node(code.fields[2])) + ">" in text
        assert parse_code(text) == code


def test_template_instantiation_notation_preserves_origin():
    from opulse.atoms.spec import Definition, TemplateSpec

    pattern = {"name": "increment", "role": "transform", "rule": "add one",
               "inputs": [{"sort": "int", "enter": "bottom"}],
               "output": {"sort": "int", "enter": "bottom"},
               "input_names": ["arg0"],
               "definition_body": n.Call("add", (n.Var("arg0"), n.Lit("$step")))}
    spec = TemplateSpec("incrementer", (("step", "int"),), "operation", pattern)
    template = C.quote(Definition("incrementer", "template", "invented", 1, (), spec, None),
                       lambda _: None, {})
    instance = C.instantiate_code(template, (1,), lambda name: C.Resolved(digest="add-digest")
                                  if name == "add" else None)
    text = show_code(instance, signature=True, deps=True, exact=True)
    assert "where origin " in text
    assert ' = let v0 = &"#' in text
    assert "\nwhere #" in text
    assert parse_code(text) == instance


def test_memoized_recursion_round_trips_through_code_notation():
    program = C.make_code("operation", C.sig_op((), ("int", "bottom")), (),
                          n.Rec("loop", ("value",), n.Var("value"), (n.Lit(3),), "fuel", True),
                          lambda _: None)
    text = show_code(program, signature=True, deps=True, exact=True)
    assert "rec memo r0" in text
    assert parse_code(text) == program


def test_seeded_canonical_codes_and_compact_context():
    rng = random.Random(73421)
    for index in range(320):
        program = gen_code.random_code(rng, index % 4)
        exact = show_code(program, signature=True, deps=True, exact=True)
        assert parse_code(exact) == program
        compact = show_code(program)
        assert compact.isascii()
        assert "#" not in compact or len(compact.split("#", 1)[1][:12]) == 12
        resolver = {"#" + C.code_hash(dep): C.Resolved(code=dep)
                    for dep in C.items(program.fields[4])}
        resolver.update({atom.fields[0]: C.Resolved(digest=atom.fields[1])
                         for atom in C.items(program.fields[3])})
        assert parse_code(compact, resolver, signature=program.fields[1]) == program


def test_case_rec_blocks_and_value_escapes():
    signature = C.sig_op([("int", "normalize")], ("int", "bottom"))
    rec = n.Rec("loop", ("counter",), n.Case((
        (n.Or(n.Test(n.Call("eq", (n.Var("counter"), n.Lit(0)))),
              n.Not(n.Test(n.Call("lt", (n.Var("counter"), n.Lit(0)))))),
         n.Lit('a"\\\n')),), n.Call("loop", (n.Lit(0),))),
        (n.Var("value"),), "fuel")
    block = n.Blocks((("temp", rec),), "start", (("start", n.Block((
        ("temp", n.Var("temp")),), n.CondJump(n.Test(n.Lit(Card("bool", "true"))), "end", "start"))),
                                                ("end", n.Block((), n.Halt(n.Var("temp"))))))
    program = _code("operation", signature, ("value",), block,
                    {"eq": "abc", "lt": "def"})
    printed = show_code(program, signature=True, deps=True, exact=True)
    assert "x0: int!normalize" in printed
    assert "blocks {" in printed and "measure fuel" in printed
    assert "not lt(" in printed
    assert parse_code(printed) == program


def test_combinator_operator_position_order_and_blocks_entry():
    comb = _code("combinator", C.sig_comb(3, [2, 0]), ("a", "b", "c"),
                 n.Call("c", (n.Var("b"),)))
    assert show_code(comb) == "Code<comb [x2, x0] (x1) = x2(x1)>"
    assert parse_code(show_code(comb)) == comb
    blocks = _code("object", C.sig_const(), (), n.Blocks((), "second", (
        ("first", n.Block((), n.Jump("second"))),
        ("second", n.Block((), n.Halt(n.Lit(0)))))))
    assert show_code(blocks) == (
        "Code<obj = prog () entry l0 { l1: jump l0; l0: halt 0 }>")
    assert parse_code(show_code(blocks)) == blocks


def test_seeded_vn_states_and_both_memory_forms():
    rng = random.Random(850)
    for index in range(200):
        size = (16, 32)[index % 2]
        memory = tuple(rng.randrange(256) for _ in range(size - 4)) + (0,) * 4
        state = machine.to_card(reference.State(rng.randrange(size), rng.randrange(256),
                                                memory, bool(rng.randrange(2))))
        for compact in (False, True):
            assert parse_vn(show_vn(state, compact=compact)) == state


def test_builder_world_values():
    cases = [base(), z5(), body_world()[0],
             base(ops=[W.table("id", "transform", ["z"], "z", ["overflow"],
                               [W.row([Card("z", "z0")], W.err("overflow")),
                                W.row([Card("z", "z1")], W.val(Card("z", "z1")))])])]
    for world in cases:
        printed = show_world(world)
        assert printed.isascii()
        assert parse_world(printed) == world
    assert "err(overflow)" in show_world(cases[-1])
    assert "add5(z<z0>, z<z0>) = z<z0>" in show_world(cases[1])


def test_builder_world_with_laws_exact_round_trip():
    from opulse.meta.builder import world_value as W

    law_code = C.make_code("law", C.sig_law((("item", "digit"),)), ("item",),
                           n.Call("eq", (n.Var("item"), n.Var("item"))),
                           lambda name: C.Resolved(digest="eq-digest") if name == "eq" else None)
    world = W.world("lawful", 1, (W.range_sort("digit", 0, 2),), (), ("Lit",), "none", (),
                    "full_state", ("law",), (), (W.law("reflexive", law_code),))
    printed = show_world(world)
    assert printed.isascii()
    assert "laws {" in printed and "#reflexive = Code<law" in printed
    assert parse_world(printed) == world
    with pytest.raises(ValueError):
        parse_world(printed.replace("#reflexive", "reflexive", 1))
    with pytest.raises(ValueError):
        parse_world(printed.replace("#reflexive = Code<law", "#reflexive = Code<op", 1))


@pytest.mark.parametrize("parse,text,fragment", [
    (parse_code, "Code<obj = case { always -> 0; else -> }>", "line 1, column"),
    (parse_code, "Code<obj = 1>\nwhere #000000000000 = Code<obj = 2>", "line 2, column"),
    (parse_vn, "VN<pc=0, a=0, halted=false, mem=Mem<16: 1, 2, nope>>", "line 1, column"),
    (parse_world, "World<broken@1\n  missing anything;\n>", "line 2, column"),
])
def test_errors_report_position(parse, text, fragment):
    with pytest.raises(NotationError, match=fragment):
        parse(text)
