"""Exact law, bridge and template code identities and kernel semantics."""

import pytest

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.bridges import bridge_defn
from opulse.atoms.spec import (
    BridgeSpec,
    Definition,
    Edge,
    LawSpec,
    ObjectSpec,
    OperationSpec,
    TemplateSpec,
)
from opulse.atoms.templates import _encode_nodes, instantiate
from opulse.atoms.values import Bottom, Ok
from opulse.meta import code as C


def resolve(name):
    return C.Resolved(digest="digest-" + name) if name in {"eq", "add", "positive"} else None


def test_quoted_template_instance_with_invented_dependency_round_trip():
    inc = Definition("inc", "operation", "invented", 1, (),
                     OperationSpec("inc", "transform", (Edge("int"),), Edge("int"), "add"),
                     n.Call("add", (n.Var("arg0"), n.Lit(1))))
    pattern = {"name": "twice", "role": "transform", "rule": "twice",
               "inputs": [{"sort": "int"}], "output": {"sort": "int"},
               "definition_body": n.Call("inc", (n.Call("inc", (n.Var("arg0"),)),)),
               "input_names": ["arg0"]}
    template = Definition("Twice", "template", "invented", 1, (),
                          TemplateSpec("Twice", (("label", "str"),), "operation", _encode_nodes(pattern)), None)
    instance = instantiate(template, {"label": "twice"}, "twice")
    definitions = {item.name: item for item in (inc, template, instance)}
    quoted = C.quote(instance, definitions.get, {"add": "digest-add"})
    assert C.canonicalize(quoted) == quoted
    decoded = C.decode(quoted)
    assert {dep.kind for dep in decoded.deps} == {"operation", "template"}
    scope = kernel.DictScope([kernel.Atom("add", 2, lambda left, right: left + right)],
                             (*decoded.deps, decoded.main))
    run = kernel.call(decoded.main.name, (3,), scope)
    assert run.outcome == Ok(5)
    assert run.steps == 2


def test_law_alpha_and_kernel_instance():
    first = C.make_code("law", C.sig_law([("a", "int"), ("b", "int")]), ("a", "b"),
                        n.Call("eq", (n.Var("a"), n.Var("b"))), resolve)
    second = C.make_code("law", C.sig_law([("left", "int"), ("right", "int")]),
                         ("left", "right"), n.Call("eq", (n.Var("left"), n.Var("right"))), resolve)
    assert first == second and C.code_hash(first) == C.code_hash(second)
    spec = LawSpec("same", (("a", "int"), ("b", "int")), n.Call("eq", (n.Var("a"), n.Var("b"))))
    quoted = C.quote(Definition("same", "law", "invented", 1, (), spec, spec.statement),
                     lambda _: None, {"eq": "digest-eq"})
    assert C.canonicalize(quoted) == quoted
    decoded = C.decode(quoted)
    scope = kernel.DictScope([kernel.Atom("eq", 2, lambda left, right: left == right)], [decoded.main])
    assert kernel.call(decoded.main.name, (2, 2), scope).outcome == Ok(True)
    assert kernel.call(decoded.main.name, (2, 3), scope).outcome == Ok(False)
    assert kernel.call(decoded.main.name, (2, 3), scope).steps == 1


