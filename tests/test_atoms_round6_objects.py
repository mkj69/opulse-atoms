"""Regressions for refined values, sealed constructors, and bool JSON (spec sections 2-4)."""

from hypothesis import given, settings
from hypothesis import strategies as st

from opulse.atoms import nodes as n
from opulse.atoms.kernel import Atom
from opulse.atoms.library import Library
from opulse.atoms.objects import sealed_private_names
from opulse.atoms.spec import Definition, Edge, ObjectSpec, OperationSpec
from opulse.atoms.values import (
    FALSE,
    TRUE,
    Bottom,
    Card,
    Ok,
    decode,
    decode_outcome,
    encode,
    encode_outcome,
    outcome_equal,
    value_equal,
)
from opulse.atoms.world import WorldDecl


def world(*objects):
    return WorldDecl("round6_objects", 1, "atoms-v2", {}, {}, objects, (),
                     {"nodes": ("Call", "Var"), "recursion": "none"}, {}, {})


def test_refined_base_rechecks_validity_and_normalizes_field_access():
    record = ObjectSpec("Pair", "compose", tags={"pair": (("num", "int"),)})
    refined = ObjectSpec("Molecule", "refine", base="Pair",
                         valid=n.Call("positive", (n.Call("Pair.num", (n.Var("x"),)),)),
                         canon=n.Call("normalize", (n.Var("x"),)),
                         extra={"fields": ("num",)})
    lib = Library(world(record, refined), (Atom("positive", 1, lambda number: number > 0),
                                           Atom("normalize", 1, lambda value: Card(
                                               "Pair", "pair", (min(value.fields[0], 2),)))))
    normal = Card("Pair", "pair", (2,))
    wrapped = lib.run("Molecule.make", (Card("Pair", "pair", (3,)),)).outcome.value
    assert wrapped == Card("Molecule", "val", (normal,))
    assert lib.run("Molecule.base", (wrapped,)).outcome == Ok(normal)
    assert lib.run("Molecule.num", (wrapped,)).outcome == Ok(2)
    noncanonical = Card("Molecule", "val", (Card("Pair", "pair", (3,)),))
    assert lib.run("Molecule.base", (noncanonical,)).outcome == Ok(noncanonical.fields[0])
    assert lib.run("Molecule.num", (noncanonical,)).outcome == Ok(2)
    for forged in (Card("Molecule", "val", (Card("Pair", "pair", (0,)),)),
                   Card("Molecule", "val", (Card("Pair", "other", (1,)),)),
                   Card("Molecule", "val", (Card("Pair", "pair"),)),
                   Card("Molecule", "other", (normal,)),
                   Card("Molecule", "val"), Card("Molecule", "val", (1,))):
        assert lib.run("Molecule.base", (forged,)).outcome == Bottom("invalid")
        assert lib.run("Molecule.num", (forged,)).outcome == Bottom("invalid")
    assert lib.run("Molecule.base", (Card("Pair", "pair", (2,)),)).outcome == Bottom("wrong_tag")
    assert lib.run("Molecule.base", (wrapped,)).steps >= 3


def test_sealed_interface_constructor_alias_is_callable():
    record = ObjectSpec("OrderData", "compose", tags={"order": (("count", "int"),)})
    refined = ObjectSpec("Order", "refine", base="OrderData",
                         valid=n.Call("positive", (n.Call("OrderData.count", (n.Var("x"),)),)),
                         sealed=True, interface=("make_order", "Order.count"))
    lib = Library(world(record, refined), (Atom("positive", 1, lambda count: count > 0),))
    assert "Order.make" not in sealed_private_names(lib)
    assert "Order.base" in sealed_private_names(lib)
    operation = OperationSpec("make_order", "combine", (Edge("int"),), Edge("Order"),
                              "Construct an order")
    lib.write(Definition("make_order", "operation", "invented", 1,  # Order is a world object (layer 0)
                         ("Order.make", "OrderData.order"), operation,
                         n.Call("Order.make", (n.Call("OrderData.order", (n.Var("arg0"),)),))))
    lib.check("make_order")
    lib.make_callable("make_order", [(2,)])
    assert lib.run("make_order", (2,)).outcome == Ok(Card(
        "Order", "val", (Card("OrderData", "order", (2,)),)))
    short_name = ObjectSpec("Box", "refine", base="int", valid=n.Lit(True),
                            sealed=True, interface=("make",))
    assert "Box.make" not in sealed_private_names(Library(world(short_name), ()))


