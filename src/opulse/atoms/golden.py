"""Published legacy-v1 compatibility checks (atoms-v2 spec section 13.3)."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Protocol

from opulse.core.semantics import NAN
from opulse.core.types import same_value

WORLDS = ("successor", "integer", "clock", "bits", "strings", "lists",
          "logic", "perm", "rel", "grid", "pitch", "action")
DEFAULT_ROOT = Path(__file__).resolve().parents[3] / "docs/assets/data/worlds"
MANIFEST = Path(__file__).resolve().parents[3] / "tests/data/atoms_golden/manifest.json"
CLOCK_REASON = "clock regenerated under true-clock semantics (spec section 14)"
TASK_REASON = "task answers include non-evaluation questions and counterfactual registries"


def decode(value: dict | None):
    """Decode the browser's world-context legacy value representation."""
    if value is None or value["t"] == "nan":
        return NAN
    kind, item = value["t"], value["v"]
    if kind in ("int", "note", "bool", "str", "entity"):
        return item
    if kind == "list":
        return tuple(decode(child) if isinstance(child, dict) else child for child in item)
    if kind == "grid":
        return tuple(tuple(row) for row in item)
    if kind == "melody":
        return tuple((note["p"], note["d"]) for note in item)
    if kind == "perm":
        from opulse.worlds.perm import Permutation

        return Permutation(item)
    if kind == "state":
        from opulse.worlds.action import State

        return State.from_dict(item)
    if kind in ("colour", "direction"):
        from opulse.worlds.action import Colour, Direction

        return (Colour if kind == "colour" else Direction)(item)
    raise ValueError(f"unknown published value type {kind!r}")


@dataclass(frozen=True)
class GoldenCase:
    world: str
    source: str
    seed: int
    operator: str
    definition: str
    param_types: tuple[str, ...]
    inputs: tuple
    expected_output: object
    expected_steps: list[dict] | None
    kind: str
    example_index: int = 0
    skip_reason: str | None = None
    expression_tree: dict | None = None
    task_chain: tuple[str, ...] = ()
    expected_base_ops: int | None = None


@dataclass(frozen=True)
class EngineResult:
    output: object
    steps: list[dict] | None = None
    base_ops: int | None = None
    trace_complete: bool = False
    raw_ops: int | None = None


class Engine(Protocol):
    name: str

    def load(self, world_json: dict) -> object: ...

    def run(self, state: object, case: GoldenCase) -> EngineResult: ...


def _world_files(world: str, root: Path) -> Iterator[Path]:
    main = root / f"{world}.json"
    yield main
    for entry in json.loads(main.read_text(encoding="utf-8"))["seeds"]:
        path = root / entry["file"]
        if path != main:
            yield path


def iter_cases(world: str, root: Path = DEFAULT_ROOT, *, main_only: bool = False) -> Iterator[GoldenCase]:
    """Yield published examples; ``main_only`` skips secondary seed files."""
    if world not in WORLDS:
        raise ValueError(f"unknown world {world!r}")
    root = Path(root)
    for source in ((root / f"{world}.json",) if main_only else _world_files(world, root)):
        data = json.loads(source.read_text(encoding="utf-8"))
        seed = data["seed"]
        for row in data["atoms"]:
            example = row.get("example")
            if example:
                yield GoldenCase(world, source.relative_to(root).as_posix(), seed, row["name"],
                                 row["rule"], tuple(p["type"] for p in row["params"]),
                                 tuple(map(decode, example["inputs"])), decode(example["output"]),
                                 None, "atom_example")
        steps_dir = root / data["steps"]
        for index, row in enumerate(data["operators"]):
            examples = row["examples"]
            steps = json.loads((steps_dir / f"{index}.json").read_text(encoding="utf-8"))
            if len(steps) != len(examples):
                raise ValueError(f"{steps_dir / f'{index}.json'}: example count differs")
            for example_index, (example, trace) in enumerate(zip(examples, steps)):
                yield GoldenCase(world, source.relative_to(root).as_posix(), seed, row["name"],
                                 row["definition"], tuple(p["type"] for p in row["params"]),
                                 tuple(map(decode, example["inputs"])), decode(example["output"]),
                                 trace, "operator_example", example_index)
    tasks = root / world / "tasks.json"
    if tasks.is_file():
        data = json.loads(tasks.read_text(encoding="utf-8"))
        for index, row in enumerate(data.get("expressions", ())):
            tree = row.get("tree")
            yield GoldenCase(world, tasks.relative_to(root).as_posix(), data["seed"],
                             row["id"], row["expression"], (),
                             (decode(row["first"]),) if tree is None else (),
                             decode(row["value"]), None, "task", index,
                             expression_tree=tree,
                             task_chain=tuple(row["operators"]) if tree is None else ())
        yield GoldenCase(world, tasks.relative_to(root).as_posix(), data["seed"], "(tasks)",
                         "", (), (), NAN, None, "task", skip_reason=TASK_REASON)
        for task_file in sorted((root / data["files"]).glob("*.json")):
            yield GoldenCase(world, task_file.relative_to(root).as_posix(), data["seed"],
                             task_file.stem, "", (), (), NAN, None, "task",
                             skip_reason=TASK_REASON)


