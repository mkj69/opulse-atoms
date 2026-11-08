"""The larger public DFA vocabulary is real, not a small-word sample."""

import importlib.util
from pathlib import Path

from opulse.atoms.kernel import FnRef
from opulse.atoms.values import Bottom, Ok, boolean
from opulse.worlds_v2.automata import hosts
from opulse.worlds_v2.automata.world import new_library


def reference():
    path = Path(__file__).resolve().parents[3] / "worlds/catalogue/depth/automata.py"
    spec = importlib.util.spec_from_file_location("automata_depth_reference", path)
    module = importlib.util.module_from_spec(spec)
    import sys
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_full_depth_inputs_and_generic_fold():
    oracle = reference()
    library = new_library()
    fixtures = hosts.depth_examples()
    for name, machine in fixtures.items():
        expected = getattr(oracle, name)
        assert hosts.from_card(machine) == (len(expected.transitions), expected.initial,
                                          tuple(sorted(expected.finals)), expected.transitions)
        assert library.run("size", (machine,)).outcome == Ok(len(expected.transitions))
        for word in ("", "a", "b", "bb", "aabababababa", "a" * 70):
            answer = library.run("fold", (FnRef("step"), machine, hosts.start(machine), word))
            assert answer.outcome == Ok(oracle.fold(lambda state, char, expected=expected: oracle.step(expected, state, char),
                                                    expected.initial, word))
            assert library.run("accept", (machine, word)).outcome == Ok(boolean(oracle.accept(expected, word)))
    assert hosts.count_a(7).fields == fixtures["mod7_a"].fields[3].fields
    assert hosts.count_b(5).fields == fixtures["mod5_b"].fields[3].fields
    assert hosts.distinct_count(hosts.to_card(1, 0, (), ((0, 0),)).fields[2]) == 0
    assert library.run("step", (fixtures["mod35_a"], 35, "a")).outcome == Bottom("invalid")
    assert library.run("step", ([], 0, "a")).outcome == Bottom("invalid")
    assert library.run("fold", (FnRef("step"), fixtures["mod7_a"], 0, "c")).outcome == Bottom("measure")


def test_realistic_product_capacity():
    oracle = reference()
    product = oracle.combine(oracle.mod7_a, oracle.mod5_a, "and")
    from_card = hosts.to_card(len(product.transitions), product.initial, sorted(product.finals),
                              product.transitions)
    assert hosts.count(from_card) == 35
    assert hosts.machine_valid(from_card)
    assert hosts.count(hosts.to_card(105, 0, (), ((0, 0),) * 105)) == 105
