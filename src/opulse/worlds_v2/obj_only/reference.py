"""Exact design reference checker for obj_only.

Only make_* functions introduce new kinds. Algebra and bounded iteration expand to
the fixed integer/list primitives; a proof object stores no unchecked oracle bit.
"""

import json
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path

from .counting import F, comb, items


def rat(num, den=1):
    if den == 0:
        raise ValueError("Bottom(denominator_zero)")
    return F(num, den)


def show(value):
    return str(value.numerator) if value.denominator == 1 else f"{value.numerator}/{value.denominator}"


@dataclass(frozen=True)
class SparsePoly:
    terms: tuple


def poly(raw):
    totals = {}
    for exponent, coefficient in items(raw):
        if not isinstance(exponent, int) or exponent < 0:
            raise ValueError("Bottom(exponent)")
        if exponent > 256:
            raise ValueError("Bottom(degree_limit)")
        totals[exponent] = totals.get(exponent, F(0)) + F(coefficient)
    return SparsePoly(tuple(sorted((key, val) for key, val in totals.items() if val)))


def coeffs(source):
    return dict(source.terms)


def mul(left, right):
    return poly((i + j, a * b) for i, a in items(left.terms) for j, b in items(right.terms))


def derivative(source):
    return poly((i - 1, i * a) for i, a in items(source.terms) if i)


def evaluate(source, point):
    return sum((a * point**i for i, a in items(source.terms)), F(0))


def power(source, exponent):
    if exponent < 0:
        raise ValueError("Bottom(exponent)")
    result = poly([(0, 1)])
    while exponent:
        if exponent % 2:
            result = mul(result, source)
        source = mul(source, source)
        exponent //= 2
    return result


@dataclass(frozen=True)
class Span:
    lo: F
    hi: F


def span(lo, hi):
    lo, hi = F(lo), F(hi)
    if lo >= hi:
        raise ValueError("Bottom(empty_span)")
    return Span(lo, hi)


@dataclass(frozen=True)
class BernsteinPatch:
    polynomial: SparsePoly
    domain: Span
    values: tuple


def patch(source, domain):
    degree = source.terms[-1][0] if source.terms else 0
    a, width = domain.lo, domain.hi - domain.lo
    shifted = [F(0)] * (degree + 1)
    for exponent, coefficient in items(source.terms):
        for index in range(exponent + 1):
            shifted[index] += coefficient * comb(exponent, index) * a**(exponent - index) * width**index
    values = tuple(sum((shifted[index] * F(comb(position, index), comb(degree, index))
                        for index in range(position + 1)), F(0))
                   for position in range(degree + 1))
    return BernsteinPatch(source, domain, values)


@dataclass(frozen=True)
class SignTile:
    patch: BernsteinPatch
    sign: int


def tile(source, domain, sign=None):
    witness = patch(source, domain)
    lower, upper = min(witness.values), max(witness.values)
    actual = 1 if lower > 0 else -1 if upper < 0 else 0
    if not actual or (sign is not None and sign != actual):
        raise ValueError("Bottom(uncertified_sign)")
    return SignTile(witness, actual)


@dataclass(frozen=True)
class SignCover:
    polynomial: SparsePoly
    domain: Span
    tiles: tuple
    sign: int


def cover(source, domain, tiles):
    ordered = tuple(sorted(tiles, key=lambda item: item.patch.domain.lo))
    if not ordered or ordered[0].patch.domain.lo != domain.lo or ordered[-1].patch.domain.hi != domain.hi:
        raise ValueError("Bottom(cover_boundary)")
    for previous, following in pairwise(items(ordered)):
        if previous.patch.domain.hi != following.patch.domain.lo:
            raise ValueError("Bottom(cover_gap_or_overlap)")
    if any(item.patch.polynomial != source or item.sign != ordered[0].sign or
           tile(source, item.patch.domain) != item for item in ordered):
        raise ValueError("Bottom(cover_mismatch)")
    return SignCover(source, domain, ordered, ordered[0].sign)


