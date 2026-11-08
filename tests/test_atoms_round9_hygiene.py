"""Pipeline regressions for named edges and memory dependencies (spec sections 8 and 9)."""

import pytest

from opulse.atoms import nodes as n
from opulse.atoms.check import check_definition
from opulse.atoms.library import Library, PipelineError, VerifyRequest
from opulse.atoms.spec import (
    Definition,
    Edge,
    ObjectSpec,
    ObservationSpec,
    OperationSpec,
)
from opulse.atoms.values import Ok
from opulse.atoms.world import WorldDecl


def world(*operations):
    return WorldDecl("hygiene", 1, "atoms-v2", {}, {}, (ObjectSpec("int", "given"),),
                     operations, {"nodes": list(n.NODE_NAMES), "recursion": "fuel"}, {}, {})


def test_bare_edge_names_bind_operation_through_pipeline():
    lib = Library(world(), ())
    spec = OperationSpec("identity", "transform", (Edge("int", name="value"),),
                         Edge("int"), "return value")
    assert "input_names" not in spec.extra
    body = n.Var("value")
    lib.write(Definition("identity", "operation", "invented", 1, (), spec, body))
    assert lib.check("identity").status == "checked"
    assert lib.make_callable("identity", ((3,),)).status == "callable"
    assert lib.verify("identity", VerifyRequest("bounded", ((3,), (7,)),
                                         {"domain": "named edge inputs", "size": 2},
                                         reference=lambda value: value)).status == "verified"
    assert lib.run("identity", (7,)).outcome == Ok(7)


@pytest.mark.parametrize(("edge", "variable"), [
    (Edge("int", name="value"), "other"),
    (Edge("int"), "value"),
])
def test_body_cannot_use_a_name_not_bound_by_edges(edge, variable):
    lib = Library(world(), ())
    spec = OperationSpec("invalid", "transform", (edge,),
                         Edge("int"), "return value")
    lib.write(Definition("invalid", "operation", "invented", 1, (), spec, n.Var(variable)))
    with pytest.raises(PipelineError, match=f"unbound variable: {variable}"):
        lib.check("invalid")


def test_check_uses_definition_validation_for_memory_dependencies(monkeypatch):
    seed = OperationSpec("seed", "transform", (), Edge("int"), "seed")
    inc = OperationSpec("inc", "transform", (Edge("int"),), Edge("int"), "increment")
    declaration = world(seed, inc)
    body = n.Lit(0)
    memory = {"init": n.Call("seed", ()), "step": n.Call("inc", (n.Var("memory"),))}
    spec = ObservationSpec("remember", (), body, memory)
    definition = Definition("remember", "observation", "invented", 1,
                            ("seed", "inc"), spec, body)
    original = n.dependencies_match
    calls = []

    def record_dependencies(depends_on, expression, excluded=frozenset(), extra_nodes=()):
        calls.append((depends_on, expression, excluded, extra_nodes))
        return original(depends_on, expression, excluded, extra_nodes)

    monkeypatch.setattr(n, "dependencies_match", record_dependencies)
    assert check_definition(definition, declaration, lambda name: None) == []
    assert calls == [(definition.depends_on, body, set(), (memory["init"], memory["step"]))]

    missing_step_dependency = Definition("remember", "observation", "invented", 1,
                                         ("seed",), spec, body)
    assert "depends_on does not match body references" in check_definition(
        missing_step_dependency, declaration, lambda name: None)

    original_validate = Definition.validate

    def reject_memory_dependencies(self):
        return [*original_validate(self), "depends_on does not match body references"]

    monkeypatch.setattr(Definition, "validate", reject_memory_dependencies)
    assert "depends_on does not match body references" in check_definition(
        definition, declaration, lambda name: None)
