"""Small world adapter for generic tasks (docs/spec/atoms-v2.md, sections 7 and 12)."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from opulse.atoms.library import Library
from opulse.atoms.notation import print_value
from opulse.atoms.values import Card, Ok, Unknown
from opulse.tasks_v2.task import KINDS


def show(value: object) -> str:
    """Print kernel values, retaining the machine-state teaching view."""
    if isinstance(value, Ok):
        return show(value.value)
    if isinstance(value, Unknown):
        return "Unknown"
    if isinstance(value, Card):
        if value.sort == "machine_state" and value.tag == "machine" and len(value.fields) == 4:
            regs, memory, zero, carry = value.fields
            cells = ", ".join(f"{index}:{byte}" for index, byte in enumerate(memory.fields) if byte)
            return ("State<" + ", ".join(f"r{index}={byte}" for index, byte in enumerate(regs.fields))
                    + f", zero={show(zero)}, carry={show(carry)}, mem={{{cells}}}>")
        if value.sort == "bool" and value.tag in ("true", "false") and not value.fields:
            return value.tag
        if value.sort == "List" and value.tag == "List":
            return "List<" + ", ".join(map(show, value.fields)) + ">"
        if not value.sort[:1].isupper():
            return f"{value.sort.split('[')[0].title()}.{value.tag}<" + ", ".join(map(show, value.fields)) + ">"
    return print_value(value)


class TaskWorld(Protocol):
    def library(self) -> Library: ...
    def domain(self, sort: str) -> Sequence[object]: ...
    def family(self, op_param_sort: str) -> Sequence[str]: ...
    def states(self) -> Sequence[object]: ...
    def show(self, value: object) -> str: ...
    def modalities(self) -> Mapping[str, Callable]: ...
    def open_kinds(self) -> Sequence[str]: ...
    def tags(self) -> dict | None: ...
    def to_value(self, host: object) -> object: ...
    def from_value(self, value: object) -> object: ...


@dataclass(frozen=True)
class LibraryWorld:
    stored: Library
    domains: Mapping[str, Sequence[object]] = field(default_factory=dict)
    families: Mapping[str, Sequence[str]] = field(default_factory=dict)
    truth_states: Sequence[object] = ()
    renderers: Mapping[str, Callable] = field(default_factory=dict)
    kinds: Sequence[str] | None = None
    world_tags: dict | None = None
    printer: Callable[[object], str] = show
    encode_host: Callable[[object], object] = lambda value: value
    decode_host: Callable[[object], object] = lambda value: value

    def library(self) -> Library:
        return self.stored

    def domain(self, sort: str) -> Sequence[object]:
        return self.domains.get(sort, ())

    def family(self, op_param_sort: str) -> Sequence[str]:
        if op_param_sort in self.families:
            return self.families[op_param_sort]
        return tuple(name for name, definition in self.stored.definitions.items()
                     if definition.kind == "operation")

    def states(self) -> Sequence[object]:
        return self.truth_states

    def show(self, value: object) -> str:
        if isinstance(value, Ok):
            return self.show(value.value)
        return self.printer(self.to_value(value))

    def to_value(self, host: object) -> object:
        return self.encode_host(host)

    def from_value(self, value: object) -> object:
        return self.decode_host(value)

    def modalities(self) -> Mapping[str, Callable]:
        return {"text": self.printer, **self.renderers}

    def open_kinds(self) -> Sequence[str]:
        declared = self.stored.world.extra.get("open_kinds", KINDS)
        return tuple(self.kinds if self.kinds is not None else declared)

    def tags(self) -> dict | None:
        return self.world_tags if self.world_tags is not None else self.stored.world.extra.get("tags")


def from_library(library: Library, *, domains: Mapping[str, Sequence[object]] | None = None,
                 family: Mapping[str, Sequence[str]] | None = None, states: Sequence[object] = (),
                 modalities: Mapping[str, Callable] | None = None, open_kinds: Sequence[str] | None = None,
                 tags: dict | None = None, show_value: Callable[[object], str] = show,
                 to_value: Callable[[object], object] = lambda value: value,
                 from_value: Callable[[object], object] = lambda value: value) -> TaskWorld:
    """Supply just finite domains and, optionally, passed-operation families."""
    return LibraryWorld(library, domains or {}, family or {}, states, modalities or {},
                        open_kinds, tags, show_value, to_value, from_value)
