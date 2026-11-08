"""Legacy-v1 evaluation adapter (docs/spec/atoms-v2.md, sections 3 and 13).

All legacy evaluation lives here; the kernel adapter can replace this module alone.
The legacy interpreter has no step-budget hook: fuel is checked against counted
layer-0 operations after evaluation. Its recursion-depth guard bounds recursive calls.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from opulse.atoms.values import Bottom, Card, Ok, Unknown, boolean
from opulse.config import Settings
from opulse.core.operator import Operator
from opulse.core.primitives import atom_records
from opulse.core.registry import OperatorRegistry
from opulse.core.semantics import NAN
from opulse.definition import ast
from opulse.definition.codegen import compile_definition, registry_resolver
from opulse.definition.interpreter import EngineError
from opulse.verify.oracle import Oracle


@lru_cache(maxsize=8)
def _published(world: str) -> dict:
    path = Path(__file__).resolve().parents[3] / "docs/assets/data/worlds" / f"{world.split('@')[0]}.json"
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=8)
def _base(world: str):
    from opulse.core.presets import PRESETS as typed
    from opulse.presets import PRESETS as numeric

    world = world.split("@")[0]
    if world not in typed and world not in numeric:
        raise ValueError(f"unknown legacy world {world!r}")
    names = typed[world] if world in typed else numeric[world]["atoms"]
    settings = Settings.from_dict({"preset": world})
    return settings, tuple(Operator.from_dict(row) for row in atom_records(names, seed=0))


def _oracle(world: str, definitions: dict[str, str]) -> Oracle:
    return _cached_oracle(world, tuple(definitions.items()))


@lru_cache(maxsize=256)
def _cached_oracle(world: str, definitions: tuple[tuple[str, str], ...]) -> Oracle:
    settings, operators = _base(world)
    registry = OperatorRegistry(operators)
    parser = Oracle(registry, settings.symbols, settings.semantics.build()).parser
    pending = []
    published = {row["name"]: row for row in _published(world)["operators"]}
    for index, (name, text) in enumerate(definitions):
        parsed = parser.parse(text)
        if parsed.lhs.symbol != name:
            raise ValueError("definition name mismatch")
        signature = published.get(name, {})
        parameter_types = tuple(param["type"] for param in signature.get("params", ()))
        if len(parameter_types) != parsed.lhs.n_ary:
            parameter_types = ("int",) * parsed.lhs.n_ary
        operator = Operator(func_id=f"task_{index}", symbol=name, n_ary=parsed.lhs.n_ary,
                            unary_position=parsed.lhs.unary_position, definition=text,
                            definition_type="simple_definition",
                            parameter_types=parameter_types, result_type=signature.get("result_type", "int"),
                            op_compute_func="reference_only", op_count_func="reference_only")
        registry.add(operator)
        parser.add(operator)
        pending.append((operator, parsed))
    for operator, parsed in pending:
        code = compile_definition(parsed, operator.func_id, registry_resolver(registry, operator),
                                  operator.parameter_types, operator.result_type)
        operator.op_compute_func, operator.op_count_func = code.compute, code.count
        operator.dependencies = list(code.dependencies)
    oracle = Oracle(registry, settings.symbols, settings.semantics.build())
    oracle.interpreter.max_depth = 128
    return oracle


def _outcome(result, fuel: int, reason: str = "undefined"):
    if result.base_ops > fuel:
        return Unknown("fuel"), result.base_ops
    if result.value is NAN:
        return Bottom(reason), result.base_ops
    value = result.value
    if isinstance(value, bool):
        value = boolean(value)
    elif isinstance(value, tuple) and all(type(item) is int for item in value):
        value = Card("list[int]", "list", value)
    return Ok(value), result.base_ops


def evaluate(world: str, definitions: dict[str, str], expression: str, fuel: int,
             variables: dict | None = None):
    oracle = _oracle(world, definitions)
    try:
        if variables:
            oracle.parser.notation.variables = tuple(variables)
        result = oracle.evaluate_expr(oracle.parser.parse_expr(expression), variables or {})
    except (EngineError, RecursionError):
        return Unknown("depth"), 0
    return _outcome(result, fuel, "div_zero" if "/ 0" in expression or "% 0" in expression else "undefined")


def call(world: str, definitions: dict[str, str], name: str, args: tuple, fuel: int):
    oracle = _oracle(world, definitions)
    operator = next((op for op in oracle.registry if op.symbol == name and op.n_ary == len(args)), None)
    if operator is None:
        raise ValueError(f"unknown operator {name!r}")
    try:
        reason = "div_zero" if name in ("/", "%") and args[-1] == 0 else "undefined"
        return _outcome(oracle.evaluate(operator, tuple(args)), fuel, reason)
    except (EngineError, RecursionError):
        return Unknown("depth"), 0


def parse_definition(world: str, text: str, definitions: dict[str, str] | None = None):
    settings, operators = _base(world)
    oracle = (_oracle(world, definitions) if definitions else
              Oracle(OperatorRegistry(operators), settings.symbols, settings.semantics.build()))
    parsed = oracle.parser.parse(text)
    if not parsed.branches or not all(isinstance(parameter, ast.Var) for parameter in parsed.lhs.args):
        raise ValueError("invalid definition parameters")
    if len(set(parsed.parameters)) != len(parsed.parameters):
        raise ValueError("duplicate parameter")
    allowed = {(op.symbol, op.n_ary, op.unary_position) for op in operators}
    if definitions:
        for helper in _oracle(world, definitions).registry:
            allowed.add((helper.symbol, helper.n_ary, helper.unary_position))
    allowed.add((parsed.lhs.symbol, parsed.lhs.n_ary, parsed.lhs.unary_position))
    for branch in parsed.branches:
        nodes = [branch.expr, branch.condition] if branch.condition else [branch.expr]
        for node in nodes:
            if any((app.symbol, app.n_ary, app.unary_position) not in allowed for app in ast.iter_applications(node)):
                raise ValueError("unknown or forbidden operator")
        if ast.free_variables(branch.expr) - set(parsed.parameters):
            raise ValueError("unknown variable")
    return parsed