def subdivide(source, domain, max_depth=20):
    """Fixed @bounded/@branch search, not an invented operation."""
    if max_depth > 20 or max_depth < 0:
        raise ValueError("Bottom(depth_limit)")
    try:
        return (tile(source, domain),)
    except ValueError:
        if max_depth == 0:
            raise RuntimeError("Unknown(resource)")
        midpoint = (domain.lo + domain.hi) / 2
        return (subdivide(source, span(domain.lo, midpoint), max_depth - 1) +
                subdivide(source, span(midpoint, domain.hi), max_depth - 1))


@dataclass(frozen=True)
class RootBracket:
    polynomial: SparsePoly
    domain: Span
    slope_cover: SignCover | None
    exact_root: F | None = None
    multiplicity: int = 1
    cofactor_cover: SignCover | None = None

    @property
    def slope(self):
        return self.slope_cover.sign if self.slope_cover else 0


def divide_linear(source, root):
    """Exact synthetic division; return quotient and remainder."""
    degree = source.terms[-1][0] if source.terms else 0
    coefficients = coeffs(source)
    carry = F(0)
    quotient = []
    for exponent in range(degree, 0, -1):
        carry = coefficients.get(exponent, F(0)) + root * carry
        quotient.append((exponent - 1, carry))
    return poly(quotient), coefficients.get(0, F(0)) + root * carry


def root_bracket(source, domain, exact_root=None, multiplicity=1):
    if exact_root is not None:
        root = F(exact_root)
        if multiplicity < 2 or not domain.lo < root < domain.hi:
            raise ValueError("Bottom(multiplicity_or_root)")
        quotient = source
        for _ in range(multiplicity):
            quotient, remainder = divide_linear(quotient, root)
            if remainder:
                raise ValueError("Bottom(nonzero_remainder)")
        if evaluate(quotient, root) == 0:
            raise ValueError("Bottom(multiplicity_not_exact)")
        proof = cover(quotient, domain, subdivide(quotient, domain))
        return RootBracket(source, domain, None, root, multiplicity, proof)
    if multiplicity != 1:
        raise ValueError("Bottom(missing_exact_root)")
    left, right = evaluate(source, domain.lo), evaluate(source, domain.hi)
    if left == 0 or right == 0 or (left > 0) == (right > 0):
        raise ValueError("Bottom(endpoint_sign)")
    derivative_poly = derivative(source)
    slope_cover = cover(derivative_poly, domain, subdivide(derivative_poly, domain))
    slope = slope_cover.sign
    if (left < 0) != (slope > 0):
        raise ValueError("Bottom(slope_mismatch)")
    return RootBracket(source, domain, slope_cover)


@dataclass(frozen=True)
class RootAtlas:
    polynomial: SparsePoly
    domain: Span
    pieces: tuple


def atlas(source, domain, pieces):
    ordered = tuple(sorted(pieces, key=lambda item: item.domain.lo if isinstance(item, RootBracket)
                           else item.patch.domain.lo))
    if not ordered:
        raise ValueError("Bottom(empty_atlas)")
    boundaries = [item.domain if isinstance(item, RootBracket) else item.patch.domain for item in ordered]
    if boundaries[0].lo != domain.lo or boundaries[-1].hi != domain.hi or any(
            left.hi != right.lo for left, right in pairwise(boundaries)):
        raise ValueError("Bottom(atlas_gap_or_overlap)")
    for item in items(ordered):
        if isinstance(item, RootBracket):
            if item.polynomial != source or item != root_bracket(source, item.domain,
                                                                  item.exact_root, item.multiplicity):
                raise ValueError("Bottom(invalid_root_proof)")
        elif isinstance(item, SignTile):
            if item.patch.polynomial != source or item != tile(source, item.patch.domain):
                raise ValueError("Bottom(invalid_sign_proof)")
        else:
            raise TypeError("Bottom(invalid_piece)")
    return RootAtlas(source, domain, ordered)


def count_roots(proof):
    return sum(isinstance(piece, RootBracket) for piece in proof.pieces)


def count_multiplicity(proof):
    return sum(piece.multiplicity for piece in proof.pieces if isinstance(piece, RootBracket))


def encode_cover(proof):
    return [[show(item.patch.domain.lo), show(item.patch.domain.hi), item.sign]
            for item in proof.tiles]


