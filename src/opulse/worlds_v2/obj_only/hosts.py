"""Generic layer-zero arithmetic, finite records and list primitives."""

from fractions import Fraction
from functools import lru_cache
from math import comb, gcd

from opulse.atoms.values import Bottom, Card, Ok, Unknown


def raw(name, *fields):
    return Card("raw", name, fields)


def entries(rows):
    return tuple(raw("term", exponent, str(coefficient)) for exponent, coefficient in rows)


def polynomial(rows):
    return raw("SparsePoly", entries(rows))


def interval(lo, hi):
    return raw("Span", str(lo), str(hi))


def tile(source, domain, sign=0):
    return raw("SignTile", source, domain, sign)


def bracket(source, domain, root="", multiplicity=1, witness=()):
    return raw("RootBracket", source, domain, str(root) if root is not None else "",
               multiplicity, tuple(raw("witness", str(lo), str(hi), sign)
                                   for lo, hi, sign in witness))


def cover(source, domain, tiles):
    return raw("SignCover", source, domain, tuple(tiles))


def atlas(source, domain, pieces):
    return raw("RootAtlas", source, domain, tuple(pieces))


def make_record(sort, tag, fields):
    if type(sort) is not str or type(tag) is not str or not isinstance(fields, tuple):
        return Bottom("type")
    return Card(sort, tag, fields)


def field(value, index):
    if type(index) is not int or index < 0:
        return Bottom("field")
    if isinstance(value, Card):
        values = value.fields
    elif isinstance(value, tuple):
        values = value
    else:
        return Bottom("field")
    return values[index] if index < len(values) else Bottom("field")


def tag(value):
    return value.tag if isinstance(value, Card) else Bottom("type")


def field_count(value):
    return len(value.fields) if isinstance(value, Card) else Bottom("type")


def rat_parse(value):
    if type(value) is int:
        return (value, 1)
    if type(value) is not str:
        return Bottom("rational")
    return _parse_rational_text(value)


@lru_cache(maxsize=8192)
def _parse_rational_text(value):
    try:
        parts = value.split("/")
        if len(parts) not in (1, 2) or any(not part or str(int(part)) != part for part in parts):
            return Bottom("rational")
        return (int(parts[0]), int(parts[1]) if len(parts) == 2 else 1)
    except ValueError:
        return Bottom("rational")


def rat_format(value):
    if (not isinstance(value, tuple) or len(value) != 2 or
            any(type(part) is not int for part in value) or value[1] <= 0):
        return Bottom("rational")
    return _format_rational_pair(value)


def _rational(value):
    if not isinstance(value, tuple) or len(value) != 2 or any(type(part) is not int for part in value):
        return None
    if value[1] == 0:
        return None
    return value


def _rational_result(value):
    return (value.numerator, value.denominator)


def rat_add(left, right):
    first, second = _rational(left), _rational(right)
    return _rational_cached("add", left, right) if first is not None and second is not None else Bottom("rational")


def rat_mul(left, right):
    first, second = _rational(left), _rational(right)
    return _rational_cached("mul", left, right) if first is not None and second is not None else Bottom("rational")


def rat_div(left, right):
    first, second = _rational(left), _rational(right)
    return (_rational_cached("div", left, right) if first is not None and second is not None and second[0]
            else Bottom("rational"))


def rat_pow(value, exponent):
    rational = _rational(value)
    return (_rational_cached("pow", value, exponent)
            if rational is not None and type(exponent) is int and 0 <= exponent <= 256
            else Bottom("rational"))


def rat_lt(left, right):
    first, second = _rational(left), _rational(right)
    return _rational_cached("lt", left, right) if first is not None and second is not None else Bottom("rational")


def rat_eq(left, right):
    first, second = _rational(left), _rational(right)
    return _rational_cached("eq", left, right) if first is not None and second is not None else Bottom("rational")


@lru_cache(maxsize=32768)
def _rational_cached(operation, left, right):
    first = Fraction(*left)
    second = Fraction(*right) if operation != "pow" else right
    if operation == "lt":
        return first < second
    if operation == "eq":
        return first == second
    if operation == "pow":
        return _rational_result(first**second)
    if operation == "add":
        return _rational_result(first + second)
    if operation == "mul":
        return _rational_result(first * second)
    return _rational_result(first / second)


