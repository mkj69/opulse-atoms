"""Entry normalization for the clock object (atoms-v2 section 14)."""

import json
import random
from pathlib import Path

from conftest import INITIAL_OPERATORS

from opulse.config import Settings
from opulse.core.operator import BRANCH, SIMPLE, Operator
from opulse.core.registry import OperatorRegistry
from opulse.core.semantics import NAN, Semantics, base_operation_name
from opulse.definition.codegen import compile_definition, registry_resolver
from opulse.definition.parser import DefinitionParser
from opulse.expression.nodes import from_dict
from opulse.expression.nodes import Call, Number
from opulse.generation.drafts import Draft
from opulse.generation.pipeline import OperatorFactory
from opulse.runtime.python_backend import PythonRuntime
from opulse.trace.reducer import Reducer
from opulse.trace.tree import TreeBuilder
from opulse.verify import Oracle
from opulse.worlds.showcase_tasks import prepare
from opulse.worlds.showcase_tasks import _rename_tree


def test_clock_enters_before_every_base_operation():
    operations = Semantics("modular", modulus=12).operations()
    assert operations["add"](14, 0) == 2
    assert operations["add"](-4, 0) == 8
    assert operations["reverse"](12) == operations["reverse"](0) == 0
    assert operations["reverse"](19) == 7
    assert operations["digitsum"](19) == 7
    assert operations["popcount"](-4) == 1
    assert operations["div"](3, 12) is NAN
    assert operations["mod"](3, 24) is NAN
    assert operations["defined"](NAN) == 0


def test_clock_generated_definitions_agree_with_reference():
    registry = OperatorRegistry.from_jsonl(INITIAL_OPERATORS)
    settings = Settings.from_dict({"preset": "clock"})
    semantics = settings.semantics.build()
    parser = DefinitionParser(settings.symbols, registry)
    runtime = PythonRuntime(registry, semantics)
    definitions = (
        ("a ◇ b = { a + 13 }", SIMPLE),
        ("a ◆ b = { 13, if a == 13; b, else }", BRANCH),
        ("a ◈ b = { (a @) + b }", SIMPLE),
        ("a ▽ b = { a / b, if b != 12; 4, else }", BRANCH),
        ("a ♤ b = { - 4, if a == - 4; 13, else }", BRANCH),
    )
    operators = []
    for index, (text, kind) in enumerate(definitions):
        operator = Operator(f"clocktrue{index}", text.split()[1], 2, definition=text,
                            definition_type=kind)
        definition = parser.parse(text)
        code = compile_definition(definition, operator.func_id, registry_resolver(registry, operator),
                                  modulus=semantics.modulus)
        operator.op_compute_func, operator.op_count_func = code.compute, code.count
        operator.dependencies = list(code.dependencies)
        registry.add(operator)
        runtime.load(operator)
        operators.append(operator)
    oracle = Oracle(registry, settings.symbols, semantics)
    rng = random.Random(20261104)
    for operator in operators:
        for _ in range(60):
            args = (rng.randrange(-48, 49), rng.randrange(-48, 49))
            expected = oracle.evaluate(operator, args)
            actual = runtime.evaluate(operator)(*args)
            assert actual == (expected.value, expected.base_ops, expected.calls)
    assert oracle.evaluate(operators[0], (0, 0)).value == 1
    assert runtime.compute(operators[1])(13, 0) == 1
    assert oracle.evaluate_expr(parser.parse("a ◇ b = { 13 }").branches[0].expr, {}).value == 1
    assert runtime.compute(operators[-1])(8, 0) == 8
    assert oracle.evaluate(operators[-1], (-4, 0)).value == 8


def test_clock_pipeline_compiles_canonical_literals():
    settings = Settings.from_dict({"preset": "clock"})
    registry = OperatorRegistry.from_jsonl(INITIAL_OPERATORS)
    factory = OperatorFactory(settings, registry, random.Random(20261104))
    definition = DefinitionParser(settings.symbols, registry).parse(
        "a ◇ b = { 13, if a == - 4; - 4, else }")
    draft = Draft("◇", 2, None, definition, BRANCH)
    operator = factory._compile(draft)
    registry.add(operator)
    for args, expected in (((8, 2), 1), ((-4, 2), 1), ((0, 2), 8)):
        result = factory.oracle.evaluate(operator, args)
        assert result.value == expected
        assert factory.runtime.evaluate(operator)(*args) == (result.value, result.base_ops, result.calls)


def test_clock_trace_enters_literals_and_defined_call_arguments():
    settings = Settings.from_dict({"preset": "clock"})
    registry = OperatorRegistry.from_jsonl(INITIAL_OPERATORS)
    parser = DefinitionParser(settings.symbols, registry)
    runtime = PythonRuntime(registry, settings.semantics.build())
    definitions = (("a ◇ b = { 37 }", SIMPLE),
                   ("a ◆ b = { (a ◇ 37) + 37, if a == 13; 37, else }", BRANCH))
    operators = []
    for index, (text, kind) in enumerate(definitions):
        operator = Operator(f"clocktrace{index}", text.split()[1], 2,
                            definition=text, definition_type=kind)
        compiled = compile_definition(parser.parse(text), operator.func_id,
                                      registry_resolver(registry, operator), modulus=12)
        operator.op_compute_func, operator.op_count_func = compiled.compute, compiled.count
        operator.dependencies = list(compiled.dependencies)
        registry.add(operator)
        runtime.load(operator)
        operators.append(operator)
    oracle = Oracle(registry, settings.symbols, settings.semantics.build())
    expression = Call(operators[1], (Number(13), Number(-4)))
    trace = Reducer(registry, runtime, parser).reduce(expression)
    assert trace.value == oracle.evaluate(operators[1], (13, -4)).value == 2
    assert trace.source.args == (Number(1), Number(8))
    assert trace.steps[0].branch_index == 0
    assert "13" not in trace.steps[0].condition
    assert trace.steps[0].after.args[0].args == (Number(1), Number(1))
    assert trace.steps[0].after.args[1] == Number(1)
    assert any(step.operator == operators[0] and step.after == Number(1)
               for step in trace.steps)
    tree = TreeBuilder(registry, runtime, parser).application(operators[1], (13, -4))
    assert tree.inputs == (1, 8)
    assert tree.value == trace.value


