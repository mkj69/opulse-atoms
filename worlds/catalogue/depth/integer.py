"""Executable, bounded-budget reference semantics for the integer depth tower.

All non-primitive arithmetic in the tower is defined in terms of the named
operations below. The evaluator accepts the exact ASCII expressions in the
companion JSON; it never evaluates arbitrary Python from a prompt.
"""

from dataclasses import dataclass
from math import gcd as host_gcd
from pathlib import Path
import json
import re


class Bottom(ValueError):
    pass


class Unknown(RuntimeError):
    pass


class Ledger:
    def __init__(self, fuel=3_000_000):
        self.fuel = fuel
        self.cost = 0

    def tick(self):
        if self.cost == self.fuel:
            raise Unknown("resource")
        self.cost += 1


ledger = Ledger()


def require_int(number):
    if type(number) is not int:
        raise Bottom("type")
    return number


def succ(number):
    ledger.tick()
    return require_int(number) + 1


def add(left, right):
    ledger.tick()
    return require_int(left) + require_int(right)


def neg(number):
    ledger.tick()
    return -require_int(number)


def gcd(left, right):
    ledger.tick()
    return host_gcd(require_int(left), require_int(right))


def value(number):
    ledger.tick()
    return require_int(number)


@dataclass(frozen=True)
class Nat:
    number: int


def nat(number):
    if value(number) < 0:
        raise Bottom("range")
    return Nat(number)


def repeat(step, seed, count):
    if not isinstance(count, Nat):
        raise Bottom("type")
    for _ in range(count.number):
        seed = step(seed)
    return seed


def sequence(first, second, seed):
    return second(first(seed))


def mul(left, right):
    require_int(left)
    require_int(right)
    left_negative = value(left) < 0
    right_negative = value(right) < 0
    magnitude_left = neg(left) if left_negative else left
    magnitude_right = neg(right) if right_negative else right
    magnitude = repeat(lambda total: add(total, magnitude_left), 0, nat(magnitude_right))
    return neg(magnitude) if left_negative != right_negative else magnitude


@dataclass(frozen=True)
class Frac:
    num: int
    den: int


def make_frac(num, den):
    require_int(num)
    require_int(den)
    if value(den) == 0:
        raise Bottom("div0")
    divisor = gcd(num, den)
    ledger.tick()
    ledger.tick()
    num, den = num // divisor, den // divisor
    if value(den) < 0:
        num, den = neg(num), neg(den)
    return Frac(num, den)


def whole(frac):
    if not isinstance(frac, Frac):
        raise Bottom("type")
    return value(frac.den) == 1


def qadd(left, right):
    if not isinstance(left, Frac) or not isinstance(right, Frac):
        raise Bottom("type")
    return make_frac(add(mul(left.num, right.den), mul(right.num, left.den)),
                     mul(left.den, right.den))


def qmul(left, right):
    if not isinstance(left, Frac) or not isinstance(right, Frac):
        raise Bottom("type")
    return make_frac(mul(left.num, right.num), mul(left.den, right.den))


def fold_frac(step, items, seed):
    if not isinstance(items, list) or not isinstance(seed, Frac):
        raise Bottom("type")
    for item in items:
        seed = step(seed, item)
    return seed


def cf_divmod(number, divisor):
    require_int(number)
    require_int(divisor)
    if value(divisor) <= 0:
        raise Bottom("divisor")
    quotient, remainder = 0, number
    while value(remainder) < 0:
        remainder = add(remainder, divisor)
        quotient = add(quotient, -1)
    while value(remainder) >= value(divisor):
        remainder = add(remainder, neg(divisor))
        quotient = succ(quotient)
    return (quotient, remainder)


@dataclass(frozen=True)
class CF:
    digits: tuple


def make_cf(frac):
    if not isinstance(frac, Frac):
        raise Bottom("type")
    number, divisor = frac.num, frac.den
    digits = []
    while value(divisor) != 0:
        quotient, remainder = cf_divmod(number, divisor)
        digits.append(quotient)
        number, divisor = divisor, remainder
    assert len(digits) == 1 or digits[-1] >= 2
    return CF(tuple(digits))


def cf_step(state, digit):
    previous_num, older_num, previous_den, older_den = state
    return (add(mul(digit, previous_num), older_num), previous_num,
            add(mul(digit, previous_den), older_den), previous_den)


def convergents(step, continued):
    if not isinstance(continued, CF):
        raise Bottom("type")
    state = (1, 0, 0, 1)
    results = []
    for digit in continued.digits:
        state = step(state, digit)
        results.append(make_frac(state[0], state[2]))
    return results


def bounded_convergent(pair):
    if not isinstance(pair, tuple) or len(pair) != 2:
        raise Bottom("type")
    continued, bound = pair
    if not isinstance(bound, Nat):
        raise Bottom("type")
    options = [frac for frac in convergents(cf_step, continued)
               if value(frac.den) <= bound.number]
    if not options:
        raise Bottom("no_convergent")
    return options[-1]


OPERATIONS = {"succ": succ, "add": add, "neg": neg, "gcd": gcd,
              "mul": mul, "qadd": qadd, "qmul": qmul,
              "cf_divmod": cf_divmod, "cf_step": cf_step}
COMBINATORS = {"sequence": sequence, "repeat": repeat, "fold_frac": fold_frac,
               "convergents": convergents}
OBSERVATIONS = {"value": value, "whole": whole,
                "bounded_convergent": bounded_convergent}
