"""Cross-world bridges with finite, recorded commuting domains."""

from dataclasses import replace
from itertools import product

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.bridges import BridgeContext, bridge_defn
from opulse.atoms.library import Library, VerifyRequest
from opulse.atoms.spec import BridgeSpec, Contract, Definition
from opulse.atoms.values import Bottom, Card, value_equal
from opulse.worlds_v2.integer import hosts as integers
from opulse.worlds_v2.integer import story as integer_story
from opulse.worlds_v2.integer import world as integer_world
from opulse.worlds_v2.pixels import hosts as pixels
from opulse.worlds_v2.pixels import world as pixel_world
from opulse.worlds_v2.rhythm import hosts as rhythm
from opulse.worlds_v2.rhythm import world as rhythm_world


def beat_domain(value):
    cells = rhythm.from_card(value)
    return not isinstance(cells, Bottom) and 1 <= len(cells) <= 8 and value.sort == "rhythm"


def beat_to_row(value):
    if not beat_domain(value):
        return Bottom("invalid")
    cells = rhythm.from_card(value)
    return pixels.to_card(("".join("#" if cell in (1, 2) else "." for cell in cells),))


def rotate_one(value):
    return rhythm.left(value, 1) if beat_domain(value) else Bottom("invalid")


def shift_one(value):
    if not isinstance(value, Card) or (value.sort, value.tag) != ("grid", "rows"):
        return Bottom("invalid")
    rows = pixels.from_card(value)
    if isinstance(rows, Bottom) or len(rows) != 1:
        return Bottom("invalid")
    return pixels.to_card((rows[0][1:] + rows[0][:1],))


def pair_domain(value):
    return (isinstance(value, Card) and (value.sort, value.tag) == ("pair", "items")
            and len(value.fields) == 2 and type(value.fields[0]) is int
            and type(value.fields[1]) is int and 1 <= value.fields[1] <= 3)


def int_product(left, right):
    return left * right if type(left) is int and type(right) is int else Bottom("invalid")


def cross_sum(left, right, *, numerator="first", denominator="second"):
    def field(name, value):
        return n.Call(name, (value,))

    top = n.Call("add", (
        n.Call("int_product", (field(numerator, left), field(denominator, right))),
        n.Call("int_product", (field(numerator, right), field(denominator, left))),
    ))
    bottom = n.Call("int_product", (field(denominator, left), field(denominator, right)))
    return top, bottom


def pair_add_definition():
    left, right = n.Var("left"), n.Var("right")
    top, bottom = cross_sum(left, right)
    reduced = n.Let("top", top, n.Let("bottom", bottom,
        n.Let("factor", n.Call("gcd", (n.Var("top"), n.Var("bottom"))),
              n.Call("pair", (
                  n.Call("quotient", (n.Var("top"), n.Var("factor"))),
                  n.Call("quotient", (n.Var("bottom"), n.Var("factor"))),
              )))))
    invalid = n.Lit(Bottom("invalid"))
    body = n.Case(((n.Test(n.Call("pair_domain", (left,))),
                    n.Case(((n.Test(n.Call("pair_domain", (right,))), reduced),), invalid)),), invalid)
    spec = integer_story.operation("pair_add", ("left", "right"), body,
                                   ("pair", "pair"), "pair")[2]
    return Definition("pair_add", "operation", "invented", 1,
                      tuple(sorted(n.references(body))), spec, body)


def frac_shape(value):
    return (isinstance(value, Card) and (value.sort, value.tag) == ("frac", "val")
            and len(value.fields) == 1 and isinstance(value.fields[0], Card)
            and (value.fields[0].sort, value.fields[0].tag) == ("pair", "items")
            and len(value.fields[0].fields) == 2
            and all(type(field) is int for field in value.fields[0].fields))


def frac_add_definition():
    def canonical(value):
        top = n.Call("numerator", (value,))
        bottom = n.Call("denominator", (value,))
        return n.Case(((n.Test(n.Call("le", (n.Lit(1), bottom))),
                        n.Call("card_equal", (value, n.Call("frac.make", (n.Call("pair", (top, bottom)),))))),),
                      n.Lit(False))

    left, right = n.Var("left"), n.Var("right")
    invalid = n.Lit(Bottom("invalid"))
    top, bottom = cross_sum(left, right, numerator="numerator", denominator="denominator")
    result = n.Call("frac.make", (n.Call("pair", (top, bottom)),))
    for value in (right, left):
        result = n.Case(((n.Test(n.Call("frac_shape", (value,))),
                          n.Case(((n.Test(canonical(value)), result),), invalid)),), invalid)
    spec = integer_story.operation("frac_add", ("left", "right"), result,
                                   ("unknown", "unknown"), "frac")[2]
    return Definition("frac_add", "operation", "invented", 2,
                      tuple(sorted(n.references(result))), spec, result)


