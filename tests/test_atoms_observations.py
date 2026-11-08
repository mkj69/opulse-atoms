"""Sealed robot observations (spec sections 7 and 11.I3)."""

from dataclasses import replace
from types import SimpleNamespace

from hypothesis import given, settings
from hypothesis import strategies as st

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.library import Library as AtomLibrary
from opulse.atoms.library import VerifyRequest
from opulse.atoms.observations import (
    check_observation,
    judge,
    observe,
    robot_probe_atoms,
    verify_observation,
)
from opulse.atoms.spec import Definition, Edge, ObservationSpec, OperationSpec
from opulse.atoms.values import Ok
from opulse.atoms.world import WorldDecl
from opulse.worlds import action


class Library:
    dialect = "atoms-v2"

    def __init__(self, granted="all"):
        self.world = SimpleNamespace(observation={"truth": "state",
                                           "probes": [{"name": name} for name in action.OBS_RULES],
                                           "capabilities": {"learner": {"probes": granted}}},
                                     operations=tuple(OperationSpec(name, "act" if name in action.ACTION_RULES
                                                                     else "decide", (Edge("state"),),
                                                                     Edge("state"), name)
                                                      for name in (*action.ACTION_RULES, *action.OBS_RULES)) +
                                                tuple(OperationSpec(name, "transform", (Edge("int"),),
                                                                    Edge("int"), name)
                                                      for name in ("not", "inc", "is_red")))
        self.definitions = {}

    def scope(self):
        return kernel.DictScope(atoms=[*robot_probe_atoms(),
                                       kernel.Atom("not", 1, lambda value: not value),
                                       kernel.Atom("inc", 1, lambda value: value + 1),
                                       kernel.Atom("is_red", 1, lambda value: value == "R")])

    def get(self, name):
        return self.definitions[name]


def definition(name, reads, body, memory=None):
    return Definition(name, "observation", "invented", 1, (),
                      ObservationSpec(name, tuple(reads), body, memory), body)


def test_generic_probe_mutation_fails_facts_unchanged():
    class MutableLibrary:
        dialect = "atoms-v2"
        world = SimpleNamespace(observation={"truth": "box", "probes": [{"name": "peek"}],
                                             "capabilities": {"learner": {"probes": "all"}}}, operations=())

        def scope(self):
            def mutate(state):
                state["count"] += 1
                return state["count"]

            return kernel.DictScope(atoms=[kernel.Atom("peek", 1, mutate, kind="observation")])

        def get(self, name):
            raise KeyError(name)

    state = {"count": 0}
    observation = definition("seen", ("peek",), n.Var("peek"))
    result = verify_observation(observation, MutableLibrary(), SimpleNamespace(extra={"states": [state]},
                                                                   reference=None))
    assert not result.ok and "facts_unchanged: observation changed truth state" in result.problems


def test_probe_costs_and_front_free_with_non_interference():
    lib = Library(["front_wall", "front_water"])
    defn = definition("front_free", ("front_wall", "front_water"),
                      n.Case(((n.Test(n.Var("front_wall")), n.Lit(False)),
                              (n.Test(n.Var("front_water")), n.Lit(False))), n.Lit(True)))
    states = action._examples_states()[:4]
    assert len(robot_probe_atoms()) == 12
    assert all(atom.cost == 1 for atom in robot_probe_atoms())
    assert observe(defn, lib, states) == [Ok(not action.apply_atom("front_wall", state) and
                                             not action.apply_atom("front_water", state)) for state in states]
    request = SimpleNamespace(extra={"states": [states]},
                              reference=lambda state: not action.apply_atom("front_wall", state) and
                                                      not action.apply_atom("front_water", state))
    result = verify_observation(defn, lib, request)
    assert result.ok and {"dependency", "reference", "non_interference", "facts_unchanged"} <= set(result.checks)


def test_reference_free_observation_rejects_different_inline_result(monkeypatch):
    from opulse.atoms import observations

    lib = Library(["front_wall"])
    defn = definition("seen", ("front_wall",), n.Var("front_wall"))
    state = action._examples_states()[0]
    original = observations._run

    def changed_inline(definition, scope, states, *, inline=False):
        if inline:
            return [Ok("wrong") for _ in states], [0 for _ in states]
        return original(definition, scope, states)

    monkeypatch.setattr(observations, "_run", changed_inline)
    request = SimpleNamespace(extra={"states": [state]}, reference=None, scope={})
    result = verify_observation(defn, lib, request)
    assert not result.ok
    assert "unfold_equivalence: observation differs from inlined body" in result.problems
    assert "unfold_equivalence" not in result.checks


