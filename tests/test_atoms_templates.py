"""Template instantiation, family evidence and ordinary pipeline regression tests."""

from dataclasses import replace
from math import gcd

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from opulse.atoms import kernel, nodes
from opulse.atoms.boundary import Boundary
from opulse.atoms.library import Library, VerifyRequest, register_kind
from opulse.atoms.spec import (
    BridgeSpec,
    Contract,
    Definition,
    Edge,
    LawSpec,
    ObjectSpec,
    ObservationSpec,
    OperationSpec,
    TemplateSpec,
)
from opulse.atoms.templates import (
    check_template,
    cite_template_evidence,
    instantiate,
    verify_template,
)
from opulse.atoms.values import Card, Ok
from opulse.atoms.verify import unfold_equivalent_calls
from opulse.atoms.world import WorldDecl


def library():
    operations = (OperationSpec("add", "combine", (Edge("int"), Edge("int")), Edge("int"), "add"),)
    world = WorldDecl("templates", 1, "atoms-v2", {}, {}, (ObjectSpec("int", "given"),),
                      operations, {"nodes": list(nodes.NODE_NAMES), "recursion": "fuel"}, {}, {})
    return Library(world, (kernel.Atom("add", 2, lambda left, right: left + right),))


def template():
    spec = TemplateSpec("Lift", (("increment", "int"),), "operation",
                        {"name": "$increment", "role": "transform", "inputs": [{"sort": "int"}],
                         "output": {"sort": "int"}, "rule": "add $increment",
                         "input_names": ["arg0"],
                         "definition_body": nodes.to_json(nodes.Call("add", (nodes.Var("arg0"),
                                                                         nodes.Lit("$increment"))))})
    return Definition("Lift", "template", "invented", 1, (), spec, nodes.Lit(0))


def install_template(lib):
    register_kind("template", check_template, verify_template)
    definition = template()
    lib._definitions[definition.name] = definition
    lib.check(definition.name)
    lib.make_callable(definition.name, [(0,)])
    return lib.get(definition.name)


def request(increment):
    return VerifyRequest("bounded", ((0,), (3,)), {"domain": "bound 0..3", "size": 2},
                         reference=lambda value: value + increment)


def test_instantiation_pipeline_and_family_evidence():
    lib = library()
    base = install_template(lib)
    member_requests = [request(1), request(2)]
    family = [{"increment": 1}, {"increment": 2}]
    family_request = VerifyRequest("bounded", ((),), {"domain": "bounded family", "size": 1,
                                                       "family": family},
                                   extra={"family": family, "member_requests": member_requests})
    lib.verify(base.name, family_request)
    member = instantiate(lib.get(base.name), family[0], "one", lib=lib)
    assert member.depends_on == ("Lift", "add")
    assert member.spec.extra["template"]["args"] == family[0]
    assert cite_template_evidence(member, lib)
    lib.write(member)
    lib.check(member.name)
    lib.make_callable(member.name, [(3,)])
    lib.verify(member.name, request(1))
    lib.promote(member.name, Contract("increment by one"))
    assert lib.get("one").evidence.scope["domain"] == "bound 0..3"
    assert lib.get("one").contract.guarantees == "increment by one"
    assert lib.run("one", (3,)).outcome == Ok(4)
    trace = lib.run("one", (3,), trace=True).trace
    assert unfold_equivalent_calls(trace, [Boundary.unfold_all(), Boundary.unfold_none(),
                                          Boundary(open_names=frozenset({"Lift"}),
                                                   kinds=frozenset({"template"}))]).ok
    assert not cite_template_evidence(instantiate(lib.get("Lift"), {"increment": 3}, "three", lib=lib), lib)
    assert lib.get("one").evidence.content_hash == lib.content_hash("one")
    changed_pattern = {**lib.get("Lift").spec.pattern, "rule": "different rule"}
    previous = lib._definitions["Lift"]
    lib._definitions["Lift"] = replace(previous, spec=replace(previous.spec, pattern=changed_pattern))
    assert not cite_template_evidence(member, lib)


