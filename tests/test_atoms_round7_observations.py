"""Pure definition closure and public observations (spec sections 7 and 18.3)."""

from dataclasses import replace

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.bridges import bridge_defn
from opulse.atoms.library import Library, PipelineError, VerifyRequest
from opulse.atoms.observations import check_observation, observe, verify_observation
from opulse.atoms.spec import (
    BridgeSpec,
    CombinatorSpec,
    Contract,
    Definition,
    Edge,
    ObservationSpec,
    OperationSpec,
)
from opulse.atoms.values import Ok
from opulse.atoms.world import WorldDecl


def library(combinator=False):
    operations = (OperationSpec("peek", "decide", (Edge("state"),), Edge("int"), "peek"),
                  OperationSpec("add", "transform", (Edge("int"), Edge("int")), Edge("int"), "add"),
                  OperationSpec("change", "act", (Edge("int"),), Edge("int"), "change"))
    compose = CombinatorSpec("apply", ("f", "x"), ("f",), n.Call("f", (n.Var("x"),)))
    world = WorldDecl("observation-closure", 1, "atoms-v2", {}, {}, (), operations,
                      {"nodes": list(n.NODE_NAMES), "recursion": "fuel",
                       "library": (compose.to_dict(),) if combinator else ()},
                      {"truth": "state", "probes": [{"name": "peek"}]}, {},
                      open_kinds=("operation", "observation", "bridge"))
    return Library(world, (kernel.Atom("peek", 1, lambda state: state["value"], kind="observation"),
                           kernel.Atom("add", 2, lambda left, right: left + right),
                           kernel.Atom("change", 1, lambda value: value + 1)))


def operation(name, body, depends_on, role="transform"):
    spec = OperationSpec(name, role, (Edge("int"),), Edge("int"), name,
                         extra={"input_names": ["value"]})
    return Definition(name, "operation", "invented", 1, depends_on, spec, body)


def observation(name, body, depends_on, *, inputs=None, reads=()):
    extra = {} if inputs is None else {"inputs": inputs}
    spec = ObservationSpec(name, reads, body, extra=extra)
    layer = 2 if set(depends_on) - {"peek", "add", "change"} else 1
    return Definition(name, "observation", "invented", layer, depends_on, spec, body)


@settings(deadline=None)
@given(st.integers(-100, 100), st.integers(-100, 100))
def test_pure_operation_tower_keeps_truth_and_unfolds(value, offset):
    lib = library()
    pure = operation("step", n.Call("add", (n.Var("value"), n.Lit(offset))), ("add",))
    lib.write(pure)
    lib.check("step")
    lib.make_callable("step", [(value,)])
    body = n.Call("step", (n.Call("peek", (n.Var("s"),)),))
    seen = observation("seen", body, ("step", "peek"), reads=("peek",))
    lib.write(seen)
    lib.check("seen")
    state = {"value": value}
    assert observe(lib.get("seen"), lib, [state]) == [Ok(value + offset)]
    assert state == {"value": value}
    lib.make_callable("seen", [(state,)])
    request = VerifyRequest("bounded", ((state,),), {"domain": "one state", "size": 1})
    verified = lib.verify("seen", request)
    assert {"dependency", "facts_unchanged", "non_interference", "unfold_equivalence"} <= set(
        verified.evidence.checks)


@settings(deadline=None)
@given(st.integers(-100, 100), st.integers(-100, 100))
def test_public_two_inputs_promote_without_hidden_truth(left, right):
    lib = library()
    body = n.Call("add", (n.Var("xs"), n.Var("steps")))
    seen = observation("certificate", body, ("add",), inputs=[["xs", "int"], ["steps", "int"]])
    lib.write(seen)
    lib.check("certificate")
    lib.make_callable("certificate", [(left, right)])
    scope = {"domain": "two public inputs", "size": 1}
    verified = lib.verify("certificate", VerifyRequest("bounded", ((left, right),), scope))
    assert verified.evidence.scope["non_interference"] == "n/a"
    assert "non_interference" not in verified.evidence.checks
    assert lib.run("certificate", (left, right)).outcome == Ok(left + right)
    assert lib.promote("certificate", Contract("sum")).status == "promoted"


