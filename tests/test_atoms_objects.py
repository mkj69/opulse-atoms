"""Object declaration, refinement, and sealing (spec section 4)."""

from math import gcd

import pytest

from opulse.atoms import nodes as n
from opulse.atoms.kernel import Atom, Defn
from opulse.atoms.library import Library, VerifyRequest
from opulse.atoms.objects import (
    check_object,
    object_atoms,
    random_interface_programs,
    verify_object,
)
from opulse.atoms.spec import Definition, Edge, ObjectSpec, OperationSpec
from opulse.atoms.values import Bottom, Card, Ok
from opulse.atoms.world import WorldDecl


class ObjectLibrary(Library):
    """Real library with an ad hoc kernel-Defn scope for local program fixtures."""
    def __init__(self, objects=(), operations=()):
        world = WorldDecl("objects_test", 1, "atoms-v2", {}, {}, tuple(objects), tuple(operations),
                          {"nodes": list(n.NODE_NAMES), "recursion": "measure"}, {}, {})
        super().__init__(world, ())
        self.defns = []

    def add(self, *entries):
        for entry in entries:
            if isinstance(entry, Atom):
                self.atoms += (entry,)
            else:
                self.defns.append(entry)

    def scope(self):
        return super().scope().extend(self.defns)


def request(domain, method="exhaustive", seed=None, extra=None):
    return VerifyRequest(method, domain, {"domain": "test scope", "size": len(domain)},
                         seed=seed, extra=extra or {})


def definition(spec, name=None, body=None):
    expressions = (body,) if body is not None else (spec.valid, spec.canon)
    return Definition(name or spec.name, "object", "invented", 1,
                      tuple(sorted(set().union(*(n.references(node) for node in expressions
                                                 if node is not None)))), spec, body)