OBJECTS = {"Int": lambda number: require_int(number), "Nat": nat,
           "Frac": make_frac, "CF": make_cf, "List": lambda *items: list(items),
           "Pair": lambda left, right: (left, right)}


class Parser:
    def __init__(self, source):
        self.tokens = re.findall(r"-?\d+|[A-Za-z_][A-Za-z_0-9]*|[@?<>()[\]{},]", source)
        if "".join(self.tokens) != re.sub(r"\s+", "", source):
            raise Bottom("syntax")
        self.position = 0

    def take(self, expected=None):
        if self.position >= len(self.tokens):
            raise Bottom("syntax")
        token = self.tokens[self.position]
        self.position += 1
        if expected is not None and token != expected:
            raise Bottom("syntax")
        return token

    def arguments(self, closing):
        arguments = []
        if self.tokens[self.position] != closing:
            arguments.append(self.expression())
            while self.tokens[self.position] == ",":
                self.take(",")
                arguments.append(self.expression())
        self.take(closing)
        return arguments

    def expression(self):
        token = self.take()
        if token == "@":
            name = self.take()
            self.take("[")
            slots = [self.take()]
            while self.tokens[self.position] == ",":
                self.take(",")
                slots.append(self.take())
            self.take("]")
            self.take("(")
            args = self.arguments(")")
            return COMBINATORS[name](*(OPERATIONS[slot] for slot in slots), *args)
        if token == "?":
            name = self.take()
            self.take("{")
            args = self.arguments("}")
            return OBSERVATIONS[name](*args)
        if re.fullmatch(r"-?\d+", token):
            return int(token)
        bracket = self.take()
        if bracket == "<":
            return OBJECTS[token](*self.arguments(">"))
        if bracket == "(":
            args = self.arguments(")")
            if token in ("eq", "ne", "lt", "le"):
                if len(args) != 2:
                    raise Bottom("arity")
                if token == "eq":
                    return args[0] == args[1]
                if token == "ne":
                    return args[0] != args[1]
                if type(args[0]) is int and type(args[1]) is int:
                    return args[0] < args[1] if token == "lt" else args[0] <= args[1]
                raise Bottom("order")
            return OPERATIONS[token](*args)
        raise Bottom("syntax")


def evaluate(expression):
    global ledger
    ledger = Ledger()
    parser = Parser(expression)
    result = parser.expression()
    if parser.position != len(parser.tokens):
        raise Bottom("syntax")
    return result


def display(result):
    if isinstance(result, bool):
        return "true" if result else "false"
    if isinstance(result, Nat):
        return f"Nat<{result.number}>"
    if isinstance(result, Frac):
        return f"Frac<{result.num}, {result.den}>"
    if isinstance(result, CF):
        return "CF<" + ", ".join(map(str, result.digits)) + ">"
    if isinstance(result, list):
        return "List<" + ", ".join(map(display, result)) + ">"
    if isinstance(result, tuple):
        return "Pair<" + ", ".join(map(display, result)) + ">"
    return str(result)


def verify():
    catalog = json.loads(Path(__file__).with_suffix(".json").read_text())
    assert len(catalog["tower"]) == 12
    assert evaluate("@sequence[succ,neg](Int<4>)") == -5
    assert evaluate("?value{Int<-8>}") == -8
    for layer in catalog["tower"]:
        assert display(evaluate(layer["example"])) == layer["value"], layer["layer"]
    for showcase in catalog["showcase"]:
        expression = showcase["prompt"].split("Expression: ", 1)[1].split("\n", 1)[0]
        if showcase["angle"] == "Invert":
            target_expr = re.search(r"such that this bounded convergent is (Frac<[^>]+>)", showcase["prompt"])
            bounds = re.search(r"k in (\d+)\.\.(\d+)", showcase["prompt"])
            assert target_expr and bounds
            target = evaluate(target_expr.group(1))
            matches = [candidate for candidate in range(int(bounds.group(1)), int(bounds.group(2)) + 1)
                       if evaluate(expression.replace("<k,", f"<{candidate},")) == target]
            assert matches == [42]
            assert showcase["answer"] == display(nat(matches[0]))
        else:
            assert display(evaluate(expression)) == showcase["answer"], expression
    assert make_frac(2, 4) == make_frac(1, 2)
    assert make_frac(2, -4) == make_frac(-1, 2)
    for numerator in range(-12, 13):
        for divisor in range(1, 13):
            quotient, remainder = cf_divmod(numerator, divisor)
            assert 0 <= remainder < divisor and quotient * divisor + remainder == numerator
    for left in range(-12, 13):
        for right in range(-12, 13):
            assert mul(left, right) == left * right
    for numerator in range(-10, 11):
        for divisor in range(1, 11):
            frac = make_frac(numerator, divisor)
            assert convergents(cf_step, make_cf(frac))[-1] == frac
    for expression, reason in [("Frac<1,0>", "div0"),
                               ("Nat<-1>", "range"),
                               ("cf_divmod(1,0)", "divisor")]:
        try:
            evaluate(expression)
        except Bottom as error:
            assert str(error) == reason
        else:
            raise AssertionError(expression)
    global ledger
    ledger = Ledger(2)
    try:
        repeat(succ, 0, nat(3))
    except Unknown as error:
        assert str(error) == "resource"
    else:
        raise AssertionError("fuel exhaustion must be Unknown")
    ledger = Ledger()
    try:
        bounded_convergent((make_cf(make_frac(1, 2)), nat(0)))
    except Bottom as error:
        assert str(error) == "no_convergent"
    else:
        raise AssertionError("zero bound must fail")
    print("OK")


if __name__ == "__main__":
    verify()
