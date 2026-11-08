"""Line-oriented MASM parser; semantic validation belongs to check.py."""

import re
from dataclasses import dataclass


class MasmSyntaxError(Exception):
    def __init__(self, message, line, col):
        self.message, self.line, self.col = message, line, col
        super().__init__(f"{message} at {line}:{col}")


@dataclass(frozen=True)
class Instruction:
    op: str
    args: tuple[str, ...] = ()
    line: int = 0


@dataclass(frozen=True)
class Sub:
    name: str
    lines: tuple[Instruction, ...]


@dataclass(frozen=True)
class Program:
    defs: tuple[Sub, ...]
    saves: tuple[str, ...]


NAME = re.compile(r"[A-Za-z_][A-Za-z_0-9]*\Z")
ARITY = {"set": 2, "add": 2, "dec": 1, "load": 2, "store": 2,
         "mul": 0, "call": 1, "jz": 2, "jnz": 2, "jmp": 1, "halt": 0}


def parse_program(text):
    if not isinstance(text, str):
        raise MasmSyntaxError("expected text", 1, 1)
    defs, saves, current, lines = [], [], None, []
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("sub ") and line.endswith(":"):
            name = line[4:-1].strip()
            if current is not None or not NAME.fullmatch(name):
                raise MasmSyntaxError("invalid sub", number, 1)
            current, lines = name, []
        elif line == "end":
            if current is None:
                raise MasmSyntaxError("unexpected end", number, 1)
            defs.append(Sub(current, tuple(lines)))
            current = None
        elif line.startswith("save ") and current is None:
            name = line[5:].strip()
            if not NAME.fullmatch(name):
                raise MasmSyntaxError("invalid save", number, 1)
            saves.append(name)
        elif current is not None:
            if line.endswith(":") and NAME.fullmatch(line[:-1]):
                lines.append(Instruction("label", (line[:-1],), number))
                continue
            match = re.fullmatch(r"([a-z]+)(?:\s+(.+))?", line)
            if match is None or match[1] not in ARITY:
                raise MasmSyntaxError("invalid instruction", number, 1)
            args = tuple(part.strip() for part in match[2].split(",")) if match[2] else ()
            if len(args) != ARITY[match[1]] or any(not NAME.fullmatch(arg) and not re.fullmatch(r"[0-9]+", arg) for arg in args):
                raise MasmSyntaxError("invalid operands", number, 1)
            lines.append(Instruction(match[1], args, number))
        else:
            raise MasmSyntaxError("expected sub or save", number, 1)
    if current is not None:
        raise MasmSyntaxError("missing end", len(text.splitlines()) + 1, 1)
    return Program(tuple(defs), tuple(saves))
