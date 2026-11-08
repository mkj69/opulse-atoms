"""One pipeline for every kind: observations and combinators through the library (spec 9, 11)."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.combinators import standard_combinators
from opulse.atoms.library import Library, PipelineError, VerifyRequest
from opulse.atoms.observations import robot_probe_atoms
from opulse.atoms.spec import Contract, Definition, Edge, ObservationSpec, OperationSpec
from opulse.atoms.world import WorldDecl, legacy_world_decl
from opulse.worlds import action

WORLDS = Path(__file__).resolve().parents[1] / "docs/assets/data/worlds"


def robot_library():
    world = replace(legacy_world_decl(json.loads((WORLDS / "action.json").read_text(encoding="utf-8"))),
                    open_kinds=("operation", "observation"))
    return Library(world, robot_probe_atoms())


def test_card_counter_observation_runs_through_the_pipeline():
    from opulse.atoms.values import Card, Ok

    operations = (OperationSpec("parity", "decide", (Edge("counter"),), Edge("int"), "counter mod 2"),
                  OperationSpec("is_zero", "decide", (Edge("counter"),), Edge("bool"), "counter is zero"),
                  OperationSpec("mutate", "act", (Edge("counter"),), Edge("counter"), "change counter"))
    world = WorldDecl("cards", 1, "atoms-v2", {}, {}, (), operations,
                      {"nodes": list(n.NODE_NAMES), "recursion": "measure"},
                      {"truth": "counter", "probes": [{"name": "parity"}, {"name": "is_zero"}],
                       "capabilities": {"learner": {"probes": "all"}}}, {})
    lib = Library(world, [kernel.Atom("parity", 1, lambda state: state.fields[0] % 2,
                                      kind="observation"),
                          kernel.Atom("is_zero", 1, lambda state: state.fields[0] == 0,
                                      kind="observation"),
                          kernel.Atom("mutate", 1, lambda state: state, kind="operation")])
    body = n.Var("parity")
    spec = ObservationSpec("visible", ("parity", "is_zero"), body)
    lib.write(Definition("visible", "observation", "invented", 1, (), spec, body))
    lib.check("visible")
    states = [Card("counter", "value", (value,)) for value in range(5)]
    lib.make_callable("visible", [(state,) for state in states])
    request = VerifyRequest("bounded", [(state,) for state in states],
                            {"domain": "counter up to bound 4", "size": len(states)},
                            reference=lambda state: state.fields[0] % 2, extra={"states": states})
    assert {"facts_unchanged", "non_interference"} <= set(lib.verify("visible", request).evidence.checks)
    assert lib.promote("visible", Contract("parity of counter")).status == "promoted"
    assert lib.derived_world().open_kinds == world.open_kinds
    assert lib.by_hash(lib.content_hash("visible")) == lib.get("visible")
    from opulse.atoms.observations import observe

    assert observe(lib.get("visible"), lib, states) == [Ok(value % 2) for value in range(5)]
    bad = n.Call("mutate", (n.Var("parity"),))
    lib.write(Definition("bad", "observation", "invented", 1, ("mutate",),
                         ObservationSpec("bad", ("parity",), bad), bad))
    with pytest.raises(PipelineError, match="may read or change truth"):
        lib.check("bad")


def test_observation_goes_through_the_whole_pipeline():
    lib = robot_library()
    body = n.Case(((n.Test(n.Var("front_wall")), n.Lit(False)),
                   (n.Test(n.Var("front_water")), n.Lit(False))), n.Lit(True))
    spec = ObservationSpec("front_free", ("front_wall", "front_water"), body)
    lib.write(Definition("front_free", "observation", "invented", 1, (), spec, body))
    lib.check("front_free")
    states = action._examples_states()[:6]
    lib.make_callable("front_free", [(state,) for state in states])
    request = VerifyRequest("bounded", [(state,) for state in states],
                            {"domain": "6 example robot states (bound: the published examples)", "size": 6},
                            reference=lambda state: not action.apply_atom("front_wall", state)
                            and not action.apply_atom("front_water", state),
                            extra={"states": states})
    verified = lib.verify("front_free", request)
    assert {"dependency", "facts_unchanged", "non_interference", "reference"} <= set(verified.evidence.checks)
    promoted = lib.promote("front_free", Contract("true iff the front cell is neither wall nor water"))
    assert promoted.status == "promoted"
    assert lib.derived_world().scopes()["front_free"]["size"] == 6


def test_observation_that_acts_is_rejected_at_check():
    lib = robot_library()
    body = n.Call("forward", (n.Var("front_wall"),))
    spec = ObservationSpec("sneaky", ("front_wall",), body)
    lib.write(Definition("sneaky", "observation", "invented", 1, ("forward",), spec, body))
    with pytest.raises(PipelineError, match="truth"):
        lib.check("sneaky")


def integer_library():
    ops = (("succ", lambda value: value + 1), ("double", lambda value: 2 * value), ("neg", lambda value: -value))
    specs = tuple(OperationSpec(name, "transform", (Edge("int"),), Edge("int"), name) for name, _ in ops)
    world = WorldDecl("ints", 1, "atoms-v2", {}, {}, (), specs,
                      {"nodes": list(n.NODE_NAMES), "recursion": "fuel"}, {}, {})
    return Library(world, [kernel.Atom(name, 1, fn) for name, fn in ops])


def test_combinator_bounded_evidence_promotes_and_exhaustive_is_refused():
    lib = integer_library()
    twice = next(spec for spec in standard_combinators() if spec.name == "twice")
    lib.write(Definition("twice", "combinator", "invented", 1, (), twice, twice.body))
    lib.check("twice")
    lib.make_callable("twice", [(kernel.FnRef("succ"), 2)])
    family = ["succ", "double", "neg"]
    domain = [(value,) for value in range(-3, 4)]
    scope = {"domain": "x in -3..3 (bound 3), f over the listed family", "size": len(domain), "op_family": family}
    with pytest.raises(PipelineError, match="exhaustive"):
        lib.verify("twice", VerifyRequest("exhaustive", domain, scope, extra={"op_family": family}))
    reference = {"succ": lambda x: x + 2, "double": lambda x: 4 * x, "neg": lambda x: x}
    request = VerifyRequest("bounded", domain, scope,
                            reference=lambda ops, inputs: reference[ops["f"]](inputs[0]),
                            extra={"op_family": family})
    assert {"unfold_equivalence", "reference"} <= set(lib.verify("twice", request).evidence.checks)
    assert lib.promote("twice", Contract("f(f(x)) for any f in the family")).status == "promoted"


def test_invented_fraction_object_through_the_pipeline():
    from math import gcd

    from opulse.atoms.spec import ObjectSpec
    from opulse.atoms.values import Bottom, Card, Ok

    pair = ObjectSpec("pair", "compose", tags={"pair": (("num", "int"), ("den", "int"))})

    def canonical(num, den):
        divisor = gcd(num, den)
        return Card("pair", "pair", (num // divisor * (1 if den > 0 else -1), abs(den) // divisor))

    ops = (OperationSpec("canonical", "combine", (Edge("int"), Edge("int")), Edge("pair"), "reduce by gcd, den > 0"),
           OperationSpec("nonzero", "decide", (Edge("int"),), Edge("bool"), "x != 0"))
    world = WorldDecl("rationals", 1, "atoms-v2", {}, {}, (pair,), ops,
                      {"nodes": list(n.NODE_NAMES), "recursion": "measure"}, {}, {})
    lib = Library(world, [kernel.Atom("canonical", 2, canonical), kernel.Atom("nonzero", 1, lambda x: x != 0)])
    x_num, x_den = n.Call("pair.num", (n.Var("x"),)), n.Call("pair.den", (n.Var("x"),))
    fraction = ObjectSpec("fraction", "refine", base="pair", valid=n.Call("nonzero", (x_den,)),
                          canon=n.Call("canonical", (x_num, x_den)), sealed=True,
                          interface=("fraction.make", "fraction.num", "fraction.den"), extra={"fields": ("num", "den")})
    lib.write(Definition("fraction", "object", "invented", 1,
                         ("canonical", "nonzero", "pair.den", "pair.num"), fraction, None))
    lib.check("fraction")
    lib.make_callable("fraction", [(Card("pair", "pair", (2, 4)),)])
    made = lib.run("fraction.make", (Card("pair", "pair", (2, 4)),))
    assert made.outcome == Ok(Card("fraction", "val", (Card("pair", "pair", (1, 2)),)))
    assert lib.run("fraction.make", (Card("pair", "pair", (1, 0)),)).outcome == Bottom("invalid")
    domain = [(Card("pair", "pair", (a, b)),) for a in range(-4, 5) for b in range(-4, 5)]
    request = VerifyRequest("exhaustive", domain, {"domain": "num, den in -4..4", "size": len(domain)},
                            extra={"interface_ops": {"fraction.num": [0], "fraction.den": [0]}})
    checks = set(lib.verify("fraction", request).evidence.checks)
    assert {"canon_total", "canon_idempotent", "canon_keeps_valid", "respects_canon"} <= checks
    assert lib.promote("fraction", Contract("canonical fractions; num and den read the reduced form")).status == "promoted"


def test_object_verifier_dispatch_checks_abstraction_and_finite_base():
    from opulse.atoms.spec import ObjectSpec

    base = ObjectSpec("int", "given")
    operations = (OperationSpec("is_positive", "decide", (Edge("int"),), Edge("bool"), "x > 0"),
                  OperationSpec("identity", "transform", (Edge("int"),), Edge("int"), "x"))
    world = WorldDecl("positive", 1, "atoms-v2", {}, {}, (base,), operations,
                      {"nodes": list(n.NODE_NAMES), "recursion": "measure"}, {}, {})
    lib = Library(world, [kernel.Atom("is_positive", 1, lambda value: value > 0),
                          kernel.Atom("identity", 1, lambda value: value)])
    invalid = ObjectSpec("loop", "compose", tags={"step": [("tail", "other")]},
                         group=("loop", "other"))
    other = ObjectSpec("other", "compose", tags={"back": [("tail", "loop")]},
                       group=("loop", "other"))
    lib.write(Definition("other", "object", "invented", 1, (), other, None))
    lib.write(Definition("loop", "object", "invented", 1, (), invalid, None))
    with pytest.raises(PipelineError, match="recursive group needs a base tag"):
        lib.check("loop")

    spec = ObjectSpec("positive", "refine", base="int", valid=n.Call("is_positive", (n.Var("x"),)),
                      canon=n.Var("x"))
    lib.write(Definition("positive", "object", "invented", 1, ("is_positive",), spec, None))
    lib.check("positive")
    lib.make_callable("positive", [(1,)])
    domain = [(1,), (2,), (3,)]
    request = VerifyRequest("exhaustive", domain, {"domain": "positive integers 1..3", "size": 3},
                            extra={"abs": "positive.base", "interface_pairs": [
                                ("positive.base", "identity")],
                                   "interface_ops": {"positive.base": [0]}})
    assert "abs_commutes" in lib.verify("positive", request).evidence.checks


def test_observation_subject_form_and_its_rules():
    lib = robot_library()
    s = n.Var("s")
    wall, water = n.Call("front_wall", (s,)), n.Call("front_water", (s,))
    body = n.Case(((n.Test(wall), n.Lit(False)), (n.Test(water), n.Lit(False))), n.Lit(True))
    spec = ObservationSpec("front_free", ("front_wall", "front_water"), body, extra={"subject": "s"})
    assert ObservationSpec.from_dict(spec.to_dict()) == spec and spec.subject == "s"
    lib.write(Definition("front_free", "observation", "invented", 1, ("front_wall", "front_water"), spec, body))
    lib.check("front_free")
    states = action._examples_states()[:6]
    lib.make_callable("front_free", [(state,) for state in states])
    from opulse.atoms.observations import observe

    expected = [not action.apply_atom("front_wall", st) and not action.apply_atom("front_water", st) for st in states]
    assert [outcome.value for outcome in observe(lib.get("front_free"), lib, states)] == expected
    # A derived observation calls another observation with the subject.
    outer_body = n.Call("front_free", (s,))
    outer = ObservationSpec("free_again", ("front_wall", "front_water"), outer_body)
    lib.write(Definition("free_again", "observation", "invented", 2, ("front_free",), outer, outer_body))
    lib.check("free_again")
    assert [outcome.value for outcome in observe(lib.get("free_again"), lib, states)] == expected
    # The subject must not reach an operation.
    leak_body = n.Call("forward", (s,))
    leak = ObservationSpec("leak", (), leak_body)
    lib.write(Definition("leak", "observation", "invented", 1, ("forward",), leak, leak_body))
    with pytest.raises(PipelineError, match="subject"):
        lib.check("leak")


def test_mapping_tags_with_named_fields_and_hashes_over_generated_operations():
    from opulse.atoms.spec import ObjectSpec
    from opulse.atoms.values import Card, Ok

    move = ObjectSpec("Move", "compose", tags={"move": {"start": "int", "stop": "int"}})
    world = WorldDecl("moves", 1, "atoms-v2", {}, {}, (move,), (),
                      {"nodes": list(n.NODE_NAMES), "recursion": "fuel"}, {}, {})
    lib = Library(world, [])
    assert lib.run("Move.stop", (Card("Move", "move", (1, 5)),)).outcome == Ok(5)
    body = n.Call("Move.stop", (n.Var("m"),))
    spec = OperationSpec("stop_of", "transform", (Edge("Move"),), Edge("int"), "the stop",
                         extra={"input_names": ["m"]})
    lib.write(Definition("stop_of", "operation", "invented", 1, ("Move.stop",), spec, body))
    lib.check("stop_of")
    lib.make_callable("stop_of", [(Card("Move", "move", (1, 5)),)])
    assert lib.content_hash("stop_of")
    request = VerifyRequest("exhaustive", [(Card("Move", "move", (a, b)),) for a in range(2) for b in range(2)],
                            {"domain": "start, stop in 0..1", "size": 4},
                            reference=lambda m: m.fields[1])
    assert lib.verify("stop_of", request).status == "verified"


def test_observations_are_called_with_their_subject_and_wildcard_sorts():
    lib = robot_library()
    s = n.Var("s")
    body = n.Call("front_wall", (s,))
    spec = ObservationSpec("wall", ("front_wall",), body)
    lib.write(Definition("wall", "observation", "invented", 1, ("front_wall",), spec, body))
    lib.check("wall")
    state = action._examples_states()[0]
    lib.make_callable("wall", [(state,)])
    assert lib.run("wall", (state,)).outcome.value == action.apply_atom("front_wall", state)
    any_spec = OperationSpec("ident", "transform", (Edge("any"),), Edge("any"), "identity",
                             extra={"input_names": ["x"]})
    lib.write(Definition("ident", "operation", "invented", 1, (), any_spec, n.Lit(3)))
    assert lib.check("ident").status == "checked"


def test_reference_free_observation_promotes_on_its_unfolding():
    lib = robot_library()
    s = n.Var("s")
    body = n.Call("front_wall", (s,))
    spec = ObservationSpec("wall_seen", ("front_wall",), body)
    lib.write(Definition("wall_seen", "observation", "invented", 1, ("front_wall",), spec, body))
    lib.check("wall_seen")
    states = action._examples_states()[:4]
    lib.make_callable("wall_seen", [(state,) for state in states])
    request = VerifyRequest("bounded", [(state,) for state in states],
                            {"domain": "4 example robot states (bound: published examples)", "size": 4},
                            extra={"states": states})
    evidence = lib.verify("wall_seen", request).evidence
    assert "unfold_equivalence" in evidence.checks and "reference" not in evidence.checks
    assert evidence.scope["reference"] == "none"
    assert lib.promote("wall_seen", Contract("the front-wall probe")).status == "promoted"