@settings(deadline=None)
@given(st.integers(-20, 20))
def test_transitive_act_dependency_is_rejected(value):
    lib = library()
    bad = operation("hidden_act", n.Call("change", (n.Var("value"),)), ("change",))
    lib.write(bad)
    lib.check("hidden_act")
    lib.make_callable("hidden_act", [(value,)])
    body = n.Call("hidden_act", (n.Var("input"),))
    seen = observation("unsafe", body, ("hidden_act",), inputs=[["input", "int"]])
    assert any("act" in problem or "truth" in problem for problem in check_observation(seen, lib))
    lib.write(seen)
    with pytest.raises(PipelineError, match="truth"):
        lib.check("unsafe")


def test_public_reference_and_arity_are_checked():
    lib = library()
    seen = observation("parse_count", n.Call("add", (n.Var("w"), n.Lit(1))), ("add",),
                       inputs=[["w", "int"]])
    lib.write(seen)
    lib.check("parse_count")
    lib.make_callable("parse_count", [(2,)])
    request = VerifyRequest("bounded", ((2,),), {"domain": "words", "size": 1},
                            reference=lambda word: word + 1)
    assert lib.verify("parse_count", request).evidence.checks == ("dependency", "facts_unchanged", "reference")
    assert lib.promote("parse_count", Contract("count")).status == "promoted"
    invalid = replace(seen, name="bad", spec=replace(seen.spec, name="bad"), status="written")
    assert not verify_observation(invalid, lib, VerifyRequest("bounded", ((1, 2),),
                                      {"domain": "wrong", "size": 1})).ok


def test_observation_calls_pure_bridge_and_memory_step():
    lib = library()
    spec = BridgeSpec("map_value", "int", "int", n.Call("add", (n.Var("x"), n.Lit(2))))
    bridge = Definition("map_value", "bridge", "invented", 1, ("add",), spec, bridge_defn(spec).body)
    lib.write(bridge)
    lib.check("map_value")
    lib.make_callable("map_value", [(3,)])
    step = n.Call("map_value", (n.Call("add", (n.Var("memory"), n.Var("peek"))),))
    body = n.Var("memory")
    seen = observation("tower", body, ("add", "map_value"), reads=("peek",))
    seen = replace(seen, spec=replace(seen.spec, memory={"init": n.Lit(0), "step": step}))
    lib.write(seen)
    lib.check("tower")
    assert observe(lib.get("tower"), lib, [{"value": 3}, {"value": 4}]) == [Ok(5), Ok(11)]


def test_public_input_cannot_be_sealed_truth_or_probe():
    lib = library()
    body = n.Var("state")
    seen = observation("unsafe_truth", body, (), inputs=[["state", "state"]])
    assert "observation inputs must be named public sorts" in check_observation(seen, lib)
    probe = observation("unsafe_probe", n.Call("peek", (n.Var("value"),)), ("peek",),
                        inputs=[["value", "int"]])
    assert any("public observation cannot call probe" in problem for problem in check_observation(probe, lib))


def test_truth_observation_calls_public_observation():
    lib = library()
    doubled = observation("twice", n.Call("add", (n.Var("value"), n.Var("value"))),
                          ("add",), inputs=[["value", "int"]])
    lib.write(doubled)
    lib.check("twice")
    lib.make_callable("twice", [(4,)])
    body = n.Call("twice", (n.Call("peek", (n.Var("s"),)),))
    seen = observation("visible_twice", body, ("twice", "peek"), reads=("peek",))
    lib.write(seen)
    lib.check("visible_twice")
    assert observe(lib.get("visible_twice"), lib, [{"value": 4}]) == [Ok(8)]


