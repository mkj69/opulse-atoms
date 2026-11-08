"""Program and lowercase-sort regressions (docs/spec/atoms-v2.md, sections 18.5 and 19)."""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.library import Library, VerifyRequest
from opulse.atoms.notation import (
    NotationError,
    parse_definition,
    parse_expr,
    parse_program,
    parse_value,
    print_definition,
    print_expr,
    print_value,
)
from opulse.atoms.spec import Edge, OperationSpec
from opulse.atoms.values import Card, Ok
from opulse.atoms.world import WorldDecl


def test_program_accepts_learner_examples():
    source = """# lesson
op solve(x: Nat) -> Nat = x
op MUL(a: Nat, b: Nat) -> Nat = add(a, b) L1 # note
op f() -> Nat = 0 L1
op g() -> Nat = f() L1
save MUL
save g
"""
    items = parse_program(source)
    assert [item.name for item in items[:4]] == ["solve", "MUL", "f", "g"]
    assert items[0].layer == 1
    assert items[0].spec.extra["layer_unspecified"] is True
    assert print_definition(items[0]) == "op solve(x: Nat) -> Nat = x"
    assert print_definition(items[1]) == "op MUL(a: Nat, b: Nat) -> Nat = add(a, b) L1"
    assert parse_definition(print_definition(items[1])) == items[1]
    assert parse_expr(print_expr(n.Call("MUL", (n.Lit(2), n.Lit(3))))) == n.Call("MUL", (n.Lit(2), n.Lit(3)))
    assert items[4:] == ["save MUL", "save g"]
    assert parse_program("\n".join(print_definition(item) for item in items[:4]) + "\nsave g")[:4] == items[:4]


def test_law_sigil_and_comment_boundary():
    items = parse_program("law #identity: eq(x, x) for x: code L1 # note\n#\nsave identity")
    assert items[0] == parse_definition("law #identity: eq(x, x) for x: code L1")
    assert items[1] == "save identity"
    with pytest.raises(NotationError):
        parse_program("op f() -> int = 0 #nospace")
    with pytest.raises(NotationError):
        parse_definition("op f() -> int = 0")
    assert parse_program('op msg() -> str = "# a literal" # comment')[0].body == n.Lit("# a literal")


@pytest.mark.parametrize("sort", ["code", "expr", "list", "world"])
def test_lowercase_sort_and_card_round_trip(sort):
    source = f"op wrap(value: {sort}) -> {sort} = {sort}.item<1> L2"
    definition = parse_definition(source)
    assert parse_definition(print_definition(definition)) == definition
    assert parse_value(f"{sort}.item<1>") == Card(sort, "item", (1,))
    assert parse_expr(sort) == n.Var(sort)
    assert parse_value(sort) == Card(sort, sort)


def test_bridge_cross_world_sort_round_trip():
    source = "bridge ~embed: z5@1:z -> z5xbool@1:pair = pair(x) L2"
    assert print_definition(parse_definition(source)) == source


def test_public_value_observation_signature_round_trip():
    source = "obs ?palindrome{xs: List, steps: int} -> bool = eq(xs, steps) L3"
    definition = parse_definition(source)
    assert definition.spec.extra["inputs"] == (("xs", "List"), ("steps", "int"))
    assert print_definition(definition) == source
    assert parse_definition(print_definition(definition)) == definition


def test_parsed_public_observation_enters_pipeline_and_private_remains_private():
    eq = OperationSpec("eq", "decide", (Edge("int"), Edge("int")), Edge("bool"), "eq")
    world = WorldDecl("notation-observations", 1, "atoms-v2", {}, {}, (), (eq,),
                      {"nodes": list(n.NODE_NAMES), "recursion": "fuel"},
                      {"truth": "state", "probes": [{"name": "peek"}],
                       "capabilities": {"learner": {"probes": "all"}}}, {})
    lib = Library(world, (kernel.Atom("eq", 2, lambda left, right: left == right),
                          kernel.Atom("peek", 1, lambda state: state > 0, kind="observation")))
    source = "obs ?same{left: int, right: int} -> bool = eq(left, right) L1"
    definition = parse_definition(source, lib)
    assert definition.spec.extra["inputs"] == (("left", "int"), ("right", "int"))
    assert print_definition(definition) == source
    assert print_definition(parse_definition(print_definition(definition), lib)) == source
    lib.write(definition)
    lib.check("same")
    domain = ((2, 2), (2, 3))
    lib.make_callable("same", domain)
    verified = lib.verify("same", VerifyRequest("bounded", domain,
                                                {"domain": "two integer pairs", "size": len(domain)}))
    assert verified.evidence.scope["non_interference"] == "n/a"
    assert lib.run("same", (2, 2)).outcome == Ok(True)
    assert lib.run("same", (2, 3)).outcome == Ok(False)

    private = "obs ?p{s} = ?peek{s} L1"
    private_definition = parse_definition(private, lib)
    assert "inputs" not in private_definition.spec.extra
    assert print_definition(parse_definition(print_definition(private_definition), lib)) == private
    lib.write(private_definition)
    lib.check("p")

    typed = "obs ?q{s: state} = ?peek{s} L1"
    typed_definition = parse_definition(typed, lib)
    assert "inputs" not in typed_definition.spec.extra
    assert print_definition(typed_definition) == typed
    lib.write(typed_definition)
    lib.check("q")


