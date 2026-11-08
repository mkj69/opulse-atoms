"""Static MASM and persistent-library checks."""

def calls(sub):
    return [line.args[0] for line in sub.lines if line.op == "call"]


def check_program(program, group, library):
    errors = []
    defs = {sub.name: sub for sub in program.defs}
    existing = set(library.names()) if library else set()
    if len(defs) != len(program.defs):
        errors.append("duplicate subroutine name")
    for sub in program.defs:
        if sub.name in existing or sub.name in ("write", "add", "dec", "load", "store", "is_zero", "mul"):
            errors.append(f"shadowing name {sub.name}")
        labels = [line.args[0] for line in sub.lines if line.op == "label"]
        if len(set(labels)) != len(labels):
            errors.append(f"duplicate label in {sub.name}")
        for line in sub.lines:
            op, args = line.op, line.args
            if op in ("jmp", "jz", "jnz") and args[-1] not in labels:
                errors.append(f"unknown label {args[-1]}")
            if op == "call" and args[0] not in defs.keys() | existing:
                errors.append(f"unknown target {args[0]}")
            if op == "mul" and group != "A":
                errors.append("mul is unavailable")
            register_indices = {"set": (0,), "add": (0, 1), "dec": (0,),
                                "load": (0,), "store": (0,), "jz": (0,), "jnz": (0,)}
            for position in register_indices.get(op, ()):
                if args[position] not in ("r0", "r1", "r2", "r3"):
                    errors.append(f"invalid register {args[position]}")
            if op in ("set", "load", "store"):
                literal = args[1].lstrip("0") or "0"
                if not args[1].isascii() or not args[1].isdigit() or len(args[1]) > 4096 or len(literal) > 3 or (
                        len(literal) == 3 and literal > "255"):
                    errors.append(f"operand out of range {args[1]}")
    if len(set(program.saves)) != len(program.saves):
        errors.append("duplicate save")
    if group == "C" and program.saves:
        errors.append("saving definitions is not available in this world")
    for name in program.saves:
        if name == "main":
            errors.append("cannot save main")
        elif name not in defs or name in existing:
            errors.append(f"cannot save {name}")
    graph = {sub.name: calls(sub) for sub in program.defs}
    for name in existing:
        graph[name] = list(library.get(name).depends_on)
    for name in graph:
        pending = [(name, ())]
        while pending:
            current, path = pending.pop()
            if current in path:
                errors.append(f"recursive call {current}")
                break
            pending.extend((target, (*path, current)) for target in graph.get(current, ()) if target in graph)
    for name in program.saves:
        for target in graph.get(name, ()):
            if target in defs and target not in program.saves:
                errors.append(f"cannot save {name}: calls unsaved {target}")
    return list(dict.fromkeys(errors))
