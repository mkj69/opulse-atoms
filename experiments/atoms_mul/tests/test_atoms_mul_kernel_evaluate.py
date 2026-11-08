import pytest
from atoms_mul.kernel import (
    Bottom,
    Library,
    Ok,
    Unknown,
    check_program,
    constant_multiplier,
    evaluate,
    is_mul_equivalent,
    load_world,
    parse_program,
)


@pytest.mark.parametrize("operation,args,expected", [
    ("add", (2, 3), Ok(5)), ("sub", (3, 2), Ok(1)),
    ("succ", (3,), Ok(4)), ("pred", (3,), Ok(2)),
    ("is_zero", (0,), Ok(True)), ("eq", (2, 2), Ok(True)),
    ("lt", (2, 3), Ok(True)), ("mul", (2, 3), Ok(6)),
    ("add", (10**9, 1), Bottom("overflow")),
    ("sub", (0, 1), Bottom("negative")),
    ("succ", (10**9,), Bottom("overflow")),
    ("pred", (0,), Bottom("negative")),
])
def test_operations(operation, args, expected):
    run = evaluate(operation, args, world=load_world("A"))
    assert run.outcome == expected
    assert run.steps == run.boundary_steps == 1


def test_types_names_and_short_circuit():
    world = load_world("B")
    assert evaluate("add", (True, 2), world=world).outcome == Bottom("type: add expects natural numbers")
    assert evaluate("add", (2,), world=world).outcome == Bottom("wrong arity for add")
    assert evaluate("mul", (2, 3), world=world).outcome == Bottom("no such name mul")
    assert evaluate("solve", (), world=world, program=parse_program("op solve() -> Nat = if is_zero(0) then 7 else pred(0)")).outcome == Ok(7)
    for expr, expected in [
        ("if 0 then 1 else 2", Bottom("type: condition is not a bool")),
        ("if is_zero(pred(0)) then 1 else 2", Bottom("nan_condition")),
        ("if loop() then 1 else 2", Unknown("depth")),
    ]:
        program = parse_program(f"op solve() -> Nat = {expr} op loop() -> Nat = loop()")
        assert evaluate("solve", (), world=world, program=program, max_depth=15).outcome == expected


def test_depth_fuel_and_large_recursive_product():
    world = load_world("B")
    program = parse_program("op product(a: Nat, b: Nat) -> Nat = if is_zero(b) then 0 else add(a, product(a, pred(b)))")
    assert check_program(program, world, Library()) == []
    assert evaluate("product", (7, 1000), world=world, program=program).outcome == Ok(7000)
    assert evaluate("product", (7, 1000), world=world, program=program, max_depth=40).outcome == Unknown("depth")
    assert evaluate("product", (7, 1000), world=world, program=program, fuel=10).outcome == Unknown("fuel")
    assert evaluate("product", (7, 1000), world=world, program=program, fuel=10).steps == 10


def test_boundaries_preserve_failures_and_resource_limits():
    program = parse_program("op fail(x: Nat) -> Nat = pred(x) op solve(x: Nat) -> Nat = fail(x)")
    world = load_world("B")
    for fuel, depth, expected in ((20, 20, Bottom("negative")),
                                  (0, 20, Unknown("fuel")),
                                  (20, 1, Unknown("depth"))):
        for boundary in (frozenset(), frozenset({"fail"}), frozenset({"solve"}),
                         frozenset({"fail", "solve"})):
            run = evaluate("solve", (0,), world=world, program=program, fuel=fuel,
                           max_depth=depth, boundary=boundary)
            assert run.outcome == expected


def test_boundary_library_equivalence_and_determinism():
    world = load_world("B")
    source = "op helper(x: Nat) -> Nat = add(x, succ(x)) op solve(x: Nat) -> Nat = if is_zero(x) then 0 else helper(x)"
    program = parse_program(source)
    library = Library()
    library.add_from_program(program, ["helper"], "task")
    local = program
    pasted = parse_program("op solve(x: Nat) -> Nat = if is_zero(x) then 0 else helper(x)")
    for value in (0, 1, 13):
        original = evaluate("solve", (value,), world=world, program=local)
        saved = evaluate("solve", (value,), world=world, program=pasted, library=library)
        assert (original.outcome, original.steps) == (saved.outcome, saved.steps)
        for boundary in (frozenset(), frozenset({"helper"}), frozenset({"solve"}), frozenset({"helper", "solve"})):
            run = evaluate("solve", (value,), world=world, program=pasted, library=library, boundary=boundary)
            assert (run.outcome, run.steps, run.calls) == (saved.outcome, saved.steps, saved.calls)
            assert run == evaluate("solve", (value,), world=world, program=pasted, library=library, boundary=boundary)
        if value:
            assert evaluate("solve", (value,), world=world, program=pasted, library=library,
                            boundary=frozenset({"helper"})).boundary_steps == 2


def test_equivalence():
    world = load_world("B")
    recursive = parse_program("op product(a: Nat, b: Nat) -> Nat = if is_zero(b) then 0 else add(a, product(a, pred(b)))")
    assert is_mul_equivalent("product", world=world, program=recursive)["equivalent"]
    wrapped = parse_program("op product(a: Nat, b: Nat) -> Nat = mul(a, b)")
    assert is_mul_equivalent("product", world=load_world("A"), program=wrapped)["equivalent"]
    for source in (
        "op product(a: Nat, b: Nat) -> Nat = succ(mul(a, b))",
        "op product(a: Nat, b: Nat) -> Nat = product(a, b)",
        "op product(a: Nat, b: Nat) -> Nat = sub(a, b)",
    ):
        result = is_mul_equivalent("product", world=load_world("A"), program=parse_program(source))
        assert result["equivalent"] is False and result["counterexample"] is not None
    assert constant_multiplier("triple", world=world,
                               program=parse_program("op triple(x: Nat) -> Nat = add(x, add(x, x))")) == 3
    assert constant_multiplier("single", world=world,
                               program=parse_program("op single(x: Nat) -> Nat = x")) is None
