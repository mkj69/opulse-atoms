"""Eight invented object cards, verified and promoted through the core library."""

import json
from fractions import Fraction
from pathlib import Path

from opulse.atoms import nodes as n
from opulse.atoms.library import VerifyRequest
from opulse.atoms.spec import Contract, Definition, ObjectSpec
from opulse.atoms.values import Ok

from . import bodies, hosts
from .world import new_library

DESIGN_PATH = Path(__file__).resolve().parents[4] / "worlds/catalogue/depth/obj_only.json"
NAMES = ("Rat", "SparsePoly", "Span", "BernsteinPatch", "SignTile",
         "SignCover", "RootBracket", "RootAtlas")


def design():
    return json.loads(DESIGN_PATH.read_text(encoding="utf-8"))


def definitions():
    for layer, name in enumerate(NAMES, 1):
        canon = bodies.body(name)
        valid = n.Call("is_ok", (canon,))
        spec = ObjectSpec(name, "refine", base="raw", valid=valid, canon=canon,
                          sealed=True, interface=(f"{name}.make", "read"))
        dependencies = tuple(sorted(n.references(valid) | n.references(canon)))
        yield Definition(name, "object", "invented", layer, dependencies, spec, None)


def example_raws():
    unit = hosts.interval(0, 1)
    square = hosts.polynomial(((2, 1),))
    positive = hosts.polynomial(((0, 1), (2, 1)))
    linear = hosts.polynomial(((0, "-1/3"), (1, 1)))
    quadratic = hosts.polynomial(((0, "2/9"), (1, -1), (2, 1)))
    quadratic_pieces = (
        hosts.tile(quadratic, hosts.interval(0, "1/4")),
        hosts.bracket(quadratic, hosts.interval("1/4", "5/12")),
        hosts.tile(quadratic, hosts.interval("5/12", "7/12")),
        hosts.bracket(quadratic, hosts.interval("7/12", "3/4")),
        hosts.tile(quadratic, hosts.interval("3/4", 1)),
    )
    return (
        hosts.raw("Rat", 2, 4),
        hosts.polynomial(((0, 1), (2, 3), (2, -1), (9, 0))),
        hosts.interval("2/4", "6/4"),
        hosts.raw("BernsteinPatch", square, unit),
        hosts.tile(positive, unit),
        hosts.cover(positive, unit, (hosts.tile(positive, hosts.interval(0, "1/2")),
                                     hosts.tile(positive, hosts.interval("1/2", 1)))),
        hosts.bracket(linear, hosts.interval("1/4", "1/2")),
        hosts.atlas(quadratic, unit, quadratic_pieces),
    )


def showcase_raw(task):
    source = hosts.polynomial(task["coefficients"])
    domain = hosts.interval(0, 1)
    if task["answer"] == "true":
        return hosts.cover(source, domain, tuple(hosts.tile(source, hosts.interval(lo, hi), sign)
                                                   for lo, hi, sign in task["certificate"]))
    pieces = []
    for item in task["certificate"]:
        piece_domain = hosts.interval(*item["interval"])
        if item["kind"] == "SignTile":
            pieces.append(hosts.tile(source, piece_domain, item["sign"]))
        else:
            pieces.append(hosts.bracket(source, piece_domain, item["root"],
                                        item["multiplicity"], item["witness"]))
    return hosts.atlas(source, domain, tuple(pieces))


def answer(value, task):
    assert isinstance(value, Ok)
    card = value.value.fields[0]
    if card.tag == "SignCover":
        return "true" if all(piece.fields[2] == 1 for piece in card.fields[2]) else "false"
    brackets = [piece for piece in card.fields[2] if piece.tag == "RootBracket"]
    if task["answer"] == "RootCount<1;mult=2>":
        return f"RootCount<{len(brackets)};mult={sum(piece.fields[3] for piece in brackets)}>"
    if task["answer"] == "RootCount<1;no_rational_root>":
        terms = {exponent: Fraction(coefficient) for exponent, coefficient in task["coefficients"]}
        candidates = task["rational_root_candidates"]
        degree = max(terms)
        constant = terms.get(0)
        if (terms[degree] != 1 or constant is None or constant.denominator != 1 or
                not all(coefficient.denominator == 1 for coefficient in terms.values())):
            raise ValueError("rational-root exhaustion requires a monic integer polynomial")
        divisors = {divisor for divisor in range(1, abs(constant.numerator) + 1)
                    if constant.numerator % divisor == 0}
        expected = {sign * divisor for divisor in divisors for sign in (-1, 1)}
        if {Fraction(candidate) for candidate in candidates} != expected:
            raise ValueError("rational-root candidates incomplete")
        if all(sum((coefficient * candidate**exponent for exponent, coefficient in terms.items()),
                   Fraction(0)) != 0 for candidate in expected):
            return f"RootCount<{len(brackets)};no_rational_root>"
    return str(len(brackets))


def build_library():
    library = new_library()
    for definition, sample in zip(definitions(), example_raws()):
        library.write(definition)
        library.check(definition.name)
        verification_sample = (hosts.atlas(hosts.polynomial(((0, 1),)), hosts.interval(0, 1),
                                           (hosts.tile(hosts.polynomial(((0, 1),)),
                                                       hosts.interval(0, 1)),))
                               if definition.name == "RootAtlas" else sample)
        library.make_callable(definition.name, ((verification_sample,),))
        request = VerifyRequest("bounded", ((verification_sample,),), {
            "domain": f"exact finite constructor sample for {definition.name}", "size": 1})
        library.verify(definition.name, request)
        library.account(definition.name)
        library.promote(definition.name, Contract("Exact validation on the stated finite scope"))
    return library
