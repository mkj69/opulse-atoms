"""Integration regressions and non-interference properties (spec sections 11 and 19)."""

from dataclasses import replace

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.boundary import Boundary
from opulse.atoms.bridges import (
    BridgeContext,
    bridge_defn,
    runtime_bridge_defn,
    verify_bridge,
)
from opulse.atoms.laws import check_law
from opulse.atoms.library import Library, PipelineError, VerifyRequest
from opulse.atoms.notation import parse_definition
from opulse.atoms.objects import verify_object
from opulse.atoms.observations import check_observation, observe
from opulse.atoms.spec import (
    BridgeSpec,
    CombinatorSpec,
    Definition,
    Edge,
    ObjectSpec,
    ObservationSpec,
    OperationSpec,
    TemplateSpec,
)
from opulse.atoms.templates import instantiate
from opulse.atoms.values import Ok
from opulse.atoms.verify import unfold_equivalent_calls
from opulse.atoms.world import WorldDecl


def bridge_library():
    world = WorldDecl("bridge-integ", 1, "atoms-v2", {}, {},
                      (ObjectSpec("int", "given"),), (),
                      {"nodes": list(n.NODE_NAMES), "recursion": "fuel"}, {}, {},
                      open_kinds=("bridge", "object", "operation"))
    return Library(world, ())


def test_bridge_rejects_out_of_sort_and_vacuous_domain():
    lib = bridge_library()
    spec = BridgeSpec("identity", "int", "int", n.Var("x"), n.Lit(False))
    definition = Definition("identity", "bridge", "invented", 1, (), spec, bridge_defn(spec).body)
    assert any("source sort" in problem for problem in verify_bridge(
        definition, lib, VerifyRequest("bounded", ((True,),), {"domain": "bool", "size": 1})).problems)
    lib.write(definition)
    lib.check("identity")
    lib.make_callable("identity", ((1,),))
    with pytest.raises(PipelineError):
        lib.verify("identity", VerifyRequest("bounded", ((1,),), {"domain": "empty", "size": 1}))


def test_bridge_requires_checked_pair_for_each_interface_operation():
    lib = bridge_library()
    lib.atoms += (kernel.Atom("positive", 1, lambda value: value > 0),
                  kernel.Atom("dec", 1, lambda value: value - 1))
    spec = BridgeSpec("translate", "int", "int", n.Var("x"),
                      n.Call("positive", (n.Var("x"),)), (("dec", "dec"),))
    definition = Definition("translate", "bridge", "invented", 1, ("positive",), spec,
                            bridge_defn(spec).body)
    request = VerifyRequest("bounded", ((1,),), {"domain": "positive", "size": 1})
    result = verify_bridge(definition, lib, request)
    assert not result.ok
    assert request.scope["pairs_checked"] == 0
    assert any("no checked pairs" in problem for problem in result.problems)


@settings(deadline=None)
@given(st.integers(-30, 30))
def test_fast_frame_rejects_wrong_outcome_with_correct_steps(number):
    scope = kernel.DictScope(atoms=(kernel.Atom("inc", 1, lambda item: item + 1),),
                             defns=(kernel.Defn("twice", ("x",), n.Call("inc", (n.Var("x"),))),),
                             fast_paths={"twice": kernel.FastPath("twice", lambda item: item + 99,
                                                                   lambda item: 1, lambda item: True)})
    root = kernel.call("twice", (number,), scope, trace=True).trace
    assert not unfold_equivalent_calls(root, [Boundary.unfold_all(), Boundary.unfold_none()]).ok


