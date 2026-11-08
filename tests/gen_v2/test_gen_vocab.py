from opulse.gen_v2 import vocab
from opulse.gen_v2.base import GenState
from opulse.gen_v2.library import GenLibrary
from opulse.gen_v2.worlds import classic, toy


def _state(world):
    return GenState(world, GenLibrary(world.decl, world.atoms, world.dialect), dict(world.sorts))


def test_roles_are_found_by_behaviour_not_by_name():
    state = _state(toy.gen_world())
    assert vocab.less(state, "int") == ["lt"]
    assert vocab.equal(state, "int") == ["eq"]
    assert vocab.zero_test(state, "int") == ["is_zero"]
    assert set(vocab.deciders(state, "int")) == {"is_zero", "is_pos"}
    assert "absv" in vocab.int_measures(state, "int") and "neg" not in vocab.int_measures(state, "int")
    assert "add" in vocab.combiners(state, "int")


def test_roles_in_a_classic_world():
    state = _state(classic.gen_world("integer"))
    assert vocab.combiners(state, "int")
    assert vocab.steps(state, "int")