def test_invalid_family_or_member_fails_closed():
    lib = library()
    base = install_template(lib)
    family = [{"increment": 1}]
    bad = VerifyRequest("bounded", ((),), {"domain": "bounded family", "size": 1, "family": family},
                        extra={"family": family, "member_requests": [request(2)]})
    result = verify_template(base, lib, bad)
    assert not result.ok and "family member 0" in result.problems[0]
    assert not verify_template(base, lib, replace(bad, method="exhaustive")).ok
    assert not verify_template(base, lib, replace(bad, scope={"family": []})).ok


def test_object_and_node_substitution():
    lib = library()
    pattern = {"form": "refine", "base": "$T", "valid": nodes.to_json(nodes.Lit(True)),
               "canon": nodes.to_json(nodes.Call("$canon", (nodes.Var("x"),)))}
    spec = TemplateSpec("Quot", (("T", "sort"), ("canon", "operation")), "object", pattern)
    base = Definition("Quot", "template", "invented", 1, (), spec, nodes.Lit(0))
    canon = OperationSpec("mod12", "transform", (Edge("int"),), Edge("int"), "mod12")
    lib.atoms += (kernel.Atom("mod12", 1, lambda value: value % 12),)
    lib._definitions["mod12"] = Definition("mod12", "operation", "given", 0, (), canon, {"host": "mod12"},
                                             status="promoted")
    assert not check_template(base, lib)
    hour = instantiate(base, {"T": "int", "canon": "mod12"}, "Hour", lib=lib)
    assert hour.spec.base == "int" and hour.spec.canon == nodes.Call("mod12", (nodes.Var("x"),))
    assert hour.depends_on == ("Quot", "mod12")
    assert hour.body is None and hour.validate() == []
    lib._definitions["Quot"] = base
    lib.write(hour)
    lib.check("Hour")
    lib.make_callable("Hour", [(14,)])
    assert lib.run("Hour.make", (14,)).outcome == Ok(Card("Hour", "val", (2,)))
    lib.verify("Hour", VerifyRequest("bounded", ((14,), (2,)), {"domain": "bound 0..14", "size": 2}))
    assert lib.get("Hour").evidence.scope["domain"] == "bound 0..14"


