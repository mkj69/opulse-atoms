"""Layer-0 declaration and metered machine adapter (atoms-meta sections 2.7, 5)."""

from dataclasses import replace

from opulse.atoms import kernel
from opulse.atoms.spec import Edge, ObjectSpec, OperationSpec
from opulse.atoms.values import Bottom, Card, Ok, Unknown, boolean
from opulse.meta import arith, code_world
from opulse.meta.code import items, lst
from opulse.meta.compiler import interp
from opulse.meta.export_util import host_rule
from opulse.meta.vn import reference

TAGS = {
    "domain": "program", "modalities": ["text"],
    "open_kinds": ["object", "operation", "combinator", "observation", "law", "bridge"],
    "star_kind": "operation", "reasoning": ["compute", "equivalence", "inference"],
    "state": "stateful", "outcomes": "deterministic", "visibility": "full",
    "agents": 1, "scale": "16- and 256-byte programs with bounded input tuples",
    "difficulty": "single instruction to translation validation",
    "uses": ["evaluation", "interpretability", "rl-training"],
}


def is_zero(value):
    return boolean(arith.is_zero(value))


def eq(left, right):
    return boolean(left == right)


def lt(left, right):
    return boolean(arith.lt(left, right))


_NAMED_GIVENS = {"add": arith.add, "sub": arith.sub, "is_zero": is_zero, "eq": eq, "lt": lt}


def result_a(result):
    """Read the result channel, not the final machine memory."""
    if not isinstance(result, Card) or result.sort != "result":
        return Bottom("invalid")
    if result.tag == "ok" and len(result.fields) == 2:
        return result.fields[0]
    return Bottom("no_result")


def fail_mismatch():
    return Bottom("mismatch")


def _run_prog(ctx, program, inputs, fuel):
    if (not isinstance(program, Card) or program.sort != "prog" or program.tag != "prog"
            or len(program.fields) != 4 or type(fuel) is not int or fuel < 0):
        return Bottom("invalid")
    size, code, addresses, output = program.fields
    try:
        code, addresses, inputs = items(code), items(addresses), items(inputs)
        if (output != "a" or len(inputs) != len(addresses)
                or any(type(value) is not int or not 0 <= value < 256 for value in inputs)):
            return Bottom("invalid")
        state = reference.load(code, size, dict(zip(addresses, inputs)))
    except (TypeError, ValueError, IndexError):
        return Bottom("invalid")
    status, final, steps = reference.run(state, fuel)
    for _ in range(steps):
        exhausted = ctx.engine.charge(1)
        if isinstance(exhausted, Unknown):
            return exhausted
    if status == "ok":
        return Ok(Card("result", "ok", (final.a, Card("list", "items", final.mem))))
    return Ok(Card("result", "err" if status == "illegal" else "out",
                   ("illegal" if status == "illegal" else "fuel",)))


def make_world():
    """Build a fresh opulse.world/2 declaration from the interpreter's primitives."""
    original = interp.make_library()
    base = original.world
    given = {atom.name: _NAMED_GIVENS.get(atom.name, atom.fn) for atom in original.atoms}
    extra = (
        OperationSpec("result_a", "transform", (Edge("result"),), Edge("int"),
                      "Return the accumulator of ok, else Bottom(no_result)", ("invalid", "no_result"),
                      host_rule(result_a), cost=0),
        OperationSpec("fail_mismatch", "transform", (), Edge("int"),
                      "Return Bottom(mismatch)", ("mismatch",), host_rule(fail_mismatch), cost=0),
        OperationSpec("run_prog", "transform", (Edge("prog"), Edge("list"), Edge("int")),
                      Edge("result"), "Run vn/1; charge exactly the executed machine instructions",
                      ("invalid",), host_rule(_run_prog), cost=0),
    )
    return replace(base, world="compiler",
                   combinators={**base.combinators, "recursion": "fuel"},
                   operations=tuple(replace(op, impl=host_rule(given[op.name]))
                                    for op in base.operations) + extra + code_world.operations(),
                   objects=base.objects + (code_world.code_object(),
                                           ObjectSpec("prog", "compose", tags={"prog": [
                                               ["n", "int"], ["code", "list"],
                                               ["args", "list"], ["out", "str"]]})),
                   extra={"tags": TAGS}, open_kinds=tuple(TAGS["open_kinds"]))


def declaration():
    """Build a fresh declaration (atoms-meta section 8)."""
    return make_world()


def make_library():
    """Build the shared interpreter library against this world's fixed hash."""
    original = interp.make_library()
    world = make_world()
    machine_atoms = tuple(replace(atom, fn=_NAMED_GIVENS[atom.name])
                          if atom.name in _NAMED_GIVENS else atom for atom in original.atoms) + (
        kernel.Atom("result_a", 1, result_a, cost=0),
        kernel.Atom("fail_mismatch", 0, fail_mismatch, cost=0),
        kernel.Atom("run_prog", 3, _run_prog, cost=0, metered=True))
    library = code_world.MeteredLibrary(world, machine_atoms + code_world.atoms(machine_atoms, world))
    for name, sample in (("fetch", (lst((0,) * 16), 0)),
                         ("exec_one", (lst((0,) * 16), 0, 0, 1)),
                         ("vn_interp", (lst((0,) * 16), 0, 0, 2))):
        library.write(replace(original.get(name), status="written"))
        library.check(name)
        library.make_callable(name, (sample,))
    return library


def machine_scope(library):
    """Expose the given metered atom to opulse.meta.engine.call."""
    return library.scope()
