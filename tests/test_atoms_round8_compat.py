"""World compatibility regressions for generic value refinements (spec sections 2 and 4.3)."""

from hypothesis import given, settings
from hypothesis import strategies as st

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.library import Library
from opulse.atoms.spec import Definition, Edge, ObjectSpec, OperationSpec
from opulse.atoms.values import Bottom, Card, Ok
from opulse.atoms.world import WorldDecl


def valid_host_distribution(value):
    return (isinstance(value, Card) and value.sort == "host_dist" and value.tag == "finite"
            and len(value.fields) == 1 and type(value.fields[0]) is int and value.fields[0] > 0)


def canon_host_distribution(value):
    return Card("host_dist", "finite", (min(value.fields[0], 2),))


@settings(deadline=None)
@given(st.integers(3, 100))
def test_given_host_refinement_keeps_card_codec_at_edges(number):
    rule = lambda name: {"host": f"test_atoms_round8_compat:{name}", "digest": "0" * 64}
    host_dist = ObjectSpec("host_dist", "refine", base="value",
                           valid=rule("valid_host_distribution"), canon=rule("canon_host_distribution"))
    generic = ObjectSpec("value", "given")
    world = WorldDecl("host-refine", 1, "atoms-v2", {}, {}, (generic, host_dist), (),
                      {"nodes": list(n.NODE_NAMES), "recursion": "fuel"}, {}, {},
                      open_kinds=("operation",))
    lib = Library(world, ())
    for enter in ("bottom", "normalize"):
        name = f"pass_{enter}"
        spec = OperationSpec(name, "transform", (Edge("host_dist", enter),),
                             Edge("host_dist", enter), name, extra={"input_names": ["item"]})
        lib.write(Definition(name, "operation", "invented", 1, (), spec, n.Var("item")))
        lib.check(name)
        lib.make_callable(name, ((Card("host_dist", "finite", (number,)),),))
        actual = lib.run(name, (Card("host_dist", "finite", (number,)),))
        expected = number if enter == "bottom" else 2
        assert actual.outcome == Ok(Card("host_dist", "finite", (expected,)))
        assert actual.steps == (0 if enter == "bottom" else 2)
        inline = kernel.inline(n.Call(name, (n.Lit(Card("host_dist", "finite", (number,))),)), lib.scope())
        expanded = kernel.evaluate(inline, scope=lib.scope())
        assert (actual.outcome, actual.steps) == (expanded.outcome, expanded.steps)
        assert lib.run(name, (Card("host_dist", "finite", (-1,)),)).outcome == Bottom("invalid")


@settings(deadline=None)
@given(st.integers(0, 100))
def test_generic_given_value_refinement_accepts_concrete_card_sort(number):
    generic = ObjectSpec("value", "given")
    envelope = ObjectSpec("Envelope", "refine", base="value",
                          valid=n.Call("is_event", (n.Var("x"),)), canon=n.Var("x"))
    world = WorldDecl("generic-value", 1, "atoms-v2", {}, {}, (generic, envelope), (),
                      {"nodes": list(n.NODE_NAMES), "recursion": "fuel"}, {}, {})
    lib = Library(world, (kernel.Atom("is_event", 1, lambda value: isinstance(value, Card)
                               and value.sort == "event" and value.tag == "range"
                               and len(value.fields) == 1 and type(value.fields[0]) is int
                               and value.fields[0] >= 0),))
    event = Card("event", "range", (number,))
    wrapped = Card("Envelope", "val", (event,))
    assert lib.run("Envelope.make", (event,)).outcome == Ok(wrapped)
    assert lib.run("Envelope.base", (wrapped,)).outcome == Ok(event)
    assert lib.run("Envelope.base", (Card("Envelope", "val", (Card("other", "range", (number,)),)),)).outcome == Bottom("invalid")


@settings(deadline=None)
@given(st.integers(0, 100))
def test_generic_any_field_accepts_other_declared_card_sort(number):
    generic = ObjectSpec("any", "given")
    sequence = ObjectSpec("List", "compose", tags={"list": {"items": "any"}})
    pair = ObjectSpec("Pair", "compose", tags={"pair": (("value", "int"),)})
    world = WorldDecl("any-field", 1, "atoms-v2", {}, {}, (generic, sequence, pair), (),
                      {"nodes": list(n.NODE_NAMES), "recursion": "fuel"}, {}, {})
    lib = Library(world, ())
    element = lib.run("Pair.pair", (number,)).outcome.value
    result = Card("List", "list", (element,))
    assert lib.run("List.list", ((element,),)).outcome == Ok(result)
    assert lib.run("Pair.pair", (element,)).outcome == Bottom("invalid")
