import pytest
from atoms_mul.kernel import Library, check_program, load_world, parse_program


@pytest.mark.parametrize("source,fragment", [
    ("op solve(x: Nat) -> Nat = bad(x)", "unknown call target bad"),
    ("op solve(x: Nat) -> Nat = add(x)", "wrong arity for add"),
    ("op solve() -> Nat = 1 op solve() -> Nat = 2", "duplicate definition solve"),
    ("op add(x: Nat) -> Nat = x", "shadows an existing name"),
    ("op solve(x: Nat, x: Nat) -> Nat = x", "duplicate parameter x"),
    ("op solve(x: Nat) -> Nat = y", "unbound variable y"),
    ("op solve() -> Nat = 1 save missing", "cannot save unknown name missing"),
    ("op solve() -> Nat = 1 save solve", "cannot save solve"),
    ("op helper() -> Nat = 1 op solve() -> Nat = helper() save solve", "cannot save solve"),
    ("op helper() -> Nat = other() op other() -> Nat = 1 save helper", "calls unsaved definition other"),
])
def test_check_errors(source, fragment):
    assert any(fragment in message for message in check_program(parse_program(source), load_world("B"), Library()))


def test_existing_library_and_no_saves_in_c():
    library = Library()
    library.add_from_program(parse_program("op helper() -> Nat = 1"), ["helper"], "task")
    assert any("shadows" in message for message in check_program(parse_program("op helper() -> Nat = 2"), load_world("B"), library))
    assert any("already in the library" in message for message in check_program(parse_program("save helper"), load_world("B"), library))
    assert check_program(parse_program("op solve() -> Nat = helper()"), load_world("B"), library) == []
    assert "saving definitions is not available in this world" in check_program(parse_program("save missing"), load_world("C"), Library())


def test_closed_saves_and_mutual_recursion():
    program = parse_program("op first(x: Nat) -> Nat = second(x) op second(x: Nat) -> Nat = first(x) save first save second")
    assert check_program(program, load_world("B"), Library()) == []
