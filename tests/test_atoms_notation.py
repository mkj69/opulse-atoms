"""ASCII notation round trips for six atom kinds and templates (spec 0.4)."""

from dataclasses import replace
from types import SimpleNamespace

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from opulse.atoms import nodes as n
from opulse.atoms.kernel import FnRef
from opulse.atoms.notation import (
    NotationError,
    generated_name,
    is_valid_name,
    legacy_symbol_to_ascii,
    parse_definition,
    parse_expr,
    parse_step_annotation,
    parse_value,
    print_definition,
    print_expr,
    print_step_annotation,
    print_value,
    stored_name,
)
from opulse.atoms.values import Card

CONTEXT = {"kinds": {"twice": "combinator", "both": "combinator", "repeat": "combinator",
                     "whole": "observation", "seven": "observation", "islands": "observation",
                     "table": "observation", "front_wall": "observation", "front_water": "observation"},
           "op_arity": {"twice": 1, "both": 2, "repeat": 1},
           "infix": {"add": "+", "sub": "-", "mul": "*"}}


@pytest.mark.parametrize("text", ["Frac<1, 2>", "Set<>", "List<1, 2>", "true", "false", "-12", '"hi"', "Grid<(0, 0), (2, 2)>"])
def test_values(text):
    value = parse_value(text)
    assert parse_value(print_value(value)) == value
    assert print_value(value).isascii()


@pytest.mark.parametrize("text", [
    "f6(a, b)", "f1(12)", "@twice[f1](2)", "@both[roll, roll]()",
    "?whole{Frac<2, 4>}", "a + b * (c - d)",
    "if is_zero(b) then 0 else add(a, mul(a, dec(b)))",
    "?seven{@both[roll, roll]()}",
    "safe_step(Bot<0, E, Set<2>, Set<>>)",
    "?islands{Grid<(0, 0), (2, 2)>}",
    "?table{Xor}",
    "@repeat[f1](2, 12)",
    "not_a_function(1)", "let x = 1 in add(x, x)",
    "rec f(x) = if eq(x, 0) then 1 else f(dec(x)) measure x in f(2)",
    "rec memo f(x) = x measure fuel in f(2)",
    "prog (x = 0) entry L0 { L0: x := add(x, 1); if lt(x, 3) jump L0 else L1; L1: halt x }",
])
def test_expressions(text):
    node = parse_expr(text, CONTEXT)
    printed = print_expr(node, CONTEXT)
    assert parse_expr(printed, CONTEXT) == node
    assert printed.isascii()


@pytest.mark.parametrize("text", [
    "obj Frac = <num: Int, den: Int> where ne(den, 0) canon reduce sealed (make, num, den) L2",
    "obj List = Nil | Cons<head: Int, tail: List> L1",
    "obj Answer = 42 L1",
    "op mul(a: Int, b: Int) -> Int = if is_zero(b) then 0 else add(a, mul(a, dec(b))) L1",
    "comb @twice[f: A -> A](x: A) -> A = f(f(x)) L1",
    "obs ?front_free{s} = not(?front_wall{s}) and not(?front_water{s}) L1",
    "op f6(x: Int) -> Int = x given",
])
def test_declarations(text):
    definition = parse_definition(text)
    printed = print_definition(definition)
    assert parse_definition(printed) == definition
    assert not definition.validate()
    assert printed.isascii()
    if text.startswith("obs ?front_free"):
        assert printed == text


@pytest.mark.parametrize("text", ["x < y", "f(1,)", "a + b", "@twice[f, g](2)", "?whole{a, b}", "1 2", "List<1,>", "α(1)"])
def test_reject_ambiguous(text):
    with pytest.raises(NotationError) as error:
        parse_expr(text, CONTEXT if text != "a + b" else None)
    assert error.value.column >= 1


def test_generated_and_legacy_names():
    for kind, index, expected in [("object", 7, "H0"), ("operation", 6, "f6"),
                                  ("combinator", 3, "@k3"), ("observation", 4, "?q4"),
                                  ("law", 5, "#r5"), ("bridge", 2, "~b2")]:
        assert generated_name(kind, index) == expected
        assert is_valid_name(kind, expected)
    for symbol in ("♦₆", "♡₆", "♠₆", "◆₆", "▲₆", "⊕₆"):
        assert legacy_symbol_to_ascii(symbol) == "f6"
    assert not is_valid_name("operation", "♦₆")


