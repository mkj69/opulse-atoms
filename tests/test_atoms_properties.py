"""Seeded properties of the four atoms-v2 invariants (spec section 11)."""

import json
import random
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.boundary import Boundary
from opulse.atoms.golden import (
    DEFAULT_ROOT,
    CurrentEngine,
    GoldenCase,
    KernelEngine,
    KernelState,
)
from opulse.atoms.legacy import scope_from_registry
from opulse.atoms.library import Library, PipelineError, bounded, exhaustive, sampled
from opulse.atoms.observations import observe, robot_probe_atoms
from opulse.atoms.random_programs import MODES, programs, seeded_program
from opulse.atoms.spec import Contract, Definition, Edge, ObservationSpec, OperationSpec
from opulse.atoms.values import Bottom, Ok, Unknown, value_equal
from opulse.atoms.verify import unfold_equivalent_calls, unfold_equivalent_legacy
from opulse.atoms.world import WorldDecl, legacy_world_decl
from opulse.config import Settings
from opulse.core.operator import Operator
from opulse.core.primitives import atom_records
from opulse.core.registry import OperatorRegistry
from opulse.definition.parser import DefinitionParser
from opulse.expression.nodes import Call, Number
from opulse.generation.pipeline import OperatorFactory, build_layers
from opulse.presets import PRESETS
from opulse.trace.tree import build_tree, flatten_view
from opulse.worlds import action

PROPERTY = settings(max_examples=36, derandomize=True, deadline=None)


def same_run(left, right):
    if isinstance(left.outcome, Ok):
        assert isinstance(right.outcome, Ok) and value_equal(left.outcome.value, right.outcome.value)
    else:
        assert type(left.outcome) is type(right.outcome) and left.outcome == right.outcome
    assert left.steps == right.steps


@pytest.mark.parametrize("mode", MODES)
def test_seeded_program_covers_node_families(mode):
    program = seeded_program(43, mode)
    assert program.mode == mode
    assert program.scope.resolve(program.name) is not None
    assert isinstance(kernel.call(program.name, program.args, program.scope).outcome,
                      (Ok, Bottom, Unknown))
    with pytest.raises(ValueError, match="unknown program mode"):
        seeded_program(43, "invalid")


def test_seeded_program_exercises_bottom_and_fuel_unknown():
    program = seeded_program(34, "case")
    assert isinstance(kernel.call(program.name, program.args, program.scope).outcome, Bottom)
    for dialect in ("atoms-v2", "legacy-v1"):
        exhausted = kernel.call(program.name, program.args, program.scope,
                                kernel.Limits(fuel=0), dialect=dialect)
        assert exhausted.outcome == Unknown("fuel")


@given(program=programs, dialect=st.sampled_from(("atoms-v2", "legacy-v1")),
       fuel=st.one_of(st.none(), st.integers(min_value=0, max_value=12)))
@settings(max_examples=90, derandomize=True, deadline=None)
def test_i1_seeded_unfolding(program, dialect, fuel):
    limits = kernel.Limits(fuel=fuel)
    direct = kernel.call(program.name, program.args, program.scope, limits, dialect=dialect)
    unfolded = kernel.inline(n.Call(program.name, tuple(map(n.Lit, program.args))), program.scope)
    same_run(direct, kernel.evaluate(unfolded, scope=program.scope, limits=limits, dialect=dialect))


def random_boundaries(trace, rng):
    descendants = []
    stack = [trace]
    while stack:
        current = stack.pop()
        descendants.extend(child for child in current.children if not child.given)
        stack.extend(current.children)
    names = [node.name for node in descendants]
    paths = [node.path for node in descendants]
    kinds = ("object", "operation", "combinator", "observation")
    return [Boundary(), Boundary.unfold_all(), *(Boundary(
        depth=rng.choice((None, 0, 1, 2, 3)),
        open_names=frozenset(rng.sample(names, rng.randrange(len(names) + 1))),
        keep_names=frozenset(rng.sample(names, rng.randrange(len(names) + 1))),
        open_paths=frozenset(rng.sample(paths, rng.randrange(len(paths) + 1))),
        kinds=frozenset(kind for kind in kinds if rng.getrandbits(1))) for _ in range(5))]


@given(program=programs, seed=st.integers(min_value=0, max_value=99999),
       fuel=st.one_of(st.none(), st.integers(min_value=0, max_value=12)))
@PROPERTY
def test_i2_kernel_random_boundaries(program, seed, fuel):
    run = kernel.call(program.name, program.args, program.scope, kernel.Limits(fuel=fuel),
                      trace=True, dialect="legacy-v1")
    result = unfold_equivalent_calls(run.trace, random_boundaries(run.trace, random.Random(seed)))
    assert result.ok, (program.mode, seed, result.problems)


