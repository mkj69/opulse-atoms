import random

from opulse.atoms import nodes as n
from opulse.atoms.kernel import FnRef
from opulse.atoms.values import FALSE, TRUE, Bottom, Card
from opulse.gen_v2.notation import (
    parse_declaration,
    parse_term,
    print_declaration,
    print_node,
    tokens,
)


def test_declared_infix_round_trip_and_tokens():
    from dataclasses import replace

    from opulse.gen_v2.base import GenState
    from opulse.gen_v2.library import GenLibrary
    from opulse.gen_v2.worlds import toy

    world = toy.gen_world()
    add = replace(world.decl.operations[0], extra={"symbol": "+"})
    mul = replace(next(spec for spec in world.decl.operations if spec.name == "mul"), extra={"symbol": "*"})
    world.decl = replace(world.decl, operations=tuple(add if spec.name == "add" else mul if spec.name == "mul" else spec
                                                      for spec in world.decl.operations))
    state = GenState(world, GenLibrary(world.decl, world.atoms, world.dialect), dict(world.sorts))
    node = n.Call("add", (n.Call("mul", (n.Var("a"), n.Lit(2))),
                          n.Call("add", (n.Var("b"), n.Lit(3)))))
    text = print_node(node, state)
    assert text == "(a * 2) + (b + 3)"
    assert parse_term(text, state) == node
    assert print_node(n.Call("lt", (n.Var("a"), n.Var("b"))), state) == "lt(a, b)"
    pieces = tokens(node, state)
    assert "".join(piece["text"] for piece in pieces) == text
    assert any(piece["text"] == "+" and piece["kind"] == "operation" and piece["name"] == "add"
               and piece["given"] for piece in pieces)
    assert text.isascii()


def test_declaration_head_parsing_and_errors():
    examples = [
        ("op f6(a: int, b: int) -> int = add(a, b)  L3", "operation", "f6", 3, [("a", "int"), ("b", "int")], "int"),
        ("comb @k3[f: int -> int](x: int) -> int = f(x)  L5", "combinator", "k3", 5, [("x", "int")], "int"),
        ("obs ?q4{s: state} = front_wall()  L6", "observation", "q4", 6, [("s", "state")], None),
        ("obj A7 = <pair(x: int, y: int)>  L2", "object", "A7", 2, [("x", "int"), ("y", "int")], "A7"),
        ("obj B3 = refine int where is_pos(x)  L4", "object", "B3", 4, [], "B3"),
    ]
    for text, kind, name, layer, params, output in examples:
        parsed = parse_declaration(text)
        assert (parsed["kind"], parsed["name"], parsed["layer"], parsed["params"], parsed["output"]) == (
            kind, name, layer, params, output)
    import pytest

    with pytest.raises(ValueError):
        parse_declaration("op @k3() -> int = 1  L1")


def test_random_typed_terms_round_trip():
    rng = random.Random(314)

    def term(sort, depth):
        if depth == 0:
            if sort == "bool":
                return rng.choice([n.Lit(True), n.Lit(False), n.Var("flag")])
            return rng.choice([n.Var("x"), n.Var("y"), n.Lit(rng.randint(-8, 8))])
        if sort == "bool":
            return n.Call(rng.choice(["lt", "eq"]), (term("int", depth - 1), term("int", depth - 1)))
        return n.Call(rng.choice(["add", "mul", "f6"]), (term("int", depth - 1), term("int", depth - 1)))

    for _ in range(50):
        node = term(rng.choice(["int", "bool"]), rng.randint(0, 3))
        text = print_node(node)
        assert text.isascii()
        assert parse_term(text) == node
        assert " < " not in text and " > " not in text