@pytest.mark.parametrize("text", [
    "law #mul_comm: eq(mul(a, b), mul(b, a)) for a: Int, b: Int L1",
    "law #identity: eq(add(x, 0), x) for x: Int given",
    "bridge ~to_frac: MyFrac -> Frac = make(x) where valid(x) commutes (add2 -> add, neg2 -> neg) L2",
    "bridge ~identity: Frac -> Frac = x given",
    "bridge ~translate: integer -> clock = x L2",
    "template obj Quot[T: obj, canon: op] = refine T canon(canon) L2",
    "template op lift[f: op] = lift(f) L1",
    "template comb @fold[step: op] = step(x) L1",
    "template obs ?count[probe: obs] = probe(x) L1",
    "obj Frac = Quot[Pair<Int, Int>, reduce] L3",
])
def test_six_kind_declarations_and_templates(text):
    definition = parse_definition(text)
    rendered = print_definition(definition)
    assert rendered == text
    assert rendered.isascii()
    assert parse_definition(rendered) == definition
    assert not definition.validate()


def test_template_pattern_and_instantiation_dependency():
    template = parse_definition("template obj Quot[T: obj, canon: op] = refine T canon(canon) L2")
    assert template.spec.pattern["form"] == "refine"
    assert template.spec.pattern["base"] == "$T"
    assert template.spec.pattern["canon"] == n.to_json(n.Call("$canon", (n.Var("x"),)))
    instance = parse_definition("obj Frac = Quot[Pair, reduce] L3")
    assert instance.depends_on == ("Quot",)
    assert print_definition(instance) == "obj Frac = Quot[Pair, reduce] L3"


def test_law_rewrite_step_annotation():
    assert parse_step_annotation("by #mul_comm") == "mul_comm"
    assert print_step_annotation("mul_comm") == "by #mul_comm"
    for source in ("by mul_comm", "by #mul_comm extra", "by ~to_frac", "by #MUL"):
        with pytest.raises(NotationError):
            parse_step_annotation(source)
    with pytest.raises(ValueError):
        print_step_annotation("#mul_comm")


def test_bridge_application_requires_context_and_sigil():
    ctx = {"kinds": {"to_frac": "bridge"}}
    node = parse_expr("~to_frac(x)", ctx)
    assert node == n.Call("to_frac", (n.Var("x"),))
    assert print_expr(node, ctx) == "~to_frac(x)"
    for text in ("to_frac(x)", "~to_frac(x, y)", "~other(x)"):
        with pytest.raises(NotationError):
            parse_expr(text, ctx)
    with pytest.raises(ValueError):
        print_expr(n.Call("to_frac", (n.Var("x"), n.Var("y"))), ctx)


@pytest.mark.parametrize("text", [
    "Frac<1, 2>", "mul(3, 4)", "@twice[double](3)", "?even{12}",
    "law #mul_comm: eq(mul(a, b), mul(b, a)) for a: Int, b: Int L1",
    "bridge ~to_frac: MyFrac -> Frac = make(x) L2",
    "~to_frac(x)", "by #mul_comm",
])
def test_six_kinds_common_examples(text):
    if text.startswith(("law ", "bridge ")):
        assert print_definition(parse_definition(text)) == text
    elif text.startswith("by "):
        assert print_step_annotation(parse_step_annotation(text)) == text
    else:
        context = {"kinds": {"twice": "combinator", "even": "observation", "to_frac": "bridge"},
                   "op_arity": {"twice": 1}}
        assert parse_expr(print_expr(parse_expr(text, context), context), context) == parse_expr(text, context)


@given(st.sampled_from(["eq", "lt", "le", "ne"]), st.sampled_from(["a", "b", "x"]),
       st.sampled_from(["Int", "Frac"]))
@settings(max_examples=100, deadline=None)
def test_generated_law_round_trip(predicate, variable, sort):
    source = f"law #r5: {predicate}({variable}, 0) for {variable}: {sort} L1"
    definition = parse_definition(source)
    assert definition.spec.statement == definition.body
    assert parse_definition(print_definition(definition)) == definition
    assert print_definition(definition).isascii()


@given(st.sampled_from(["MyFrac", "Frac", "Pair"]), st.sampled_from(["Frac", "Int"]),
       st.sampled_from(["x", "make(x)", "normalize(x)"]), st.booleans())
@settings(max_examples=100, deadline=None)
def test_generated_bridge_round_trip(source, target, mapping, partial):
    text = f"bridge ~b2: {source} -> {target} = {mapping}"
    if partial:
        text += " where valid(x) commutes (add2 -> add, neg2 -> neg)"
    definition = parse_definition(text + " L2")
    assert parse_definition(print_definition(definition)) == definition
    assert print_definition(definition).isascii()