class CurrentEngine:
    """Reference world builders and the exact showcase trace producer."""

    name = "current"

    def load(self, world_json: dict) -> object:
        return _prepared(world_json)

    def load_published(self, world_json: dict) -> object:
        """Load a published seed without regenerating its operator library."""
        key = (world_json["world"], world_json["seed"])
        if key not in _PUBLISHED:
            _PUBLISHED[key] = _load_published(world_json)
        return _PUBLISHED[key]

    def run(self, state: object, case: GoldenCase) -> EngineResult:
        return _run_current(state, case)


_PREPARED: dict[tuple[str, int], object] = {}
_PUBLISHED: dict[tuple[str, int], object] = {}


def _prepared(world_json: dict):
    key = (world_json["world"], world_json["seed"])
    if key not in _PREPARED:
        _PREPARED[key] = _load_current(world_json)
    return _PREPARED[key]


def _load_current(world_json: dict) -> object:
    world, seed = world_json["world"], world_json["seed"]
    if world == "action":
        from opulse.worlds.action import generate_skills

        skills = generate_skills(seed=seed)
        published = world_json["operators"]
        if [(skill.name, skill.definition()) for skill in skills] != [
                (row["name"], row["definition"]) for row in published]:
            raise ValueError(f"{world} seed {seed}: generated definitions differ from publication")
        return {skill.name: skill for skill in skills}
    from opulse.worlds.showcase_tasks import prepare

    state = prepare(world, seed)
    if [(state.name(op), state.show(op.definition)) for op in state.ordered] != [
            (row["name"], row["definition"]) for row in world_json["operators"]]:
        raise ValueError(f"{world} seed {seed}: generated definitions differ from publication")
    state.tools.reducer.max_steps = 91
    return state


def _load_published(world_json: dict) -> object:
    world, seed = world_json["world"], world_json["seed"]
    if world == "action":
        return _load_current(world_json)
    from opulse.config import Settings
    from opulse.core.operator import BINARY, POSTFIX, PREFIX, Operator
    from opulse.core.primitives import atom_records
    from opulse.core.registry import OperatorRegistry
    from opulse.definition.parser import DefinitionParser
    from opulse.expression.render import ExpressionRenderer
    from opulse.trace.reducer import Reducer
    from opulse.verify import Oracle
    from opulse.worlds.present import Describer
    from opulse.worlds.showcase import Tools, world_spec
    from opulse.worlds.showcase_tasks import World

    settings = Settings.from_dict({"preset": world, "operators": {"max_if_branches": 3,
                                   "min_defined_share": 0.5}, "expressions": {"max_depth": 2}})
    registry = OperatorRegistry(Operator.from_dict(row) for row in
                                atom_records((atom["name"] for atom in world_json["atoms"]), seed))
    ordered = []
    for index, row in enumerate(world_json["operators"]):
        name = row["name"]
        parameters = row["params"]
        arity = len(parameters)
        position = None if arity > 1 else PREFIX if row["definition"].startswith(name) else POSTFIX
        operator = Operator(f"published_{index}", name, arity, position,
                            recursive_layer=row["layer"], definition=row["definition"],
                            parameter_types=tuple(param["type"] for param in parameters),
                            result_type=row["result_type"],
                            priority=1 if arity == BINARY else 4,
                            op_compute_func="published", op_count_func="published")
        registry.add(operator)
        ordered.append(operator)

    spec = world_spec(world)
    semantics = settings.semantics.build()
    parser = DefinitionParser(settings.symbols, registry)
    oracle = Oracle(registry, settings.symbols, semantics)

    class PublishedRuntime:
        def compute(self, operator):
            return lambda *args: oracle.evaluate(operator, args).value

    reducer = Reducer(registry, PublishedRuntime(), parser, max_steps=91, max_depth=2)
    names = {op.symbol: op.symbol for op in registry}
    tools = Tools(spec, settings, registry, names, oracle, reducer,
                  ExpressionRenderer(settings.symbols), parser,
                  Describer(registry, names, parser, spec.value_text))
    return World(spec, seed, tools, ordered, [op for op, row in zip(ordered,
                 world_json["operators"]) if row.get("featured")],
                 all(op.result_type == "int" and all(kind == "int" for kind in op.parameter_types)
                     for op in registry), None)


