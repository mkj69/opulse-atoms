"""Boundary invariance across legacy reductions and kernel call trees."""

import json
import random
from dataclasses import dataclass, field

import pytest

from opulse.atoms.boundary import Boundary, flatten_calls, legacy_expand
from opulse.atoms.values import Ok
from opulse.atoms.verify import (
    unfold_equivalent,
    unfold_equivalent_calls,
    unfold_equivalent_legacy,
)
from opulse.config import Settings
from opulse.core.operator import Operator
from opulse.core.primitives import atom_records
from opulse.core.registry import OperatorRegistry
from opulse.definition.parser import DefinitionParser
from opulse.expression.nodes import Call, Number
from opulse.generation.pipeline import OperatorFactory, build_layers
from opulse.trace.tree import build_tree, cut, flatten_view


@dataclass
class CallNode:
    name: str | None
    kind: str
    layer: int
    given: bool
    path: tuple[int, ...]
    inputs: tuple = ()
    outcome: object = None
    steps: int = 0
    children: list = field(default_factory=list)
    jumps: int = 0
    metered: bool = False


@pytest.fixture(scope="module", params=("integer", "clock", "bits"))
def world(request):
    from opulse.presets import PRESETS

    settings = Settings.from_dict({"preset": request.param})
    registry = OperatorRegistry(Operator.from_dict(row) for row in
                                atom_records(PRESETS[request.param]["atoms"], seed=28))
    factory = OperatorFactory(settings, registry, random.Random(28))
    build_layers(factory, [5, 3, 2])
    return registry, factory.runtime, DefinitionParser(settings.symbols, registry)


def test_from_cut_matches_legacy_predicate(world):
    registry = world[0]
    randomizer = random.Random(42)
    choices = [name for op in registry for name in (op.symbol, op.func_id)]
    for _ in range(40):
        names = randomizer.sample(choices, randomizer.randrange(min(5, len(choices))))
        layers = randomizer.randrange(5)
        boundary = Boundary.from_cut(names, layers)
        assert [boundary.opens(op) for op in registry] == [cut(names, layers)(op) for op in registry]
        assert [legacy_expand(boundary)(op) for op in registry] == [cut(names, layers)(op)
                                                                 for op in registry]


def test_random_expressions_and_boundaries(world):
    registry, runtime, parser = world
    randomizer = random.Random(173)
    defined = [op for op in registry if op.definition and op.n_ary <= 2]
    base = [op for op in registry if op.definition is None and op.n_ary <= 2]
    assert defined
    for _ in range(100):
        op = randomizer.choice(defined + base)
        arguments = tuple(Number(randomizer.randrange(0, 4)) for _ in range(op.n_ary))
        if arguments and randomizer.randrange(3) == 0:
            inner = randomizer.choice(defined)
            nested = Call(inner, tuple(Number(randomizer.randrange(0, 3))
                                       for _ in range(inner.n_ary)))
            arguments = (nested, *arguments[1:])
        expression = Call(op, arguments)
        names = frozenset(randomizer.sample([item.symbol for item in defined],
                                            randomizer.randrange(3)))
        boundaries = [Boundary.unfold_all(), Boundary.unfold_none(),
                      Boundary(depth=randomizer.choice((None, 0, 1, 2, 3)),
                               open_names=names if randomizer.randrange(2) else frozenset(),
                               keep_names=names if randomizer.randrange(2) else frozenset(),
                               open_paths=frozenset({randomizer.choice(((0,), (1,), (0, 0),
                                                                        (1, 0)))})
                               if randomizer.randrange(2) else frozenset(),
                               kinds=frozenset({"operation"}) if randomizer.randrange(2)
                               else frozenset({"object"}))]
        check = unfold_equivalent_legacy(expression, registry, runtime, parser, boundaries)
        assert check.ok, (expression, check.problems)


def test_one_occurrence_only_and_round_trip(world):
    registry, runtime, parser = world
    op = next(op for op in registry if op.definition and op.n_ary == 1)
    binary = next(op for op in registry if not op.definition and op.n_ary == 2)
    expression = Call(binary, (Call(op, (Number(1),)), Call(op, (Number(1),))))
    root = build_tree(expression, registry, runtime, parser)
    boundary = Boundary(open_paths=frozenset({(0,)}))
    view = flatten_view(root, expand_at=boundary.opens)
    assert sum(step.step.kind == "eval" and step.step.operator is op for step in view) == 1
    assert len(view) > len(flatten_view(root, expand_at=Boundary.unfold_none().opens))
    assert Boundary.from_dict(json.loads(json.dumps(boundary.to_dict()))) == boundary
    assert unfold_equivalent_legacy(expression, registry, runtime, parser, [boundary]).ok
    assert unfold_equivalent(expression, registry, runtime, parser, [boundary]).ok
    with pytest.raises(ValueError):
        legacy_expand(boundary)


def test_kernel_kind_filter_paths_and_corruption():
    first = CallNode("add", "operation", 0, True, (0, 0), outcome=Ok(1), steps=1)
    second = CallNode("probe", "observation", 0, True, (0, 1), outcome=Ok(2), steps=1)
    third = CallNode("add", "operation", 0, True, (1,), outcome=Ok(3), steps=1)
    composed = CallNode("mix", "combinator", 1, False, (0,), outcome=Ok(2), steps=2,
                        children=[first, second])
    root = CallNode(None, "combinator", 2, False, (), outcome=Ok(3), steps=3,
                    children=[composed, third])
    boundaries = [Boundary.unfold_none(), Boundary.unfold_all(),
                  Boundary(open_paths=frozenset({(0,)})),
                  Boundary(depth=0, kinds=frozenset({"operation"})),
                  Boundary(depth=0, kinds=frozenset({"combinator"}))]
    assert flatten_calls(root, boundaries[2]) == [first, second, third]
    assert flatten_calls(root, boundaries[3]) == [composed, third]
    assert unfold_equivalent_calls(root, boundaries).ok
    assert unfold_equivalent(root, boundaries).ok
    assert not Boundary(depth=0, kinds=frozenset({"operation"})).opens(composed)
    assert Boundary(depth=0, kinds=frozenset({"observation"})).opens(
        CallNode("derived", "observation", 1, False, ()))
    assert Boundary(open_paths=frozenset({(0,)})).opens(composed)
    assert not Boundary.unfold_all().opens(second)
    third.steps = 2
    assert not unfold_equivalent_calls(root, boundaries).ok
    third.steps = 1
    second.path = (3, 1)
    assert not unfold_equivalent_calls(root, boundaries).ok