@pytest.mark.parametrize("source", [
    "@fix[step](x, h)", "@turns[act, wait](state)", "@S.fold[step](v)",
    "rec memo f(x) = f(dec(x)) measure x in f(3)",
])
def test_combination_modes_ascii(source):
    context = {"kinds": {"fix": "combinator", "turns": "combinator", "S.fold": "combinator"},
               "op_arity": {"fix": 1, "turns": 2, "S.fold": 1}}
    node = parse_expr(source, context)
    assert print_expr(node, context) == source


def test_reject_unrepresentable_values():
    for value in (Card("List", "List"), Card("bool", "true"), FnRef("f")):
        with pytest.raises((TypeError, ValueError)):
            print_value(value)
    with pytest.raises(ValueError):
        print_expr(n.Var("Xor"))


def test_condition_and_constant_forms():
    assert parse_value("Xor") == Card("Xor", "Xor")
    condition = parse_expr("not(?front_wall{s}) and not(?front_water{s})", CONTEXT)
    assert parse_expr(print_expr(condition, CONTEXT), CONTEXT) == condition
    with pytest.raises(ValueError):
        print_value(Card("Xor", "bad tag"))
    definition = parse_definition("obj Code = (Xor<>) L1")
    assert parse_definition(print_definition(definition)) == definition
    with pytest.raises(NotationError) as error:
        parse_definition("op f(x: Int, x: Int) -> Int = x L1")
    assert error.value.column >= 1


def test_context_maps_kernel_names_to_display_names():
    ctx = {"kinds": {"twice": "combinator", "whole": "observation"}, "op_arity": {"twice": 1}}
    for node in (n.Call("twice", (n.Lit(FnRef("f")), n.Lit(3))),
                 n.Call("whole", (n.Lit(3),))):
        printed = print_expr(node, ctx)
        assert printed.startswith(("@twice[", "?whole{"))
        assert parse_expr(printed, ctx) == node


def test_kind_sigil_and_stored_references():
    ctx = {"kinds": {"front_wall": "observation", "front_water": "observation",
                     "front_free": "observation", "twice": "combinator", "f": "operation"},
           "op_arity": {"twice": 1}, "probes": {"front_wall", "front_water"}}
    text = "obs ?front_free{s} = not(?front_wall{s}) and not(?front_water{s}) L1"
    definition = parse_definition(text, ctx)
    assert definition.name == definition.spec.name == "front_free"
    assert definition.depends_on == ("front_wall", "front_water")
    assert definition.spec.reads == definition.depends_on
    assert definition.spec.extra["subject"] == "s"
    assert {part.fn for part in n.walk(definition.body) if isinstance(part, n.Call)} == set(definition.depends_on)
    assert all(part.args == (n.Var("s"),) for part in n.walk(definition.body) if isinstance(part, n.Call))
    assert print_definition(definition, ctx) == text
    assert parse_definition(print_definition(definition, ctx), ctx) == definition
    with pytest.raises(ValueError):
        print_definition(replace(definition, depends_on=("?front_wall", "front_water")), ctx)
    assert parse_expr("@twice[f](?front_wall{s})", ctx) == n.Call("twice", (
        n.Lit(FnRef("f")), n.Call("front_wall", (n.Var("s"),))))
    for text in ("?twice{s}", "@front_wall[f](s)", "front_wall(s)", "@twice[front_wall](s)"):
        with pytest.raises(NotationError):
            parse_expr(text, ctx)
    for kind, display in (("combinator", "@twice"), ("observation", "?front_wall")):
        assert is_valid_name(kind, stored_name(display))
        assert is_valid_name(kind, display)
    assert stored_name("@k3") == "k3"
    assert stored_name("?q4") == "q4"


def test_observation_subject_and_library_kinds():
    world = SimpleNamespace(operations=(SimpleNamespace(name="f"),),
                            observation={"probes": ({"name": "front_wall"},)})
    lib = SimpleNamespace(world=world, definitions={
        "front_free": SimpleNamespace(kind="observation", spec=None),
        "twice": SimpleNamespace(kind="combinator", spec=SimpleNamespace(op_params=("f",))),
    })
    source = "obs ?front_free{robot} = ?front_wall{robot} L1"
    definition = parse_definition(source, lib)
    assert definition.spec.extra["subject"] == "robot"
    assert definition.spec.reads == ("front_wall",)
    assert definition.depends_on == ("front_wall",)
    assert print_definition(definition, lib) == source
    assert parse_definition(print_definition(definition, lib), lib) == definition
    assert parse_expr("?front_wall{robot}", lib) == n.Call("front_wall", (n.Var("robot"),))
    for expression in ("?f{robot}", "@front_wall[f](robot)", "?missing{robot}"):
        with pytest.raises(NotationError):
            parse_expr(expression, lib)
    with pytest.raises(ValueError):
        print_expr(n.Call("?front_wall", (n.Var("robot"),)), lib)
    with pytest.raises(NotationError):
        parse_definition("comb @front_free[f: A -> A](x: A) -> A = x L1", lib)


