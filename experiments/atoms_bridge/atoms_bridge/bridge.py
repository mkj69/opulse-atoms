"""Core-verified partial bridges and the scripted integer library state."""

from dataclasses import replace
from functools import lru_cache

from atoms_mul.kernel import Library as IntegerSavings
from atoms_mul.kernel import parse_program as parse_integer
from atoms_mul.kernel.core_library import CoreMirror
from atoms_mul.kernel.ops import add as integer_add
from atoms_mul.kernel.ops import nat_valid
from atoms_mul.machine.core_library import load_decl

from opulse.atoms import kernel, nodes
from opulse.atoms.bridges import bridge_defn
from opulse.atoms.library import Library, bounded, exhaustive
from opulse.atoms.spec import BridgeSpec, Contract, Definition, Edge, OperationSpec
from opulse.atoms.values import Bottom, Card, Ok
from opulse.worlds_v2.computer.kernel_scope import scope as machine_scope
from opulse.worlds_v2.computer.machine import byte_ok

INTEGER_MUL = ("op mul(a: Nat, b: Nat) -> Nat = "
               "if is_zero(b) then 0 else add(a, mul(a, pred(b)))\nsave mul")
MUL_DOMAIN = "a in 0..255, b in 0..20"


def mul_scope(first, second):
    """Admit only arguments covered by the saved source operation's evidence."""
    return type(first) is int and 0 <= first <= 255 and type(second) is int and 0 <= second <= 20


def wrap_byte(value):
    """Explicitly reduce the natural-number product before applying the partial bridge."""
    return value % 256 if type(value) is int and value >= 0 else Bottom("invalid")


def byte_add(left, right):
    """Verification-only interface witness, not an exposed MASM instruction."""
    if not all(isinstance(item, Card) and item.sort == "byte" and item.tag == "val"
               and len(item.fields) == 1 and type(item.fields[0]) is int
               and 0 <= item.fields[0] < 256 for item in (left, right)):
        return Bottom("invalid")
    return Card("byte", "val", ((left.fields[0] + right.fields[0]) % 256,))


def nat_add(left, right):
    """Expose the integer host's addition on refined cards for bridge verification."""
    if isinstance(left, Card) and isinstance(right, Card):
        if not all(item.sort == "nat" and item.tag == "val" and len(item.fields) == 1
                   and nat_valid(item.fields[0]) for item in (left, right)):
            return Bottom("invalid")
        result = integer_add(left.fields[0], right.fields[0])
        return Card("nat", "val", (result.value,)) if isinstance(result, Ok) else result
    return integer_add(left, right)


def _machine_library():
    declaration = load_decl("B")
    objects = tuple(replace(item, valid=nodes.Call("byte_valid", (nodes.Var("x"),)))
                    if item.name == "byte" else item for item in declaration.objects)
    witness = OperationSpec("byte_add", "combine", (Edge("byte"), Edge("byte")), Edge("byte"),
                            "Verification-only modular byte addition.")
    world = replace(declaration, objects=objects, operations=(*declaration.operations, witness),
                    open_kinds=("bridge", "operation"))
    return Library(world, (*machine_scope().atoms.values(), kernel.Atom("byte_add", 2, byte_add),
                           kernel.Atom("byte_valid", 1, byte_ok, cost=0)))


def _integer_library(group):
    mirror = CoreMirror("B" if group == "B" else "A")
    world = mirror.library.world
    objects = tuple(replace(item, valid=nodes.Call("nat_valid", (nodes.Var("x"),)))
                    if item.name == "nat" else item for item in world.objects)
    operations = tuple(replace(item, output=Edge("nat")) if item.name == "add" else item
                       for item in world.operations)
    mirror.library.world = replace(world, objects=objects, operations=operations,
                                   open_kinds=("operation", "bridge"))
    mirror.library.atoms = (*tuple(replace(atom, fn=nat_add) if atom.name == "add" else atom
                                   for atom in mirror.library.atoms),
                            kernel.Atom("nat_valid", 1, nat_valid, cost=0),
                            kernel.Atom("byte_domain", 1, byte_ok, cost=0))
    if group == "B":
        saved = IntegerSavings().add_from_program(parse_integer(INTEGER_MUL), ("mul",), "scripted_stage1")
        report = mirror.mirror([saved[0]])[0]
        if report["core_status"] != "callable":
            raise ValueError(f"scripted integer mul not verified: {report['problems']}")
        request = exhaustive((range(256), range(21)), MUL_DOMAIN)
        request = replace(request, reference=lambda first, second: first * second)
        mirror.library.verify("mul", request)
        mirror.library.account("mul")
        mirror.library.promote("mul", Contract(f"result = a * b for {MUL_DOMAIN}; no state",
                                               keeps=("full_state",)))
    return mirror.library


def _definition(spec):
    return Definition(spec.name, "bridge", "invented", 2,
                      tuple(sorted(nodes.references(bridge_defn(spec).body))), spec,
                      bridge_defn(spec).body)


def _install(library, spec, sample, domain, contract):
    library.write(_definition(spec))
    library.check(spec.name)
    library.make_callable(spec.name, sample)
    library.verify(spec.name, domain)
    library.account(spec.name)
    library.promote(spec.name, Contract(contract))


@lru_cache(maxsize=2)
def worlds(group):
    """Construct and verify independently metered bridges; G2 saves, G3 is given."""
    if group not in ("B", "C"):
        raise ValueError("a bridge is not available in G1")
    integer = _integer_library(group)
    machine = _machine_library()
    integer.attach_world("computer@1", machine)
    machine.attach_world(f"{integer.world.world}@{integer.world.version}", integer)
    base = nodes.Call("nat.base", (nodes.Var("x"),))
    byte = BridgeSpec("to_byte", "nat", "computer@1:byte",
                      nodes.Call("byte.make", (base,)),
                      nodes.Call("byte_domain", (base,)),
                      (("add", "byte_add"),))
    source_values = tuple(Card("nat", "val", (number,)) for number in range(256))
    request = bounded((source_values,), "bound <= 255")
    request.extra["pairs"] = tuple((source_values[left], source_values[right])
                                   for left in range(16) for right in range(16))
    _install(integer, byte, ((source_values[0],), (source_values[15],)), request,
             "add commutes for input pairs 0..15; partial on 0..255")
    nat = BridgeSpec("to_nat", "computer@1:byte",
                     f"{integer.world.world}@{integer.world.version}:nat",
                     nodes.Call("nat.make", (nodes.Call("byte.base", (nodes.Var("x"),)),)))
    sample = tuple((Card("byte", "val", (number,)),) for number in range(256))
    _install(machine, nat, sample[:2], bounded((tuple(item[0] for item in sample),), "bound <= 255"),
             "byte embeds in natural numbers for all 256 byte values")
    return integer, machine
