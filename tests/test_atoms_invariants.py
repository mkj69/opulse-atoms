"""The four invariants of atoms-v2, stated once each (docs/spec/atoms-v2.md section 11).

I1 always unfoldable: a definition and its full unfolding give the same outcome and steps.
I2 a boundary never changes a result: every view of one run accounts for the same layer-0 steps.
I3 observation never changes facts: observing leaves the truth unchanged; grading uses full truth.
I4 promotion carries scope and contract: no evidence, sampled evidence or a stale world hash
   cannot be promoted; the derived world carries each scope and contract.
"""

import json
import random
from dataclasses import replace

import pytest

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.boundary import Boundary
from opulse.atoms.golden import DEFAULT_ROOT, KernelEngine
from opulse.atoms.library import (
    Library,
    PipelineError,
    VerifyRequest,
    exhaustive,
    sampled,
)
from opulse.atoms.observations import judge, observe, robot_probe_atoms
from opulse.atoms.spec import Contract, Definition, Edge, ObservationSpec, OperationSpec
from opulse.atoms.values import outcome_equal
from opulse.atoms.verify import unfold_equivalent_calls
from opulse.atoms.world import WorldDecl, legacy_world_decl
from opulse.worlds import action

WORLDS = ("integer", "lists", "pitch")


def published_scopes():
    engine = KernelEngine()
    for world in WORLDS:
        state = engine.load(json.loads((DEFAULT_ROOT / f"{world}.json").read_text(encoding="utf-8")))
        yield world, state.scope


def sample_inputs(world, arity, rng):
    if world == "lists":
        return tuple(tuple(rng.randint(-5, 9) for _ in range(rng.randint(0, 3))) for _ in range(arity))
    if world == "pitch":
        return tuple(rng.choice([60, 62, 64, 65, 67]) for _ in range(arity))
    return tuple(rng.randint(-12, 12) for _ in range(arity))


def test_i1_definitions_equal_their_full_unfolding_on_published_worlds():
    rng = random.Random(11)
    checked = 0
    for world, scope in published_scopes():
        for defn in sorted(scope.defns.values(), key=lambda item: item.name)[:25]:
            args = sample_inputs(world, len(defn.params), rng)
            direct = kernel.call(defn.name, args, scope, dialect="legacy-v1")
            unfolded = kernel.evaluate(kernel.inline(n.Call(defn.name, tuple(map(n.Lit, args))), scope),
                                       scope=scope, dialect="legacy-v1")
            assert direct.steps == unfolded.steps, (world, defn.name, args)
            assert outcome_equal(direct.outcome, unfolded.outcome) or (
                type(direct.outcome) is type(unfolded.outcome) and not hasattr(direct.outcome, "value")), \
                (world, defn.name, args)
            checked += 1
    assert checked == 75


def test_i2_every_boundary_view_accounts_for_the_same_run():
    rng = random.Random(12)
    for world, scope in published_scopes():
        names = sorted(scope.defns)
        for defn in [scope.defns[name] for name in names[:20]]:
            run = kernel.call(defn.name, sample_inputs(world, len(defn.params), rng), scope,
                              dialect="legacy-v1", trace=True)
            paths = []
            stack = [run.trace]
            while stack:
                node = stack.pop()
                paths.extend(child.path for child in node.children if not child.given)
                stack.extend(node.children)
            boundaries = [Boundary(), Boundary.unfold_all(), Boundary(depth=2), Boundary(depth=3),
                          Boundary(open_names=frozenset(rng.sample(names, 3))),
                          Boundary(depth=0, keep_names=frozenset(rng.sample(names, 3))),
                          Boundary(open_paths=frozenset(rng.sample(paths, min(2, len(paths))))),
                          Boundary(depth=0, kinds=frozenset({"observation"}))]
            check = unfold_equivalent_calls(run.trace, boundaries)
            assert check.ok, (world, defn.name, check.problems)


def test_i3_observing_never_changes_the_truth_and_grading_uses_full_state():
    world = legacy_world_decl(json.loads((DEFAULT_ROOT / "action.json").read_text(encoding="utf-8")))
    lib = Library(world, robot_probe_atoms())
    narrow = Definition("wall", "observation", "invented", 1, (),
                        ObservationSpec("wall", ("front_wall",), n.Var("front_wall")), n.Var("front_wall"))
    states = action._examples_states()[:5]
    before = [state.to_dict() for state in states]
    observe(narrow, lib, states)
    assert [state.to_dict() for state in states] == before
    for truth in states:
        # Two learners who saw different things are graded on the same full truth.
        assert judge("full_state", truth, truth) and judge(None, truth, truth)
    assert not judge("full_state", states[0], states[1]) or states[0].to_dict() == states[1].to_dict()


def small_library():
    ops = (("succ", lambda value: value + 1), ("pred", lambda value: value - 1),
           ("is_zero", lambda value: value == 0), ("add", lambda left, right: left + right))
    specs = tuple(OperationSpec(name, "transform", tuple(Edge("int") for _ in range(fn.__code__.co_argcount)),
                                Edge("int"), name) for name, fn in ops)
    world = WorldDecl("nat", 1, "atoms-v2", {}, {}, (), specs, {"nodes": list(n.NODE_NAMES), "recursion": "fuel"},
                      {}, {})
    return Library(world, [kernel.Atom(name, fn.__code__.co_argcount, fn) for name, fn in ops])


def double_definition():
    body = n.Call("add", (n.Var("x"), n.Var("x")))
    spec = OperationSpec("double", "transform", (Edge("int"),), Edge("int"), "x + x", extra={"input_names": ["x"]})
    return Definition("double", "operation", "invented", 1, ("add",), spec, body)


def test_i4_promotion_carries_scope_and_contract():
    lib = small_library()
    lib.write(double_definition())
    with pytest.raises(PipelineError):
        lib.promote("double", Contract("2x"))  # not verified
    lib.check("double")
    lib.make_callable("double", ((3,),))
    lib.verify("double", replace(sampled(lambda rng: (rng.randint(0, 99),), 20, 5, "x in 0..99, 20 seeded draws"),
                                 reference=lambda x: 2 * x))
    with pytest.raises(PipelineError, match="sampled"):
        lib.promote("double", Contract("2x"))

    lib = small_library()
    lib.write(double_definition())
    lib.check("double")
    lib.make_callable("double", ((3,),))
    request = replace(exhaustive((range(16),), "x in 0..15"), reference=lambda x: 2 * x)
    lib.verify("double", request)
    lib.promote("double", Contract("returns 2x", keeps=("all state",)))
    derived = lib.derived_world()
    assert derived.scopes()["double"] == {
        **request.scope,
        "checked": lib.get("double").evidence.scope["checked"],
    }
    assert derived.promoted[0].contract.guarantees == "returns 2x"
    lib.world = replace(lib.world, version=2)  # a new world version invalidates the evidence
    assert lib.get("double").status == "callable" and lib.get("double").evidence is None
    assert isinstance(request, VerifyRequest)
