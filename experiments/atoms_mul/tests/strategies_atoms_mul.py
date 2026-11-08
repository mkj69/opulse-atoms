"""Typed, bounded syntax-tree generators for both experiment languages."""

from functools import lru_cache

from atoms_mul.kernel.nodes import Call, Def, If, Let, Lit, Program, Var
from atoms_mul.machine.lang import Instruction, Sub
from atoms_mul.machine.lang import Program as MachineProgram
from hypothesis import strategies as st


@lru_cache
def nat_expressions(names, variables=("a", "b"), *, mul=False):
    """Generate Nat terms; only previously declared definitions may be called."""
    leaf = st.one_of(st.sampled_from(tuple(variables)).map(Var),
                     st.integers(0, 20).map(Lit))

    def extend(children):
        choices = [st.tuples(st.sampled_from(("add", "sub")), children, children)
                   .map(lambda parts: Call(parts[0], parts[1:])),
                   st.tuples(st.sampled_from(("succ", "pred")), children)
                   .map(lambda parts: Call(parts[0], (parts[1],))),
                   st.tuples(children, st.one_of(children, st.just(Var("tmp"))))
                   .map(lambda parts: Let("tmp", parts[0], parts[1])),
                   st.tuples(bool_expressions(children), children, children)
                   .map(lambda parts: If(*parts))]
        if names:
            choices.append(st.tuples(st.sampled_from(tuple(names)), children, children)
                           .map(lambda parts: Call(parts[0], parts[1:])))
        if mul:
            choices.append(st.tuples(children, children).map(lambda parts: Call("mul", parts)))
        return st.one_of(*choices)

    return st.recursive(leaf, extend, max_leaves=5)


def bool_expressions(nat_terms):
    """Generate Boolean world-operation results from Nat operands."""
    return st.one_of(st.tuples(nat_terms).map(lambda parts: Call("is_zero", parts)),
                     st.tuples(st.sampled_from(("eq", "lt")), nat_terms, nat_terms)
                     .map(lambda parts: Call(parts[0], parts[1:])))


@st.composite
def aml_cases(draw):
    """Build one to four typed definitions, with optional decreasing recursion."""
    count = draw(st.integers(1, 4))
    mul = draw(st.booleans())
    definitions = []
    for index in range(count):
        name = "solve" if index == count - 1 else f"helper{index}"
        earlier = tuple(definition.name for definition in definitions)
        body = draw(nat_expressions(earlier, mul=mul))
        if draw(st.booleans()):
            base = draw(nat_expressions(earlier, mul=mul))
            tail = draw(nat_expressions(earlier, mul=mul))
            body = If(Call("is_zero", (Var("a"),)), base,
                      Call(name, (Call("pred", (Var("a"),)), tail)))
        definitions.append(Def(name, ("a", "b"), body))
    mask = draw(st.integers(0, (1 << (count - 1)) - 1))
    saved = {definition.name for index, definition in enumerate(definitions[:-1])
             if mask & (1 << index)}
    from atoms_mul.kernel.check import calls

    for definition in reversed(definitions[:-1]):
        if definition.name in saved:
            saved.update(set(calls(definition.body)) & {item.name for item in definitions[:-1]})
    return Program(tuple(definitions), ()), tuple(definition.name for definition in definitions[:-1]
                                             if definition.name in saved), "A" if mul else "B"


@st.composite
def machine_cases(draw):
    """Construct checked straight-line/finite countdown MASM control-flow graphs."""
    count = draw(st.integers(1, 3))
    group = draw(st.sampled_from(("A", "B", "C")))
    definitions = []
    registers = ("r0", "r1", "r2", "r3")
    for index in range(count):
        name = "main" if index == count - 1 else f"helper{index}"
        lines = []
        for _ in range(draw(st.integers(0, 3))):
            op = draw(st.sampled_from(("set", "add", "dec", "load", "store", "call")))
            if op == "call" and not definitions:
                op = "dec"
            if op == "call":
                args = (draw(st.sampled_from(tuple(sub.name for sub in definitions))),)
            elif op in ("set", "load", "store"):
                args = (draw(st.sampled_from(registers)), str(draw(st.integers(0, 255))))
            elif op == "add":
                args = (draw(st.sampled_from(registers)), draw(st.sampled_from(registers)))
            else:
                args = (draw(st.sampled_from(registers)),)
            lines.append(Instruction(op, args))
        if draw(st.booleans()):
            counter = draw(st.sampled_from(registers))
            lines.extend((Instruction("set", (counter, str(draw(st.integers(0, 4))))),
                          Instruction("label", ("again",)),
                          Instruction("jz", (counter, "done")),
                          Instruction("dec", (counter,)),
                          Instruction("jnz", (counter, "again")),
                          Instruction("label", ("done",))))
        if draw(st.booleans()):
            lines.extend((Instruction("jmp", ("exit",)),
                          Instruction("label", ("exit",))))
        lines.append(Instruction("halt"))
        definitions.append(Sub(name, tuple(lines)))
    mask = draw(st.integers(0, (1 << (count - 1)) - 1))
    saved = {sub.name for index, sub in enumerate(definitions[:-1]) if mask & (1 << index)}
    from atoms_mul.machine.check import calls

    for sub in reversed(definitions[:-1]):
        if sub.name in saved:
            saved.update(calls(sub))
    names = tuple(sub.name for sub in definitions[:-1] if sub.name in saved)
    return MachineProgram(tuple(definitions), ()), names, group