def _run_current(state: object, case: GoldenCase) -> EngineResult:
    if case.task_chain:
        from opulse.worlds.action import run_skill

        value = case.inputs[0]
        for name in case.task_chain:
            value, _ = run_skill(name, value, state, unfold=False)
        return EngineResult(value)
    if case.expression_tree is not None:
        from opulse.expression.nodes import from_dict, to_ast

        names = {name: symbol for symbol, name in state.tools.names.items()}

        def unalias(value):
            if isinstance(value, list):
                return [unalias(item) for item in value]
            if isinstance(value, dict):
                return {key: names.get(item, item) if key == "operator" else unalias(item)
                        for key, item in value.items()}
            return value

        tree = from_dict(unalias(case.expression_tree), state.tools.registry)
        return EngineResult(state.oracle.evaluate_expr(to_ast(tree), {}).value)
    if case.world == "action":
        from opulse.worlds.action import apply_atom, run_skill

        if case.kind == "atom_example":
            return EngineResult(apply_atom(case.operator, case.inputs[0]))
        output, steps = run_skill(state[case.operator], case.inputs[0], state)
        return EngineResult(output, steps, sum(step["kind"] == "atom" for step in steps))

    from opulse.expression.nodes import Call, Number
    from opulse.worlds.showcase import _notes

    tools = state.tools
    if case.kind == "atom_example":
        op = next(op for op in tools.registry if op.primitive_name == case.operator and
                  op.definition is None and op.parameter_types == case.param_types)
        return EngineResult(tools.oracle.evaluate(op, case.inputs).value)
    op = next(op for op in state.ordered if state.name(op) == case.operator)
    tree = Call(op, tuple(Number(value) for value in case.inputs))
    trace = tools.reducer.reduce(tree)
    if trace.truncated:
        raise ValueError(f"{case.source} {case.operator}: truncated trace")
    kinds = {item.func_id: item.result_type for item in tools.registry}
    steps = []
    for step in trace.steps:
        note, note_zh = _notes(step, tools, kinds)
        record = {"kind": step.kind,
                  "expression": tools.show(tools.renderer.full(step.expression_after)),
                  "focus": tools.show(tools.renderer.full(step.before)),
                  "value": state.spec.encode(step.output, kinds.get(step.operator.func_id))
                  if step.output is not None else None,
                  "note": note, "note_zh": note_zh,
                  "gate": tools.names.get(step.operator.symbol, step.operator.symbol),
                  "branch": step.branch_index}
        if state.spec.step_extra:
            state.spec.step_extra(step, record, tools)
        steps.append(record)
    return EngineResult(tools.oracle.evaluate(op, case.inputs).value, steps,
                        sum(step.kind == "eval" and step.operator.definition is None
                            for step in trace.steps))


@dataclass
class KernelState:
    reference: object
    scope: object
    names: dict[str, str]
    ids: dict[str, str]
    search_names: frozenset[str] = frozenset()
    conditional_names: frozenset[str] = frozenset()
    translate: Callable | None = None


