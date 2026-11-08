"""Differential checks for the legacy-v1 adapter (spec section 13.2)."""

import json
import random
from dataclasses import replace

from opulse.atoms import nodes as n
from opulse.atoms.golden import DEFAULT_ROOT, KernelEngine, iter_cases
from opulse.atoms.kernel import call, evaluate, inline
from opulse.atoms.legacy import scope_from_registry, scope_from_skills
from opulse.atoms.values import Bottom, outcome_equal
from opulse.core.operator import PREFIX, Operator
from opulse.core.registry import OperatorRegistry
from opulse.core.semantics import NAN, Semantics
from opulse.core.types import same_value
from opulse.definition import ast
from opulse.definition.codegen import registry_resolver
from opulse.definition.interpreter import ReferenceInterpreter
from opulse.worlds.action import Skill, initial_state, run_skill


def test_structural_translation_and_nan():
    engine = KernelEngine()
    state = engine.load(json.loads((DEFAULT_ROOT / "integer.json").read_text()))
    scope = state.scope
    assert any(isinstance(defn.body, n.Let) for defn in scope.defns.values())
    assert scope.atoms["__legacy_nan"].cost == 0
    assert scope.atoms["__legacy_compare_<"].cost == 0
    assert isinstance(call("__legacy_nan", (), scope, dialect="legacy-v1").outcome, Bottom)
    compare = n.Case(((n.Test(n.Call("__legacy_compare_<", (n.Lit(NAN), n.Lit(2)))),
                       n.Lit(1)),), n.Lit(0))
    result = evaluate(compare, scope=scope, dialect="legacy-v1")
    assert result.outcome == Bottom("nan_condition") and result.steps == 0


def test_search_conditions_typed_guard_and_nan_steps():
    plus = Operator("plus", "+", 2)
    search = Operator("seek", "?", 1, PREFIX, definition="search")
    typed = Operator("typed", "!", 1, PREFIX, definition="typed",
                     parameter_types=("str",), result_type="str")
    bad = Operator("bad", "~", 1, PREFIX, definition="bad")
    logic = Operator("logic", "^", 1, PREFIX, definition="logic")
    registry = OperatorRegistry((plus, search, typed, bad, logic))
    seek_ast = ast.Definition(ast.Apply("?", (ast.Var("a"),), PREFIX),
                              (ast.Branch(ast.Search("index", 3, ast.Compare(
                                  ast.Apply("+", (ast.Var("index"), ast.Num(1))),
                                  "==", ast.Var("a")))),))
    typed_ast = ast.Definition(ast.Apply("!", (ast.Var("a"),), PREFIX),
                               (ast.Branch(ast.Var("a")),))
    bad_ast = ast.Definition(ast.Apply("~", (ast.Var("a"),), PREFIX),
                             (ast.Branch(ast.Num(1), ast.And(ast.Compare(
                                 ast.Apply("+", (ast.NaN(), ast.Num(1))), "==", ast.Num(1)),
                                 ast.Truth(ast.Literal(True)))), ast.Branch(ast.Num(0), is_else=True)))
    logic_ast = ast.Definition(ast.Apply("^", (ast.Var("a"),), PREFIX),
                               (ast.Branch(ast.Num(7), ast.Or(ast.Not(ast.Truth(
                                   ast.Literal(False))), ast.Compare(ast.NaN(), "==", ast.Num(0)))),
                                ast.Branch(ast.Num(8), is_else=True)))
    definitions = {"search": seek_ast, "typed": typed_ast, "bad": bad_ast,
                   "logic": logic_ast}

    class Parser:
        def parse(self, definition):
            return definitions[definition]

    semantics = Semantics()
    scope, _ = scope_from_registry(registry, semantics, Parser())
    charged = call("plus", (NAN, 2), scope, dialect="legacy-v1")
    assert isinstance(charged.outcome, Bottom) and charged.steps == 1
    reference = ReferenceInterpreter(registry_resolver(registry),
                                     lambda operator: definitions[operator.definition], semantics)
    for operator, arguments in ((search, (3,)), (search, (0,)), (typed, ("abc",)),
                                (typed, (2,)), (bad, (5,)), (logic, (9,))):
        actual = call(operator.func_id, arguments, scope, dialect="legacy-v1")
        expected = reference.evaluate(operator, arguments)
        assert same_value(actual.outcome.value if hasattr(actual.outcome, "value") else NAN,
                          expected.value)
        assert actual.steps == expected.base_ops
    assert call("bad", (5,), scope, dialect="legacy-v1").outcome == Bottom("nan_condition")