@pytest.fixture(scope="module", params=("integer", "clock", "bits"))
def legacy_world(request):
    settings_ = Settings.from_dict({"preset": request.param})
    registry = OperatorRegistry(Operator.from_dict(row) for row in
                                atom_records(PRESETS[request.param]["atoms"], seed=28))
    factory = OperatorFactory(settings_, registry, random.Random(28))
    build_layers(factory, [5, 3, 2])
    return registry, factory.runtime, DefinitionParser(settings_.symbols, registry)


@given(seed=st.integers(min_value=0, max_value=100_000))
@settings(max_examples=10, derandomize=True, deadline=None)
def test_i2_legacy_random_expressions(legacy_world, seed):
    registry, runtime, parser = legacy_world
    rng = random.Random(seed)
    operators = [op for op in registry if op.n_ary <= 2 and op.definition]
    operator = rng.choice(operators)
    args = [Number(rng.randrange(0, 4)) for _ in range(operator.n_ary)]
    if args and rng.getrandbits(1):
        nested = rng.choice([op for op in operators if op.n_ary == 1])
        args[0] = Call(nested, (Number(rng.randrange(0, 4)),))
    expression = Call(operator, tuple(args))
    names = [name for op in registry for name in (op.symbol, op.func_id)]
    boundaries = [Boundary(), Boundary.unfold_all(), Boundary.from_cut(
        rng.sample(names, rng.randrange(min(5, len(names)) + 1)), rng.randrange(5)),
        Boundary(open_names=frozenset(rng.sample(names, 3)),
                 kinds=frozenset({"operation"}) if rng.getrandbits(1) else frozenset())]
    result = unfold_equivalent_legacy(expression, registry, runtime, parser, boundaries)
    assert result.ok, (seed, result.problems)


@pytest.fixture(scope="module")
def robot_library():
    data = json.loads((DEFAULT_ROOT / "action.json").read_text(encoding="utf-8"))
    return Library(legacy_world_decl(data), robot_probe_atoms())


@given(seed=st.integers(min_value=0, max_value=100_000))
@PROPERTY
def test_i3_random_robot_observations(robot_library, seed):
    rng = random.Random(seed)
    granted = sorted(item["name"] for item in robot_library.world.observation["probes"])
    probes = tuple(rng.sample(granted, rng.randrange(1, min(4, len(granted)) + 1)))
    body = n.Let("sample", n.Var(probes[0]),
                 n.Case(((n.Always(), n.Var(probes[-1] if rng.getrandbits(1) else "sample")),)))
    definition = Definition("test_probe", "observation", "invented", 1, (),
                            ObservationSpec("test_probe", probes, body), body)
    states = action._examples_states()
    first = rng.choice(states)
    indistinguishable = [state for state in states
                         if all(action.apply_atom(probe, first) == action.apply_atom(probe, state)
                                for probe in probes) and state != first]
    pair = [first, rng.choice(indistinguishable) if indistinguishable else rng.choice(states)]
    before = [state.to_dict() for state in pair]
    outputs = observe(definition, robot_library, pair)
    assert before == [state.to_dict() for state in pair]
    if all(action.apply_atom(probe, pair[0]) == action.apply_atom(probe, pair[1]) for probe in probes):
        assert outputs[0] == outputs[1]


def _library():
    atom = kernel.Atom("inc", 1, lambda value: value + 1)
    spec = OperationSpec("inc", "transform", (Edge("int"),), Edge("int"), "increment")
    world = WorldDecl("properties", 1, "atoms-v2", {}, {}, (), (spec,),
                      {"nodes": list(n.NODE_NAMES), "recursion": "fuel"}, {}, {})
    return Library(world, (atom,))


def _definition(name, target):
    body = n.Call(target, (n.Var("arg0"),))
    spec = OperationSpec(name, "transform", (Edge("int"),), Edge("int"), "increment")
    return Definition(name, "operation", "invented", 2 if target == "first" else 1,
                      (target,), spec, body)


@given(actions=st.lists(st.sampled_from(("write", "check", "callable", "verify", "promote",
                                        "replace", "world")), min_size=1, max_size=20),
       seed=st.integers(min_value=0, max_value=100_000))