def test_bridge_domain_hash_and_bottom():
    spec = BridgeSpec("convert", "int", "int", n.Call("add", (n.Var("x"), n.Lit(1))),
                      n.Call("positive", (n.Var("x"),)), (("add", "add"),))
    code = C.quote(Definition("convert", "bridge", "invented", 1, (), spec,
                              n.Case(((n.Test(spec.domain), spec.map),), n.Lit(Bottom("outside_domain")))),
                   lambda _: None, {"add": "digest-add", "positive": "digest-positive"})
    assert C.canonicalize(code) == code
    decoded = C.decode(code)
    scope = kernel.DictScope([kernel.Atom("add", 2, lambda left, right: left + right),
                              kernel.Atom("positive", 1, lambda value: value > 0)], [decoded.main])
    assert kernel.call(decoded.main.name, (2,), scope).outcome == Ok(3)
    assert kernel.call(decoded.main.name, (0,), scope).outcome == Bottom("outside_domain")
    baseline = kernel.DictScope(scope.atoms, [bridge_defn(spec)])
    for value in (0, 2):
        original = kernel.call(spec.name, (value,), baseline)
        translated = kernel.call(decoded.main.name, (value,), scope)
        assert (translated.outcome, translated.steps) == (original.outcome, original.steps)
    changed = C.sig_bridge("int", "int", (("add", "add"),), n.Call("positive", (n.Lit(0),)))
    assert C.code_hash(C.make_code("bridge", changed, ("x",), spec.map, resolve)) != C.code_hash(code)


def test_template_pattern_and_instantiation_identity():
    pattern = {"name": "$label", "role": "transform", "rule": "add", "inputs": [{"sort": "int", "enter": "bottom"}],
               "output": {"sort": "int", "enter": "bottom"},
               "definition_body": n.Call("add", (n.Var("arg0"), n.Lit("$amount"))),
               "input_names": ["arg0"]}
    spec = TemplateSpec("make_add", (("label", "str"), ("amount", "int")), "operation", pattern)
    source = Definition("make_add", "template", "invented", 1, (), spec, None)
    template = C.quote(source, lambda _: None, {})
    assert C.canonicalize(template) == template
    assert C.decode_pattern(template.fields[2].fields[0])["definition_body"] == n.Call(
        "add", (n.Var("arg0"), n.Lit("$x1")))
    produced = C.instantiate_code(template, ("increment", 1), resolve, name="increment")
    core_pattern = {**pattern, "definition_body": n.to_json(pattern["definition_body"])}
    core_spec = TemplateSpec("make_add", spec.params, "operation", core_pattern)
    core_source = Definition("make_add", "template", "invented", 1, (), core_spec, None)
    core_instance = instantiate(core_source, {"label": "increment", "amount": 1}, "increment")
    assert C.quote(core_instance, lambda key: core_source if key == "make_add" else None,
                   {"add": "digest-add"}) == produced
    assert C.canonicalize(produced) == produced
    other = C.instantiate_code(template, ("increment", 2), resolve, name="increment")
    assert C.code_hash(produced) != C.code_hash(other)
    altered = TemplateSpec("make_add", spec.params, spec.produces, {**pattern, "rule": "add differently"})
    altered_code = C.quote(Definition("make_add", "template", "invented", 1, (), altered, None),
                           lambda _: None, {})
    assert C.code_hash(C.instantiate_code(altered_code, ("increment", 1), resolve,
                                         name="increment")) != C.code_hash(produced)
    with pytest.raises(C.CodeError, match="parameters"):
        C.instantiate_code(template, {"x0": "increment"}, resolve)
    with pytest.raises(ValueError, match="expects int"):
        C.instantiate_code(template, ("increment", "one"), resolve)
    assert C.items(produced.fields[4])[-1].fields[0] == template
    decoded = C.decode(produced)
    scope = kernel.DictScope([kernel.Atom("add", 2, lambda left, right: left + right)], [decoded.main])
    assert kernel.call(decoded.main.name, (4,), scope).outcome == Ok(5)