def test_observation_dependency_is_not_a_probe_read():
    ctx = {"kinds": {"front_wall": "observation", "front_free": "observation",
                     "safe": "observation"}, "probes": {"front_wall"}}
    source = "obs ?safe{s} = ?front_free{s} and ?front_wall{s} L2"
    definition = parse_definition(source, ctx)
    assert definition.spec.reads == ("front_wall",)
    assert definition.depends_on == ("front_free", "front_wall")
    assert print_definition(definition, ctx) == source
    assert parse_definition(source, ctx) == definition


def test_object_generated_names_cycle():
    assert [generated_name("object", index) for index in (0, 25, 26, 27, 51, 52)] == [
        "A0", "Z0", "A1", "B1", "Z1", "A2"]
    for name in ("A0", "Z123", "Xor"):
        assert is_valid_name("object", name)


def test_observation_boolean_shortcut_is_not_ambiguous():
    for condition in (n.Always(), n.Test(n.Lit(0)), n.And(n.Always(), n.Test(n.Var("x")))):
        body = n.Case(((condition, n.Lit(True)),), n.Lit(False))
        declaration = parse_definition("obs ?check{x} = " + print_expr(body) + " L1")
        assert parse_definition(print_definition(declaration)) == declaration


values = st.one_of(st.integers(-100, 100), st.text(alphabet="abc_", max_size=6), st.booleans(),
                   st.sampled_from([Card("Frac", "Frac"), Card("Set", "Set"), Card("Frac", "Set")]))
base = st.one_of(st.builds(n.Lit, values), st.builds(n.Var, st.sampled_from(["x", "y", "z"])))
expressions = st.recursive(base, lambda children: st.one_of(
    st.builds(n.Call, st.sampled_from(["add", "sub", "mul", "eq", "f"]), st.lists(children, max_size=2).map(tuple)),
    st.builds(n.Let, st.sampled_from(["x", "y"]), children, children),
    st.builds(n.Case, st.tuples(st.tuples(st.builds(n.Test, children), children)), children),
    st.builds(n.Call, st.just("twice"), children.map(lambda item: (n.Lit(FnRef("f")), item))),
    st.builds(n.Call, st.just("whole"), children.map(lambda item: (item,))),
), max_leaves=12)


@given(expressions)
@settings(max_examples=600, deadline=None)
def test_generated_expression_round_trip(node):
    printed = print_expr(node, CONTEXT)
    assert printed.isascii()
    assert parse_expr(printed, CONTEXT) == node


@given(st.sampled_from(["operation", "combinator", "observation", "object"]), expressions)
@settings(max_examples=500, deadline=None)
def test_generated_definition_round_trip(kind, body):
    if kind == "operation":
        source = "op f(x: Int) -> Int = " + print_expr(body, CONTEXT) + " L1"
    elif kind == "combinator":
        source = "comb @twice[f: A -> A](x: A) -> A = " + print_expr(body, CONTEXT) + " L1"
    elif kind == "observation":
        source = "obs ?whole{x} = " + print_expr(body, CONTEXT) + " L1"
    else:
        source = "obj Frac = <num: Int, den: Int> where " + print_expr(body, CONTEXT) + " L1"
    definition = parse_definition(source, CONTEXT)
    assert parse_definition(print_definition(definition, CONTEXT), CONTEXT) == definition


@given(st.integers(0, 20), st.integers(0, 20), st.booleans())
@settings(max_examples=200, deadline=None)
def test_generated_control_flow(first, second, memo):
    condition = n.Or(n.And(n.Test(n.Call("lt", (n.Var("x"), n.Lit(first)))),
                             n.Not(n.Test(n.Call("eq", (n.Var("x"), n.Lit(second)))))),
                     n.Always())
    recursive = n.Rec("loop", ("x",), n.Case(((condition, n.Var("x")),),
                                                   n.Call("loop", (n.Call("dec", (n.Var("x"),)),))),
                      (n.Lit(first),), n.Var("x"), memo)
    program = n.Blocks((("x", n.Lit(first)),), "L0", (
        ("L0", n.Block((("x", n.Call("add", (n.Var("x"), n.Lit(1)))),),
                         n.CondJump(condition, "L0", "L1"))),
        ("L1", n.Block((), n.Halt(n.Lit(second))))))
    for node in (recursive, program):
        rendered = print_expr(node)
        assert rendered.isascii()
        assert parse_expr(rendered) == node
