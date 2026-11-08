"""Shared layer-0 integer rules for the meta worlds (atoms-meta section 2.3)."""

from opulse.atoms.values import Bottom


def add(left, right):
    return left + right


def sub(left, right):
    return left - right


def mul(left, right):
    return left * right


def div(left, right):
    return Bottom("div_zero") if right == 0 else left // right


def is_zero(value):
    return value == 0


def lt(left, right):
    return left < right