def test_notation_instantiates_object_template_and_uses_edge_names():
    lib = bridge_library()
    lib.world = replace(lib.world, objects=lib.world.objects + (ObjectSpec("Pair", "given"),))
    template = Definition("Quot", "template", "invented", 1, (),
                          TemplateSpec("Quot", (("T", "sort"), ("reduce", "operation")), "object",
                                       {"form": "refine", "base": "$T", "valid": n.to_json(n.Lit(True)),
                                        "canon": n.to_json(n.Call("$reduce", (n.Var("x"),)))}), n.Lit(0))
    lib._definitions["Quot"] = template
    lib._definitions["reduce"] = Definition(
        "reduce", "operation", "given", 0, (), OperationSpec("reduce", "transform",
            (Edge("Pair"),), Edge("Pair"), "reduce"), {"host": "reduce"}, status="promoted")
    lib.atoms += (kernel.Atom("reduce", 1, lambda value: value),)
    instance = parse_definition("obj Frac = Quot[Pair, reduce] L2", lib)
    assert instance == instantiate(template, {"T": "Pair", "reduce": "reduce"}, "Frac", lib=lib)
    lib.write(instance)
    lib.check("Frac")
    parsed = parse_definition("op ident(x: int) -> int = x L1")
    lib.write(parsed)
    lib.check("ident")
    lib.make_callable("ident", ((3,),))
    assert lib.run("ident", (3,)).outcome == Ok(3)


def test_abstraction_checks_all_declared_interface_operations():
    lib = bridge_library()
    lib.atoms += (kernel.Atom("good", 1, lambda value: value),
                  kernel.Atom("bad", 1, lambda value: value + 1),
                  kernel.Atom("identity", 1, lambda value: value))
    spec = ObjectSpec("Box", "refine", base="int", valid=n.Lit(True), canon=n.Var("x"),
                      interface=("bad",))
    definition = Definition("Box", "object", "invented", 1, (), spec, None)
    request = VerifyRequest("bounded", ((1,),), {"domain": "one", "size": 1},
                            extra={"abs": lambda value: value.fields[0],
                                   "interface_pairs": (("good", "identity"),)})
    result = verify_object(definition, lib, request)
    assert not result.ok
    assert any("missing interface operations" in problem for problem in result.problems)


def test_attached_world_bridge_resolves_same_name_on_target():
    source = bridge_library()
    target = bridge_library()
    target.world = replace(target.world, world="target-integ")
    source.atoms += (kernel.Atom("scale", 1, lambda value: value + 1),)
    target.atoms += (kernel.Atom("scale", 1, lambda value: value * 2),)
    source.attach_world("target-integ@1", target)
    spec = BridgeSpec("translate", "int", "int", n.Call("scale", (n.Var("x"),)))
    context = BridgeContext(source, target)
    scope = kernel.ChainScope(source.local_scope(), "bridge-integ@1",
                              {"target-integ@1": target.local_scope()})
    evaluated = kernel.call("translate", (3,), scope.extend((runtime_bridge_defn(spec, context),)))
    assert evaluated.outcome == Ok(6)


def test_law_and_bridge_template_provenance_preserves_body_equality():
    lib = bridge_library()
    for kind, pattern, body, name in (
        ("law", {"vars": [], "statement": n.to_json(n.Lit(True))}, n.Lit(True), "lemma"),
        ("bridge", {"source": "int", "target": "int", "map": n.to_json(n.Var("x"))},
         n.Var("x"), "convert"),
        ("bridge", {"source": "int", "target": "int", "map": n.to_json(n.Var("x")),
                    "domain": n.to_json(n.Lit(True))},
         bridge_defn(BridgeSpec("partial", "int", "int", n.Var("x"), n.Lit(True))).body, "partial"),
    ):
        template = Definition("Family", "template", "invented", 1, (),
                              TemplateSpec("Family", (("index", "int"),), kind, pattern), n.Lit(0))
        instance = instantiate(template, {"index": 2}, name)
        assert instance.body == body
        assert not instance.validate()
        assert not (check_law(instance, lib) if kind == "law" else
                    verify_bridge(instance, lib, VerifyRequest(
                        "bounded", ((1,),), {"domain": "one", "size": 1})).problems)


