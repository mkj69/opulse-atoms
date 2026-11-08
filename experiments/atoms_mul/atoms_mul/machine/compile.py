"""Compile MASM to computer-world Blocks."""

from opulse.atoms import nodes as n
from opulse.worlds_v2.computer.machine import REGISTERS


def format_sub(sub):
    return "\n".join([f"sub {sub.name}:", *(
        f"  {line.args[0]}:" if line.op == "label" else
        f"  {line.op}" + (" " + ", ".join(line.args) if line.args else "")
        for line in sub.lines), "end"])


def size(sub):
    """Count every instruction and label line (excluding sub/end)."""
    return len(sub.lines)


def compile_sub(sub):
    blocks, assigns = [], []
    lines = sub.lines
    label_names = [f"__pc_{index}" for index in range(len(lines) + 1)]
    current = label_names[0]
    for index, line in enumerate(lines):
        following = label_names[index + 1]
        if line.op == "label":
            if current != label_names[index]:
                blocks.append((current, n.Block(tuple(assigns), n.Jump(label_names[index]))))
                assigns = []
            current = label_names[index]
            continue
        args = line.args
        if line.op in ("jmp", "jz", "jnz"):
            destination = next(label_names[position] for position, item in enumerate(lines)
                               if item.op == "label" and item.args[0] == args[-1])
            if line.op == "jmp":
                end = n.Jump(destination)
            else:
                test = n.Test(n.Call("is_zero", (n.Var("s"), n.Lit(REGISTERS[int(args[0][1:])]))))
                end = n.CondJump(test, destination if line.op == "jz" else following,
                                 following if line.op == "jz" else destination)
            blocks.append((current, n.Block(tuple(assigns), end)))
            assigns = []
            current = following
            continue
        if line.op == "halt":
            blocks.append((current, n.Block(tuple(assigns), n.Halt(n.Var("s")))))
            assigns = []
            current = following
            continue
        if line.op == "call":
            operation, operands = args[0], ()
        elif line.op == "mul":
            operation, operands = "mul", ()
        else:
            operation = "write" if line.op == "set" else line.op
            operands = tuple(n.Lit(REGISTERS[int(arg[1:])] if arg.startswith("r") else int(arg)) for arg in args)
        assign = ("s", n.Call(operation, (n.Var("s"), *operands)))
        assigns.append(assign)
    blocks.append((current, n.Block(tuple(assigns), n.Halt(n.Var("s")))))
    return n.Blocks((), label_names[0], tuple(blocks))