@settings(max_examples=45, derandomize=True, deadline=None)
def test_i4_random_library_sessions(actions, seed):
    rng = random.Random(seed)
    lib = _library()
    names = ("first", "dependent")
    for action_name in actions:
        name = rng.choice(names)
        target = "inc" if name == "first" else "first"
        try:
            if action_name == "write":
                lib.write(_definition(name, target))
            elif action_name == "check":
                lib.check(name)
            elif action_name == "callable":
                lib.make_callable(name, ((0,), (2,)))
            elif action_name == "verify":
                method = rng.choice(("sampled", "exhaustive", "bounded"))
                request = (sampled(lambda rand: (rand.randrange(3),), 3, seed, "seeded")
                           if method == "sampled" else
                           exhaustive((range(3),), "0..2") if method == "exhaustive" else
                           bounded((range(3),), "bounded 0..2"))
                lib.verify(name, replace(request, reference=lambda value: value + 1))
            elif action_name == "promote":
                lib.promote(name, Contract("increment", keeps=("state",)))
            elif action_name == "replace":
                if name in lib.definitions:
                    lib.replace(name, _definition(name, target))
                    if name == "first" and "dependent" in lib.definitions:
                        assert lib.get("dependent").status != "promoted"
            else:
                lib.world = replace(lib.world, version=lib.world.version + 1)
                assert all(defn.status != "promoted" for defn in lib.definitions.values()
                           if defn.origin == "invented")
        except (PipelineError, KeyError):
            pass
        for defn in lib.derived_world().promoted:
            evidence = defn.evidence
            assert defn.contract is not None
            assert evidence.method in ("exhaustive", "bounded")
            assert evidence.scope["size"] > 0
            assert evidence.world_hash == lib.world.world_hash()
            assert evidence.deps_hash == lib._deps_hash(defn.name)


@pytest.mark.parametrize("method", ("exhaustive", "bounded", "sampled"))
def test_i4_dependency_replacement_and_world_change(method):
    lib = _library()
    for name, target in (("first", "inc"), ("dependent", "first")):
        lib.write(_definition(name, target))
        lib.check(name)
        lib.make_callable(name, ((0,),))
        request = (exhaustive((range(3),), "0..2") if method == "exhaustive" else
                   bounded((range(3),), "bounded 0..2") if method == "bounded" else
                   sampled(lambda rng: (rng.randrange(3),), 3, 71, "seeded"))
        lib.verify(name, replace(request, reference=lambda value: value + 1))
        if method == "sampled":
            with pytest.raises(PipelineError, match="sampled"):
                lib.promote(name, Contract("increment"))
        else:
            lib.promote(name, Contract("increment"))
            assert lib.get(name).evidence.method == method
    if method != "sampled":
        assert set(lib.derived_world().scopes()) == {"first", "dependent"}
    changed = deepcopy(lib)
    changed.world = replace(changed.world, version=changed.world.version + 1)
    assert not changed.derived_world().promoted
    assert changed.get("dependent").evidence is None
    assert changed.get("dependent").status not in ("promoted", "verified")
    if method == "sampled":  # verified but not promoted: a replacement demotes every dependent
        lib.replace("first", _definition("first", "inc"))
        assert lib.get("dependent").status not in ("promoted", "verified")
        assert lib.get("dependent").evidence is None
    else:  # promoted definitions are immutable; a change is a new definition that inherits nothing
        with pytest.raises(PipelineError, match="immutable"):
            lib.replace("first", _definition("first", "inc"))
        assert lib.get("dependent").status == "promoted"


@lru_cache(maxsize=3)
def published_pair(world):
    data = json.loads((DEFAULT_ROOT / f"{world}.json").read_text(encoding="utf-8"))
    current = CurrentEngine().load_published(data)
    tools = current.tools
    scope, info = scope_from_registry(tools.registry, tools.settings.semantics.build(),
                                      tools.oracle.parser)
    ids = {current.name(operator): operator.func_id for operator in current.ordered}
    info.names.update({operator.func_id: current.name(operator) for operator in current.ordered})
    return data, current, KernelState(current, scope, info.names, ids, info.search_names,
                                      info.conditional_names, info.translate)


@given(seed=st.integers(min_value=0, max_value=100_000),
       world=st.sampled_from(("successor", "integer", "bits")))
@settings(max_examples=9, derandomize=True, deadline=None)
def test_random_published_inputs_against_reference(world, seed):
    data, current, state = published_pair(world)
    rng = random.Random(seed)
    operator = rng.choice([item for item in current.ordered if item.recursive_layer == 0])
    name = current.name(operator)
    values = tuple(rng.randint(0, 3) for _ in range(operator.n_ary))
    case = GoldenCase(world, f"{world}.json", data["seed"], name, operator.definition,
                      tuple(operator.parameter_types), values, None, [], "operator_example")
    actual = KernelEngine().run(state, case)
    reference = CurrentEngine().run(current, case)
    assert value_equal(actual.output, reference.output), (world, name, values)
    tree = build_tree(Call(operator, tuple(Number(value) for value in values)),
                      current.tools.registry, current.tools.reducer.runtime,
                      current.tools.oracle.parser)
    base_steps = sum(step.step.kind == "eval" and step.step.operator.definition is None
                     for step in flatten_view(tree))
    assert actual.base_ops == base_steps, (world, name, values)