BEAT_SPEC = BridgeSpec(
    "beat_row", "rhythm@1:rhythm", "pixels@1:grid",
    n.Call("beat_to_row", (n.Var("x"),)), n.Call("beat_domain", (n.Var("x"),)),
    (("rotate_one", "shift_one"),),
)
FRAC_SPEC = BridgeSpec(
    "to_frac", "integer@2:pair", "integer@2:frac",
    n.Call("frac.make", (n.Var("x"),)),
    n.Call("pair_domain", (n.Var("x"),)), (("pair_add", "frac_add"),),
)


def definition(spec):
    dependencies = tuple(sorted(n.references(spec.map) | n.references(spec.domain)))
    layer = 2 if spec.name == "to_frac" else 1
    return Definition(spec.name, "bridge", "invented", layer, dependencies, spec, bridge_defn(spec).body)


def _library(world, atoms, additions):
    declared = replace(world, open_kinds=(*world.open_kinds, "bridge"))
    return Library(declared, (*atoms, *(kernel.Atom(name, arity, fn) for name, arity, fn in additions)))


def beat_libraries():
    source = _library(rhythm_world.decl(), rhythm_world.atoms(),
                      (("beat_domain", 1, beat_domain), ("rotate_one", 1, rotate_one)))
    target = _library(pixel_world.decl(), pixel_world.atoms(),
                      (("beat_to_row", 1, beat_to_row), ("shift_one", 1, shift_one)))
    source.attach_world("pixels@1", target)
    return source, BridgeContext(source, target)


def frac_library():
    library = _library(integer_world.decl(), integer_world.atoms(),
                       (("pair_domain", 1, pair_domain), ("int_product", 2, int_product),
                        ("frac_shape", 1, frac_shape), ("card_equal", 2, value_equal)))
    fraction = next(card for card in integer_story.definitions() if card.name == "frac")
    library.write(fraction)
    library.check("frac")
    library.make_callable("frac", ((integers.pair(2, 3),),))
    library.write(pair_add_definition())
    library.check("pair_add")
    library.make_callable("pair_add", ((integers.pair(1, 2), integers.pair(1, 3)),))
    library.write(frac_add_definition())
    library.check("frac_add")
    library.make_callable("frac_add", ((integer_story.frac(1, 2), integer_story.frac(1, 3)),))
    return library


def beat_values():
    return tuple(rhythm.make_rhythm(cells) for length in range(1, 9)
                 for cells in product((0, 1, 2), repeat=length))


def beat_request(values=None):
    values = tuple(value for value in beat_values() if len(value.fields) <= 3) if values is None else tuple(values)
    return VerifyRequest("bounded", tuple((value,) for value in values),
                         {"domain": "all rhythm beat tuples of length 1..3, cells in {0,1,2}; "
                          "rotate_one/shift_one (k=1); separate exhaustive sweep: length 1..8, all k residues",
                          "size": len(values)})


def frac_request():
    values = tuple(integers.pair(number, denominator)
                   for number in range(-4, 5) for denominator in range(1, 4))
    return VerifyRequest("bounded", tuple((value,) for value in values),
                         {"domain": "pair<Int, Nat> numerator -4..4, denominator 1..3; "
                          "pair_add/frac_add on ordered pairs whose sum retains denominator 1..3",
                          "size": len(values)})


def check_all_rotations(values):
    """Check every residue k for every pattern, using the native rhythm rotation."""
    checked = 0
    for value in values:
        original = beat_to_row(value)
        row = pixels.from_card(original)[0]
        for offset in range(len(value.fields)):
            shifted = pixels.to_card((row[offset:] + row[:offset],))
            if beat_to_row(rhythm.left(value, offset)) != shifted:
                raise AssertionError((value, offset))
            checked += 1
    return checked


def build_library():
    beats, context = beat_libraries()
    fractions = frac_library()
    beat_scope = beat_request()
    beat_scope.scope["source_world_hash"] = context.source_lib.world.world_hash()
    beat_scope.scope["target_world_hash"] = context.target_lib.world.world_hash()
    beat_scope.scope["all_rotation_residues_checked"] = check_all_rotations(beat_values())
    beat_scope.scope["rotation_sweep_domain"] = "all beat tuples length 1..8, cells {0,1,2}, k=0..length-1"
    for library, spec, request, sample in (
        (beats, BEAT_SPEC, beat_scope, rhythm.make_rhythm((2, 0, 1))),
        (fractions, FRAC_SPEC, frac_request(), integers.pair(2, 1)),
    ):
        library.write(definition(spec))
        library.check(spec.name)
        library.make_callable(spec.name, ((sample,),))
        library.verify(spec.name, request)
        library.account(spec.name)
        library.promote(spec.name, Contract("Commuting on the recorded finite domain and interface"))
    return beats, fractions
