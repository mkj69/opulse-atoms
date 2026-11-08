"""Values and outcomes (docs/spec/atoms-v2.md, sections 2 and 3).

A value is an ``int``, a ``str`` or a :class:`Card`. Worlds may keep a given sort in a host
representation (Python ``bool``, ``tuple``, ``Permutation``, the robot state); kernel equality
then falls back to :func:`opulse.core.types.same_value`, which never treats a bool as an int.
"""

from __future__ import annotations

from dataclasses import dataclass

VALUE_SCHEMA = "opulse.value/2"


@dataclass(frozen=True)
class Card:
    """A tagged node: ``sort`` with its static parameters, one of its tags, ordered fields."""

    sort: str
    tag: str
    fields: tuple = ()

    def __post_init__(self) -> None:
        if not isinstance(self.fields, tuple):
            object.__setattr__(self, "fields", tuple(self.fields))


FALSE = Card("bool", "false")
TRUE = Card("bool", "true")


def boolean(flag: bool) -> Card:
    return TRUE if flag else FALSE


def truth(value: object) -> bool:
    """The Python truth of a bool card or a host bool; anything else is a type error."""
    if value is True or value == TRUE:
        return True
    if value is False or value == FALSE:
        return False
    raise TypeError(f"not a boolean value: {value!r}")


@dataclass(frozen=True)
class Ok:
    value: object


@dataclass(frozen=True)
class Bottom:
    """A domain failure: division by zero, a blocked move, no matching arm, an invalid value."""

    reason: str = "undefined"


@dataclass(frozen=True)
class Unknown:
    """A resource ran out (``fuel``, ``depth``, ``nodes``). Not a value; never equal to anything."""

    resource: str = "fuel"


Outcome = Ok | Bottom | Unknown


def value_equal(left: object, right: object) -> bool:
    """Kernel equality: structural on cards, ``same_value`` on host values."""
    if type(left) is bool and isinstance(right, Card) and right.sort == "bool":
        return right == boolean(left)
    if type(right) is bool and isinstance(left, Card) and left.sort == "bool":
        return left == boolean(right)
    if isinstance(left, (tuple, list)) and isinstance(right, (tuple, list)):
        return len(left) == len(right) and all(value_equal(a, b) for a, b in zip(left, right))
    if isinstance(left, Card) or isinstance(right, Card):
        return (isinstance(left, Card) and isinstance(right, Card) and left.sort == right.sort
                and left.tag == right.tag and len(left.fields) == len(right.fields)
                and all(value_equal(a, b) for a, b in zip(left.fields, right.fields)))
    from opulse.core.types import same_value

    return same_value(left, right)


def outcome_equal(left: Outcome, right: Outcome) -> bool:
    """Ok by value; any two Bottoms are equal (legacy NaN rule); Unknown equals nothing."""
    if isinstance(left, Unknown) or isinstance(right, Unknown):
        return False
    if isinstance(left, Bottom) or isinstance(right, Bottom):
        return isinstance(left, Bottom) and isinstance(right, Bottom)
    return value_equal(left.value, right.value)


# ------------------------------------------------------------------ JSON codec
def encode(value: object) -> dict:
    """``opulse.value/2`` JSON of an int, str or card (host values need a world codec)."""
    from opulse.atoms.kernel import FnRef

    if isinstance(value, FnRef):
        return {"t": "fn", "v": value.name}
    if isinstance(value, bool):
        return encode(boolean(value))
    if isinstance(value, int):
        return {"t": "int", "v": value}
    if isinstance(value, str):
        return {"t": "str", "v": value}
    if isinstance(value, Card):
        return {"t": value.sort, "tag": value.tag, "f": [encode(item) for item in value.fields]}
    if isinstance(value, tuple):
        return {"t": "tuple", "v": [encode(item) for item in value]}
    raise TypeError(f"no opulse.value/2 encoding for {value!r}; use the world codec")


def decode(data: dict) -> object:
    if data["t"] == "fn" and "tag" not in data and isinstance(data.get("v"), str):
        from opulse.atoms.kernel import FnRef

        return FnRef(data["v"])
    if data["t"] == "tuple" and "tag" not in data:
        return tuple(decode(item) for item in data["v"])
    if "tag" in data:
        return Card(data["t"], data["tag"], tuple(decode(item) for item in data.get("f", ())))
    if data["t"] == "int" and type(data["v"]) is int:
        return data["v"]
    if data["t"] == "str" and isinstance(data["v"], str):
        return data["v"]
    raise ValueError(f"not an opulse.value/2 value: {data!r}")


def encode_outcome(outcome: Outcome) -> dict:
    if isinstance(outcome, Ok):
        return {"ok": encode(outcome.value)}
    if isinstance(outcome, Bottom):
        return {"bottom": outcome.reason}
    return {"unknown": outcome.resource}


def decode_outcome(data: dict) -> Outcome:
    if "ok" in data:
        return Ok(decode(data["ok"]))
    if "bottom" in data:
        return Bottom(data["bottom"])
    return Unknown(data["unknown"])