def test_free_canon_rechecks_without_charging_the_canon():
    valid = n.Call("valid", (n.Var("x"),))
    canon = n.Call("normalize", (n.Var("x"),))
    counted = ObjectSpec("Counted", "refine", base="int", valid=valid, canon=canon)
    free = ObjectSpec("Free", "refine", base="int", valid=valid, canon=canon,
                      canon_cost="free")
    lib = Library(world(counted, free), (Atom("valid", 1, lambda value: value > 0),
                                         Atom("normalize", 1, lambda value: min(value, 2))))
    counted_value = Card("Counted", "val", (2,))
    free_value = Card("Free", "val", (2,))
    counted_run = lib.run("Counted.base", (counted_value,))
    free_run = lib.run("Free.base", (free_value,))
    assert counted_run.outcome == free_run.outcome == Ok(2)
    assert counted_run.steps == free_run.steps >= 2
    assert lib.run("Counted.make", (3,)).steps > lib.run("Free.make", (3,)).steps
    assert lib.run("Free.base", (Card("Free", "val", (3,)),)).outcome == Ok(3)
    assert lib.run("Free.base", (Card("Free", "val", (0,)),)).outcome == Bottom("invalid")


def test_subgroup_base_accepts_valid_noncanonical_members():
    subgroup = ObjectSpec("Subgroup", "refine", base="int",
                          valid=n.Call("in_range", (n.Var("x"),)),
                          canon=n.Call("order", (n.Var("x"),)))
    lib = Library(world(subgroup), (Atom("in_range", 1, lambda count: 0 <= count < 10),
                                    Atom("order", 1, lambda count: count % 3)))
    assert lib.run("Subgroup.base", (Card("Subgroup", "val", (8,)),)).outcome == Ok(8)
    assert lib.run("Subgroup.base", (Card("Subgroup", "val", (12,)),)).outcome == Bottom("invalid")
    made = lib.run("Subgroup.make", (8,)).outcome.value
    assert lib.run("Subgroup.base", (made,)).outcome == Ok(2)


SCALARS = st.one_of(st.booleans(), st.integers(), st.text(max_size=8),
                    st.sampled_from((TRUE, FALSE)))
CARDS = st.builds(Card, st.sampled_from(("pair", "bool")),
                  st.sampled_from(("pair", "other")), st.tuples(SCALARS, SCALARS))


@settings(max_examples=80, derandomize=True, deadline=None)
@given(st.one_of(SCALARS, CARDS, st.tuples(SCALARS, CARDS),
                 st.tuples(SCALARS, SCALARS), st.tuples(CARDS, CARDS)))
def test_encoded_values_and_node_literals_preserve_value_equality(value):
    assert value_equal(value, decode(encode(value)))
    assert outcome_equal(Ok(value), decode_outcome(encode_outcome(Ok(value))))
    assert value_equal(value, n.from_json(n.to_json(n.Lit(value))).value)


def test_bool_cards_equal_only_the_matching_host_bool():
    for card, flag in ((TRUE, True), (FALSE, False)):
        assert value_equal(card, flag) and value_equal(flag, card)
        assert outcome_equal(Ok(card), Ok(flag))
        assert not value_equal(card, not flag)
        assert not value_equal(card, int(flag))
    assert not value_equal(Card("bool", "true", (1,)), True)
