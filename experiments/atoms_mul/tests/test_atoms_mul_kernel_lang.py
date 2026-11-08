import pytest
from atoms_mul.kernel import (
    AmlSyntaxError,
    Call,
    Def,
    If,
    Let,
    Lit,
    Var,
    format_def,
    node_from_json,
    parse_program,
    size,
)


@pytest.mark.parametrize("source,body", [
    ("op solve() -> Nat = 123", Lit(123)),
    ("op solve(x: Nat) -> Nat = x", Var("x")),
    ("op solve(x: Nat) -> Nat = add(x, 3)", Call("add", (Var("x"), Lit(3)))),
    ("op solve() -> Nat = zero()", Call("zero", ())),
    ("op solve(x: Nat) -> Nat = let y = succ(x) in y", Let("y", Call("succ", (Var("x"),)), Var("y"))),
    ("op solve(x: Nat) -> Nat = if is_zero(x) then (0) else pred(x)",
     If(Call("is_zero", (Var("x"),)), Lit(0), Call("pred", (Var("x"),)))),
])
def test_forms(source, body):
    program = parse_program(source + "\nsave solve # example")
    assert program.defs[0].body == body
    assert program.saves == ("solve",)
    assert node_from_json(program.to_json()) == program
    assert parse_program(format_def(program.defs[0])).defs == program.defs


@pytest.mark.parametrize("source,line,col", [
    ("op x() -> Nat = @", 1, 17),
    ("op x() -> Nat =\n?", 2, 1),
    ("op if() -> Nat = 0", 1, 4),
    ("op x(a: Nat,) -> Nat = a", 1, 13),
    ("op x() -> Nat = if a then 0", 1, 28),
    ("save", 1, 5),
    ("hello", 1, 1),
    ("op x() -> Nat = add(1,)", 1, 23),
])
def test_error_position(source, line, col):
    with pytest.raises(AmlSyntaxError) as error:
        parse_program(source)
    assert (error.value.line, error.value.col) == (line, col)
    assert error.value.message


def test_format_and_size():
    samples = [
        "op solve(a: Nat, b: Nat) -> Nat = if eq(a, 0) then b else let temp = add(a, b) in temp",
        "op solve(x: Nat) -> Nat = if is_zero(x) then 0 else solve(pred(x))",
        "op helper() -> Nat = add(1, 2)",
        "op solve(x: Nat) -> Nat = let v = x in if is_zero(v) then 3 else add(v, v)",
    ]
    for condition in ("is_zero(x)", "eq(x, 2)"):
        for branch in ("x", "succ(x)", "let y = pred(x) in add(y, x)"):
            samples.append(f"op solve(x: Nat) -> Nat = if {condition} then {branch} else 1")
    for source in samples:
        definition = parse_program(source).defs[0]
        assert parse_program(format_def(definition)).defs[0] == definition
    assert size(Def("x", (), Lit(0))) == 2
    assert size(Def("x", ("a", "b"), Call("add", (Var("a"), Var("b"))))) == 6
    assert size(parse_program(samples[0]).defs[0]) == 13


def test_aml_printer_keeps_canonical_unsuffixed_output():
    source = "op MUL(a: Nat, b: Bool) -> Nat = if b then a else 0"
    definition = parse_program(source).defs[0]
    assert format_def(definition) == source
    assert parse_program(format_def(definition)).defs == (definition,)
