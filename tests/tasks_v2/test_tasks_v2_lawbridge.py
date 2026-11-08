"""Law and bridge task, replay and commuting invariants."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.values import Card, Unknown, encode, outcome_equal
from opulse.tasks_v2 import kernel_engine as engine
from opulse.tasks_v2 import lawbridge as lb
from opulse.tasks_v2.angles import bridge, law
from opulse.tasks_v2.build_lawbridge import build
from opulse.tasks_v2.task import Task


@pytest.mark.parametrize("module", [law, bridge])
@pytest.mark.parametrize("angle", law.ANGLES)
def test_reference_perturbation_and_determinism(module, angle):
    prompts = set()
    questions = set()
    for index in range(8):
        task = module.generate(angle, 13, index)
        assert task.to_dict() == module.generate(angle, 13, index).to_dict()
        assert Task.from_dict(task.to_dict()) == task
        assert task.prompt["en"].isascii() and "Answer format:" in task.prompt["en"]
        assert len(task.prompt["en"]) < 1500
        assert "Checked assignments: [" not in task.prompt["en"]
        assert "opulse.value/2" not in task.prompt["en"]
        if module is law and angle == "compute":
            assert "gcd(" not in task.prompt["en"] and "frac_add(" not in task.prompt["en"]
        if module is bridge and task.question["name"].endswith("pair_to_frac"):
            assert "MUL(" not in task.prompt["en"] and "iappend(" not in task.prompt["en"]
        prompts.add(task.prompt["en"])
        questions.add(json.dumps(task.question, sort_keys=True))
        answer = task.reference.get("outcome", task.reference.get("answer", task.reference.get("choice", task.reference.get("definition"))))
        assert lb.grade(task, answer).correct
        if angle == "decide" and not answer["true"]:
            if module is law:
                record = law._law(task)
                row = next(row for row in task.grader["scope"]["assignments"]
                           if not lb.law_instance(record, tuple(lb.unpack(value) for value in row)))
                answer = {**answer, "counterexample": row}
            else:
                record = bridge._bridge(task)
                pair, row = next((pair, row) for pair in record.interface for row in task.grader["scope"]["assignments"]
                                 if lb.bridge_instance(record, pair, tuple(lb.unpack(value) for value in row)) is False)
                answer = {**answer, "counterexample": {"op": list(pair), "value": row}}
        assert module.grade(task, answer).correct, (module.__name__, angle, index)
        assert not module.grade(task, None).correct
        if angle == "compute":
            assert not module.grade(task, {"ok": encode("wrong")}).correct
        elif angle == "invert":
            assert not module.grade(task, []).correct
        elif angle == "describe":
            assert not module.grade(task, next(option for option in task.question["options"]
                                               if option != answer)).correct
        elif angle == "decide":
            assert not module.grade(task, {"true": not answer["true"]}).correct
        elif module is bridge:
            record = bridge._bridge(task)
            bad = f"bridge ~bad: {record.source_sort} -> {record.target_sort} = increment(x)"
            assert not module.grade(task, bad).correct
        else:
            record = law._law(task)
            params = ", ".join(f"{name}: {sort}" for name, sort in record.variables)
            assert not module.grade(task, f"law #bad: eq(0, 0) for {params}").correct
        if angle == "decide" and not answer["true"]:
            assert not module.grade(task, {"true": False, "counterexample": []}).correct
        if angle in ("induce", "create"):
            assert answer not in task.prompt["en"]
    assert len(prompts) >= 8
    assert len(questions) == 8


@pytest.mark.parametrize("module", (law, bridge))
@settings(max_examples=8, deadline=None)
@given(st.integers(min_value=0, max_value=7))
def test_description_ignores_poisoned_reference_choice(module, index):
    task = module.generate("describe", 0, index)
    correct = task.reference["choice"]
    wrong = next(option for option in task.question["options"] if option != correct)
    poisoned = replace(task, reference={**task.reference, "choice": wrong})
    assert module.grade(poisoned, correct).correct
    assert not module.grade(poisoned, wrong).correct


def test_description_rejects_inconsistent_displayed_statement_and_interface():
    law_task = law.generate("describe", 0, 0)
    incorrect_law = replace(law_task, question={**law_task.question, "statement": "law #fake: eq(0, 1) for a: Int, b: Int"})
    assert not law.grade(incorrect_law, law_task.reference["choice"]).correct
    bridge_task = bridge.generate("describe", 0, 0)
    incorrect_bridge = replace(bridge_task, question={**bridge_task.question, "interface": [["bogus", "bogus"]]})
    assert not bridge.grade(incorrect_bridge, bridge_task.reference["choice"]).correct


def test_laws_bottom_unknown_and_relations():
    scope = ((0,),)
    both_bottom = lb.Law("both_bottom", (("x", "Int"),), n.Call("mod", (n.Var("x"), n.Lit(0))),
                         n.Call("mod", (n.Lit(1), n.Lit(0))), scope=scope)
    assert lb.check_law(both_bottom)
    assert not lb.check_law(replace(both_bottom, rhs=n.Lit(1)))
    assert not lb.check_law(replace(both_bottom, rhs=n.Lit(Unknown("fuel"))))
    assert lb.check_law(lb.Law("le", (("x", "Int"),), n.Var("x"), n.Lit(2), "le", scope))
    assert lb.check_law(lb.Law("implies", (("x", "Int"),), n.Lit(False), n.Lit(False), "implies", scope))
    assert lb.parse_law("law #contrapositive: implies(false, true) for x: Int", scope).relation == "implies"
    with pytest.raises(ValueError, match="parameters"):
        lb.parse_law("law #bad: eq(x, x) for malformed", scope)


def test_law_scope_replay_and_parser():
    original = lb.references()["add_comm"]
    parsed = lb.parse_law(str(original), original.scope)
    assert parsed == original
    assert lb.check_law(parsed)
    assert not lb.check_law(replace(parsed, scope=((99, 100),)))
    assert lb.nontrivial_law(parsed)
    assert not lb.nontrivial_law(replace(parsed, rhs=parsed.lhs))
    term = n.Call("add", (n.Lit(1), n.Lit(2)))
    rewritten = lb.apply_law(parsed, term, {"a": 1, "b": 2})
    assert rewritten == n.Call("add", (n.Lit(2), n.Lit(1)))
    assert outcome_equal(lb.evaluate(term), lb.evaluate(rewritten))
    with pytest.raises(ValueError, match="outside checked scope"):
        lb.apply_law(parsed, n.Call("add", (n.Lit(10), n.Lit(20))), {"a": 10, "b": 20})
    with pytest.raises(ValueError, match="checked equation"):
        lb.apply_law(lb.references()["sub_comm"], term, {"a": 1, "b": 2})
    with pytest.raises(ValueError, match="checked equation"):
        lb.apply_law(replace(original, evidence=lb.Evidence("sampled", original.scope)), term,
                     {"a": 1, "b": 2})


def test_law_creation_measures_scoped_derivations():
    task = law.generate("create", 7, 0)
    verdict = law.grade(task, task.reference["definition"])
    assert verdict.correct and verdict.detail["saving"] == task.reference["saving"]
    tampered = replace(task, question={**task.question, "derivations": [
        {**row, "assignment": [lb.pack(100), lb.pack(200)]}
        for row in task.question["derivations"]]})
    assert not law.grade(tampered, task.reference["definition"]).correct


def test_rewrite_paths_and_refused_step():
    for index in range(8):
        task = law.generate("compute", 4, index)
        assert len(task.question["steps"]) == 2
        assert "by #" in task.prompt["en"]
        assert law.grade(task, task.reference["outcome"]).correct
        if index % 4 == 0:
            assert task.reference["outcome"] == "refused at step 2"
            assert not law.grade(task, "refused at step 1").correct
        else:
            assert task.reference["outcome"].startswith("add(")
    original = lb.references()["add_comm"]
    with pytest.raises(ValueError, match="position"):
        lb.rewrite_at(original, n.Lit(1), (0,), {"a": 1, "b": 2})


def test_lemma_requires_generalization_and_all_endpoints():
    task = law.generate("create", 7, 0)
    assert task.reference["saving"] == len(task.question["derivations"])
    assert all(len(derivation["steps"]) == 2 for derivation in task.question["derivations"])
    source = task.question["derivations"][0]["source"]
    target = task.question["derivations"][0]["target"]
    assert not law.grade(task, f"law #concrete: eq({source}, {target}) for a: Int, b: Int").correct
    assert not law.grade(task, "law #identity: eq(add(a, b), add(a, b)) for a: Int, b: Int").correct
    broken = replace(task, question={**task.question, "derivations": [
        {**task.question["derivations"][0], "steps": ["add(0, 0)", "add(0, 0)"]},
        *task.question["derivations"][1:]]})
    assert not law.grade(broken, task.reference["definition"]).correct


@settings(max_examples=12, deadline=None)
@given(st.integers(min_value=-2, max_value=2), st.integers(min_value=-2, max_value=2))
def test_symbolic_rewrite_preserves_evaluation(left, right):
    assume(-3 <= left + right <= 3)
    record = lb.references()["add_comm"]
    binding = n.Call("add", (n.Lit(left), n.Lit(right)))
    source = n.Call("add", (binding, n.Lit(1)))
    rewritten = lb.rewrite_expression(record, source, {"a": binding, "b": n.Lit(1)})
    assert outcome_equal(lb.evaluate(source), lb.evaluate(rewritten))


def test_symbolic_rewrite_refuses_unchecked_result():
    record = lb.references()["add_comm"]
    expression = n.Call("add", (n.Lit(2), n.Lit(2)))
    source = n.Call("add", (expression, n.Lit(1)))
    with pytest.raises(ValueError, match="outside checked scope"):
        lb.rewrite_expression(record, source, {"a": expression, "b": n.Lit(1)})
    sampled = replace(record, evidence=lb.Evidence("sampled", record.scope))
    with pytest.raises(ValueError, match="checked equation"):
        lb.rewrite_expression(sampled, n.Call("add", (n.Lit(1), n.Lit(2))),
                              {"a": n.Lit(1), "b": n.Lit(2)})


def test_induction_samples_are_unnamed_and_checked():
    task = law.generate("induce", 0, 0)
    assert all(len(row) == 3 for row in task.question["examples"])
    assert "eq(" not in task.prompt["en"].split("Answer format:")[0]
    wrong = "law #wrong: eq(add(a, b), mul(a, b)) for a: Int, b: Int"
    assert not law.grade(task, wrong).correct


def test_bridge_partial_domain_is_not_counterexample():
    task = bridge.generate("decide", 0, 2)
    record = bridge._bridge(task)
    outside = next(row for row in record.scope if any(
        isinstance(value, Card) and value.sort == "pair[int,int]" and value.fields[1] == 0 for value in row))
    assert lb.bridge_instance(record, record.interface[0], outside) is None
    fake = {"true": False, "counterexample": {"op": list(record.interface[0]),
                                                "value": [lb.pack(value) for value in outside]}}
    assert not bridge.grade(task, fake).correct


def test_ascii_answers_and_local_definitions():
    for index in range(8):
        task = bridge.generate("compute", 3, index)
        result = lb.outcome_unwire(task.reference["outcome"])
        assert bridge.grade(task, lb.display(result.value)).correct
    task = bridge.generate("invert", 3, 1)
    assert task.question["mode"] == "preimage"
    assert bridge.grade(task, [lb.display(lb.unpack(value)) for value in task.reference["answer"]]).correct
    task = law.generate("invert", 3, 0)
    expected = [lb.display_scope((tuple(lb.unpack(value) for value in row),))[1:-1]
                for row in task.reference["answer"]]
    assert law.grade(task, expected).correct


def test_law_descriptions_have_refuting_instances():
    for index in range(8):
        task = law.generate("describe", 2, index)
        record = law._law(task)
        assignment = tuple(lb.unpack(value) for value in task.question["examples"][0])
        bindings = dict(zip((name for name, _ in record.variables), assignment))
        left, right = lb.evaluate(record.lhs, bindings), lb.evaluate(record.rhs, bindings)
        assert outcome_equal(left, right)
        assert left.value not in (0, 1, engine.fraction(0, 1), engine.fraction(1, 1))


def test_bridges_commute_domain_unknown_and_counterexample():
    records = lb.bridges()
    for name in ("pair_to_frac", "ilist_to_list", "mul8"):
        assert lb.check_bridge(records[name])
    assert isinstance(lb._scope("integer@1").resolve("pair_add"), kernel.Defn)
    assert isinstance(lb._scope("integer@1").resolve("invented_list_sum"), kernel.Defn)
    assert isinstance(lb._scope("computer@1").resolve("invented_square8"), kernel.Defn)
    native = records["ilist_to_list"].apply(engine.ilist((1, 2)))
    assert outcome_equal(native, kernel.call("list_append", ((1,), (2,)), engine.scope("lists@1")).outcome)
    assert outcome_equal(lb.evaluate(n.Call("list_sum", (n.Lit(native.value),)), world="lists@1"),
                         kernel.call("list_sum", ((1, 2),), engine.scope("lists@1")).outcome)
    for name in ("broken_pair_to_frac", "broken_ilist_to_list", "broken_mul8"):
        assert not lb.check_bridge(records[name])
    pair = records["pair_to_frac"]
    assert lb.bridge_instance(pair, pair.interface[0], (Card("pair[int,int]", "pair", (1, 0)), Card("pair[int,int]", "pair", (1, 2)))) is None
    assert lb.bridge_instance(records["broken_mul8"], records["broken_mul8"].interface[0], (0, 1)) is False
    assert not lb.check_bridge(replace(pair, map=n.Lit(Unknown("fuel"))))
    assert lb.parse_bridge(bridge._map_notation(pair), pair) == pair
    bottom_bridge = lb.Bridge("partial", "Int", "Int", n.Var("x"), (("mod", "mod"),),
                              n.Lit(True), ((1, 0),))
    assert lb.bridge_instance(bottom_bridge, ("mod", "mod"), (1, 0)) is True
    assert lb.check_bridge(bottom_bridge)
    assert not lb.check_bridge(replace(bottom_bridge, interface=(("mod", "missing_op"),)))
    assert not lb.check_bridge(replace(bottom_bridge, scope=((7, 0),)))
    assert not lb.check_bridge(replace(bottom_bridge, domain=n.Lit(False)))
    assert not lb.check_bridge(replace(bottom_bridge, domain=n.Lit(Unknown("fuel"))))


@settings(max_examples=16, deadline=None)
@given(st.integers(min_value=-3, max_value=3), st.integers(min_value=-3, max_value=3))
def test_promoted_law_rewrite_preserves_result(left, right):
    original = lb.references()["add_comm"]
    term = n.Call("add", (n.Lit(left), n.Lit(right)))
    result = lb.apply_law(original, term, {"a": left, "b": right})
    assert outcome_equal(lb.evaluate(term), lb.evaluate(result))


@settings(max_examples=16, deadline=None)
@given(st.integers(min_value=0, max_value=255), st.integers(min_value=0, max_value=255))
def test_commuting_bridge_preserves_result(left, right):
    original = lb.bridges()["mul8"]
    checked = ((left, right), (left,))
    candidate = replace(original, scope=checked, evidence=lb.Evidence("bounded", checked))
    assert lb.bridge_instance(candidate, candidate.interface[0], (left, right)) is True
    assert lb.bridge_instance(candidate, candidate.interface[1], (left,)) is True
    assert lb.evaluate(n.Call("MUL", (n.Lit(left), n.Lit(right))), world="computer@1").value == left * right % 256
    assert lb.check_bridge(candidate)


def test_builder_frozen_samples(tmp_path):
    paths = build(out=tmp_path)
    assert len(paths) >= 12
    assert sum(len(json.loads(path.read_text())) for path in paths) == 96
    for path in paths:
        assert path.read_text().isascii()
        assert path.read_bytes() == (Path("worlds/tasks") / path.relative_to(tmp_path)).read_bytes()
        for data in json.loads(path.read_text()):
            task = Task.from_dict(data)
            assert task.to_dict() == data
            grader = lb.grade(task, next(task.reference[key] for key in ("outcome", "answer", "choice", "definition")
                                         if key in task.reference))
            assert grader.correct
    with pytest.raises(ValueError):
        build(per_angle=7, out=tmp_path)


@pytest.mark.parametrize("module", (law, bridge))
def test_decide_truth_is_not_parity_or_a_name_hint(module):
    for seed in (0, 7):
        tasks = [module.generate("decide", seed, index) for index in range(16)]
        for parity in (0, 1):
            assert {task.reference["answer"]["true"] for task in tasks[parity::2]} == {True, False}
        for task in tasks:
            assert not any(hint in task.prompt["en"].lower() for hint in
                           ("broken_", "wrong_", "false_", "valid_"))
            assert module.grade(task, task.reference["answer"]).correct


def test_bridge_coverage_excludes_unchecked_scope():
    original = lb.bridges()["pair_to_frac"]
    checked, excluded = lb.bridge_coverage(original)
    assert len(checked) == 4 and len(excluded) == 5
    assert len(original.evidence.scope) == 4
    assert set(original.evidence.scope) == {row for _, row in checked}
    assert all(lb.bridge_instance(original, pair, row) is not None for pair, row in checked)
    assert all(lb.bridge_instance(original, pair, row) is None for pair, row in excluded)
    task = bridge.generate("decide", 0, 2)
    evidence = task.grader["scope"]
    assert evidence["size"] == evidence["checked"]
    assert evidence["excluded_count"] == len(excluded)
    assert len(evidence["checked_cases"]) == evidence["checked"]
    assert len(evidence["excluded_cases"]) == evidence["excluded_count"]
    assert all(lb.bridge_instance(bridge._bridge(task), tuple(item["op"]),
                                  tuple(lb.unpack(value) for value in item["value"])) is None
               for item in evidence["excluded_cases"])
    assert f"{evidence['checked']} checked" in task.prompt["en"]
    assert f"{evidence['excluded_count']} excluded" in task.prompt["en"]


@given(st.integers(min_value=0, max_value=8))
@settings(max_examples=9, deadline=None)
def test_bridge_partition_is_exhaustive_for_every_scope_rotation(offset):
    original = lb.bridges()["pair_to_frac"]
    scope = original.scope[offset:] + original.scope[:offset]
    rotated = replace(original, scope=scope)
    checked, excluded = lb.bridge_coverage(rotated)
    assert len(checked) + len(excluded) == len(scope) * len(rotated.interface)
    assert not set(checked) & set(excluded)