def test_worlds_action_exported_declaration_round_trip():
    source = ("obs ?front_clear{b: Bot} -> bool = "
              "not(?front_wall{b}) and not(?front_water{b}) L1")
    assert print_definition(parse_definition(source)) == source


def test_multi_input_observation_call_round_trip():
    source = "obs ?same{left: int, right: int} -> bool = eq(left, right) L1"
    assert print_definition(parse_definition(source)) == source
    expression = n.Call("same", (n.Lit(1), n.Lit(2)))
    context = {"kinds": {"same": "observation"}, "observation_arity": {"same": 2}}
    assert parse_expr(print_expr(expression, context), context) == expression
    assert parse_definition("obs ?same{left: int, right: int} -> bool = ?same{left, right} L1")
    assert parse_definition("obs ?same{left: int, right: int} -> bool = ?same{left, right} L1",
                            {"kinds": {"same": "observation"}})


@settings(deadline=None)
@given(st.sampled_from(["code", "expr", "list"]), st.integers(-20, 20))
def test_public_observation_round_trip_does_not_change_body(sort, value):
    source = f"obs ?peek{{item: {sort}, offset: int}} -> bool = eq(item, {value}) L2"
    definition = parse_definition(source)
    restored = parse_definition(print_definition(definition))
    assert restored.body == definition.body
    assert restored.spec == definition.spec


def test_meta_display_only_projection_is_parseable():
    source = ('op has_div(e: Expr) -> bool = '
              '"see body JSON; compact notation cannot express this card tree" L1')
    assert print_definition(parse_definition(source)) == source
    source = "op count_row(arg0: int, arg1: row) -> int = int_add(arg0, 1) L1"
    assert print_definition(parse_definition(source)) == source
    source = "op generated_1353916b003a(x0: int) -> int = add(2, x0) L1"
    assert print_definition(parse_definition(source)) == source


def test_program_template_followed_by_definition():
    items = parse_program("template obj Wrap[T: obj, canon: op] = refine T canon(canon) L1\n"
                          "op f() -> int = 1\nsave f")
    assert [item.name for item in items[:2]] == ["Wrap", "f"]
    assert items[2] == "save f"
    assert items[1].spec.extra["layer_unspecified"] is True
    unsuffixed = parse_program("template obj Wrap[T: obj, canon: op] = refine T canon(canon)\n"
                               "op f() -> int = 1")
    assert [item.name for item in unsuffixed] == ["Wrap", "f"]
    assert unsuffixed[0].spec.extra["layer_unspecified"] is True


@settings(deadline=None)
@given(st.sampled_from(["code", "expr", "list"]), st.integers(-100, 100))
def test_lowercase_cards_preserve_literal_and_do_not_mutate_context(sort, value):
    context = {"kinds": {"other": "operation"}}
    original = {"kinds": dict(context["kinds"])}
    card = Card(sort, sort, (value,))
    expression = n.Lit(card)
    assert parse_expr(print_expr(expression, context), context) == expression
    assert parse_value(print_value(card)) == card
    assert context == original


@settings(deadline=None)
@given(st.sampled_from(["code", "expr", "list"]))
def test_zero_field_lowercase_card_is_not_confused_with_variable(sort):
    card = Card(sort, sort)
    assert parse_expr(sort) == n.Var(sort)
    assert parse_expr(print_expr(n.Lit(card))) == n.Lit(card)
    assert parse_value(print_value(card)) == card
