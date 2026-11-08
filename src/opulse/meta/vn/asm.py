"""ASCII assembler for vn/1 (docs/spec/atoms-meta.md, section 4.1)."""

from __future__ import annotations

import re

from opulse.meta.vn.reference import NAMES, OPCODES, SIZES

_LINE = re.compile(r"^(?:(?P<label>[A-Za-z_][A-Za-z_0-9]*):\s*)?(?:(?P<op>[A-Za-z]+)(?:\s+(?P<arg>\S+))?)?$")
_ARG = re.compile(r"^@([A-Za-z_][A-Za-z_0-9]*)([+-]\d+)?$")


def assemble(text: str, n: int) -> list[int]:
    """Resolve labels against byte addresses; diagnose source errors by line."""
    if n not in SIZES:
        raise ValueError("invalid memory size")
    labels = {}
    instructions = []
    offset = 0
    for line_number, raw in enumerate(text.splitlines(), 1):
        line = raw.split(";", 1)[0].strip()
        if not line:
            continue
        match = _LINE.fullmatch(line)
        if not match:
            raise ValueError(f"line {line_number}: invalid syntax")
        label, op, arg = match.group("label", "op", "arg")
        if label:
            if label in labels:
                raise ValueError(f"line {line_number}: duplicate label {label}")
            labels[label] = offset
        if op is None:
            continue
        op = op.upper()
        if op not in OPCODES and op != "DB":
            raise ValueError(f"line {line_number}: unknown instruction {op}")
        if (op == "HALT") == (arg is not None):
            raise ValueError(f"line {line_number}: invalid operand for {op}")
        instructions.append((line_number, op, arg))
        offset += 1 if op == "DB" else 2
        if offset > n:
            raise ValueError(f"line {line_number}: program exceeds memory size {n}")
    result = []
    for line_number, op, arg in instructions:
        if op == "HALT":
            result.extend((0, 0))
            continue
        label = _ARG.fullmatch(arg)
        try:
            value = (labels[label[1]] + int(label[2] or 0) if label else
                     int(arg, 16 if arg.lower().startswith("0x") else 10))
        except (KeyError, ValueError):
            raise ValueError(f"line {line_number}: invalid operand {arg}") from None
        if not 0 <= value < 256:
            raise ValueError(f"line {line_number}: byte out of range {value}")
        if op != "DB":
            result.append(OPCODES[op])
        result.append(value)
    return result


def disassemble(data: list[int] | tuple[int, ...]) -> str:
    """Render bytes without losing data, including odd tails and illegal opcodes."""
    if any(type(byte) is not int or not 0 <= byte < 256 for byte in data):
        raise ValueError("invalid byte")
    lines = []
    offset = 0
    while offset < len(data):
        opcode = data[offset]
        if opcode in NAMES and offset + 1 < len(data) and (opcode != 0 or data[offset + 1] == 0):
            lines.append("HALT" if opcode == 0 else f"{NAMES[opcode]} {data[offset + 1]}")
            offset += 2
        else:
            lines.append(f"DB {opcode}")
            offset += 1
    return "\n".join(lines)
