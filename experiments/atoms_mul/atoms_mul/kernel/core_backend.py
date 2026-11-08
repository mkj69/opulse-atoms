"""Run AML programs on the atoms-v2 reference kernel (``opulse.atoms.kernel``).

The experiment's own evaluator (``evaluate.py``) stays the grader until the core library
API lands. This backend compiles the same programs to core kernel nodes so that a test can
check that both give the same outcome and the same layer-0 step count. Learner recursion is
a definition calling itself by name, bounded by fuel only (spec atoms-v2/0.2,
``combinators.recursion: fuel``).
"""

from opulse.atoms import kernel as core
from opulse.atoms import nodes as cn
from opulse.atoms import values as cv

from .evaluate import Bottom, Ok, Unknown
from .nodes import Call, If, Let, Lit, Var, node_from_json


def compile_node(node):
    """AML syntax node -> core kernel node."""
    if isinstance(node, Var):
        return cn.Var(node.name)
    if isinstance(node, Lit):
        return cn.Lit(node.value)
    if isinstance(node, Call):
        return cn.Call(node.name, tuple(compile_node(arg) for arg in node.args))
    if isinstance(node, Let):
        return cn.Let(node.name, compile_node(node.bound), compile_node(node.body))
    if isinstance(node, If):
        return cn.Case(((cn.Test(compile_node(node.cond)), compile_node(node.then)),),
                       compile_node(node.other))
    raise TypeError(f"not an AML expression: {node!r}")


def _reference_operation(name, args):
    """Independent layer-0 oracle; the grader and declaration hosts use ops.py."""
    if any(type(value) is not int or value < 0 or value > 1_000_000_000 for value in args):
        return cv.Bottom(f"type: {name} expects natural numbers")
    if name == "is_zero":
        return cv.Ok(args[0] == 0)
    if name == "eq":
        return cv.Ok(args[0] == args[1])
    if name == "lt":
        return cv.Ok(args[0] < args[1])
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
        return cv.Bottom(f"no such name {name}")
    if value < 0:
        return cv.Bottom("negative")
    if value > 1_000_000_000:
        return cv.Bottom("overflow")
    return cv.Ok(value)


def _atom(spec):
    def fn(*args):
        return _reference_operation(spec.name, args)

    return core.Atom(spec.name, len(spec.inputs), fn, cost=spec.cost)


def scope_for(world, program=None, library=None):
    defns = []
    if library is not None:
        for name in library.names():
            entry = library.get(name)
            defns.append(core.Defn(name, tuple(entry.params), compile_node(node_from_json(entry.body)),
                                   layer=entry.layer))
    if program is not None:
        defns.extend(core.Defn(definition.name, tuple(definition.params),
                               compile_node(definition.body)) for definition in program.defs)
    return core.DictScope([_atom(spec) for spec in world.operations.values()], defns)


def core_evaluate(name, args, *, world, program=None, library=None, fuel=200_000, max_depth=2_000):
    """Outcome (the experiment's Ok/Bottom/Unknown classes) and layer-0 steps on the core kernel."""
    run = core.call(name, list(args), scope_for(world, program, library),
                    core.Limits(fuel=fuel, max_depth=max_depth))
    outcome = run.outcome
    if isinstance(outcome, cv.Ok):
        return Ok(outcome.value), run.steps
    if isinstance(outcome, cv.Bottom):
        return Bottom(outcome.reason), run.steps
    return Unknown(outcome.resource), run.steps