class KernelEngine:
    """Legacy-v1 evaluation; visible kernel calls are compared without display prose."""

    name = "kernel"

    def load(self, world_json: dict) -> KernelState:
        from opulse.atoms.legacy import scope_from_registry, scope_from_skills

        reference = CurrentEngine().load_published(world_json)
        if world_json["world"] == "action":
            scope, info = scope_from_skills(reference)
            ids = {name: name for name in (*reference, *scope.atoms)}
        else:
            tools = reference.tools
            scope, info = scope_from_registry(tools.registry, tools.settings.semantics.build(),
                                              tools.oracle.parser)
            ids = {reference.name(op): op.func_id for op in reference.ordered}
            ids.update({op.primitive_name: op.func_id for op in tools.registry
                        if op.definition is None and op.primitive_name})
            info.names.update({op.func_id: reference.name(op) for op in reference.ordered})
        return KernelState(reference, scope, info.names, ids, info.search_names,
                           info.conditional_names, info.translate)

    def run(self, state: KernelState, case: GoldenCase) -> EngineResult:
        from opulse.atoms.kernel import call, evaluate
        from opulse.atoms.values import Ok

        if case.kind == "task" and case.task_chain:
            value = case.inputs[0]
            for name in case.task_chain:
                outcome = call(name, (value,), state.scope, dialect="legacy-v1").outcome
                value = outcome.value if isinstance(outcome, Ok) else NAN
            return EngineResult(value)
        if case.kind == "task" and case.expression_tree is not None:
            from opulse.expression.nodes import from_dict, to_ast

            names = {name: symbol for symbol, name in state.reference.tools.names.items()}

            def unalias(value):
                if isinstance(value, list):
                    return [unalias(item) for item in value]
                if isinstance(value, dict):
                    return {key: names.get(item, item) if key == "operator" else unalias(item)
                            for key, item in value.items()}
                return value

            tree = from_dict(unalias(case.expression_tree), state.reference.tools.registry)
            outcome = evaluate(state.translate(to_ast(tree)), scope=state.scope,
                               dialect="legacy-v1").outcome
            return EngineResult(outcome.value if isinstance(outcome, Ok) else NAN)
        name = state.ids[case.operator]
        run = call(name, case.inputs, state.scope, dialect="legacy-v1", trace=True)
        output = run.outcome.value if isinstance(run.outcome, Ok) else NAN
        if case.world == "action" and case.expected_steps is not None:
            steps = _robot_steps(run.trace, state)
        else:
            steps = _kernel_steps(run.trace, state) if case.expected_steps is not None else None
        visible_gates = {state.names.get(name, name) for name in state.scope.atoms
                         if not name.startswith("__legacy_")}
        visible_base = sum(row["kind"] == "eval" and row.get("gate") in visible_gates
                           for row in steps or ()) if case.world != "action" else run.steps
        return EngineResult(output, steps, run.steps,
                            steps is not None and not any(row["kind"] == "eval" and
                                row.get("defined") for row in steps) and run.steps == visible_base)


def _reference_base_ops(case: GoldenCase, state: KernelState) -> int:
    reference = state.reference
    operator = next(op for op in reference.ordered if reference.name(op) == case.operator)
    return reference.tools.oracle.evaluate(operator, case.inputs).base_ops


def _kernel_steps(root, state: KernelState) -> list[dict]:
    """Project the call tree to structural kind, gate and evaluated value only.

    Published expression/focus strings, notes, translations, branch labels and
    observation prose are display-only. The showcase opens its legacy cut to
    two nested definitions; synthetic zero-cost adapters are hidden.
    """
    from opulse.atoms.boundary import Boundary
    from opulse.atoms.values import Ok

    steps = []
    boundary = Boundary.from_cut(known_layers=0)
    cut_depth = state.reference.tools.reducer.max_depth

    def visit(frame, depth=0):
        name = frame.name or ""
        if name == "__legacy_search":
            return
        visible = bool(name) and not name.startswith("__legacy_")
        if visible and not frame.given:
            entry = next((index for index, child in enumerate(frame.children)
                          if child.name == "__legacy_enter"), len(frame.children))
            for child in frame.children[:entry]:
                visit(child, depth)
            if depth < 2 and name in state.search_names:
                steps.append({"kind": "eval",
                              "gate": state.names.get(name, name),
                              "value": frame.outcome.value if isinstance(frame.outcome, Ok) else NAN,
                              "defined": True})
                return
            if not boundary.opens(frame, frame.path) or (cut_depth is not None and depth >= cut_depth):
                steps.append({"kind": "eval", "gate": state.names.get(name, name),
                              "value": frame.outcome.value if isinstance(frame.outcome, Ok) else NAN,
                              "defined": True})
                return
            steps.append({"kind": "expand", "gate": state.names.get(name, name), "value": None})
            children = frame.children[entry + 1:]
            body = next((index for index, child in enumerate(children)
                         if child.name == "__legacy_body"), None)
            if body is not None:
                children = children[body + 1:]
            elif name in state.conditional_names or name in state.search_names:
                steps[-1] = {"kind": "undefined", "gate": state.names.get(name, name),
                             "value": NAN}
                return
            for child in children:
                visit(child, depth + 1)
            return
        for child in frame.children:
            visit(child, depth)
        if visible and frame.given:
            steps.append({"kind": "eval", "gate": state.names.get(name, name),
                          "value": frame.outcome.value if isinstance(frame.outcome, Ok) else NAN})

    visit(root)
    return steps


