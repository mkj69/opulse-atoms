import json
from pathlib import Path

from atoms_mul.kernel import Library, load_world, parse_program, write_worlds


def test_library_layers_listing_round_trip():
    program = parse_program("op first(x: Nat) -> Nat = succ(x) op second(x: Nat) -> Nat = add(first(x), first(x))")
    library = Library()
    first, second = library.add_from_program(program, ["first", "second"], "task-one")
    assert first.layer == 1 and first.depends_on == ("succ",)
    assert second.layer == 2 and second.depends_on == ("add", "first")
    assert second.cost == {"size": 7, "length": 5} and second.created_task == "task-one"
    assert library.names() == ["first", "second"]
    assert parse_program(library.listing()).defs == program.defs
    assert Library.from_json(json.loads(json.dumps(library.to_json()))).to_json() == library.to_json()
    third = parse_program("op third(x: Nat) -> Nat = second(x)")
    assert library.add_from_program(third, ["third"], "task-two")[0].layer == 3


def test_mutually_recursive_definitions_share_a_layer():
    library = Library()
    program = parse_program("op left(x: Nat) -> Nat = right(x) op right(x: Nat) -> Nat = left(x)")
    added = library.add_from_program(program, ["left", "right"], "task")
    assert [definition.layer for definition in added] == [1, 1]


def test_world_declarations_match_generator(tmp_path):
    write_worlds(tmp_path)
    root = Path(__file__).resolve().parents[1] / "worlds"
    for group in "ABC":
        assert (root / f"{group}.json").read_bytes() == (tmp_path / f"{group}.json").read_bytes()
        assert json.loads((root / f"{group}.json").read_text()) == load_world(group).to_json()
