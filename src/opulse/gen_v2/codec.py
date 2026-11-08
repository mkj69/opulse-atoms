"""Reversible generator checkpoint values and display-only legacy host values.

The core node codec handles FnRef literals, but the core value codec does not encode
FnRef as a standalone checkpoint value, so this module preserves the value form.
"""

from __future__ import annotations

from opulse.atoms import kernel
from opulse.atoms.values import Bottom, Card, Ok, boolean


def value_key(value):
    """Type-preserving immutable key for pure values; never use display-only host JSON."""
    if isinstance(value, Card):
        return (Card, value.sort, value.tag, tuple(value_key(item) for item in value.fields))
    if isinstance(value, tuple):
        return (tuple, tuple(value_key(item) for item in value))
    hash(value)
    return (type(value), value)


def require_restorable(data):
    if isinstance(data, dict):
        if data.get("t") == "host":
            raise ValueError("checkpoint contains display-only host value; cannot restore")
        for item in data.values():
            require_restorable(item)
    elif isinstance(data, (list, tuple)):
        for item in data:
            require_restorable(item)


def encode_checkpoint_value(value):
    """Reversible checkpoint encoding, preserving host bool versus bool cards."""
    if isinstance(value, bool):
        return {"t": "python_bool", "v": value}
    if isinstance(value, tuple):
        return {"t": "tuple", "v": [encode_checkpoint_value(item) for item in value]}
    if isinstance(value, Card):
        return {"t": value.sort, "tag": value.tag,
                "f": [encode_checkpoint_value(item) for item in value.fields]}
    return encode_value(value)


def decode_checkpoint_value(data):
    if data.get("t") == "python_bool":
        if type(data.get("v")) is not bool:
            raise ValueError("invalid checkpoint bool")
        return data["v"]
    if data.get("t") == "tuple":
        return tuple(decode_checkpoint_value(item) for item in data["v"])
    if "tag" in data:
        return Card(data["t"], data["tag"],
                    tuple(decode_checkpoint_value(item) for item in data.get("f", ())))
    return decode_value(data)


def encode_value(value: object) -> dict:
    if isinstance(value, bool):
        return encode_value(boolean(value))
    if isinstance(value, int):
        return {"t": "int", "v": value}
    if isinstance(value, str):
        return {"t": "str", "v": value}
    if isinstance(value, Card):
        return {"t": value.sort, "tag": value.tag, "f": [encode_value(item) for item in value.fields]}
    if isinstance(value, kernel.FnRef):
        return {"t": "fn", "v": value.name}
    if isinstance(value, Bottom):  # legacy NaN flowing as a value inside a host structure
        return {"t": "bottom", "v": value.reason}
    if isinstance(value, tuple):
        return {"t": "tuple", "v": [encode_value(item) for item in value]}
    return {"t": "host", "type": type(value).__name__, "repr": repr(value)}


def encode_outcome(outcome) -> dict:
    if isinstance(outcome, Ok):
        return {"ok": encode_value(outcome.value)}
    if isinstance(outcome, Bottom):
        return {"bottom": outcome.reason}
    return {"unknown": outcome.resource}


def decode_value(data: dict) -> object:
    """Inverse of ``encode_value`` (host values stay as their display record)."""
    from opulse.atoms.values import decode

    kind = data.get("t")
    if kind == "fn":
        return kernel.FnRef(data["v"])
    if kind == "tuple":
        return tuple(decode_value(item) for item in data["v"])
    if kind == "host":
        return dict(data)
    if kind == "bottom":
        return Bottom(data["v"])
    if "tag" in data:
        return Card(data["t"], data["tag"], tuple(decode_value(item) for item in data.get("f", ())))
    return decode(data)