def observation_library():
    operations = (OperationSpec("peek", "decide", (Edge("state"),), Edge("int"), "peek"),
                  OperationSpec("add", "transform", (Edge("int"), Edge("int")), Edge("int"), "add"),
                  OperationSpec("act", "act", (Edge("int"),), Edge("int"), "act"),
                  OperationSpec("read_state", "decide", (Edge("state"),), Edge("int"), "read_state"))
    combinator = CombinatorSpec("@apply", ("f", "x"), ("f",), n.Call("f", (n.Var("x"),)))
    world = WorldDecl("observation-integ", 1, "atoms-v2", {}, {}, (), operations,
                      {"nodes": list(n.NODE_NAMES), "recursion": "fuel",
                       "library": (combinator.to_dict(),)},
                      {"truth": "state", "probes": [{"name": "peek"}]}, {},
                      open_kinds=("operation", "observation", "bridge"))
    lib = Library(world, (kernel.Atom("peek", 1, lambda state: state["visible"], kind="observation"),
                          kernel.Atom("add", 2, lambda left, right: left + right),
                          kernel.Atom("act", 1, lambda value: value + 5),
                          kernel.Atom("read_state", 1, lambda state: state["secret"])))
    spec = OperationSpec("increment", "transform", (Edge("int"),), Edge("int"), "increment",
                         extra={"input_names": ["value"]})
    lib.write(Definition("increment", "operation", "invented", 1, ("add",), spec,
                         n.Call("add", (n.Var("value"), n.Lit(1)))))
    lib.check("increment")
    lib.make_callable("increment", ((1,),))
    bridge = BridgeSpec("shift", "int", "int", n.Call("increment", (n.Var("x"),)))
    lib.write(Definition("shift", "bridge", "invented", 2, ("increment",), bridge,
                         bridge_defn(bridge).body))
    lib.check("shift")
    lib.make_callable("shift", ((1,),))
    return lib


@settings(deadline=None)
@given(st.integers(-100, 100), st.integers(), st.integers())
def test_equal_probe_histories_yield_equal_derived_observations(value, secret_a, secret_b):
    lib = observation_library()
    body = n.Call("@apply", (n.Lit(kernel.FnRef("shift")), n.Call("peek", (n.Var("s"),))))
    spec = ObservationSpec("seen", ("peek",), body)
    definition = Definition("seen", "observation", "invented", 3,
                            ("@apply", "shift", "peek"), spec, body)
    assert not check_observation(definition, lib)
    assert observe(definition, lib, [{"visible": value, "secret": secret_a},
                                     {"visible": value, "secret": secret_b}]) == [Ok(value + 1)] * 2


@settings(deadline=None)
@given(st.sampled_from(("act", "read_state")), st.booleans())
def test_transitive_unsafe_closure_is_always_rejected(unsafe, through_bridge):
    lib = observation_library()
    if through_bridge:
        spec = BridgeSpec("unsafe_bridge", "int", "int", n.Call(unsafe, (n.Var("x"),)))
        dependency = Definition("unsafe_bridge", "bridge", "invented", 2, (unsafe,), spec,
                                bridge_defn(spec).body)
        lib._definitions[dependency.name] = dependency
        name = dependency.name
    else:
        name = unsafe
    body = n.Call("@apply", (n.Lit(kernel.FnRef(name)), n.Call("peek", (n.Var("s"),))))
    definition = Definition("seen", "observation", "invented", 3,
                            ("@apply", name, "peek"), ObservationSpec("seen", ("peek",), body), body)
    assert any("truth" in problem or "act" in problem for problem in check_observation(definition, lib))


@settings(deadline=None)
@given(st.integers(-10, 10))
def test_bridge_accepting_truth_sort_cannot_enter_observation_closure(value):
    lib = observation_library()
    spec = BridgeSpec("unseal", "state", "int", n.Lit(value))
    lib._definitions["unseal"] = Definition("unseal", "bridge", "invented", 1, (), spec,
                                             bridge_defn(spec).body)
    body = n.Call("unseal", (n.Call("peek", (n.Var("s"),)),))
    seen = Definition("seen", "observation", "invented", 2, ("unseal", "peek"),
                      ObservationSpec("seen", ("peek",), body), body)
    assert any("truth" in problem for problem in check_observation(seen, lib))


@settings(deadline=None)
@given(st.sampled_from(("act", "read_state")))
def test_qualified_attached_truth_operations_cannot_enter_observation_closure(unsafe):
    lib = observation_library()
    attached = observation_library()
    attached.world = replace(attached.world, world="attached-integ")
    lib.attach_world("attached-integ@1", attached)
    name = f"attached-integ@1:{unsafe}"
    body = n.Call(name, (n.Call("peek", (n.Var("s"),)),))
    seen = Definition("seen", "observation", "invented", 2, (name, "peek"),
                      ObservationSpec("seen", ("peek",), body), body)
    assert any("truth" in problem or "act" in problem for problem in check_observation(seen, lib))