def test_clock_trace_search_compares_canonical_hours():
    settings = Settings.from_dict({"preset": "clock"})
    registry = OperatorRegistry.from_jsonl(INITIAL_OPERATORS)
    parser = DefinitionParser(settings.symbols, registry)
    text = "a ◇ b = { search(i, 14, i == 13) }"
    operator = Operator("clocktracesearch", "◇", 2, definition=text, definition_type=SIMPLE)
    compiled = compile_definition(parser.parse(text), operator.func_id,
                                  registry_resolver(registry, operator), modulus=12)
    operator.op_compute_func, operator.op_count_func = compiled.compute, compiled.count
    registry.add(operator)
    runtime = PythonRuntime(registry, settings.semantics.build())
    trace = Reducer(registry, runtime, parser).reduce(Call(operator, (Number(14), Number(-4))))
    oracle = Oracle(registry, settings.symbols, settings.semantics.build())
    assert trace.value == oracle.evaluate(operator, (14, -4)).value == 1
    assert trace.source.args == (Number(2), Number(8))
    assert "i=1: True" in trace.steps[0].condition


def test_published_clock_example_inputs_are_hours_and_reproduce():
    path = Path(__file__).resolve().parents[1] / "docs/assets/data/worlds"
    primary = json.loads((path / "clock.json").read_text(encoding="utf-8"))
    settings = Settings.from_dict({"preset": "clock"})
    registry = OperatorRegistry.from_jsonl(INITIAL_OPERATORS)
    oracle = Oracle(registry, settings.symbols, settings.semantics.build())
    for seed in primary["seeds"]:
        data = json.loads((path / seed["file"]).read_text(encoding="utf-8"))
        for atom in data["atoms"]:
            operator = next(operator for operator in registry if base_operation_name(
                operator.symbol, operator.n_ary, operator.unary_position) == atom["name"])
            example = atom["example"]
            args = tuple(item["v"] for item in example["inputs"])
            assert all(0 <= arg < 12 for arg in args)
            result = oracle.evaluate(operator, args).value
            assert example["output"] == ({"t": "nan"} if result is NAN else {"t": "int", "v": result})
        world = prepare("clock", seed["seed"])
        by_name = {world.name(operator): operator for operator in world.ordered}
        for row in data["operators"]:
            for example in row["examples"]:
                args = tuple(item["v"] for item in example["inputs"])
                assert all(0 <= arg < 12 for arg in args)
                value = world.oracle.evaluate(by_name[row["name"]], args).value
                assert example["output"] == ({"t": "nan"} if value is NAN else {"t": "int", "v": value})


def test_published_clock_task_inputs_are_hours_and_reproduce():
    path = Path(__file__).resolve().parents[1] / "docs/assets/data/worlds/clock/tasks.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    world = prepare("clock", data["seed"])
    names = {shown: symbol for symbol, shown in world.tools.names.items()}

    def inputs(node):
        if isinstance(node, dict):
            if node.get("type") == "numeric_atoms":
                yield node["value"]
            for value in node.values():
                yield from inputs(value)
        elif isinstance(node, list):
            for value in node:
                yield from inputs(value)

    for item in data["expressions"]:
        assert all(0 <= value < 12 for value in inputs(item["tree"]))
        tree = from_dict(_rename_tree(item["tree"], names), world.tools.registry)
        assert item["value"] == world.enc(world.value(tree), tree.operator.result_type)
    for hole in data["holes"]:
        assert all(0 <= value < 12 for value in inputs(hole["tree"]))
        assert all(0 <= value["v"] < 12 for value in (hole["answer"], *hole["solutions"]))
        detail = json.loads((path.parent / "tasks" / f"{hole['id']}.json").read_text(encoding="utf-8"))
        assert all(0 <= value["v"] < 12 for value, _ in detail["candidates"])


def test_published_clock_challenge_inputs_are_hours_and_reproduce():
    path = Path(__file__).resolve().parents[1] / "docs/assets/data/worlds/clock/challenge.json"
    challenges = json.loads(path.read_text(encoding="utf-8"))["challenges"]
    world = prepare("clock", 57)
    by_name = {world.name(operator): operator for operator in world.ordered}
    for challenge in challenges[:5]:
        args = tuple(item["v"] for item in challenge["question"]["inputs"])
        assert all(0 <= arg < 12 for arg in args)
        operator = by_name[challenge["rules"][0]["symbol"]]
        assert challenge["answer"] == world.enc(world.oracle.evaluate(operator, args).value,
                                               operator.result_type)
    induction = challenges[5]
    operator = by_name[induction["reference_definition"]["text"].split()[1]]
    for example in (*induction["examples"], induction["query"]):
        args = tuple(item["v"] for item in example["inputs"])
        assert all(0 <= arg < 12 for arg in args)
        expected = induction["answer"] if example is induction["query"] else example["output"]
        assert expected == world.enc(world.oracle.evaluate(operator, args).value, operator.result_type)