def test_structured_terms_and_sigils():
    from opulse.atoms.kernel import FnRef
    from opulse.gen_v2.base import Entry

    class State:
        def __init__(self):
            self.entries = {"k3": Entry("k3", "combinator", 1, None, "test", ()),
                            "q4": Entry("q4", "observation", 1, None, "test", ())}

    terms = [n.Call("k3", (n.Lit(FnRef("f6")), n.Var("x"))),
             n.Call("q4", (n.Var("s"),)),
             n.Lit(Card("Pair", "pair", (1, 2))), n.Lit("a\n\tb"),
             n.Lit(Card("List", "items", (1, 2))), n.Lit(Card("Set", "items")),
             n.Lit(Card("A7", "items", (1, 2))),
             n.Let("a", n.Lit(3), n.Call("lt", (n.Var("a"), n.Lit(4)))),
             n.Case(((n.Test(n.Call("lt", (n.Var("x"), n.Lit(0)))), n.Lit(1)),), n.Lit(2)),
             n.Case(((n.Always(), n.Lit(1)),), n.Lit(2)),
             n.Rec("loop", ("k",), n.Call("loop", (n.Call("dec", (n.Var("k"),)),)),
                   (n.Lit(2),), n.Var("k"))]
    for node in terms:
        assert parse_term(print_node(node, State())) == node
        assert parse_term(print_node(node)) == node
    assert print_node(parse_term("List<1, 2>")) == "List<1, 2>"
    assert print_node(parse_term("A7<1, 2>")) == "A7<1, 2>"


def test_comparisons_never_use_angle_brackets():
    for op in ("lt", "le", "eq", "ne"):
        text = print_node(n.Call(op, (n.Var("a"), n.Var("b"))))
        assert text == f"{op}(a, b)"
        assert "<" not in text and ">" not in text


def test_declarations_of_all_four_kinds():
    from opulse.atoms.spec import (
        CombinatorSpec,
        Definition,
        ObjectSpec,
        ObservationSpec,
    )
    from opulse.gen_v2.base import Entry, Signature

    value = n.Var("x")
    definitions = {
        "A7": Definition("A7", "object", "invented", 2, (),
                         ObjectSpec("A7", "compose", tags={"pair": [["x", "int"], ["y", "int"]]}), value),
        "B3": Definition("B3", "object", "invented", 4, (),
                         ObjectSpec("B3", "refine", base="int", valid=n.Call("is_pos", (value,)),
                                    canon=n.Call("absv", (value,))), value),
        "k3": Definition("k3", "combinator", "invented", 5, (),
                         CombinatorSpec("k3", ("f", "x"), ("f",), n.Call("f", (value,))), n.Call("f", (value,))),
        "q4": Definition("q4", "observation", "invented", 6, (),
                         ObservationSpec("q4", ("front_wall",), n.Call("front_wall")), n.Call("front_wall")),
    }

    class Library:
        def get(self, name):
            return definitions[name]

    class State:
        def __init__(self):
            self.library = Library()
            self.entries = {}

    state = State()
    entries = [Entry("A7", "object", 2, None, "test", ()),
               Entry("B3", "object", 4, None, "test", ()),
               Entry("k3", "combinator", 5, Signature(("int",), "int", (Signature(("int",), "int"),)), "test", ()),
               Entry("q4", "observation", 6, Signature(("state",), "bool"), "test", ())]
    for entry in entries:
        state.entries[entry.name] = entry
    assert print_declaration(entries[0], state) == "obj A7 = <pair(x: int, y: int)>  L2"
    assert print_declaration(entries[1], state) == "obj B3 = refine int where is_pos(x); canon absv(x)  L4"
    assert print_declaration(entries[2], state) == "comb @k3[f: int -> int](x: int) -> int = f(x)  L5"
    assert print_declaration(entries[3], state) == "obs ?q4{s: state} = front_wall()  L6"
    assert all(print_declaration(entry, state).isascii() for entry in entries)


def test_given_declarations_end_with_given():
    from opulse.gen_v2.base import Entry, GenState
    from opulse.gen_v2.library import GenLibrary
    from opulse.gen_v2.worlds import toy

    world = toy.gen_world()
    state = GenState(world, GenLibrary(world.decl, world.atoms, world.dialect), dict(world.sorts))
    assert print_declaration(Entry("int", "object", 0, None, "given", ()), state).endswith("  given")
    assert print_declaration(Entry("add", "operation", 0, None, "given", ()), state).endswith("  given")