def test_public_verification_detects_mutated_input():
    def mutate(items):
        items.append(9)
        return len(items)

    lib = library()
    lib.world = replace(lib.world, operations=lib.world.operations +
                        (OperationSpec("count", "transform", (Edge("list"),), Edge("int"), "count"),))
    lib.atoms += (kernel.Atom("count", 1, mutate),)
    seen = observation("length", n.Call("count", (n.Var("xs"),)), ("count",),
                       inputs=[["xs", "list"]])
    sample = [1, 2]
    result = verify_observation(seen, lib, VerifyRequest("bounded", ((sample,),),
                                {"domain": "mutable list", "size": 1}, reference=lambda xs: len(xs)))
    assert not result.ok
    assert "facts_unchanged: observation changed public inputs" in result.problems


def test_combinator_handle_closure_rejects_act_and_accepts_pure():
    lib = library(combinator=True)
    step = operation("step", n.Call("add", (n.Var("value"), n.Lit(1))), ("add",))
    lib.write(step)
    lib.check("step")
    lib.make_callable("step", [(1,)])
    safe = n.Call("apply", (n.Lit(kernel.FnRef("step")), n.Var("value")))
    seen = observation("composed", safe, ("apply", "step"), inputs=[["value", "int"]])
    lib.write(seen)
    lib.check("composed")
    assert observe(lib.get("composed"), lib, [(3,)]) == [Ok(4)]
    unsafe = n.Call("apply", (n.Lit(kernel.FnRef("change")), n.Var("value")))
    rejected = observation("unsafe_handle", unsafe, ("apply", "change"), inputs=[["value", "int"]])
    assert any("truth" in problem for problem in check_observation(rejected, lib))


def test_public_value_cannot_call_truth_sorted_world_operation():
    lib = library()
    lib.world = replace(lib.world, operations=lib.world.operations +
                        (OperationSpec("inspect_truth", "decide", (Edge("state"),),
                                       Edge("int"), "inspect"),))
    lib.atoms += (kernel.Atom("inspect_truth", 1, lambda state: state["value"]),)
    seen = observation("not_public", n.Call("inspect_truth", (n.Var("value"),)), ("inspect_truth",),
                       inputs=[["value", "int"]])
    problems = check_observation(seen, lib)
    assert any("truth" in problem for problem in problems)


def test_integer_memory_literal_is_not_a_forged_truth_when_the_truth_sort_is_int():
    from types import SimpleNamespace

    from opulse.atoms import kernel
    from opulse.atoms import nodes as n
    from opulse.atoms.observations import check_observation
    from opulse.atoms.spec import Definition, ObservationSpec

    class Lib:
        dialect = "atoms-v2"
        world = SimpleNamespace(observation={"truth": "int", "probes": [{"name": "probe"}]}, operations=())
        definitions: dict = {}  # noqa: RUF012 - read-only stand-in

        def scope(self):
            return kernel.DictScope([kernel.Atom("probe", 1, lambda state: state, kind="observation")])

        def get(self, name):
            return self.definitions[name]

    spec = ObservationSpec("seen", ("probe",), n.Var("memory"), {"sort": "int", "init": n.Lit(0), "step": n.Var("probe")})
    problems = check_observation(Definition("seen", "observation", "invented", 1, (), spec, spec.body), Lib())
    assert "observation cannot receive literal truth state" not in problems


@settings(deadline=None)
@given(st.integers(-20, 20))
def test_given_probe_with_operation_spec_keeps_truth_and_unfolds(value):
    lib = library()
    state = {"value": value}
    seen = observation("seen_probe", n.Call("peek", (n.Var("s"),)), ("peek",), reads=("peek",))
    lib.write(seen)
    lib.check("seen_probe")
    lib.make_callable("seen_probe", ((state,),))
    assert observe(lib.get("seen_probe"), lib, [state]) == [Ok(value)]
    assert state == {"value": value}
    result = lib.verify("seen_probe", VerifyRequest("bounded", ((state,),),
                                                    {"domain": "one truth state", "size": 1}))
    assert {"non_interference", "facts_unchanged", "unfold_equivalence"} <= set(result.evidence.checks)