def _robot_steps(root, state: KernelState) -> list[dict]:
    """Expose skill entry/exit, action results and checked observations."""
    from opulse.atoms.values import Ok
    from opulse.worlds.action import ACTION_RULES

    steps = []

    def value(frame):
        return frame.outcome.value if isinstance(frame.outcome, Ok) else NAN

    def visit(frame):
        if frame.name in state.scope.defns:
            steps.append({"kind": "expand", "value": frame.inputs[0]})
        probe = None  # the probe call evaluated as an argument of the next comparison
        for child in frame.children:
            if child.name == "__legacy_robot_equal":
                steps.append({"kind": "eval", "value": probe.inputs[0] if probe else child.inputs[0],
                              "observation": value(probe) if probe else NAN})
                probe = None
                continue
            probe = child if child.kind == "observation" else None
            visit(child)
        if frame.name in state.scope.defns:
            steps.append({"kind": "eval" if isinstance(frame.outcome, Ok) else "undefined",
                          "value": value(frame)})
        elif frame.name in ACTION_RULES:
            steps.append({"kind": "atom" if isinstance(frame.outcome, Ok) else "undefined",
                          "value": value(frame)})
        elif frame.name and frame.name.startswith("__legacy_success_") and value(frame) is False:
            steps.append({"kind": "undefined", "value": NAN})

    visit(root)
    return steps


def compare_kernel(case: GoldenCase, result: EngineResult) -> list[str]:
    """Compare output, every counted base step, and visible kind/gate/value order."""
    diffs = []
    if not same_value(case.expected_output, result.output):
        diffs.append(f"output: expected {case.expected_output!r}, got {result.output!r}")
    if case.expected_steps is None:
        return diffs
    if case.world == "action":
        expected = [{"kind": row["kind"], "value": decode(row["value"]),
                     **({"observation": decode(row["observation"])}
                        if "observation" in row else {})} for row in case.expected_steps]
        actual = result.steps or []
        if result.base_ops != sum(row["kind"] == "atom" for row in case.expected_steps):
            diffs.append(f"base_ops: expected action atom count, got {result.base_ops}")
        if len(expected) != len(actual):
            diffs.append(f"trace length: expected {len(expected)}, got {len(actual)}")
        for index, (left, right) in enumerate(zip(expected, actual)):
            if (left["kind"] != right["kind"] or
                    not same_value(left["value"], right["value"]) or
                    ("observation" in left and not same_value(left["observation"],
                                                              right.get("observation")))):
                diffs.append(f"trace {index}: mismatch in kind/value/observation")
                break
        return diffs
    expected = [step for step in case.expected_steps
                if step.get("kind") in ("expand", "eval", "undefined")]
    published_base = sum(step["kind"] == "eval" for step in expected)
    expected_base = case.expected_base_ops if case.expected_base_ops is not None else published_base
    if result.base_ops is not None and result.base_ops != expected_base:
        diffs.append(f"base_ops: expected {expected_base}, got {result.base_ops}")
    if result.steps is not None and case.world != "action":
        actual = result.steps
        if len(actual) != len(expected):
            diffs.append(f"trace length: expected {len(expected)}, got {len(actual)}")
        for index, (left, right) in enumerate(zip(expected, actual)):
            if left["kind"] != right["kind"] or left.get("gate") != right.get("gate"):
                diffs.append(f"trace {index}: expected {left['kind']} {left.get('gate')}, "
                             f"got {right['kind']} {right.get('gate')}")
                break
            if left["kind"] in ("eval", "undefined") and left.get("value") is not None and not same_value(
                    decode(left["value"]), right["value"]):
                diffs.append(f"trace {index}: value mismatch")
                break
    return diffs


def compare(case: GoldenCase, result: EngineResult) -> list[str]:
    """Compare the outcome and every recorded trace field, including extra fields."""
    diffs = []
    if not same_value(case.expected_output, result.output):
        diffs.append(f"output: expected {case.expected_output!r}, got {result.output!r}")
    if case.expected_steps is not None:
        if result.steps is None:
            diffs.append("steps: missing trace")
        else:
            if len(result.steps) != len(case.expected_steps):
                diffs.append(f"steps: expected {len(case.expected_steps)}, got {len(result.steps)}")
            for index, (expected, actual) in enumerate(zip(case.expected_steps, result.steps)):
                for key in expected.keys() | actual.keys():
                    if key == "value" and expected.get(key) is not None and actual.get(key) is not None:
                        equal = same_value(decode(expected[key]), decode(actual[key]))
                    else:
                        equal = expected.get(key) == actual.get(key) and (key in expected) == (key in actual)
                    if not equal:
                        diffs.append(f"step {index} {key}: expected {expected.get(key)!r}, "
                                     f"got {actual.get(key)!r}")
    return diffs