@settings(deadline=None)
@given(st.lists(st.integers(min_value=-3, max_value=3), min_size=1, max_size=5))
def test_reference_free_observation_unfolds_with_memory_and_records_scope(states):
    peek = OperationSpec("peek", "decide", (Edge("int"),), Edge("bool"), "peek")
    inc = OperationSpec("inc", "transform", (Edge("int"),), Edge("int"), "inc")
    world = WorldDecl("peek-world", 1, "atoms-v2", {}, {}, (), (peek, inc),
                      {"nodes": list(n.NODE_NAMES), "recursion": "fuel"},
                      {"truth": "state", "probes": [{"name": "peek"}],
                       "capabilities": {"learner": {"probes": "all"}}}, {})
    lib = AtomLibrary(world, (kernel.Atom("peek", 1, lambda state: state > 0, kind="observation"),
                              kernel.Atom("inc", 1, lambda value: value + 1)))
    body = n.Let("observed", n.Call("peek", (n.Var("s"),)), n.Var("memory"))
    step = n.Case(((n.Test(n.Var("peek")), n.Call("inc", (n.Var("memory"),))),),
                  n.Var("memory"))
    defn = Definition("count", "observation", "invented", 1, ("peek", "inc"),
                      ObservationSpec("count", ("peek",), body,
                                      {"init": n.Lit(0), "step": step}), body)
    lib.write(defn)
    lib.check(defn.name)
    request = VerifyRequest("bounded", tuple((state,) for state in states),
                            {"domain": "integer history", "size": len(states)},
                            extra={"states": (tuple(states),)})
    result = verify_observation(lib.get(defn.name), lib, request)
    assert result.ok, result.problems
    assert {"dependency", "facts_unchanged", "non_interference", "unfold_equivalence"} <= set(result.checks)
    assert "reference" not in result.checks
    assert request.scope["reference"] == "none"
    lib.make_callable(defn.name, [(states[0],)])
    verified = lib.verify(defn.name, VerifyRequest("bounded", request.domain,
                                                   {"domain": "integer history", "size": len(states)},
                                                   extra=request.extra))
    assert verified.evidence.scope["reference"] == "none"


def test_observation_reuses_probe_scope_for_each_state(monkeypatch):
    from opulse.atoms import observations

    lib = Library()
    observation = definition("front_free", ("front_wall", "front_water"), n.Var("front_wall"))
    states = action._examples_states()[:4]
    original = lib.scope
    calls = []

    def counted_scope():
        calls.append(None)
        return original()

    monkeypatch.setattr(lib, "scope", counted_scope)
    assert observations._run(observation, lib, states)[0] == [
        Ok(action.apply_atom("front_wall", state)) for state in states]
    assert len(calls) == 2


def test_strip_subject_preserves_opaque_blocks():
    from opulse.atoms.observations import _strip_subject

    program = n.Blocks((), "start", (("start", n.Block((), n.Halt(
        n.Call("front_wall", (n.Var("s"),))))),))
    assert _strip_subject(program, "s", {"front_wall"}) is program


def test_memory_counts_consecutive_red_and_restricts_truth():
    lib = Library()
    defn = definition("seen_red_count", ("front_colour",), n.Var("memory"),
                      {"sort": "int", "init": n.Lit(0),
                       "step": n.Case(((n.Test(n.Call("is_red", (n.Var("front_colour"),))),
                                        n.Call("inc", (n.Var("memory"),))),), n.Lit(0))})
    base = action.initial_state()
    red = list(base.stacks)
    red[base.index(2, 1)] = ("R",)
    red_state = replace(base, stacks=tuple(red))
    blue = list(red)
    blue[base.index(2, 1)] = ("B",)
    blue_state = replace(base, stacks=tuple(blue))
    assert observe(defn, lib, [red_state, red_state, blue_state, red_state]) == [Ok(1), Ok(2), Ok(0), Ok(1)]
    assert check_observation(definition("act", (), n.Call("turn_left", (n.Lit(base),))), lib)
    assert check_observation(definition("secret", ("held_colour",), n.Var("held_colour")),
                             Library(["front_wall", "front_water"]))
    assert check_observation(definition("literal_truth", (), n.Lit(red_state)), lib)


def test_judge_ignores_learner_views():
    state = action.initial_state()
    other = replace(state, facing=action.Direction("N"))
    assert judge(None, state, state) and not judge(None, state, other)
    assert judge({"fields": ["robot"]}, state, other)
    assert judge("contract_projection(robot)", state, other)
    wall = definition("wall", ("front_wall",), n.Var("front_wall"))
    holding = definition("holding_view", ("holding",), n.Var("holding"))
    wall_state = replace(state, robot=(0, 1), facing=action.Direction("W"))
    assert observe(wall, Library(["front_wall"]), [wall_state]) != observe(
        holding, Library(["holding"]), [wall_state])
    verdicts = [judge("full_state", state, other) for _ in (wall, holding)]
    assert verdicts == [False, False]