def encode_atlas(proof):
    pieces = []
    for item in proof.pieces:
        if isinstance(item, SignTile):
            pieces.append({"kind": "SignTile", "interval": [show(item.patch.domain.lo),
                                                           show(item.patch.domain.hi)], "sign": item.sign})
        else:
            pieces.append({"kind": "RootBracket", "interval": [show(item.domain.lo),
                                                               show(item.domain.hi)],
                           "multiplicity": item.multiplicity,
                           "root": show(item.exact_root) if item.exact_root is not None else None,
                           "witness": encode_cover(item.cofactor_cover or item.slope_cover)})
    return pieces


def from_cover(source, domain, data):
    return cover(source, domain, [tile(source, span(F(lo), F(hi)), sign)
                                  for lo, hi, sign in data])


def from_atlas(source, domain, data):
    pieces = []
    for item in data:
        interval = span(*(F(endpoint) for endpoint in item["interval"]))
        if item["kind"] == "SignTile":
            pieces.append(tile(source, interval, item["sign"]))
        elif item["kind"] == "RootBracket":
            bracket = root_bracket(source, interval, item["root"], item["multiplicity"])
            if encode_cover(bracket.cofactor_cover or bracket.slope_cover) != item["witness"]:
                raise ValueError("Bottom(invalid_bracket_witness)")
            pieces.append(bracket)
        else:
            raise ValueError("Bottom(invalid_piece)")
    return atlas(source, domain, pieces)


def example_checks():
    results = {}
    results[1] = f"Rat<{show(rat(2, 4))}>"
    example_poly = poly([(0, 1), (2, 3), (2, -1), (9, 0)])
    results[2] = "SparsePoly<" + ",".join(f"{i}:{show(a)}" for i, a in example_poly.terms) + ">"
    sample_span = span(rat(2, 4), rat(6, 4))
    results[3] = f"Span<{show(sample_span.lo)},{show(sample_span.hi)}>"
    unit = span(0, 1)
    results[4] = "BernsteinPatch<" + ",".join(map(show, patch(poly([(2, 1)]), unit).values)) + ">"
    sample = poly([(0, 1), (2, 1)])
    positive = tile(sample, unit)
    results[5] = f"SignTile<+;{show(min(positive.patch.values))},{show(max(positive.patch.values))}>"
    proof = cover(sample, unit, [tile(sample, span(0, rat(1, 2))),
                                 tile(sample, span(rat(1, 2), 1))])
    results[6] = f"SignCover<{len(proof.tiles)}>"
    linear = poly([(1, 1), (0, rat(-1, 3))])
    bracket = root_bracket(linear, span(rat(1, 4), rat(1, 2)))
    results[7] = f"RootBracket<{show(bracket.domain.lo)},{show(bracket.domain.hi)},+>"
    quadratic = mul(linear, poly([(1, 1), (0, rat(-2, 3))]))
    first = root_bracket(quadratic, span(rat(1, 4), rat(5, 12)))
    second = root_bracket(quadratic, span(rat(7, 12), rat(3, 4)))
    pieces = [tile(quadratic, span(0, rat(1, 4))), first,
              tile(quadratic, span(rat(5, 12), rat(7, 12))), second,
              tile(quadratic, span(rat(3, 4), 1))]
    proof = atlas(quadratic, unit, pieces)
    results[8] = f"RootAtlas<{count_roots(proof)};{len(proof.pieces)}>"
    assert results == {
        1: "Rat<1/2>", 2: "SparsePoly<0:1,2:2>", 3: "Span<1/2,3/2>",
        4: "BernsteinPatch<0,0,1>", 5: "SignTile<+;1,2>",
        6: "SignCover<2>", 7: "RootBracket<1/4,1/2,+>", 8: "RootAtlas<2;5>"
    }
    return results