def test_template_alpha_identity_and_dependency_closure():
    first = TemplateSpec("first", (("amount", "int"),), "operation",
                         {"name": "increase", "role": "transform", "rule": "increase",
                          "inputs": [{"sort": "int"}], "output": {"sort": "int"},
                          "definition_body": n.Call("add", (n.Var("arg0"), n.Lit("$amount")))})
    renamed = TemplateSpec("renamed", (("increment", "int"),), "operation",
                           {**first.pattern, "definition_body": n.Call("add", (
                               n.Var("arg0"), n.Lit("$increment")))})
    first_code = C.quote(Definition("first", "template", "invented", 1, (), first, None), lambda _: None, {})
    second_code = C.quote(Definition("renamed", "template", "invented", 1, (), renamed, None), lambda _: None, {})
    assert first_code == second_code
    dependency = C.instantiate_code(first_code, (1,), resolve)
    parent = C.make_code("operation", C.sig_op([("int", "bottom")], ("int", "bottom")), ("arg",),
                         n.Call("increment", (n.Var("arg"),)),
                         lambda name: C.Resolved(code=dependency) if name == "increment" else resolve(name))
    assert C.canonicalize(parent) == parent
    assert C.decode(parent).main.body.fn == "#" + C.code_hash(dependency)


def test_template_alpha_renaming_with_original_positional_names():
    import random

    from opulse.atoms.templates import _encode_nodes

    rng = random.Random(82471)
    for _ in range(35):
        names = ("amount", "x0", "x1", "offset")
        left, right = rng.sample(names, 2)
        values = dict(zip(names, (2, 3, 5, 7)))
        pattern = {"name": "made", "role": "transform", "rule": "add", "inputs": [],
                   "output": {"sort": "int"},
                   "definition_body": n.Call("add", (n.Lit("$" + left), n.Lit("$" + right)))}
        source = Definition("t", "template", "invented", 1, (),
                            TemplateSpec("t", tuple((name, "int") for name in names),
                                         "operation", _encode_nodes(pattern)), None)
        code = C.instantiate_code(C.quote(source, lambda _: None, {}), tuple(values.values()), resolve)
        expected = instantiate(source, values, "made").body.body
        decoded = C.decode(code)
        assert isinstance(decoded.main.body, n.Let)
        assert decoded.main.body.value == n.Lit(kernel.FnRef(decoded.deps[0].name))
        assert decoded.main.body.body == expected
        assert C.canonicalize(code) == code


@pytest.mark.parametrize("literal", [True, False])
def test_template_law_bool_literal_matches_core(literal):
    from opulse.atoms.templates import _encode_nodes
    from opulse.atoms.values import outcome_equal

    pattern = {"name": "made", "vars": [], "statement": n.Lit("$flag")}
    source = Definition("t", "template", "invented", 1, (),
                        TemplateSpec("t", (("flag", "bool"),), "law", _encode_nodes(pattern)), None)
    code = C.instantiate_code(C.quote(source, lambda _: None, {}), (literal,))
    original = instantiate(source, {"flag": literal}, "made")
    baseline = kernel.call("made", (), kernel.DictScope([], [kernel.Defn("made", (), original.body, "law"),
                                                         kernel.Defn("t", (), n.Lit(0), "template")]))
    decoded = C.decode(code).main
    translated = kernel.call(decoded.name, (), kernel.DictScope([], [decoded]))
    assert outcome_equal(baseline.outcome, translated.outcome)
    assert baseline.steps == translated.steps == 0


@pytest.mark.parametrize("form,fields", [
    ("refine", {"base": "int", "valid": n.Lit(True)}),
    ("compose", {"tags": {"member": {"value": "int"}}}),
])
def test_noncallable_object_template_returns_definition_and_origin(form, fields):
    spec = TemplateSpec("object_family", (("label", "str"),), "object", {"form": form, **fields})
    template = C.quote(Definition("object_family", "template", "invented", 1, (), spec, None),
                       lambda _: None, {})
    definition, origin = C.instantiate_code(template, ("First",), name="First")
    assert isinstance(definition.spec, ObjectSpec)
    assert definition.spec.form == form
    assert definition.depends_on == ("template_source",)
    assert origin == C.Card("origin", "template", (template, C.lst((C.encode_pattern("First"),))))
    repeated_definition, repeated_origin = C.instantiate_code(template, ("First",), name="First")
    assert repeated_definition == definition and repeated_origin == origin
    assert C.instantiate_code(template, ("Second",), name="Second")[1] != origin
