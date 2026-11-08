"""Layer-0 operations of the experiment worlds: the single source of their semantics.

`compute` is used by the experiment evaluator. The module-level functions are the host
implementations named in the opulse.world/2 declarations (`worlds/decl/`); their host
digest is the sha256 of this file, so any edit here must be followed by
`core_library.write_decls()`.
"""

MAX_NAT = 10**9


def nat_valid(value):
    return type(value) is int and 0 <= value <= MAX_NAT


def compute(name, args):
    """(True, value) or (False, failure reason) for operation `name` on `args`."""
    if not all(nat_valid(value) for value in args):
        return False, f"type: {name} expects natural numbers"
    if name == "is_zero":
        return True, args[0] == 0
    if name == "eq":
        return True, args[0] == args[1]
    if name == "lt":
        return True, args[0] < args[1]
    if name == "add":
        value = args[0] + args[1]
    elif name == "sub":
        value = args[0] - args[1]
    elif name == "succ":
        value = args[0] + 1
    elif name == "pred":
        value = args[0] - 1
    elif name == "mul":
        value = args[0] * args[1]
    else:
        return False, f"no such name {name}"
    if value < 0:
        return False, "negative"
    if value > MAX_NAT:
        return False, "overflow"
    return True, value


def _host(name, args):
    from opulse.atoms.values import Bottom, Ok

    ok, payload = compute(name, args)
    return Ok(payload) if ok else Bottom(payload)


def add(*args):
    return _host("add", args)


def sub(*args):
    return _host("sub", args)


def succ(*args):
    return _host("succ", args)


def pred(*args):
    return _host("pred", args)


def is_zero(*args):
    return _host("is_zero", args)


def eq(*args):
    return _host("eq", args)


def lt(*args):
    return _host("lt", args)


def mul(*args):
    return _host("mul", args)


HOSTS = {"add": add, "sub": sub, "succ": succ, "pred": pred, "is_zero": is_zero,
         "eq": eq, "lt": lt, "mul": mul}
