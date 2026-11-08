"""Given card primitives and metered world dispatch (atoms-meta section 6)."""

from functools import lru_cache

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.values import Bottom, Unknown, boolean, value_equal
from opulse.meta import cards, code, code_world, engine
from opulse.meta.builder import world_value
from opulse.meta.builder.instantiate import WorldError, instantiate
from opulse.meta.builder.wf import wf as check_world
from opulse.meta.engine import MeteredAtom

tag_of = cards.tag_of
field = cards.field
with_field = code_world.with_field
mk = code_world.mk
list_len = cards.list_len
list_get = cards.list_get
list_append = cards.list_append
list_concat = cards.list_concat
str_eq = cards.str_eq


def eq(left, right):
    return boolean(value_equal(left, right))


def int_add(left, right):
    return left + right if type(left) is int and type(right) is int else Bottom("int")


def int_sub(left, right):
    return left - right if type(left) is int and type(right) is int else Bottom("int")


def int_eq(left, right):
    return boolean(type(left) is int and type(right) is int and left == right)


def int_lt(left, right):
    return boolean(type(left) is int and type(right) is int and left < right)


def int_mul(left, right):
    return left * right if type(left) is int and type(right) is int else Bottom("int")


def int_div(left, right):
    return left // right if type(left) is int and type(right) is int and right > 0 else Bottom("int")


def int_mod(left, right):
    return left % right if type(left) is int and type(right) is int and right > 0 else Bottom("int")


def int_text(value):
    return str(value) if type(value) is int else Bottom("int")


def str_concat(left, right):
    return left + right if isinstance(left, str) and isinstance(right, str) else Bottom("str")


def str_len(value):
    return len(value) if isinstance(value, str) else Bottom("str")


def list_index(values, value):
    try:
        return code.items(values).index(value)
    except (ValueError, TypeError):
        return Bottom("index")


def list_contains(values, value):
    try:
        return boolean(value in code.items(values))
    except (ValueError, TypeError):
        return Bottom("list")


def domain_values(value, name):
    """Enumerate a finite sort in declaration order."""
    from opulse.meta.builder.instantiate import domain

    try:
        sorts = {entry.fields[0]: entry for entry in code.items(value.fields[2])}
        values = domain(name, sorts)
        return code.lst(values) if values is not None else Bottom("infinite_sort")
    except (ValueError, TypeError, KeyError, IndexError, AttributeError):
        return Bottom("sort")


def size(value):
    return cards.size(value, 0)


def wf(value):
    return check_world(value)


def world_hash(value):
    try:
        return world_value.world_hash(value)
    except (ValueError, TypeError, IndexError, KeyError):
        return Bottom("world")


@lru_cache(maxsize=32)
def _instantiated(value):
    return instantiate(value)


def call_in(ctx, value, op_name, xs):
    """One dispatch step plus child layer-0 steps in the same meter and trace."""
    try:
        declaration, entries = _instantiated(value)
        args = code.items(xs)
    except (WorldError, ValueError, TypeError, KeyError, IndexError):
        return Bottom("world")
    if not isinstance(op_name, str) or not any(op.name == op_name for op in declaration.operations):
        return Bottom("operation")
    charged = ctx.engine.charge(1)
    if isinstance(charged, Unknown):
        return charged
    atoms = tuple(entry for entry in entries if isinstance(entry, kernel.Atom))
    defns = tuple(entry for entry in entries if isinstance(entry, kernel.Defn))
    previous = ctx.engine.scope
    ctx.engine.scope = kernel.DictScope(atoms, defns)
    try:
        return ctx.call(kernel.Defn("_builder_dispatch", (),
                                   n.Call(op_name, tuple(n.Lit(arg) for arg in args))), ())
    finally:
        ctx.engine.scope = previous


RULES = {
    "tag_of": (tag_of, 1), "field": (field, 2), "with_field": (with_field, 3),
    "mk": (mk, 3), "list_len": (list_len, 1), "list_get": (list_get, 2),
    "list_append": (list_append, 2), "list_concat": (list_concat, 2),
    "str_eq": (str_eq, 2), "eq": (eq, 2), "int_add": (int_add, 2), "int_sub": (int_sub, 2),
    "int_eq": (int_eq, 2), "int_lt": (int_lt, 2),
    "int_mul": (int_mul, 2), "int_div": (int_div, 2), "int_mod": (int_mod, 2),
    "int_text": (int_text, 1), "str_concat": (str_concat, 2), "str_len": (str_len, 1),
    "list_index": (list_index, 2), "list_contains": (list_contains, 2),
    "domain_values": (domain_values, 2),
    "size": (size, 1),
    "wf": (wf, 1), "world_hash": (world_hash, 1),
}


@lru_cache(maxsize=1)
def atoms():
    # engine is imported at module level: a local import would put the module object into the
    # closure of evaluate_builder, and the core atom digest would then include its file path.
    from .story import z5
    from .world import declaration

    given = tuple(kernel.Atom(name, arity, rule) for name, (rule, arity) in RULES.items())
    dispatch = MeteredAtom("call_in", 3, call_in)
    built_atoms = tuple(entry for entry in _instantiated(z5())[1]
                        if isinstance(entry, kernel.Atom) and entry.name in ("add5", "mul5"))
    world_atoms = engine._WorldAtoms((*given, dispatch, *built_atoms))
    meta_atoms = list(code_world.atoms(world_atoms, declaration()))
    current = declaration()
    digests = {operation.name: code.atom_digest(operation) for operation in current.operations}
    opened = tuple(sorted(current.opened_nodes()))

    def evaluate_builder(ctx, value, xs):
        prepared = engine._prepare(value, xs, digests, ctx.engine.scope, opened, world_atoms, True)
        if isinstance(prepared, Bottom):
            return prepared
        decoded, arguments, inner_scope = prepared
        converted = list(arguments)
        dependencies = list(decoded.deps)
        for index, arg in enumerate(arguments):
            if not isinstance(arg, code.Card) or arg.sort != "code" or decoded.kind != "operation":
                continue
            try:
                signature = code.items(decoded.sig.fields[0])
                if signature[index].fields[0] != "code":
                    continue
                callback_arity = len(code.items(arg.fields[1].fields[0]))
            except (code.CodeError, ValueError, TypeError, AttributeError, IndexError):
                return Bottom("ill_formed")
            checked = engine._prepare(arg, code.lst((0,) * callback_arity), digests,
                                      ctx.engine.scope, opened, world_atoms, True)
            if isinstance(checked, Bottom):
                return checked
            callback, _, _ = checked
            if callback.kind != "operation":
                return Bottom("ill_formed")
            converted[index] = kernel.FnRef(callback.main.name)
            dependencies.extend((callback.main, *callback.deps))
        previous = ctx.engine.scope
        ctx.engine.scope = inner_scope
        try:
            return ctx.call(decoded.main, tuple(converted), tuple(dependencies))
        finally:
            ctx.engine.scope = previous

    meta_atoms[1] = engine.MeteredAtom("eval", 2, evaluate_builder)
    return [*world_atoms, *meta_atoms]
