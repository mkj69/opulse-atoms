"""Definition-template pipeline and six-angle regression tests."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.library import Library, PipelineError, VerifyRequest
from opulse.atoms.values import Ok, outcome_equal
from opulse.tasks_v2 import lawbridge as lb
from opulse.tasks_v2 import templates
from opulse.tasks_v2.angles import template
from opulse.tasks_v2.build_templates import build
from opulse.tasks_v2.task import Task


@pytest.mark.parametrize("family, header", (
    ("Quot", "obj Quot[T, canon] = refine T canon(canon)"),
    ("Interval", "obj Interval[T, lt] = refine Pair<T, T> with lo <= hi"),
    ("Lift", "op Lift[f] = lift f through canon"),
    ("Until_stable", "comb @Until_stable[step] = iterate step to a fixed point"),
    ("Count", "obs ?Count[probe] = count consecutive true probe results"),
))
def test_ascii_template_grammar_and_json_backward_compatibility(family, header):
    assert template.parse_program(header) == template.PROGRAMS[family]
    assert template.parse_program(json.dumps(template.PROGRAMS[family])) == template.PROGRAMS[family]
    for angle in ("induce", "create"):
        task = template.generate(angle, 0, next(index for index, case in enumerate(template.CASES)
                                                 if case[0] == family))
        assert template.grade(task, header).correct
        assert '"kind":' not in task.prompt["en"]
        assert template.RULES[family] not in task.prompt["en"]


def test_family_membership_and_content_keys():
    first = templates.QUOT
    case = template.CASES[0]
    request = template.request_for(case, template.value_for(case))
    certified = first.check_family(((case[1], case[2], request),),
                                   lambda _: templates.library())
    member = certified.instantiate(case[1], "Hour", cite=True,
                                   world_hash=templates.library().world.world_hash())
    assert member.id == first.key(case[1])
    assert "Quot[Int, mod12]" in member.depends_on
    assert first.key(("int", "mod2")) != member.id
    assert first.key(("Int", "mod12")) == member.id
    assert templates.QUOT.display(("Pair<Int, Int>", "reduce")) == "Quot[Pair<Int, Int>, reduce]"
    box = templates.Template("Box", "object", (("item", "value"),), lambda *_: None)
    assert box.key((14,)) != box.key(("14",))
    assert box.key((template.value_for(template.CASES[2]),)) != box.key((14,))
    with pytest.raises(PipelineError, match="another world"):
        certified.instantiate(case[1], "Hour", cite=True, world_hash="other-world")
    with pytest.raises(PipelineError, match="outside"):
        certified.instantiate(("int", "mod2"), "Parity", cite=True)
    with pytest.raises(PipelineError, match="outside"):
        first.instantiate(case[1], "Hour", cite=True)


def test_template_body_identity_and_family_citation():
    base = templates.QUOT
    altered = template.candidate_template({**template.PROGRAMS["Quot"],
        "body": {**template.PROGRAMS["Quot"]["body"], "canon": "identity"}}, "Quot")
    args = ("int", "mod12")
    assert base.instantiate(args, "Hour").id != altered.instantiate(args, "Hour").id
    case = template.CASES[0]
    request = template.request_for(case, template.value_for(case))
    certified = base.check_family(((args, "Hour", request),), lambda _: templates.library())
    assert altered.key(args) not in certified.evidence.members
    with pytest.raises(PipelineError, match="outside"):
        replace(altered, evidence=certified.evidence).instantiate(
            args, "Hour", cite=True, world_hash=templates.library().world.world_hash())


@given(st.sampled_from(("mod2", "mod12", "reduce")))
@settings(max_examples=3, deadline=None)
def test_template_identity_changes_with_declarative_body(canonicalizer):
    altered = template.candidate_template({**template.PROGRAMS["Quot"],
        "body": {**template.PROGRAMS["Quot"]["body"], "canon": "identity"}}, "Quot")
    sort = "pair[int,int]" if canonicalizer == "reduce" else "int"
    arguments = (sort, canonicalizer)
    assert templates.QUOT.key(arguments) != altered.key(arguments)
    assert templates.QUOT.key(arguments) == templates.QUOT.key(arguments)


@pytest.mark.parametrize("family,args,world", [
    (templates.COMM, ("add",), "integer@1"),
    (templates.COMM, ("mul",), "integer@1"),
    (templates.CANON, ("pair[int,int]", "fraction_canon"), "integer@1"),
    (templates.CANON, ("IList", "as_list"), "lists@1"),
])
def test_statement_templates_verify_and_bind_scope(family, args, world):
    instance = family.instantiate(args, "example")
    assert instance.verify() and instance.depends_on == (family.display(args),)
    request = VerifyRequest("bounded", instance.statement.scope, {"size": len(instance.statement.scope)})
    checked = family.check_family(((args, "example", request),), lambda _: templates.library(world))
    cited = checked.instantiate(args, "example", cite=True,
                                world_hash=templates.library(world).world.world_hash())
    assert cited.verify()
    if family is templates.CANON:
        checked_cases, excluded = lb.bridge_coverage(cited.statement)
        evidence = checked.evidence.scope["members"][cited.id]["verification"]
        assert evidence["size"] == len({row for _, row in checked_cases})
        assert len(evidence["excluded"]) == len(excluded)
    promoted = cited.promote()
    assert promoted.status == "promoted" and promoted.id == cited.id
    assert promoted.evidence == cited.evidence and promoted.statement.scope == cited.statement.scope
    with pytest.raises(PipelineError):
        checked.instantiate(args, "example", cite=True, world_hash="other")
    with pytest.raises(PipelineError):
        family.check_family(((args, "example", replace(request, domain=((999,),))),),
                            lambda _: templates.library(world))
    with pytest.raises(PipelineError):
        replace(cited, evidence=lb.Evidence("sampled", cited.statement.scope)).promote()
    sampled = family.check_family(((args, "example", replace(request, method="sampled")),),
                                  lambda _: templates.library(world))
    with pytest.raises(PipelineError):
        sampled.instantiate(args, "example", cite=True,
                            world_hash=templates.library(world).world.world_hash()).promote()


@pytest.mark.parametrize("angle", template.ANGLES)
@pytest.mark.parametrize("index", (15, 16, 17, 18))
def test_statement_template_tasks(angle, index):
    task = template.generate(angle, 1, index)
    answer = task.reference[{"compute": "outcome", "invert": "answer", "decide": "answer",
                             "describe": "choice", "induce": "definition", "create": "definition"}[angle]]
    assert template.grade(task, answer).correct
    if angle == "decide" and not answer["true"]:
        assert task.source["template_evidence"] is None
    else:
        assert task.source["template_id"] in task.source["template_evidence"]["members"]
    if angle in ("induce", "create"):
        assert answer not in task.prompt["en"]


def test_template_layer_scope_is_enforced_on_reuse():
    library = templates.library()
    case = template.CASES[0]
    first = templates.QUOT.instantiate(case[1], "Hour")
    templates.advance_instance(library, first, template.request_for(case, 14))
    second = templates.QUOT.instantiate(case[1], "OtherHour")
    with pytest.raises(PipelineError, match="does not cover"):
        templates.advance_instance(library, second, template.request_for(case, 25))


def test_citing_family_requires_recorded_inputs():
    case = template.CASES[0]
    request = template.request_for(case, 14)
    family = templates.QUOT.check_family(((case[1], case[2], request),),
                                        lambda _: templates.library())
    library = templates.library()
    member = family.instantiate(case[1], case[2], cite=True,
                                world_hash=library.world.world_hash())
    with pytest.raises(PipelineError, match="family evidence does not cover"):
        templates.advance_instance(library, member, template.request_for(case, 25))
    with pytest.raises(PipelineError, match="family evidence does not cover"):
        templates.advance_instance(templates.library("clock@2"), member, request)
    assert templates.advance_instance(library, member, request).status == "promoted"


@pytest.mark.parametrize("case", template.CASES)
def test_instance_uses_its_own_library_evidence(case):
    family, arguments, name, _, world = case
    value = template.value_for(case)
    library = templates.library(world)
    definition = template.REGISTRY[family].instantiate(arguments, name)
    result = templates.advance_instance(library, definition, template.request_for(case, value))
    assert result.status == "promoted"
    assert result.evidence is not None and result.evidence.scope["size"] == 1
    assert result.evidence.content_hash == library.content_hash(name)
    assert template.outcome(case, value) is not None
    assert result.layer == 2
    assert library.get(result.depends_on[0]).status == "promoted"


@given(st.integers(min_value=-100, max_value=100))
@settings(max_examples=12, deadline=None)
def test_quotient_matches_expanded_body(value):
    case = template.CASES[0]
    library = templates.library()
    definition = templates.QUOT.instantiate(case[1], "Hour")
    templates.advance_instance(library, definition, template.request_for(case, value))
    packaged = library.run("Hour.make", (value,))
    expression = kernel.inline(n.Call("Hour.make", (n.Lit(value),)), library.scope())
    expanded = kernel.evaluate(expression, scope=library.scope(), dialect=library.dialect)
    assert outcome_equal(packaged.outcome, expanded.outcome)
    assert packaged.steps == expanded.steps
    normal = kernel.evaluate(library.get("Quot[Int, mod12]").body,
                             {"x": value}, library.scope()).outcome
    assert isinstance(packaged.outcome, Ok) and outcome_equal(
        Ok(packaged.outcome.value.fields[0]), normal)


def test_quotient_non_idempotent_rejected():
    library = templates.library()
    library.atoms += (kernel.Atom("bad_shift", 1, lambda value: value + 1),)
    definition = templates.QUOT.instantiate(("int", "mod12"), "Hour")
    from dataclasses import replace

    # The core now checks canon's layer; retain the template call to test idempotence.
    spec = replace(definition.spec, canon=n.Call("bad_shift", (
        n.Call("Quot[Int, mod12]", (n.Var("x"),)),)))
    with pytest.raises(PipelineError, match="canon_idempotent"):
        templates.advance_instance(library, replace(definition, spec=spec), VerifyRequest(
            "bounded", ((2,),), {"domain": "bounded", "size": 1}))


def test_non_idempotent_template_instance_cannot_be_promoted():
    library = templates.library()
    definition = templates.QUOT.instantiate(("int", "step_up"), "BadQuot")
    with pytest.raises(PipelineError, match="canon_idempotent"):
        templates.advance_instance(library, definition, VerifyRequest(
            "bounded", ((0,), (1,)), {"domain": "bounded 0..1", "size": 2}))
    decision = template.generate("decide", 0, 1)
    assert "Quot[Int, step_up]" in decision.prompt["en"]


def test_frac_boundary_opens_template_then_body():
    from opulse.tasks_v2 import kernel_engine as engine

    library = templates.library()
    case = template.CASES[2]
    value = engine.fraction(2, 4)
    definition = templates.QUOT.instantiate(case[1], "Frac")
    templates.advance_instance(library, definition, template.request_for(case, value))
    alias = definition.depends_on[0]
    assert templates.unfold_chain(definition) == ("Frac", alias)
    assert library.get(alias).depends_on == ("fraction_canon",)
    call = n.Call("Frac.make", (n.Lit(value),))
    expanded = kernel.inline(call, library.scope())
    assert any(isinstance(item, n.Call) and item.fn == "fraction_canon"
               for item in n.walk(expanded))
    assert outcome_equal(library.run("Frac.make", (value,)).outcome,
                         kernel.evaluate(expanded, scope=library.scope(), dialect=library.dialect).outcome)
    restored = Library.from_dict(library.to_dict(), library.world, library.atoms)
    assert restored.get("Frac").status == "promoted"
    assert outcome_equal(restored.run("Frac.make", (value,)).outcome,
                         library.run("Frac.make", (value,)).outcome)


@pytest.mark.parametrize("case", template.CASES[:7] + template.CASES[9:])
def test_instantiation_equals_full_unfold_on_recorded_scope(case):
    family, arguments, name, _, world = case
    value = template.value_for(case)
    library = templates.library(world)
    definition = template.REGISTRY[family].instantiate(arguments, name)
    templates.advance_instance(library, definition, template.request_for(case, value))
    inputs = value if isinstance(value, tuple) else (value,)
    call = n.Call(f"{name}.make" if family in ("Quot", "Interval") else name,
                  tuple(n.Lit(item) for item in inputs))
    wrapped = kernel.evaluate(call, scope=library.scope(), dialect=library.dialect)
    unfolded = kernel.evaluate(kernel.inline(call, library.scope()),
                               scope=library.scope(), dialect=library.dialect)
    assert outcome_equal(wrapped.outcome, unfolded.outcome)
    assert wrapped.steps == unfolded.steps


@given(st.integers(min_value=0, max_value=12))
@settings(max_examples=13, deadline=None)
def test_until_stable_matches_expanded_body(value):
    library = templates.library()
    definition = templates.UNTIL_STABLE.instantiate(("step_up",), "until12")
    case = template.CASES[6]
    templates.advance_instance(library, definition, template.request_for(case, value))
    alias = library.get("Until_stable[step_up]")
    expanded = kernel.evaluate(alias.body, {"x": value}, library.scope(), dialect=library.dialect)
    assert outcome_equal(library.run("until12", (value,)).outcome, expanded.outcome)


def test_until_stable_rejects_values_outside_finite_height():
    library = templates.library()
    definition = templates.UNTIL_STABLE.instantiate(("step_up",), "until12")
    with pytest.raises(PipelineError, match="finite height"):
        templates.advance_instance(library, definition, VerifyRequest(
            "bounded", ((-1,),), {"domain": "bounded -1", "size": 1},
            extra={"op_family": ["template_step_up"]}))


def test_reusable_candidate_must_match_held_out():
    from opulse.tasks_v2.angles.template import grade

    task = template.generate("create", 1, 1)
    assert grade(task, task.reference["definition"]).correct
    wrong = {**task.reference["definition"],
             "body": {**task.reference["definition"]["body"], "canon": "identity"}}
    assert not grade(task, wrong).correct


def test_task_cannot_cite_different_family_certificate():
    from opulse.tasks_v2.angles.template import grade

    task = template.generate("compute", 0, 0)
    other = template.generate("compute", 0, 3)
    tampered = replace(task, source={**task.source,
                                     "template_evidence": other.source["template_evidence"]})
    assert not grade(tampered, task.reference["outcome"]).correct


def test_memory_counter_resets_and_keeps_truth():
    case = template.CASES[7]
    wall = template.value_for(case)
    clear = template.value_for(case, 1)
    before = (wall, clear)
    assert template.outcome(case, (wall, wall)) == Ok(2)
    assert template.outcome(case, (wall, clear, wall)) == Ok(1)
    assert before == (wall, clear)
    library = templates.library("action@1")
    definition = templates.COUNT.instantiate(case[1], case[2])
    templates.advance_instance(library, definition, template.request_for(case, wall))
    alias = definition.depends_on[0]
    assert library.get(alias).kind == "observation"
    assert library.get(alias).depends_on == ("front_wall",)
    assert library.get(alias).status == "promoted"
    assert library.get(case[2]).layer == 2
    restored = Library.from_dict(library.to_dict(), library.world, library.atoms)
    assert restored.get(alias).status == "promoted"
    assert restored.get(case[2]).status == "promoted"


@given(st.sampled_from(("front_wall", "front_water")))
@settings(max_examples=2, deadline=None)
def test_count_declares_calls_in_body_and_memory(probe):
    definition = templates.COUNT.instantiate((probe,), "counter")
    memory = definition.spec.memory
    called = (n.references(definition.body) | n.references(memory["init"]) |
              n.references(memory["step"]))
    assert called == set(definition.depends_on)
    assert called == {f"Count[{probe}]", probe, "template_increment"}
    assert "depends_on does not match body references" in replace(
        definition, depends_on=(f"Count[{probe}]",)).validate()


@given(st.booleans(), st.integers(min_value=0, max_value=3))
@settings(max_examples=12, deadline=None)
def test_count_observation_unfolds_without_changing_truth(wall_present, memory):
    case = template.CASES[7]
    state = template.value_for(case, 0 if wall_present else 1)
    library = templates.library("action@1")
    definition = templates.COUNT.instantiate(case[1], case[2])
    templates.advance_instance(library, definition, template.request_for(case, state))
    before = state
    env = {"s": state, "memory": memory}
    direct = kernel.evaluate(definition.body, env, library.scope(), dialect=library.dialect)
    expanded = kernel.evaluate(kernel.inline(definition.body, library.scope()),
                               env, library.scope(), dialect=library.dialect)
    assert outcome_equal(direct.outcome, expanded.outcome)
    assert before == state


def test_interval_rejects_reversed_endpoints():
    from opulse.atoms.values import Bottom, Card

    case = template.CASES[3]
    library = templates.library()
    definition = templates.INTERVAL.instantiate(case[1], "IntInterval")
    templates.advance_instance(library, definition, template.request_for(case, template.value_for(case)))
    assert library.run("IntInterval.make", (Card("interval", "interval", (5, 2)),)).outcome == Bottom("invalid")


@given(st.integers(min_value=-48, max_value=48))
@settings(max_examples=12, deadline=None)
def test_quotient_hour_matches_clock_declaration(value):
    from opulse.tasks_v2.angles.template import clock_hour

    case = template.CASES[9]
    assert outcome_equal(Ok(template.outcome(case, value).value.fields[0]), clock_hour(value))


def test_sampled_family_does_not_promote():
    case = template.CASES[4]
    request = template.request_for(case, template.value_for(case))
    request = VerifyRequest("sampled", request.domain, request.scope,
                            seed=7, reference=request.reference)
    family = templates.LIFT.check_family(((case[1], case[2], request),),
                                        lambda _: templates.library())
    assert family.evidence.method == "sampled"
    assert family.instantiate(case[1], "frac_sum", cite=True,
                              world_hash=templates.library().world.world_hash()).status == "written"
    library = templates.library()
    instance = templates.advance_instance(library, family.instantiate(case[1], "frac_sum", cite=True,
                                                                 world_hash=library.world.world_hash()), request)
    assert instance.status == "verified"
    other_library = templates.library()
    with pytest.raises(PipelineError, match="family evidence does not cover"):
        templates.advance_instance(other_library, family.instantiate(
            case[1], "frac_sum", cite=True, world_hash=other_library.world.world_hash()),
            replace(request, seed=8))
    from opulse.atoms.spec import Contract

    with pytest.raises(PipelineError, match="sampled"):
        library.promote("frac_sum", Contract("not justified"))


@pytest.mark.parametrize("angle", template.ANGLES)
def test_angles_reference_and_wrong_answers(angle):
    from opulse.tasks_v2.angles.template import grade

    for index in range(len(template.CASES)):
        task = template.generate(angle, 7, index)
        answer = next(iter(task.reference.values()))
        assert grade(task, answer).correct, (angle, index)
        assert not grade(task, None).correct, (angle, index)
        assert task.prompt["en"].isascii()
        assert "Answer format:" in task.prompt["en"]


@pytest.mark.parametrize("angle", template.ANGLES)
def test_readable_varied_leak_free_questions(angle):
    families = set()
    for index in range(len(template.CASES)):
        task = template.generate(angle, 0, index)
        prompt = task.prompt["en"]
        families.add(task.question["template"])
        assert prompt.isascii() and all(char.isprintable() or char == "\n" for char in prompt)
        assert '"t":' not in prompt and "Ok(" not in prompt
        assert "Answer format:" in prompt
        if angle == "describe":
            assert task.question["template"] not in prompt
            assert template.RULES[task.question["template"]] not in prompt
            assert "Example 1:" in prompt and "Example 2:" in prompt
        if angle in ("compute", "invert", "decide"):
            assert "Argument rules:" in prompt or angle == "invert"
        if angle in ("induce", "create"):
            assert "Worked example of a different template" in prompt
            assert template.PROGRAMS[task.question["template"]] != template.PROGRAMS[
                "Interval" if task.question["template"] != "Interval" else "Quot"]
    assert families == set(template.REGISTRY)


def test_template_header_grading_and_perturbations():
    from opulse.tasks_v2.angles.template import grade

    quot = template.generate("create", 0, 0)
    header = "obj Example[T, canon] = refine T canon(canon)"
    assert grade(quot, header).correct
    assert not grade(quot, header.replace("canon(canon)", "canon(identity)")).correct
    interval = template.generate("create", 0, 3)
    assert grade(interval, "obj Range[T, lt] = refine Pair<T, T> with lo <= hi").correct
    assert grade(quot, json.dumps(quot.reference["definition"])).correct
    for angle in template.ANGLES:
        for index in range(len(template.CASES)):
            task = template.generate(angle, 0, index)
            reference = next(iter(task.reference.values()))
            assert grade(task, reference).correct, (angle, index)
            if angle == "compute":
                changed = {"bottom": "invalid"} if "ok" in reference else {"ok": 0}
            elif angle == "invert":
                changed = []
            elif angle == "decide":
                changed = {**reference, "true": not reference["true"]}
            elif angle == "describe":
                changed = next(option for option in task.question["options"] if option != reference)
            else:
                changed = {**reference, "params": []}
            assert not grade(task, changed).correct, (angle, index)


@given(st.integers(min_value=0, max_value=7))
@settings(max_examples=8, deadline=None)
def test_reachability_instance_matches_its_expanded_body(mask):
    case = next(item for item in template.CASES if item[2] == "reachable")
    library = templates.library()
    definition = templates.UNTIL_STABLE.instantiate(case[1], case[2])
    templates.advance_instance(library, definition, template.request_for(case, mask))
    expanded = kernel.evaluate(library.get(definition.depends_on[0]).body,
                               {"x": mask}, library.scope(), dialect=library.dialect)
    assert outcome_equal(library.run(case[2], (mask,)).outcome, expanded.outcome)


@given(st.integers(min_value=0, max_value=23), st.integers(min_value=0, max_value=23))
@settings(max_examples=10, deadline=None)
def test_hour_lift_is_canonical_and_unfoldable(left, right):
    case = next(item for item in template.CASES if item[2] == "hour_sum")
    library = templates.library()
    definition = templates.LIFT.instantiate(case[1], case[2])
    templates.advance_instance(library, definition, template.request_for(case, (left, right)))
    result = library.run(case[2], (left, right)).outcome
    expanded = kernel.evaluate(library.get(definition.depends_on[0]).body,
                               {"left": left, "right": right}, library.scope(),
                               dialect=library.dialect).outcome
    assert outcome_equal(result, expanded)
    assert result == Ok((left + right) % 12)


def test_examples_exercise_observation_memory():
    task = template.generate("create", 0, 7)
    examples = task.question["examples"]
    assert all(len(item["input"]) == 3 for item in examples)
    assert task.reference["held_out"] != [examples[0]["output"]]
    assert template.grade(task, task.reference["definition"]).correct


def test_printed_answers_and_argument_rules():
    task = template.generate("compute", 0, 5)
    assert "Hour<10>" in task.prompt["en"]
    assert "hour_add(a, b)" in task.prompt["en"]
    assert template.grade(task, "Hour<3>").correct
    assert not template.grade(task, "Hour<4>").correct
    inverse = template.generate("invert", 0, 0)
    assert "mod12(x)" in inverse.prompt["en"]
    assert "Target result: 2" in inverse.prompt["en"]
    assert "Hour<2>" not in inverse.prompt["en"]


def test_frozen_world_records(tmp_path):
    for path in build(out=tmp_path):
        import json

        tasks = json.loads(path.read_text())
        assert len(tasks) == len(template.CASES) + 4
        assert {task["kind"] for task in tasks[-4:]} == {"law", "bridge"}
        laws = {task["question"]["arguments"][0] for task in tasks[-4:] if task["kind"] == "law"}
        assert laws == ({"add", "sub"} if path.stem == "template_decide" else {"add", "mul"})
        assert all(Task.from_dict(task).family == "template" for task in tasks)
        assert path.read_text().isascii()
        frozen = Path(__file__).resolve().parents[2] / "worlds/tasks/templates" / path.name
        assert path.read_bytes() == frozen.read_bytes()