def showcase_checks(showcases):
    unit = span(0, 1)
    answers = []
    sizes = []
    for index, item in enumerate(showcases):
        source = poly((exponent, F(value)) for exponent, value in item["coefficients"])
        assert source.terms[-1][0] >= 30
        if index == 0:
            proof = from_cover(source, unit, item["certificate"])
            assert proof.sign == 1 and len(proof.tiles) >= 10
            assert min(part.patch.domain.hi - part.patch.domain.lo
                       for part in proof.tiles) <= F(1, 4096)
            answer = "true"
            sizes.append(len(proof.tiles))
        else:
            proof = from_atlas(source, unit, item["certificate"])
            roots = [part for part in proof.pieces if isinstance(part, RootBracket)]
            assert all(part.domain.hi - part.domain.lo <= F(1, 1024) for part in roots)
            assert len(proof.pieces) == 2 * len(roots) + 1
            if index == 1:
                assert len(roots) == 2 and count_roots(proof) == 2
                assert all(part.exact_root is None and part.multiplicity == 1 for part in roots)
                assert any(part.sign == -1 for part in proof.pieces if isinstance(part, SignTile))
                answer = "2"
            elif index == 2:
                assert len(roots) == 1 and roots[0].exact_root == F(3, 8)
                assert count_roots(proof) == 1 and count_multiplicity(proof) == 2
                answer = "RootCount<1;mult=2>"
            else:
                assert index == 3 and len(roots) == 1 and roots[0].exact_root is None
                assert count_roots(proof) == 1
                assert source.terms[-1] == (31, F(1)) and coeffs(source)[0] == -2
                assert all(coefficient.denominator == 1 for _, coefficient in source.terms)
                assert item["rational_root_candidates"] == ["-2", "-1", "1", "2"]
                assert all(evaluate(source, F(candidate)) != 0
                           for candidate in item["rational_root_candidates"])
                answer = "RootCount<1;no_rational_root>"
            sizes.append(len(proof.pieces))
        assert item["answer"] == answer
        answers.append(answer)
    return answers, sizes


def reject_invalid():
    from contextlib import suppress

    for constructor in (lambda: rat(1, 0), lambda: poly([(-1, 1)]),
                        lambda: poly([(257, 1)]), lambda: subdivide(poly([(0, 1)]), span(0, 1), 21),
                        lambda: span(1, 1), lambda: tile(poly([(1, 1)]), span(-1, 1)),
                        lambda: root_bracket(poly([(2, 1)]), span(-1, 1)),
                        lambda: root_bracket(poly([(2, 1)]), span(0, 1), F(1, 2), 2),
                        lambda: root_bracket(poly([(2, 1)]), span(0, 1), 0, 2),
                        lambda: atlas(poly([(0, 1)]), span(0, 1), []),
                        lambda: cover(poly([(0, 1)]), span(0, 1),
                                      [tile(poly([(0, 1)]), span(0, F(1, 3))),
                                       tile(poly([(0, 1)]), span(F(1, 2), 1))])):
        with suppress(ValueError):
            constructor()
            raise AssertionError("invalid representation accepted")


def main():
    manifest = json.loads((Path(__file__).resolve().parents[4] /
                           "worlds/catalogue/depth/obj_only.json").read_text(encoding="utf-8"))
    assert manifest["id"] == "obj_only" and manifest["open_kinds"] == ["object"]
    tags = manifest["tags"]
    assert set(tags) == {"domain", "modalities", "open_kinds", "star_kind", "reasoning",
                         "state", "outcomes", "visibility", "agents", "scale", "difficulty", "uses"}
    assert tags["domain"] == "math" and tags["modalities"] == ["text"]
    assert tags["open_kinds"] == manifest["open_kinds"] and tags["star_kind"] == "object"
    assert manifest["rejected_fixes"] == []
    assert len(manifest["tower"]) == 8 and len(manifest["ladder"]) == 5
    assert all(item["kind"] == "object" and item["layer"] == index
               for index, item in enumerate(manifest["tower"], 1))
    results = example_checks()
    for index, item in enumerate(manifest["tower"], 1):
        assert item["value"] == results[index], (index, item["value"], results[index])
    answers, sizes = showcase_checks(manifest["showcase"])
    for item, answer in zip(manifest["showcase"], answers):
        assert item["answer"] == answer, (item["answer"], answer)
    assert len(manifest["showcase"]) == 4
    reject_invalid()
    print("OK", "certificate pieces:", *sizes)


if __name__ == "__main__":
    main()