def test_finding_8_law_bridge_declarations_and_application_round_trip():
    from opulse.gen_v2.base import GenState
    from opulse.gen_v2.bridges import BridgeRecord
    from opulse.gen_v2.laws import LawRecord
    from opulse.gen_v2.library import GenLibrary
    from opulse.gen_v2.worlds import toy

    world = toy.gen_world()
    state = GenState(world, GenLibrary(world.decl, world.atoms, world.dialect), dict(world.sorts))
    statement = n.Call("eq", (n.Call("add", (n.Var("a"), n.Var("b"))),
                               n.Call("add", (n.Var("b"), n.Var("a")))))
    law = LawRecord("comm", statement, (("a", "int"), ("b", "int")), ("add", "eq"), 1)
    law_text = law.text(state)
    assert print_declaration(law, state) == law_text
    parsed_law = parse_declaration(law_text)
    assert parsed_law["statement"] == law.statement
    assert (parsed_law["kind"], parsed_law["name"], parsed_law["params"], parsed_law["layer"]) == (
        "law", "comm", [("a", "int"), ("b", "int")], 1)
    bridge = BridgeRecord("b1", ("toy", "int"), ("toy", "int"), n.Var("x"),
                          (0, 1), (("inc", "inc"),), {}, 1, ())
    assert parse_declaration(bridge.notation())["target"] == "int"
    assert print_declaration(bridge, state) == bridge.notation()
    assert parse_declaration(bridge.notation())["name"] == bridge.name
    assert parse_term(bridge.application()) == n.Call("~b1", (n.Var("x"),))
    assert print_node(parse_term(bridge.application())) == bridge.application()
    assert any(part["kind"] == "law" and part["name"] == "comm" for part in tokens(law_text, state))
    assert any(part["kind"] == "bridge" and part["name"] == "b1" for part in tokens(bridge.notation(), state))


def test_finding_9_boolean_cards_and_python_bools_round_trip_distinctly():
    for value in (TRUE, FALSE, True, False, Card("bool", "true", (True,))):
        printed = print_node(n.Lit(value))
        assert parse_term(printed) == n.Lit(value)
    assert print_node(n.Lit(TRUE)) != print_node(n.Lit(True))


def test_nested_structures_and_host_literals_round_trip():
    from opulse.worlds.perm import Permutation

    nested = n.Rec("scan", ("current",), n.Case(
        ((n.Test(n.Call("p", (n.Var("current"),))),
          n.Let("value", n.Rec("inner", ("x",), n.Var("x"), (n.Lit(1),), "fuel", True),
                n.Var("value"))),),
        n.Case(((n.Test(n.Lit(False)), n.Case(())),),
               n.Call("scan", (n.Var("current"),)))),
        (n.Lit(2),), n.Call("size", (n.Var("current"),)))
    terms = [nested, n.Call("wrap", (nested,)), n.Let("x", nested, n.Var("x")),
             n.Case((), n.Lit(2)), n.Lit(Bottom("bad")), n.Lit(FnRef("f6")),
             n.Case(((n.Test(n.Call("not", (n.Var("flag"),))), n.Lit(1)),), n.Lit(0)),
             n.Call("apply", (n.Lit(FnRef("f6")), n.Var("x"))),
             n.Call("M11.fold", (n.Lit(FnRef("f6")), n.Lit(FnRef("g9")), n.Var("x"))),
             n.Call("q4", (n.Lit(FnRef("f6")), n.Lit(3))),
             n.Blocks((("result", n.Lit(0)),), "entry", (("entry", n.Block((), n.Halt(n.Var("result")))),)),
             n.Lit((Card("pair", "ordered", (1, Card("die", "face", (2,)))),)),
             n.Lit(Permutation((2, 0, 1)))]
    for node in terms:
        text = print_node(node)
        assert text.isascii()
        assert n.from_json(n.to_json(parse_term(text))) == n.from_json(n.to_json(node)), text


def test_generated_bodies_round_trip_across_adapters():
    from opulse.gen_v2.run import generate
    from opulse.gen_v2.worlds import (
        action,
        automata,
        circuits,
        dice,
        grammar,
        hidden,
        integer,
        lists,
        rhythm,
        toy,
        toy_truth,
        versions,
    )

    for adapter in (toy, toy_truth, lists, circuits, action, versions, integer, dice,
                    rhythm, hidden, grammar, automata):
        world = adapter.gen_world()
        state = generate(world, 12, 7, per_kind_min=0, layer_target=0, time_limit=2)
        assert state.entries, world.name
        for entry in state.entries.values():
            body = state.library.get(entry.name).body
            if not isinstance(body, n.NODE_TYPES):
                continue
            text = print_node(body, state)
            assert text.isascii(), (world.name, entry.name)
            assert "".join(part["text"] for part in tokens(body, state)) == text
            assert n.from_json(n.to_json(parse_term(text, state))) == n.from_json(n.to_json(body)), (
                world.name, entry.name, entry.move, text)
