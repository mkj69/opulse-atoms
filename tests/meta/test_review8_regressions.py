"""Exact regressions for code forms of laws, bridges and templates."""

import pytest

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.notation import print_expr
from opulse.atoms.spec import Definition, Edge, LawSpec, OperationSpec, TemplateSpec
from opulse.atoms.templates import _encode_nodes, instantiate
from opulse.atoms.values import FALSE, TRUE, Bottom, Card, outcome_equal
from opulse.meta import code as C
from opulse.meta import notation as N


def template_of(params, produces, pattern):
    spec = TemplateSpec("t", params, produces, _encode_nodes(pattern))
    return Definition("t", "template", "invented", 1, (), spec, None)


def test_simultaneous_template_placeholder_substitution():
    source = template_of((("step", "int"), ("x0", "int")), "operation", {
        "name": "made", "role": "transform", "rule": "add", "inputs": [],
        "output": {"sort": "int"},
        "definition_body": n.Call("add", (n.Lit("$step"), n.Lit("$x0"))),
    })
    actual = C.instantiate_code(C.quote(source, lambda _: None, {}), (2, 3),
                                lambda name: C.Resolved(digest="D") if name == "add" else None)
    expected = instantiate(source, {"step": 2, "x0": 3}, "made").body.body
    decoded = C.decode(actual)
    assert isinstance(decoded.main.body, n.Let)
    assert decoded.main.body.value == n.Lit(kernel.FnRef(decoded.deps[0].name))
    assert decoded.main.body.body == expected
    assert C.canonicalize(actual) == actual


@pytest.mark.parametrize("literal", [True, False])
def test_law_host_boolean_outcomes(literal):
    source = n.Lit(literal)
    law = Definition("l", "law", "invented", 1, (), LawSpec("l", (), source), source)
    decoded = C.decode(C.quote(law, lambda _: None, {})).main
    original = kernel.call("l", (), kernel.DictScope([], [kernel.Defn("l", (), source, "law")]))
    translated = kernel.call(decoded.name, (), kernel.DictScope([], [decoded]))
    assert outcome_equal(original.outcome, translated.outcome)
    assert original.steps == translated.steps == 0
    assert translated.outcome.value is literal


@pytest.mark.parametrize("literal", [TRUE, FALSE])
def test_existing_boolean_cards_keep_card_identity(literal):
    code = C.make_code("operation", C.sig_op((), ("bool", "bottom")), (),
                       n.Lit(literal), lambda _: None)
    decoded = C.decode(code).main
    outcome = kernel.call(decoded.name, (), kernel.DictScope([], [decoded]))
    assert outcome.outcome.value == literal
    assert isinstance(outcome.outcome.value, Card)
    assert outcome.steps == 0
    assert C.canonicalize(code) == code
    assert N.parse_code(N.show_code(code, signature=True, exact=True)) == code


def test_partial_bridge_template_declared_failure_literal():
    body = n.Case(((n.Test(n.Lit(True)), n.Var("x")),), n.Lit(Bottom("outside_domain")))
    source = template_of((("i", "int"),), "bridge", {
        "name": "t", "source": "int", "target": "int", "map": n.Var("x"),
        "domain": n.Lit(True), "definition_body": body,
    })
    quoted = C.quote(source, lambda _: None, {})
    assert C.canonicalize(quoted) == quoted
    actual = C.instantiate_code(quoted, (1,))
    expected = instantiate(source, {"i": 1}, "b").body
    decoded = C.decode(actual).main
    assert decoded.body == n.Case(((n.Test(n.Lit(True)), n.Var("x0")),),
                                  n.Lit(Bottom("outside_domain")))
    for value in (0, 2):
        baseline = kernel.call("b", (value,), kernel.DictScope([], [kernel.Defn("b", ("x",), expected, "bridge")]))
        translated = kernel.call(decoded.name, (value,), kernel.DictScope([], [decoded]))
        assert outcome_equal(baseline.outcome, translated.outcome)
        assert baseline.steps == translated.steps == 0
    assert C.canonicalize(actual) == actual


def test_template_node_lit_supports_core_json_literals():
    from opulse.worlds.perm import Permutation

    for literal in (Bottom("outside_domain"), (True, Bottom("not_stable"), (1, "a")),
                    Permutation((1, 0))):
        node = n.Lit(literal)
        pattern = C.encode_pattern(n.to_json(node))
        assert C.decode_pattern(pattern) == node


