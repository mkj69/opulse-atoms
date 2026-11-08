"""Exact rational arithmetic unfolded through the world's given integer atoms."""

from contextvars import ContextVar
from fractions import Fraction
from math import comb as integer_comb

from opulse.atoms.values import Ok

_meter = ContextVar("obj_only_meter", default=None)


class Exhausted(Exception):
    def __init__(self, outcome):
        self.outcome = outcome


def primitive(name, *args):
    meter = _meter.get()
    if meter is None:
        if name == "binom":
            return integer_comb(*args)
        if name == "gcd":
            from math import gcd

            return gcd(*args)
        if name == "is_empty":
            return not args[0]
        if name == "head":
            return args[0][0]
        if name == "tail":
            return args[0][1:]
        return {"add": lambda: args[0] + args[1],
                "sub": lambda: args[0] - args[1],
                "mul": lambda: args[0] * args[1],
                "neg": lambda: -args[0],
                "lt": lambda: args[0] < args[1],
                "eq": lambda: args[0] == args[1],
                "pow": lambda: args[0] ** args[1],
                "div_exact": lambda: args[0] // args[1]}[name]()
    outcome = meter.call(name, args)
    if not isinstance(outcome, Ok):
        raise Exhausted(outcome)
    return outcome.value


def comb(total, chosen):
    return primitive("binom", total, chosen)


def items(values):
    if _meter.get() is None or not isinstance(values, (tuple, list)):
        yield from values
        return
    remaining = tuple(values)
    while not primitive("is_empty", remaining):
        yield primitive("head", remaining)
        remaining = primitive("tail", remaining)


class F(Fraction):
    def __new__(cls, numerator=0, denominator=None):
        if _meter.get() is None:
            return super().__new__(cls, numerator, denominator)
        if denominator is None:
            if isinstance(numerator, Fraction):
                numerator, denominator = numerator.numerator, numerator.denominator
            elif isinstance(numerator, str) and "/" in numerator:
                numerator, denominator = map(int, numerator.split("/"))
            elif isinstance(numerator, str):
                numerator, denominator = int(numerator), 1
            elif isinstance(numerator, int):
                denominator = 1
        if type(numerator) is not int or type(denominator) is not int:
            return super().__new__(cls, numerator, denominator)
        if denominator == 0:
            raise ZeroDivisionError
        if primitive("lt", denominator, 0):
            numerator, denominator = primitive("neg", numerator), primitive("neg", denominator)
        divisor = primitive("gcd", numerator, denominator)
        return super().__new__(cls, primitive("div_exact", numerator, divisor),
                               primitive("div_exact", denominator, divisor), _normalize=False)

    def _pair(self, other):
        if not isinstance(other, (int, Fraction)):
            return NotImplemented
        return F(other)

    def __add__(self, other):
        other = self._pair(other)
        if other is NotImplemented:
            return NotImplemented
        return F(primitive("add", primitive("mul", self.numerator, other.denominator),
                           primitive("mul", other.numerator, self.denominator)),
                 primitive("mul", self.denominator, other.denominator))

    __radd__ = __add__

    def __neg__(self):
        return F(primitive("neg", self.numerator), self.denominator)

    def __sub__(self, other):
        other = self._pair(other)
        return self + -other if other is not NotImplemented else NotImplemented

    def __rsub__(self, other):
        other = self._pair(other)
        return other - self if other is not NotImplemented else NotImplemented

    def __mul__(self, other):
        other = self._pair(other)
        if other is NotImplemented:
            return NotImplemented
        return F(primitive("mul", self.numerator, other.numerator),
                 primitive("mul", self.denominator, other.denominator))

    __rmul__ = __mul__

    def __truediv__(self, other):
        other = self._pair(other)
        if other is NotImplemented:
            return NotImplemented
        if not other:
            raise ZeroDivisionError
        return F(primitive("mul", self.numerator, other.denominator),
                 primitive("mul", self.denominator, other.numerator))

    def __pow__(self, exponent):
        if type(exponent) is not int:
            return NotImplemented
        if exponent < 0:
            return F(primitive("pow", self.denominator, -exponent),
                     primitive("pow", self.numerator, -exponent))
        return F(primitive("pow", self.numerator, exponent),
                 primitive("pow", self.denominator, exponent))

    def __lt__(self, other):
        other = self._pair(other)
        if other is NotImplemented:
            return NotImplemented
        return primitive("lt", primitive("mul", self.numerator, other.denominator),
                         primitive("mul", other.numerator, self.denominator))

    def __le__(self, other):
        return self == other or self < other

    def __gt__(self, other):
        return not self <= other

    def __ge__(self, other):
        return not self < other

    def __eq__(self, other):
        other = self._pair(other)
        if other is NotImplemented:
            return NotImplemented
        return primitive("eq", primitive("mul", self.numerator, other.denominator),
                         primitive("mul", other.numerator, self.denominator))

    __hash__ = Fraction.__hash__


def metered(context, function, *args):
    token = _meter.set(context)
    try:
        return function(*args)
    except Exhausted as error:
        return error.outcome
    finally:
        _meter.reset(token)
