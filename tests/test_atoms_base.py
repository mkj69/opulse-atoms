"""atoms-v2 values and kernel nodes (docs/spec/atoms-v2.md sections 2, 3, 6.1)."""

from hypothesis import given, settings
from hypothesis import strategies as st

from opulse.atoms.kernel import Atom, DictScope, evaluate
from opulse.atoms.nodes import (
    NODE_TYPES,
    Always,
    Block,
    Blocks,
    Call,
    Case,
    CondJump,
    Halt,
    Let,
    Lit,
    Not,
    Rec,
    Test,
    Var,
    from_json,
    length,
    map_nodes,
    node_kinds,
    references,
    to_json,
    walk,
)
from opulse.atoms.values import (
    FALSE,
    TRUE,
    Bottom,
    Card,
    Ok,
    Unknown,
    boolean,
    decode,
    decode_outcome,
    encode,
    encode_outcome,
    outcome_equal,
    truth,
    value_equal,
)
from opulse.worlds.perm import Permutation


def test_outcome_equality_rules():
    assert outcome_equal(Ok(3), Ok(3))
    assert not outcome_equal(Ok(3), Ok(True))
    assert outcome_equal(Bottom("div_zero"), Bottom("blocked"))
    assert not outcome_equal(Bottom("x"), Ok(0))
    assert not outcome_equal(Unknown("fuel"), Unknown("fuel"))
    assert not outcome_equal(Unknown("fuel"), Bottom("x"))


def test_map_nodes_rebuilds_conditions_recursion_and_blocks():
    tree = Blocks((("initial", Lit(1)),), "entry", (("entry", Block(
        (("current", Rec("repeat", ("item",),
                         Case(((Test(Call("positive", (Var("item"),))), Lit(2)),), Lit(3)),
                         (Lit(4),), Lit(5))),),
        CondJump(Not(Test(Lit(True))), "entry", "done"))),
        ("done", Block((), Halt(Let("result", Lit(6), Var("result")))))))
    original = tuple(node.value for node in walk(tree)
                     if isinstance(node, Lit) and type(node.value) is int)
    seen = []

    def double(node):
        seen.append(node)
        return Lit(node.value * 2) if isinstance(node, Lit) and type(node.value) is int else node

    mapped = map_nodes(tree, double)
    assert original == (1, 4, 5, 2, 3, 6)
    assert tuple(node.value for node in walk(mapped)
                 if isinstance(node, Lit) and type(node.value) is int) == (2, 8, 10, 4, 6, 12)
    assert len(seen) == sum(isinstance(node, NODE_TYPES) for node in walk(tree))
    assert tree.vars[0][1] == Lit(1)
    assert map_nodes(tree, double, stop_at=(Blocks,)) is tree


@settings(deadline=None)
@given(st.integers(min_value=-100, max_value=100))
def test_map_nodes_identity_preserves_program_semantics(number):
    expression = Case(((Test(Call("positive", (Lit(number),))),
                        Call("add", (Lit(number), Lit(1)))),), Lit(number))
    scope = DictScope(atoms=[Atom("positive", 1, lambda value: value > 0),
                             Atom("add", 2, lambda left, right: left + right)])
    original = evaluate(expression, scope=scope)
    mapped = evaluate(map_nodes(expression, lambda node: node), scope=scope)
    assert original.outcome == mapped.outcome and original.steps == mapped.steps


def test_cards_and_booleans():
    pair = Card("pair", "pair", [1, "x"])
    assert pair.fields == (1, "x")
    assert value_equal(pair, Card("pair", "pair", (1, "x")))
    assert not value_equal(pair, Card("pair", "pair", (1, "y")))
    assert not value_equal(TRUE, True) or truth(TRUE) is True
    assert boolean(False) == FALSE and truth(False) is False
    assert decode(encode(pair)) == pair
    assert decode(encode(True)) == TRUE
    for outcome in (Ok(5), Bottom("no_branch"), Unknown("depth")):
        assert decode_outcome(encode_outcome(outcome)) == outcome


def test_node_json_round_trip_and_metrics():
    rec = Rec("f", ("x",), Case([(Test(Call("is_zero", (Var("x"),))), Lit(0))],
                                default=Call("add", (Var("x"), Call("f", (Call("pred", (Var("x"),)),))))),
              (Lit(3),), measure=Var("x"))
    program = Blocks([("a", Lit(1))], "loop", [
        ("loop", Block([("a", Call("add", (Var("a"), Lit(True))))], CondJump(Not(Always()), "loop", "end"))),
        ("end", Block([], Halt(Let("y", Lit((1, Permutation((1, 0)))), Var("y"))))),
    ])
    for node in (rec, program):
        assert from_json(to_json(node)) == node
    assert references(rec) == {"is_zero", "add", "pred"}
    assert references(program) == {"add"}
    assert node_kinds(rec) == {"Rec", "Case", "Call", "Var", "Lit"}
    assert length(Call("add", (Var("a"), Lit(1)))) == 3


def test_operation_references_round_trip_as_json():
    from opulse.atoms.kernel import FnRef

    node = Call("twice", (Lit(FnRef("succ")), Lit(2)))
    assert to_json(node)["args"][0] == {"node": "Lit", "value": {"t": "fn", "v": "succ"}}
    assert from_json(to_json(node)) == node


def test_declared_failures_round_trip_as_json():
    from opulse.atoms.combinators import standard_combinators

    assert from_json(to_json(Lit(Bottom("not_stable")))) == Lit(Bottom("not_stable"))
    for spec in standard_combinators():
        assert from_json(to_json(spec.body)) == spec.body


def test_dependencies_may_list_operations_passed_as_literals():
    from opulse.atoms.kernel import FnRef
    from opulse.atoms.nodes import dependencies_match

    body = Call("repeat", (Lit(FnRef("next_date")), Var("d"), Lit(7)))
    assert dependencies_match(("repeat",), body)
    assert dependencies_match(("next_date", "repeat"), body)
    assert not dependencies_match(("next_date",), body)
    assert not dependencies_match(("repeat", "other"), body)
