"""Regression coverage for template evidence, notation and memoized blocks."""

from dataclasses import replace

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from test_atoms_templates import install_template, library, request

from opulse.atoms import kernel, nodes
from opulse.atoms.combinators import memoized_spec
from opulse.atoms.library import VerifyRequest
from opulse.atoms.notation import parse_definition, print_definition
from opulse.atoms.spec import CombinatorSpec, Contract
from opulse.atoms.templates import cite_template_evidence, instantiate, verify_template
from opulse.atoms.values import Bottom, Ok


def family_request(family, members, method="bounded"):
    return VerifyRequest(method, ((),), {"domain": "family", "size": len(family), "family": family},
                         seed=7 if method == "sampled" else None,
                         extra={"family": family, "member_requests": members})


@pytest.mark.parametrize("method, member_method", [("bounded", "sampled"), ("sampled", "bounded")])
def test_member_evidence_method_must_match_template(method, member_method):
    lib = library()
    base = install_template(lib)
    family = [{"increment": 1}]
    member = replace(request(1), method=member_method, seed=7 if member_method == "sampled" else None)
    result = verify_template(base, lib, family_request(family, [member], method))
    assert not result.ok
    assert "method must match" in result.problems[0]
    with pytest.raises(Exception, match="method must match"):
        lib.verify(base.name, family_request(family, [member], method))


def test_sampled_template_evidence_never_promotes():
    lib = library()
    base = install_template(lib)
    family = [{"increment": 1}]
    sampled = replace(request(1), method="sampled", seed=7)
    lib.verify(base.name, family_request(family, [sampled], "sampled"))
    assert lib.get(base.name).evidence.method == "sampled"
    with pytest.raises(Exception, match="sampled evidence cannot be promoted"):
        lib.promote(base.name, Contract("finite family"))


@settings(deadline=None)
@given(st.integers(min_value=-20, max_value=20), st.integers(min_value=1, max_value=20))
def test_citation_rejects_modified_spec_and_body(increment, change):
    lib = library()
    base = install_template(lib)
    family = [{"increment": increment}]
    lib.verify(base.name, family_request(family, [request(increment)]))
    member = instantiate(lib.get(base.name), family[0], "shift", lib=lib)
    assert cite_template_evidence(member, lib)
    changed_body = replace(member, body=nodes.Call("add", (nodes.Var("arg0"),
                                                              nodes.Lit(increment + change))))
    assert not cite_template_evidence(changed_body, lib)
    assert not cite_template_evidence(replace(member, spec=replace(member.spec, rule="wrong")), lib)


def test_citation_rejects_spoofed_family_arguments_after_check():
    lib = library()
    base = install_template(lib)
    family = [{"increment": 1}]
    lib.verify(base.name, family_request(family, [request(1)]))
    outside = instantiate(lib.get(base.name), {"increment": 4}, "outside", lib=lib)
    inside = instantiate(lib.get(base.name), family[0], "inside", lib=lib)
    forged = replace(outside, spec=replace(outside.spec,
                     extra={**outside.spec.extra, "template": inside.spec.extra["template"]}))
    assert not cite_template_evidence(outside, lib)
    assert not cite_template_evidence(forged, lib)
    lib.write(forged)
    lib.check(forged.name)
    assert not cite_template_evidence(lib.get(forged.name), lib)


@settings(deadline=None)
@given(st.integers(min_value=-25, max_value=25))
def test_template_body_is_never_called_when_instantiated(increment):
    lib = library()
    base = replace(install_template(lib), body=nodes.Lit(Bottom("poison")))
    lib._definitions[base.name] = base
    member = instantiate(base, {"increment": increment}, "shift", lib=lib)
    assert not any(isinstance(item, nodes.Call) and item.fn == base.name
                   for item in nodes.walk(member.body))
    lib.write(member)
    lib.check(member.name)
    lib.make_callable(member.name, [(2,)])
    assert lib.run(member.name, (2,)).outcome == Ok(2 + increment)


def test_parsed_template_produces_instantiable_and_printable_spec():
    source = "template obj Quot[T: obj, canon: op] = refine T canon(canon) L2"
    base = parse_definition(source)
    assert print_definition(base) == source
    instance = instantiate(base, {"T": "Pair", "canon": "reduce"}, "Frac")
    assert instance.spec.base == "Pair"
    assert instance.spec.canon == nodes.Call("reduce", (nodes.Var("x"),))
    assert print_definition(instance) == "obj Frac = Quot[Pair, reduce] L3"
    assert parse_definition(print_definition(instance)).depends_on == ("Quot",)
    generic = instantiate(base, {"T": "Pair<Int, Int>", "canon": "reduce"}, "Frac")
    assert print_definition(generic) == "obj Frac = Quot[Pair<Int, Int>, reduce] L3"


@settings(deadline=None)
@given(st.integers(min_value=-20, max_value=20))
def test_memoized_recursion_inside_blocks(start):
    recursive = nodes.Rec("go", ("i",), nodes.Var("i"), (nodes.Var("x"),), nodes.Var("i"))
    program = nodes.Blocks((("x", nodes.Lit(start)),), "L0",
                           (("L0", nodes.Block((("y", recursive),),
                                               nodes.Halt(nodes.Var("y")))),))
    spec = CombinatorSpec("test", ("x",), (), program)
    transformed = memoized_spec(spec)
    assert [item.memo for item in nodes.walk(transformed.body) if isinstance(item, nodes.Rec)] == [True]
    assert transformed.body.vars == program.vars
    assert transformed.body.entry == program.entry
    plain = kernel.evaluate(program)
    memoized = kernel.evaluate(transformed.body)
    assert (memoized.outcome, memoized.steps) == (plain.outcome, plain.steps)