@lru_cache(maxsize=8192)
def _format_rational_pair(value):
    return str(value[0]) if value[1] == 1 else f"{value[0]}/{value[1]}"


def add(left, right):
    return left + right if type(left) is type(right) is int else Bottom("type")


def sub(left, right):
    return left - right if type(left) is type(right) is int else Bottom("type")


def mul(left, right):
    return left * right if type(left) is type(right) is int else Bottom("type")


def neg(value):
    return -value if type(value) is int else Bottom("type")


def integer_gcd(left, right):
    return gcd(left, right) if type(left) is type(right) is int else Bottom("type")


def div_exact(left, right):
    if type(left) is not int or type(right) is not int or right == 0 or left % right:
        return Bottom("nonexact_division")
    return left // right


def power(value, exponent):
    if type(value) is not int or type(exponent) is not int or not 0 <= exponent <= 256:
        return Bottom("exponent")
    return value**exponent


def binom(total, chosen):
    if type(total) is not int or type(chosen) is not int or not 0 <= chosen <= total <= 256:
        return Bottom("binomial")
    return comb(total, chosen)


def lt(left, right):
    return left < right if type(left) is type(right) is int else Bottom("type")


def eq(left, right):
    return left == right


def is_empty(values):
    return not values if isinstance(values, tuple) else Bottom("type")


def head(values):
    return values[0] if isinstance(values, tuple) and values else Bottom("empty")


def tail(values):
    return values[1:] if isinstance(values, tuple) and values else Bottom("empty")


def list_length(values):
    return len(values) if isinstance(values, tuple) else Bottom("type")


def cons(value, values):
    return (value, *values) if isinstance(values, tuple) else Bottom("type")


def bounded_count(value):
    if value == -1:
        return Unknown("resource")
    return type(value) is int and 0 <= value <= 20


def sort(values):
    if not isinstance(values, tuple):
        return Bottom("public_integer_keys_only")
    if all(type(item) is int for item in values):
        return tuple(sorted(values))
    if all(isinstance(item, tuple) and len(item) == 2 and type(item[0]) is int
           for item in values):
        return tuple(sorted(values, key=lambda item: item[0]))
    return Bottom("public_integer_keys_only")


def is_ok(outcome):
    if isinstance(outcome, Unknown):
        return outcome
    return isinstance(outcome, Ok)


def read(value, field):
    if not isinstance(value, Card) or value.tag != "val" or len(value.fields) != 1:
        return Bottom("not_an_object")
    if field == "num":
        return field_at(value.fields[0], 0)
    if field == "den":
        return field_at(value.fields[0], 1)
    return Bottom("sealed_field")


field_at = globals()["field"]


def value(item):
    if not isinstance(item, Card) or item.tag != "val" or not isinstance(item.fields[0], Card):
        return Bottom("not_an_object")
    stored = item.fields[0]
    fields = stored.fields
    if item.sort == "Rat":
        return f"Rat<{Fraction(*fields)}>"
    if item.sort == "SparsePoly":
        return "SparsePoly<" + ",".join(f"{term.fields[0]}:{term.fields[1]}"
                                         for term in fields[0]) + ">"
    if item.sort == "Span":
        return f"Span<{fields[0]},{fields[1]}>"
    if item.sort == "BernsteinPatch":
        return "BernsteinPatch<" + ",".join(fields[2]) + ">"
    if item.sort == "SignTile":
        return f"SignTile<{'+' if fields[2] > 0 else '-'};{min(map(Fraction, fields[3]))},{max(map(Fraction, fields[3]))}>"
    if item.sort == "SignCover":
        return f"SignCover<{len(fields[2])}>"
    if item.sort == "RootBracket":
        lo, hi = fields[1].fields
        slope = fields[4][0].fields[2]
        return f"RootBracket<{lo},{hi},{'+' if slope > 0 else '-'}>"
    if item.sort == "RootAtlas":
        return f"RootAtlas<{sum(part.tag == 'RootBracket' for part in fields[2])};{len(fields[2])}>"
    return Bottom("not_an_object")


def accepted(outcome):
    return isinstance(outcome, Ok) and isinstance(outcome.value, Card) and outcome.value.tag == "val"
