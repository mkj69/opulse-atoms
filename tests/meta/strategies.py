"""Bounded Hypothesis inputs for atoms-meta section 9 over the gen_code world."""

import random

from hypothesis import strategies as st

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.boundary import Boundary
from opulse.atoms.observations import judge
from opulse.atoms.values import Card
from opulse.meta import code
from opulse.meta import gen_code as G
from opulse.meta.vn import machine, reference
from opulse.meta.vn.report import report

small_ints = st.integers(-3, 3)
arguments = st.tuples(st.integers(0, 4))


def resolve(dependencies=()):
    by_name = dict(dependencies)
    return lambda name: (code.Resolved(code=by_name[name]) if name in by_name else
                         code.Resolved(digest=G.DIGESTS[name]) if name in G.DIGESTS else None)


@st.composite
def expressions(draw, depth=2, variable="input"):
    """Well-scoped trees including shadowed Let, boolean Case, fuel Rec and jumping Blocks."""
    leaf = draw(st.one_of(st.just(n.Var(variable)), small_ints.map(n.Lit)))
    if depth == 0:
        return leaf
    kind = draw(st.sampled_from(("leaf", "call", "let", "case", "rec", "blocks")))
    if kind == "leaf":
        return leaf
    if kind == "call":
        operand = draw(expressions(depth - 1, variable))
        return n.Call(draw(st.sampled_from(("add", "sub", "mul", "div"))),
                      (operand, n.Lit(draw(small_ints))))
    if kind == "let":
        name = draw(st.sampled_from(("input", "local")))
        value = draw(expressions(depth - 1, variable))
        return n.Let(name, value, draw(expressions(depth - 1, name)))
    if kind == "case":
        test = n.Test(n.Call("is_zero", (n.Var(variable),)))
        cond = draw(st.sampled_from((test, n.Not(test), n.And(test, n.Always()),
                                     n.Or(test, n.Not(test)))))
        return n.Case(((cond, draw(expressions(depth - 1, variable))),),
                      draw(expressions(depth - 1, variable)))
    if kind == "rec":
        counter = draw(st.integers(0, 3))
        body = n.Case(((n.Test(n.Call("is_zero", (n.Var("counter"),))), n.Var("acc")),),
                      n.Call("loop", (n.Call("sub", (n.Var("counter"), n.Lit(1))),
                                      n.Call("add", (n.Var("acc"), n.Lit(1))))))
        return n.Rec("loop", ("counter", "acc"), body, (n.Lit(counter), leaf), "fuel")
    return n.Blocks((("acc", leaf),), "start", (
        ("start", n.Block((), n.Jump("finish"))),
        ("finish", n.Block((("acc", n.Call("add", (n.Var("acc"), n.Lit(1)))),),
                           n.Halt(n.Var("acc"))))))


@st.composite
def definitions(draw, allow_nested_run=True):
    """Canonical code with an optional hashed, transitive invented dependency."""
    metered = draw(st.sampled_from(("literal", "eval", "run") if allow_nested_run else
                                   ("literal", "eval")))
    marker = n.Lit(draw(small_ints))
    if metered != "literal":
        nested = code.make_code("operation", G.SIG, ("item",),
                                n.Call("add", (n.Var("item"), n.Lit(draw(small_ints)))), resolve())
        marker = n.Call(metered, (n.Lit(nested), n.Lit(code.lst((draw(arguments)[0],)))) +
                        ((n.Lit(draw(st.integers(0, 5))),) if metered == "run" else ()))
    body = n.Let("marker", marker, draw(expressions()))
    if draw(st.booleans()):
        constant = draw(small_ints)
        dependency = code.make_code("operation", G.SIG, ("arg",),
                                    n.Call("add", (n.Var("arg"), n.Lit(constant))), resolve())
        name = "helper"
        body = n.Call(name, (body,))
        resolver = resolve(((name, dependency),))
    else:
        resolver = resolve()
    return code.make_code("operation", G.SIG, ("input",), body, resolver)


@st.composite
def generated_codes(draw):
    seed = draw(st.integers(0, 2**32 - 1))
    depth = draw(st.integers(0, 2))
    return G.random_code(random.Random(seed), depth)


@st.composite
def code_argument_cases(draw):
    """Metered eval/run consume a code parameter, also through nested metered calls."""
    nested = draw(generated_codes())
    if nested.fields[1] != G.SIG:
        nested = code.make_code("operation", G.SIG, ("item",),
                                n.Call("add", (n.Var("item"), n.Lit(draw(small_ints)))), resolve())
    argument = draw(st.integers(0, 4))
    operation = draw(st.sampled_from(("eval", "run")))
    nested_call = n.Call(operation, (n.Var("program"), n.Lit(code.lst((argument,)))) +
                         ((n.Lit(draw(st.integers(0, 8))),) if operation == "run" else ()))
    signature = code.sig_op((("code", "bottom"),),
                            ("result" if operation == "run" else "int", "bottom"))
    program = code.make_code("operation", signature, ("program",), nested_call, resolve())
    return program, (nested,)


@st.composite
def edits(draw, program=None):
    """Select one integer literal (including one within a dependency) and replace it."""
    if program is None:
        program = draw(definitions())

    def paths(value, prefix=()):
        if not isinstance(value, Card):
            return
        if value.sort == "expr" and value.tag == "lit" and type(value.fields[0]) is int:
            yield prefix + (0,), value.fields[0]
        for index, field in enumerate(value.fields):
            yield from paths(field, prefix + (index,))

    candidates = tuple(paths(program.fields[2], (2,)))
    if not candidates:
        return program, None
    path, original = draw(st.sampled_from(candidates))
    return program, (path, original + draw(st.sampled_from((-1, 1))))


boundaries = st.builds(Boundary,
    depth=st.one_of(st.none(), st.integers(0, 3)),
    open_names=st.frozensets(st.sampled_from(("eval", "run", "add", "r0"))),
    keep_names=st.frozensets(st.sampled_from(("eval", "run", "add", "r0"))),
    open_paths=st.frozensets(st.tuples(st.integers(0, 2)), max_size=2),
    kinds=st.frozensets(st.sampled_from(("object", "operation", "combinator", "observation"))))


@st.composite
def vn_states(draw):
    size = draw(st.sampled_from((16, 32)))
    memory = draw(st.lists(st.integers(0, 255), min_size=size, max_size=size))
    pc = draw(st.integers(0, size - 1))
    memory[pc] = draw(st.one_of(st.integers(0, 8), st.integers(9, 255)))
    if memory[pc] == 3:
        memory[(pc + 1) % size] = draw(st.one_of(st.just(pc), st.just((pc + 1) % size),
                                                st.integers(0, 255)))
    return reference.State(pc, draw(st.integers(0, 255)), tuple(memory), draw(st.booleans()))


def vn_self_modifying_grade(state, fuel, probes, answer):
    """Observe only granted probes; grade the Decide answer from the full run (meta 4.3, 9.I3)."""
    card = machine.to_card(state)
    scope = kernel.DictScope(machine.atoms(len(state.mem)))
    view = tuple((name, kernel.call(name, (card, 1) if name == "cell" else (card,), scope))
                 for name in probes)
    return view, judge("full_state", report(state, fuel).self_modifying, answer)