@dataclass
class WorldCount:
    cases: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    kinds: Counter = field(default_factory=Counter)
    reasons: Counter = field(default_factory=Counter)
    diffs: list[str] = field(default_factory=list)


@dataclass
class Report:
    engine: str
    worlds: dict[str, WorldCount] = field(default_factory=dict)

    def __str__(self) -> str:
        lines = [f"Golden compatibility ({self.engine}):"]
        for world, count in self.worlds.items():
            lines.append(f"{world}: {count.cases} cases ({dict(count.kinds)}), "
                         f"{count.passed} passed, {count.failed} failed, {count.skipped} skipped")
            lines.extend(f"  skipped: {reason} ({number})" for reason, number in count.reasons.items())
            lines.extend(f"  {diff}" for diff in count.diffs)
        return "\n".join(lines)


def run_golden(engine: Engine, worlds: tuple[str, ...] = WORLDS, root: Path = DEFAULT_ROOT,
               *, include_clock: bool = False) -> Report:
    report = Report(engine.name)
    root = Path(root)
    for world in worlds:
        count = report.worlds[world] = WorldCount()
        states = {}
        for case in iter_cases(world, root):
            count.cases += 1
            count.kinds[case.kind] += 1
            reason = CLOCK_REASON if world == "clock" and not include_clock else case.skip_reason
            if reason:
                count.skipped += 1
                count.reasons[reason] += 1
                continue
            try:
                if case.seed not in states:
                    world_file = root / (f"{world}.json" if case.kind == "task" else case.source)
                    states[case.seed] = engine.load(json.loads(world_file.read_text(encoding="utf-8")))
                result = engine.run(states[case.seed], case)
                if isinstance(engine, KernelEngine):
                    if case.expected_steps is not None and case.world != "action":
                        case = replace(case, expected_base_ops=_reference_base_ops(case, states[case.seed]))
                    diffs = compare_kernel(case, result)
                else:
                    diffs = compare(case, result)
            except Exception as exc:  # noqa: BLE001
                diffs = [f"{type(exc).__name__}: {exc}"]
            if diffs:
                count.failed += 1
                if len(count.diffs) < 5:
                    count.diffs.append(f"{case.source} {case.operator} #{case.example_index}: " + "; ".join(diffs[:3]))
            else:
                count.passed += 1
    return report


def published_hashes(root: Path = DEFAULT_ROOT) -> dict[str, str]:
    """Hash every published source that the harness reads, excluding clock data."""
    root = Path(root)
    paths = set()
    for world in WORLDS:
        if world == "clock":
            continue
        for source in _world_files(world, root):
            paths.add(source)
            data = json.loads(source.read_text(encoding="utf-8"))
            paths.update((root / data["steps"]).glob("*.json"))
        tasks = root / world / "tasks.json"
        if tasks.is_file():
            paths.add(tasks)
            data = json.loads(tasks.read_text(encoding="utf-8"))
            paths.update((root / data["files"]).glob("*.json"))
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(paths)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("worlds", nargs="*", help="worlds to check (default: all)")
    parser.add_argument("--manifest", action="store_true", help="rewrite the published-data hash manifest")
    parser.add_argument("--include-clock", action="store_true")
    parser.add_argument("--engine", choices=("current", "kernel"), default="current",
                        help="the current interpreter or the atoms-v2 kernel (legacy-v1 dialect)")
    args = parser.parse_args()
    for world in args.worlds:
        if world not in WORLDS:
            parser.error(f"unknown world {world!r}; choose from {', '.join(WORLDS)}")
    if args.manifest:
        MANIFEST.parent.mkdir(parents=True, exist_ok=True)
        MANIFEST.write_text(json.dumps(published_hashes(), indent=2, ensure_ascii=False) + "\n",
                            encoding="utf-8")
        print(f"Wrote {MANIFEST}")
        return
    engine = KernelEngine() if args.engine == "kernel" else CurrentEngine()
    report = run_golden(engine, tuple(args.worlds) if args.worlds else WORLDS,
                        include_clock=args.include_clock)
    print(report)
    if any(count.failed for count in report.worlds.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