def test_quot_template_builds_fraction_and_hour_objects():
    lib = library()
    pair = ObjectSpec("Pair", "compose", tags={"Pair": [("num", "int"), ("den", "int")]})
    lib.write(Definition("Pair", "object", "invented", 1, (), pair, None))
    lib.check("Pair")
    lib.make_callable("Pair", [(1, 2)])

    def reduce(value):
        numerator, denominator = value.fields
        divisor = gcd(numerator, denominator)
        return Card("Pair", "Pair", (numerator // divisor, denominator // divisor))

    for name, implementation, sort in (("reduce", reduce, "Pair"),
                                       ("mod12", lambda value: value % 12, "int")):
        lib.atoms += (kernel.Atom(name, 1, implementation),)
        spec = OperationSpec(name, "transform", (Edge(sort),), Edge(sort), name)
        lib._definitions[name] = Definition(name, "operation", "given", 0, (), spec, {"host": name},
                                             status="promoted")
    base = Definition("Quot", "template", "invented", 1, (),
                      TemplateSpec("Quot", (("T", "sort"), ("canon", "operation")), "object",
                                   {"form": "refine", "base": "$T", "valid": nodes.to_json(nodes.Lit(True)),
                                    "canon": nodes.to_json(nodes.Call("$canon", (nodes.Var("x"),)))}),
                      nodes.Lit(0))
    lib._definitions["Quot"] = base
    for name, sort, canon, value, normalized in (
        ("Frac", "Pair", "reduce", Card("Pair", "Pair", (2, 4)), Card("Pair", "Pair", (1, 2))),
        ("Hour", "int", "mod12", 14, 2),
    ):
        member = instantiate(base, {"T": sort, "canon": canon}, name, lib=lib)
        lib.write(member)
        lib.check(name)
        lib.make_callable(name, [(value,)])
        lib.verify(name, VerifyRequest("bounded", ((value,),), {"domain": "bound one member", "size": 1}))
        assert lib.run(f"{name}.make", (value,)).outcome == Ok(Card(name, "val", (normalized,)))
        assert lib.get(name).evidence is not None


def test_operation_and_combinator_function_parameters():
    lib = library()
    lib.atoms += (kernel.Atom("inc", 1, lambda value: value + 1),)
    operation = OperationSpec("inc", "transform", (Edge("int"),), Edge("int"), "inc")
    lib._definitions["inc"] = Definition("inc", "operation", "given", 0, (), operation,
                                           {"host": "inc"}, status="promoted")
    for kind in ("operation", "combinator"):
        pattern = ({"role": "transform", "inputs": [{"sort": "int"}], "output": {"sort": "int"},
                    "rule": "lift $f", "input_names": ["arg0"]} if kind == "operation" else
                   {"params": ["arg0"], "op_params": [], "body": nodes.to_json(nodes.Lit(0))})
        pattern["definition_body"] = nodes.to_json(nodes.Call("$f", (nodes.Var("arg0"),)))
        base = Definition(f"Lift_{kind}", "template", "invented", 1, (),
                          TemplateSpec(f"Lift_{kind}", (("f", "operation"),), kind, pattern), nodes.Lit(0))
        lib._definitions[base.name] = base
        lib.check(base.name)
        lib.make_callable(base.name, [("inc",)])
        member = instantiate(base, {"f": "inc"}, f"lift_{kind}", lib=lib)
        assert member.spec.extra["template"]["args"] == {"f": "inc"}
        lib.write(member)
        lib.check(member.name)
        lib.make_callable(member.name, [(2,)])
        assert lib.run(member.name, (2,)).outcome == Ok(3)


def test_observation_with_memory_substitutes_probe_and_nodes():
    lib = library()
    probe = Definition("probe", "observation", "given", 0, (),
                       ObservationSpec("probe", (), nodes.Lit(1)), nodes.Lit(1), status="promoted")
    lib._definitions["probe"] = probe
    body = nodes.Call("$probe", (nodes.Var("s"),))
    pattern = {"reads": ["$probe"], "body": nodes.to_json(body),
               "memory": {"init": nodes.to_json(nodes.Lit(0)),
                          "step": nodes.to_json(nodes.Call("add", (nodes.Var("memory"),
                                                               nodes.Var("$probe"))))},
               "definition_body": nodes.to_json(body)}
    base = Definition("Count", "template", "invented", 1, (),
                      TemplateSpec("Count", (("probe", "observation"),), "observation", pattern),
                      nodes.Lit(0))
    member = instantiate(base, {"probe": "probe"}, "Count_probe", lib=lib)
    assert member.spec.reads == ("probe",)
    assert member.spec.memory["init"] == nodes.Lit(0)
    assert member.spec.memory["step"] == nodes.Call("add", (nodes.Var("memory"), nodes.Var("probe")))
    assert member.depends_on == ("Count", "probe")


def test_law_and_bridge_spec_templates():
    lib = library()
    for kind, pattern, expected in (
        ("law", {"vars": [["a", "$T"]],
                 "statement": nodes.to_json(nodes.Call("eq", (nodes.Var("a"), nodes.Var("a"))))}, LawSpec),
        ("bridge", {"source": "$T", "target": "int", "map": nodes.to_json(nodes.Var("x")),
                    "interface": []}, BridgeSpec),
    ):
        base = Definition(f"Make_{kind}", "template", "invented", 1, (),
                          TemplateSpec(f"Make_{kind}", (("T", "sort"),), kind, pattern), nodes.Lit(0))
        member = instantiate(base, {"T": "int"}, f"made_{kind}", lib=lib)
        assert isinstance(member.spec, expected)
        assert member.spec.extra["template"]["args"] == {"T": "int"}
        assert base.name in member.depends_on


def test_sort_argument_named_like_an_operation_is_not_an_operation_dependency():
    original = library()
    pair = OperationSpec("pair", "combine", (Edge("int"), Edge("int")), Edge("int"), "pair")
    world = replace(original.world, objects=(*original.world.objects, ObjectSpec("pair", "given")),
                    operations=(*original.world.operations, pair))
    lib = Library(world, (*original.atoms, kernel.Atom("pair", 2, lambda left, right: (left, right))))
    for sort_kind in ("sort", "pair"):
        base = Definition(f"Quot_{sort_kind}", "template", "invented", 1, (),
                          TemplateSpec(f"Quot_{sort_kind}", (("T", sort_kind),), "object",
                                       {"form": "refine", "base": "$T",
                                        "valid": nodes.to_json(nodes.Lit(True))}), nodes.Lit(0))
        member = instantiate(base, {"T": "pair"}, f"QuotPair_{sort_kind}", lib=lib)
        assert member.spec.base == "pair"
        assert member.depends_on == (base.name,)
        assert member.spec.extra["template"]["args"] == {"T": "pair"}


def test_observation_template_substitutes_probe_inside_memory_condition():
    original = library()
    probe = OperationSpec("probe", "decide", (Edge("state"),), Edge("bool"), "probe")
    world = replace(original.world, operations=(*original.world.operations, probe),
                    observation={"truth": "state", "probes": [{"name": "probe"}],
                                 "capabilities": {"learner": {"probes": "all"}}})
    lib = Library(world, (*original.atoms,
                          kernel.Atom("probe", 1, lambda state: state > 0, kind="observation")))
    body = nodes.Let("_probe", nodes.Call("$probe", (nodes.Var("s"),)),
                     nodes.Var("memory"))
    step = nodes.Case(((nodes.Test(nodes.Var("$probe")), nodes.Lit(1)),), nodes.Lit(0))
    base = Definition("Count", "template", "invented", 1, (),
                      TemplateSpec("Count", (("probe", "str"),), "observation",
                                   {"reads": ["$probe"], "body": nodes.to_json(body),
                                    "memory": {"init": nodes.to_json(nodes.Lit(0)),
                                               "step": nodes.to_json(step)}},
                                   extra={"family": [{"probe": "probe"}]}), nodes.Lit(0))
    member = instantiate(base, {"probe": "probe"}, "Count_probe", lib=lib)
    assert member.spec.memory["step"] == nodes.Case(
        ((nodes.Test(nodes.Var("probe")), nodes.Lit(1)),), nodes.Lit(0))
    lib.write(base)
    lib.check(base.name)
    lib.write(member)
    lib.check(member.name)
    assert member.depends_on == ("Count", "probe")


@settings(deadline=None)
@given(st.integers(min_value=-100, max_value=100), st.integers(min_value=-100, max_value=100))
def test_content_addressed_and_unfold_invariant(left, right):
    lib = library()
    base = install_template(lib)
    first = instantiate(base, {"increment": left}, "shift", lib=lib)
    same = instantiate(base, {"increment": left}, "shift", lib=lib)
    changed = instantiate(base, {"increment": right}, "shift", lib=lib)
    assert first.content_hash() == same.content_hash()
    if left != right:
        assert first.content_hash() != changed.content_hash()
    lib.write(first)
    lib.check("shift")
    lib.make_callable("shift", [(2,)])
    run = lib.run("shift", (2,), trace=True)
    assert run.outcome == Ok(2 + left)
    assert unfold_equivalent_calls(run.trace, [Boundary.unfold_all(), Boundary.unfold_none()]).ok


def test_undeclared_placeholder_and_wrong_kind_rejected():
    lib = library()
    base = template()
    broken = replace(base, spec=replace(base.spec, pattern={**base.spec.pattern, "rule": "$unknown"}))
    assert "undeclared template placeholders" in check_template(broken, lib)[0]
    with pytest.raises(ValueError, match="exactly"):
        instantiate(base, {}, "invalid")
