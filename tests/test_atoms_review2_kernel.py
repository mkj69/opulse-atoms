"""Review-round-2 kernel regressions (atoms-v2 spec sections 6, 8, 9 and 18.6)."""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from test_atoms_library import definition, fixture, ready

from opulse.atoms import nodes as n
from opulse.atoms.kernel import Atom, Defn, DictScope, FnRef, Limits, call, evaluate
from opulse.atoms.library import Library, PipelineError, VerifyRequest
from opulse.atoms.spec import Contract
from opulse.atoms.values import Bottom, Ok, Unknown


def test_bound_names_do_not_hide_scope_calls_or_fnref_dependencies():
    body = n.Let("helper", n.Lit(FnRef("other")), n.Call("helper", (n.Lit(3),)))
    assert n.references(body) == {"helper"}
    assert n.dependencies_match(("helper",), body)
    assert not n.dependencies_match((), body)
    scope = DictScope([Atom("helper", 1, lambda value: value + 1)])
    assert evaluate(body, scope=scope).outcome == Ok(4)
    unresolved = n.Let("op", n.Lit(FnRef("helper")), n.Call("op", (n.Lit(3),)))
    assert n.references(unresolved) == {"op"}
    assert n.dependencies_match(("op",), unresolved)
    assert evaluate(unresolved, scope=scope).outcome == Ok(4)


def test_recursion_excludes_only_its_local_function():
    expression = n.Rec("loop", ("helper",), n.Call("loop", (n.Call("helper"),)),
                       (n.Call("outside"),), "fuel")
    assert n.references(expression) == {"helper", "outside"}
    program = n.Blocks((("helper", n.Lit(FnRef("real"))),), "start", (
        ("start", n.Block((("result", n.Call("helper")),), n.Halt(n.Var("result")))),))
    assert n.references(program) == {"helper"}


@given(value=st.integers(-20, 20), bound=st.booleans(), recursive=st.booleans())
@settings(max_examples=60, deadline=None)
def test_reference_tracking_agrees_with_scope_first_resolution(value, bound, recursive):
    expression = n.Call("helper", (n.Lit(value),))
    if recursive:
        expression = n.Rec("local", ("helper",), expression, (n.Lit(value),), "fuel")
    if bound:
        expression = n.Let("helper", n.Lit(FnRef("other")), expression)
    scope = DictScope([Atom("helper", 1, lambda number: number + 1)])
    assert n.references(expression) == {"helper"}
    assert evaluate(expression, scope=scope).outcome == Ok(value + 1)


def test_shadowed_dependency_invalidation_survives_reload():
    lib = fixture()
    helper = definition("helper", n.Call("succ", (n.Var("arg0"),)), ("succ",), 1,
                        ("arg0",))
    ready(lib, helper, ((0,),))
    body = n.Let("helper", n.Lit(0), n.Call("helper", (n.Var("arg0"),)))
    with pytest.raises(PipelineError, match="depends_on"):
        lib.write(definition("missing", body, (), 1, ("arg0",)))
    ready(lib, definition("f", body, ("helper",), 2, ("arg0",)), ((0,),))
    lib.verify("f", VerifyRequest("bounded", ((0,),), {"domain": "0 <= 1", "size": 1},
                                  reference=lambda value: value + 1))
    lib.promote("f", Contract("x+1"))
    assert lib.run("f", (0,)).outcome == Ok(1)
    replacement = definition("helper", n.Call("succ", (n.Call("succ", (n.Var("arg0"),)),)),
                             ("succ",), 1, ("arg0",))
    lib.replace("helper", replacement)
    assert lib.get("f").status == "callable"
    assert lib.get("f").evidence is None and lib.get("f").contract is None
    assert "f" not in {item.name for item in lib.derived_world().promoted}
    assert Library.from_dict(lib.to_dict(), lib.world, lib.atoms).get("f").status != "promoted"


@given(budget=st.integers(0, 4), cost=st.integers(1, 4),
       dialect=st.sampled_from(("atoms-v2", "legacy-v1")))
@settings(max_examples=60, deadline=None)
def test_metered_swallowed_budget_unknown_overrides_host_result(budget, cost, dialect):
    scope = DictScope([Atom("tick", 0, lambda: 7, cost=cost),
                       Atom("meta", 0, lambda ctx: (ctx.call("tick", (), budget=budget),
                                                     Ok(99))[1], metered=True)])
    run = call("meta", (), scope, trace=True, dialect=dialect)
    expected = Ok(99) if budget >= cost else Unknown("fuel")
    assert (run.outcome, run.steps) == (expected, cost if budget >= cost else 0)
    assert run.trace.children[0].outcome == expected
    assert run.trace.children[0].children[0].outcome == (
        Ok(7) if budget >= cost else Unknown("fuel"))


@pytest.mark.parametrize("resource, limits, target", [
    ("fuel", Limits(fuel=0), Atom("tick", 0, lambda: 1)),
    ("depth", Limits(max_depth=0), Defn("tick", (), n.Lit(1))),
    ("nodes", Limits(max_nodes=2), Atom("tick", 0, lambda: 1)),
])
def test_metered_unknown_resource_cannot_be_swallowed(resource, limits, target):
    atoms = [target] if isinstance(target, Atom) else []
    defns = [target] if isinstance(target, Defn) else []
    scope = DictScope(atoms, defns)
    scope.atoms["meta"] = Atom("meta", 0, lambda ctx: (ctx.call("tick", ()),
                                                      Bottom("ignored"))[1], metered=True)
    run = call("meta", (), scope, limits=limits, trace=True)
    assert run.outcome == Unknown(resource)
    assert run.trace.children[0].outcome == Unknown(resource)


def test_metered_first_unknown_persists_after_successful_call():
    scope = DictScope([Atom("tick", 0, lambda: 1),
                       Atom("meta", 0, lambda ctx: (ctx.call("tick", (), budget=0),
                                                     ctx.call("tick", ()))[1], metered=True)])
    run = call("meta", (), scope, trace=True)
    assert (run.outcome, run.steps) == (Unknown("fuel"), 1)
    assert [child.outcome for child in run.trace.children[0].children] == [Unknown("fuel"), Ok(1)]