def test_robot_repeat_exhaust_and_zero():
    start = initial_state()
    for bound in (0, 1, 2):
        skill = Skill("test", 1, "recursion", "turn_left", guard="front_wall",
                      expected=True, bound=bound)
        library = {skill.name: skill}
        scope, _ = scope_from_skills(library)
        reference, steps = run_skill(skill, start, library)
        result = call(skill.name, (start,), scope, dialect="legacy-v1", trace=True)
        assert same_value(reference, result.outcome.value)
        assert result.steps == sum(step["kind"] == "atom" for step in steps)
        probes = [node for node in _frames(result.trace) if node.name == "front_wall"]
        assert len(probes) == bound

    blocked = Skill("blocked", 1, "composition", "forward", "turn_left")
    wall = replace(start, robot=(7, 7), facing=type(start.facing)("E"))
    scope, _ = scope_from_skills({blocked.name: blocked})
    result = call(blocked.name, (wall,), scope, dialect="legacy-v1")
    assert result.outcome == Bottom("blocked")
    assert result.steps == 0


def _frames(root):
    yield root
    for child in root.children:
        yield from _frames(child)


def test_published_seeded_differential_and_inline():
    rng = random.Random(936)
    pairs = set()
    for world in ("integer", "bits", "logic", "strings"):
        engine = KernelEngine()
        state = engine.load(json.loads((DEFAULT_ROOT / f"{world}.json").read_text()))
        cases = [case for case in iter_cases(world, main_only=True) if case.kind == "operator_example"
                 and case.seed == state.reference.seed]
        for case in rng.sample(cases, k=85):
            op = next(op for op in state.reference.ordered
                      if state.reference.name(op) == case.operator)
            pairs.add((world, op.func_id, repr(case.inputs)))
            reference = state.reference.oracle.evaluate(op, case.inputs)
            result = engine.run(state, case)
            assert same_value(result.output, reference.value), (world, case.operator)
            assert result.base_ops == reference.base_ops, (world, case.operator)
            named = n.Call(op.func_id, tuple(n.Lit(value) for value in case.inputs))
            unfolded = evaluate(inline(named, state.scope), scope=state.scope, dialect="legacy-v1")
            direct = call(op.func_id, case.inputs, state.scope, dialect="legacy-v1")
            assert outcome_equal(unfolded.outcome, direct.outcome), (world, case.operator)
            assert unfolded.steps == direct.steps, (world, case.operator)
    assert len(pairs) >= 300


def test_legacy_definition_records_round_trip():
    from opulse.atoms.legacy import legacy_definition_records
    from opulse.atoms.spec import Definition

    engine = KernelEngine()
    state = engine.load(json.loads((DEFAULT_ROOT / "integer.json").read_text()))
    records = legacy_definition_records(state.reference.tools.registry, state.scope)
    given = [record for record in records if record.origin == "given"]
    invented = [record for record in records if record.origin == "invented"]
    assert given and invented and all(record.layer == 0 for record in given)
    assert all(record.layer >= 1 and record.spec.extra["legacy_definition"] for record in invented)
    for record in records:
        assert Definition.from_dict(json.loads(json.dumps(record.to_dict()))) == record
        assert record.validate() == []