def test_definition_kind_argument_has_content_identity():
    source = template_of((("target", "operation"),), "operation", {
        "name": "made", "role": "transform", "rule": "call", "inputs": [],
        "output": {"sort": "int"}, "definition_body": n.Call("$target", ()),
    })
    operation = Definition("f", "operation", "invented", 1, (),
                           OperationSpec("f", "transform", (), Edge("int"), "f"), n.Lit(1))
    quoted = C.quote(source, lambda _: None, {})
    resolver = lambda name: C.Resolved(digest="D") if name == "f" else None
    actual = C.instantiate_code(quoted, (operation,), resolver)
    decoded = C.decode(actual)
    assert isinstance(decoded.main.body, n.Let)
    assert decoded.main.body.body == instantiate(source, {"target": operation}, "made").body.body
    assert decoded.main.body.value == n.Lit(kernel.FnRef(decoded.deps[0].name))
    assert C.canonicalize(actual) == actual
    origin = C.items(actual.fields[4])[-1]
    assert C.items(origin.fields[1])[0].fields == ("f", "operation", operation.content_hash())
    altered = Definition("f", "operation", "invented", 1, (), operation.spec, n.Lit(2))
    assert C.code_hash(C.instantiate_code(quoted, (altered,), resolver)) != C.code_hash(actual)


def test_forged_origin_arguments_and_body_rejected():
    source = template_of((("step", "int"),), "operation", {
        "name": "made", "role": "transform", "rule": "literal", "inputs": [],
        "output": {"sort": "int"}, "definition_body": n.Lit("$step"),
    })
    template = C.quote(source, lambda _: None, {})
    valid = C.instantiate_code(template, (1,))
    assert C.canonicalize(valid) == valid
    forged = Card("code", "def", (*valid.fields[:4], C.lst((*C.items(valid.fields[4])[:-1], Card(
        "origin", "template", (template, C.lst((C.encode_pattern(2),))))))))
    assert not C.is_canonical(forged)
    with pytest.raises(C.CodeError, match="provenance"):
        C.canonicalize(forged)
    altered = Card("code", "def", (valid.fields[0], valid.fields[1], C.encode_node(n.Lit(2)),
                                    valid.fields[3], valid.fields[4]))
    assert not C.is_canonical(altered)


def test_forged_arguments_with_invented_dependency_rejected():
    dependency = Definition("inc", "operation", "invented", 1, (),
                            OperationSpec("inc", "transform", (Edge("int"),), Edge("int"), "inc"),
                            n.Call("add", (n.Var("arg0"), n.Lit(1))))
    template = template_of((("offset", "int"),), "operation", {
        "name": "made", "role": "transform", "rule": "shift",
        "inputs": [{"sort": "int"}], "output": {"sort": "int"},
        "input_names": ["arg0"],
        "definition_body": n.Call("inc", (n.Call("add", (n.Var("arg0"), n.Lit("$offset"))),)),
    })
    instance = instantiate(template, {"offset": 2}, "made")
    definitions = {item.name: item for item in (dependency, template, instance)}
    valid = C.quote(instance, definitions.get, {"add": "digest-add"})
    assert C.canonicalize(valid) == valid
    origin = C.items(valid.fields[4])[-1]
    forged_origin = Card("origin", "template", (origin.fields[0], C.lst((C.encode_pattern(3),))))
    forged = Card("code", "def", (*valid.fields[:4], C.lst((*C.items(valid.fields[4])[:-1], forged_origin))))
    with pytest.raises(C.CodeError, match="provenance"):
        C.canonicalize(forged)
    assert not C.is_canonical(forged)


def test_malformed_template_rejected_on_entry():
    body = Card("pattern", "template", (Card("pattern", "garbage"), Card("pattern", "none")))
    sig = C.sig_template((("x0", "int"),), "operation")
    with pytest.raises(C.CodeError):
        C.make_code("template", sig, (), body, lambda _: None)
    forged = Card("code", "def", ("template", sig, body, C.lst(), C.lst()))
    assert not C.is_canonical(forged)
    missing_spec = C._template_body({"name": "made"}, None, ("x0",))
    with pytest.raises(C.CodeError):
        C.make_code("template", sig, (), missing_spec, lambda _: None)


def test_bridge_domain_global_reserves_map_binder():
    domain = n.Call("v0", (n.Var("x"),))
    code = C.make_code("bridge", C.sig_bridge("A", "B", domain=domain), ("x",),
                       n.Let("tmp", n.Lit(1), n.Var("tmp")),
                       lambda name: C.Resolved(digest="D") if name == "v0" else None)
    assert C.decode_node(code.fields[2]) == n.Let("v1", n.Lit(1), n.Var("v1"))
    assert C.canonicalize(code) == code


@pytest.mark.parametrize("domain", [
    n.Case(((n.Test(n.Lit(True)), n.Lit(True)),), n.Lit(False)),
    n.Let("z", n.Lit(1), n.Var("z")),
    n.Rec("loop", ("z",), n.Var("z"), (n.Lit(1),), "fuel"),
])
def test_bridge_domain_uses_core_expression_notation(domain):
    code = C.make_code("bridge", C.sig_bridge("A", "B", domain=domain), ("x",),
                       n.Var("x"), lambda _: None)
    printed = N.show_code(code, signature=True, exact=True)
    canonical_domain = C.decode_node(code.fields[1].fields[3].fields[0])
    assert " domain " + print_expr(canonical_domain) + " = " in printed
    assert N.parse_code(printed) == code