def fraction_library(canon=None):
    record = ObjectSpec("pair", "compose", tags={"pair": (("num", "int"), ("den", "int"))})
    default_canon = n.Call("canonical", (
        n.Call("pair.num", (n.Var("x"),)), n.Call("pair.den", (n.Var("x"),))))
    fraction = ObjectSpec("fraction", "refine", base="pair",
                          valid=n.Call("nonzero", (n.Call("pair.den", (n.Var("x"),)),)),
                          canon=canon or default_canon, sealed=True,
                          interface=("fraction.make", "fraction.num", "fraction.den", "eq", "add"),
                          extra={"fields": ("num", "den")})
    lib = ObjectLibrary((record, fraction), (
        OperationSpec("eq", "decide", (Edge("fraction"), Edge("fraction")), Edge("bool"), "equal"),
        OperationSpec("add", "combine", (Edge("fraction"), Edge("fraction")), Edge("fraction"), "add"),
    ))
    lib.add(*object_atoms(record, lib))

    def canonical(num, den):
        divisor = gcd(num, den)
        return Card("pair", "pair", (num // divisor * (1 if den > 0 else -1),
                                      abs(den) // divisor))

    lib.add(Atom("nonzero", 1, lambda den: den != 0),
            Atom("canonical", 2, canonical),
            Atom("sign", 1, lambda pair: pair),
            *object_atoms(fraction, lib))
    lib.add(Defn("eq", ("a", "b"), n.Call("pair_equal", (
        n.Call("fraction.base", (n.Call("fraction.make", (
            n.Call("fraction.base", (n.Var("a"),)),)),)),
        n.Call("fraction.base", (n.Call("fraction.make", (
            n.Call("fraction.base", (n.Var("b"),)),)),))))),
            Atom("pair_equal", 2, lambda left, right: left == right))
    numerator = n.Call("sum_num", (n.Call("fraction.base", (n.Var("a"),)),
                                    n.Call("fraction.base", (n.Var("b"),))))
    denominator = n.Call("mul_den", (n.Call("fraction.base", (n.Var("a"),)),
                                       n.Call("fraction.base", (n.Var("b"),))))
    lib.add(Defn("add", ("a", "b"), n.Call("fraction.make", (n.Call("pair.pair", (
        numerator, denominator)),))))
    lib.add(Atom("sum_num", 2, lambda left, right: left.fields[0] * right.fields[1] +
                right.fields[0] * left.fields[1]),
            Atom("mul_den", 2, lambda left, right: left.fields[1] * right.fields[1]))
    return record, fraction, lib


def test_fraction_make_sealing_and_cost():
    _, fraction, lib = fraction_library()
    assert not check_object(definition(fraction), lib)
    result = lib.run("fraction.make", (Card("pair", "pair", (2, 4)),))
    assert result.outcome == Ok(Card("fraction", "val", (Card("pair", "pair", (1, 2)),)))
    assert result.steps == 6
    assert lib.run("fraction.make", (Card("pair", "pair", (2, 0)),)).outcome == Bottom("invalid")
    assert lib.run("fraction.den", (result.outcome.value,)).outcome == Ok(2)
    outsider = definition(fraction, "leak", n.Call("fraction.base", (n.Var("x"),)))
    assert any("private sealed" in problem for problem in check_object(outsider, lib))
    lib.write(outsider)
    assert check_object(definition(fraction), lib)
    _, fraction, lib = fraction_library()
    outsider = definition(fraction, "leak", n.Call("pair.den", (
        n.Call("fraction.base", (n.Var("x"),)),)))
    assert check_object(outsider, lib)
    interface = definition(fraction, "fraction.den", n.Call("fraction.base", (n.Var("x"),)))
    assert not check_object(interface, lib)


def test_fraction_obligations_and_broken_interface():
    _, fraction, lib = fraction_library()
    domain = [(Card("pair", "pair", (num, den)),)
              for num in range(-6, 7) for den in range(-6, 7)]
    verification = request(domain, extra={"interface_ops": {
        "fraction.num": [0], "fraction.den": [0], "eq": [0, 1], "add": [0, 1]}})
    result = verify_object(definition(fraction), lib, verification)
    assert result.ok, result.problems
    assert result.checks == ("canon_total", "canon_idempotent", "canon_keeps_valid", "respects_canon")
    lib.add(Defn("raw_num", ("item",), n.Call("pair.num", (
        n.Call("fraction.base", (n.Var("item"),)),))))
    verification.extra["interface_ops"] = {"raw_num": [0]}
    assert verify_object(definition(fraction), lib, verification).ok
    _, fraction, lib = fraction_library(n.Call("broken_canonical", (n.Var("x"),)))
    lib.add(Atom("broken_canonical", 1, lambda pair: Card("pair", "pair",
                (-pair.fields[0], -pair.fields[1]))))
    verification.extra["interface_ops"] = {"fraction.num": [0]}
    broken = verify_object(definition(fraction), lib, verification)
    assert not broken.ok and any("canon_idempotent" in item for item in broken.problems)


def test_list_nat_constant_and_groups():
    lib = ObjectLibrary()
    list_spec = ObjectSpec("list[int]", "compose", tags={"nil": (),
        "cons": (("head", "int"), ("tail", "list[int]"))})
    lib.add(*object_atoms(list_spec, lib))
    empty = lib.run("list[int].nil", ()).outcome.value
    assert lib.run("list[int].head", (empty,)).outcome == Bottom("wrong_tag")
    cons = lib.run("list[int].cons", (3, empty)).outcome.value
    assert lib.run("list[int].head", (cons,)).outcome == Ok(3)
    lib.add(Atom("list_size", 1, lambda value: 0 if value.tag == "nil" else
                1 + lib.scope().resolve("list_size").fn(value.fields[1])),
            Atom("increment", 1, lambda value: value + 1))
    length = n.Rec("length", ("xs",), n.Case(((n.Test(n.Call("list[int].is_nil",
        (n.Var("xs"),))), n.Lit(0)),), n.Call("increment", (n.Call("length", (
        n.Call("list[int].tail", (n.Var("xs"),)),)),))), (n.Var("input"),),
        n.Call("list_size", (n.Var("xs"),)))
    lib.add(Defn("length", ("input",), length))
    assert lib.run("length", (cons,)).outcome == Ok(1)
    items = ObjectSpec("items", "compose", tags={"items": {"items": "int"}})
    lib.add(*object_atoms(items, lib))
    assert lib.run("items.items", ((1, 2),)).outcome == Ok(Card("items", "items", (1, 2)))
    assert lib.run("items.items", (3,)).outcome == Bottom("invalid")

    nat = ObjectSpec("nat", "compose", tags={"zero": (), "succ": (("pred", "nat"),)})
    lib.add(*object_atoms(nat, lib))
    body = n.Call("nat.zero")
    for _ in range(3):
        body = n.Call("nat.succ", (body,))
    constant = ObjectSpec("three", "constant", body=body)
    lib.add(*object_atoms(constant, lib))
    assert lib.run("three", ()).steps == 3
    assert lib.run("three", ()).outcome.value.fields[0].tag == "succ"
    with pytest.raises(ValueError, match="base tag"):
        ObjectSpec("bad", "compose", tags={"next": (("tail", "bad"),)}, group=("bad",))
    left = ObjectSpec("left", "compose", tags={"nil": (), "cons": (("right", "right"),)},
                      group=("left", "right"))
    lib = ObjectLibrary((left,))
    with pytest.raises(ValueError, match="missing sorts"):
        object_atoms(left, lib)
    right = ObjectSpec("right", "compose", tags={
        "cons": (("left", "left"),)}, group=("left", "right"))
    lib = ObjectLibrary((left, right))
    assert not check_object(definition(left), lib)
    assert not check_object(definition(right), lib)
    lib.add(*object_atoms(left, lib), *object_atoms(right, lib))
    assert lib.run("right.cons", (lib.run("left.nil", ()).outcome.value,)).outcome.value.tag == "cons"
    missing_left = ObjectSpec("missing_left", "compose", tags={
        "link": (("right", "missing_right"),)}, group=("missing_left", "missing_right"))
    missing_right = ObjectSpec("missing_right", "compose", tags={
        "link": (("left", "missing_left"),)}, group=("missing_left", "missing_right"))
    missing_lib = ObjectLibrary((missing_left, missing_right))
    assert any("base tag" in issue for issue in check_object(definition(missing_left), missing_lib))
    with pytest.raises(ValueError, match="base tag"):
        object_atoms(missing_left, missing_lib)
    negative = ObjectSpec("negative", "compose", tags={"nil": (),
        "fn": (("callback", "negative -> int"),)}, group=("negative",))
    assert any("negative function" in issue for issue in check_object(definition(negative), ObjectLibrary((negative,))))


def test_refinement_rejects_nonterminating_rules_and_seeded_programs():
    _, _, lib = fraction_library()
    invalid = ObjectSpec("broken", "refine", base="pair", valid=n.Rec("loop", ("a",),
        n.Var("a"), (n.Var("x"),), measure="fuel"),
        canon=n.Call("canonical", (n.Var("x"),)))
    assert any("measure" in issue for issue in check_object(definition(invalid), lib))
    programs = random_interface_programs({"inc": 1, "add": 2}, 12, 42, 3)
    assert programs == random_interface_programs({"add": 2, "inc": 1}, 12, 42, 3)
    assert programs != random_interface_programs({"inc": 1, "add": 2}, 12, 43, 3)


def test_refinement_binds_only_x():
    base = ObjectSpec("base_pair", "compose", tags={"pair": (("value", "int"),)})
    spec = ObjectSpec("old_binding", "refine", base="base_pair", valid=n.Var("base"))
    lib = ObjectLibrary((base, spec))
    lib.add(*object_atoms(base, lib), *object_atoms(spec, lib))
    with pytest.raises(KeyError, match="base"):
        lib.run("old_binding.make", (Card("base_pair", "pair", (1,)),))


def test_free_canon_and_totality_failure():
    _, fraction, lib = fraction_library()
    free = ObjectSpec("free_fraction", "refine", base="pair", valid=fraction.valid,
                      canon=fraction.canon, canon_cost="free")
    lib.add(*object_atoms(free, lib))
    value = Card("pair", "pair", (2, 4))
    free_canon = lib.scope().resolve("free_fraction._canon_free")
    assert isinstance(free_canon, Atom) and free_canon.cost == 0
    assert free_canon.fn(value) == Ok(Card("pair", "pair", (1, 2)))
    assert verify_object(definition(free), lib, request([(value,)])).steps == [2]
    made = lib.run("free_fraction.make", (value,))  # nested evaluation of the free canon
    counted = lib.run("fraction.make", (value,))
    assert made.outcome == Ok(Card("free_fraction", "val", (Card("pair", "pair", (1, 2)),)))
    assert made.steps < counted.steps  # canon_cost free charges nothing for the canon
    lib.add(Atom("undefined_canon", 1, lambda value: Bottom("oops")))
    broken = ObjectSpec("undefined", "refine", base="pair", valid=fraction.valid,
                        canon=n.Call("undefined_canon", (n.Var("x"),)))
    result = verify_object(definition(broken), lib, request([(value,)]))
    assert not result.ok and any("canon_total" in issue for issue in result.problems)


def test_invented_integer_abstraction_and_sampled_comparison():
    representation = ObjectSpec("representation", "compose", tags={
        "pair": (("pos", "int"), ("neg", "int"))})
    invented = ObjectSpec("invented", "refine", base="representation",
                          valid=n.Call("valid_pair", (n.Var("x"),)),
                          canon=n.Call("normalize_pair", (n.Var("x"),)))
    lib = ObjectLibrary((representation, invented))
    lib.add(*object_atoms(representation, lib),
            Atom("valid_pair", 1, lambda pair: all(item >= 0 for item in pair.fields)),
            Atom("normalize_pair", 1, lambda pair: Card("representation", "pair", (
                max(pair.fields[0] - pair.fields[1], 0),
                max(pair.fields[1] - pair.fields[0], 0)))),
            *object_atoms(invented, lib),
            Atom("raw_pair_add", 2, lambda left, right: Card("representation", "pair", (
                left.fields[0].fields[0] + right.fields[0].fields[0],
                left.fields[0].fields[1] + right.fields[0].fields[1]))),
            Atom("raw_pair_neg", 1, lambda item: Card("representation", "pair",
                tuple(reversed(item.fields[0].fields)))),
            Defn("invented_add", ("left", "right"), n.Call("invented.make", (
                n.Call("raw_pair_add", (n.Var("left"), n.Var("right"))),))),
            Defn("invented_neg", ("item",), n.Call("invented.make", (
                n.Call("raw_pair_neg", (n.Var("item"),)),))),
            Atom("int_add", 2, lambda left, right: left + right),
            Atom("int_neg", 1, lambda value: -value),
            Defn("invented_neg_copy", ("item",), n.Call("invented_neg", (n.Var("item"),))))
    domain = [(Card("representation", "pair", (pos, neg)),)
              for pos in range(6) for neg in range(6)]
    verification = request(domain, extra={"abs": lambda value:
        value.fields[0].fields[0] - value.fields[0].fields[1],
        "interface_ops": {"invented_add": [0, 1], "invented_neg": [0]},
        "interface_pairs": [("invented_add", "int_add"), ("invented_neg", "int_neg")]})
    result = verify_object(definition(invented), lib, verification)
    assert result.ok and "abs_commutes" in result.checks, result.problems
    lib.add(Atom("bad_add", 2, lambda left, right: left))
    verification.extra["interface_pairs"] = [("bad_add", "int_add")]
    verification.extra["interface_ops"]["bad_add"] = [0, 1]
    broken = verify_object(definition(invented), lib, verification)
    assert not broken.ok and any("abs_commutes" in item for item in broken.problems)
    sample = request(domain[:2], method="sampled", seed=42, extra={
        "interface_ops": {"invented_neg": [0]},
        "reference_ops": {"invented_neg": "invented_neg_copy"}, "count": 8, "depth": 2})
    assert "sampled" in verify_object(definition(invented), lib, sample).checks
