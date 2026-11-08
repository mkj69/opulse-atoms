"""Library pipeline and evidence invariants (spec sections 8, 9 and 11.I4)."""

from dataclasses import replace
from time import perf_counter

import pytest

from opulse.atoms import kernel, nodes
from opulse.atoms import library as library_module
from opulse.atoms.library import (
    Library,
    PipelineError,
    VerifyResult,
    bounded,
    exhaustive,
    register_kind,
    sampled,
)
from opulse.atoms.spec import (
    Contract,
    Definition,
    Edge,
    ObjectSpec,
    ObservationSpec,
    OperationSpec,
)
from opulse.atoms.values import Ok
from opulse.atoms.world import WorldDecl


def fixture(byte=False):
    sort = "byte" if byte else "int"
    mod = 256 if byte else None
    operations = (
        ("zero", (), lambda: 0, "transform"),
        ("succ", (sort,), lambda value: (value + 1) % mod if byte else value + 1, "transform"),
        ("pred", (sort,), lambda value: (value - 1) % mod if byte else value - 1, "transform"),
        ("is_zero", (sort,), lambda value: value == 0, "decide"),
        ("add", (sort, sort), lambda left, right: (left + right) % mod if byte else left + right, "combine"),
    )
    specs = tuple(OperationSpec(name, role, tuple(Edge(arg) for arg in inputs),
                                Edge("bool" if name == "is_zero" else sort), name)
                  for name, inputs, _, role in operations)
    object_spec = ObjectSpec(sort, "refine", base="int", valid=nodes.Lit(True)) if byte else ObjectSpec(sort, "given")
    world = WorldDecl(sort, 1, "atoms-v2", {}, {}, (object_spec,), specs,
                      {"nodes": list(nodes.NODE_NAMES), "recursion": "fuel"}, {}, {})
    atoms = [kernel.Atom(name, len(inputs), implementation) for name, inputs, implementation, _ in operations]
    return Library(world, atoms)


def definition(name, body, dependencies, layer, input_names=("arg0", "arg1"), sort="int"):
    op = OperationSpec(name, "combine", tuple(Edge(sort) for _ in input_names), Edge(sort), name,
                       extra={"input_names": list(input_names)})
    return Definition(name, "operation", "invented", layer, tuple(dependencies), op, body)


def mul_definition(sort="int"):
    body = nodes.Rec("loop", ("left", "right", "total"),
                     nodes.Case(((nodes.Test(nodes.Call("is_zero", (nodes.Var("right"),))), nodes.Var("total")),),
                                nodes.Call("loop", (nodes.Var("left"),
                                                    nodes.Call("pred", (nodes.Var("right"),)),
                                                    nodes.Call("add", (nodes.Var("total"), nodes.Var("left")))))),
                     (nodes.Var("arg0"), nodes.Var("arg1"), nodes.Lit(0)), "fuel")
    return definition("mul", body, ("is_zero", "pred", "add"), 1, sort=sort)


def ready(lib, defn, sample=((2, 3),)):
    lib.write(defn)
    lib.check(defn.name)
    lib.make_callable(defn.name, sample)


def test_multiplication_promotion_scope_cost_and_persistence():
    lib = fixture()
    ready(lib, mul_definition())
    request = replace(exhaustive((range(16), range(16)), "all 0..15 integer pairs"),
                      reference=lambda left, right: left * right)
    verified = lib.verify("mul", request)
    assert verified.evidence.checks == ("reference", "unfold_equivalence")
    assert verified.evidence.scope["size"] == 256
    assert lib.account("mul").cost.steps["max"] > 0
    lib.promote("mul", Contract("integer multiplication"))
    square = definition("square", nodes.Call("mul", (nodes.Var("arg0"), nodes.Var("arg0"))),
                        ("mul",), 2, ("arg0",))
    ready(lib, square, ((4,),))
    lib.record_solution(nodes.Call("mul", (nodes.Lit(2), nodes.Lit(3))))
    assert lib.get("mul").cost.reuse == 0
    assert lib.account("mul").cost.reuse == 2
    lib.verify("square", replace(exhaustive((range(8),), "all 0..7 integers"), reference=lambda value: value ** 2))
    lib.promote("square", Contract("square"))
    derived = lib.derived_world()
    assert set(derived.scopes()) == {"mul", "square"}
    assert derived.promoted[0].contract.guarantees == "integer multiplication"
    assert derived.scopes()["mul"]["size"] == 256
    assert lib.run("square", (6,)).outcome == Ok(36)
    loaded = Library.from_dict(lib.to_dict(), lib.world, lib.atoms)
    assert loaded.get("square").status == "promoted"
    assert loaded.run("square", (6,)).outcome == Ok(36)
    assert loaded.account("mul").cost.reuse == 2


def test_sampled_failure_and_changed_world_hash():
    lib = fixture()
    ready(lib, mul_definition())
    request = replace(sampled(lambda rng: (rng.randrange(4), rng.randrange(4)), 8, 7, "seeded pairs"),
                      reference=lambda left, right: left * right)
    lib.verify("mul", request)
    with pytest.raises(PipelineError, match="sampled evidence cannot be promoted"):
        lib.promote("mul", Contract("multiplication"))
    loaded = Library.from_dict(lib.to_dict(), replace(lib.world, version=2), lib.atoms)
    assert loaded.get("mul").status == "callable"
    assert loaded.get("mul").evidence is None

    lib = fixture()
    ready(lib, mul_definition())
    lib.verify("mul", replace(exhaustive((range(2), range(2)), "binary inputs"), reference=lambda a, b: a * b))
    lib.world = replace(lib.world, version=2)
    assert lib.get("mul").status == "callable" and lib.get("mul").evidence is None
    with pytest.raises(PipelineError, match="promote requires verified"):
        lib.promote("mul", Contract("multiplication"))

    lib = fixture()
    ready(lib, mul_definition())
    lib.verify("mul", replace(exhaustive((range(2), range(2)), "binary inputs"), reference=lambda a, b: a * b))
    lib.world.params["new_setting"] = True
    assert lib.get("mul").status == "callable" and lib.get("mul").evidence is None


def test_invalidation_and_reference_counterexample():
    lib = fixture()
    ready(lib, mul_definition())
    lib.verify("mul", replace(exhaustive((range(3), range(3)), "small pairs"), reference=lambda a, b: a * b))
    lib.promote("mul", Contract("multiply"))
    square = definition("square", nodes.Call("mul", (nodes.Var("arg0"), nodes.Var("arg0"))),
                        ("mul",), 2, ("arg0",))
    ready(lib, square, ((2,),))
    lib.verify("square", replace(exhaustive((range(3),), "small inputs"), reference=lambda value: value ** 2))
    lib.promote("square", Contract("square"))
    with pytest.raises(PipelineError, match="immutable"):
        lib.replace("mul", mul_definition())
    with pytest.raises(PipelineError, match="inherit evidence"):
        lib.replace("mul", replace(mul_definition(), evidence=lib.get("mul").evidence),
                    force_new_version=True)
    successor = lib.replace("mul", mul_definition(), force_new_version=True)
    assert successor.name == "mul.v2" and successor.status == "written"
    assert lib.get("mul").status == "promoted" and lib.get("square").status == "promoted"

    wrong = definition("wrong", nodes.Call("add", (nodes.Var("arg0"), nodes.Var("arg1"))), ("add",), 1)
    ready(lib, wrong)
    with pytest.raises(PipelineError, match="counterexample"):
        lib.verify("wrong", replace(exhaustive((range(3), range(3)), "small pairs"),
                                    reference=lambda left, right: left * right))


def test_closed_kind_and_transitive_hash_and_stale_evidence():
    lib = fixture()
    lib.world = replace(lib.world, open_kinds=("operation",))
    observation = ObservationSpec("seen", (), nodes.Lit(1))
    with pytest.raises(PipelineError, match="kind observation is closed in world"):
        lib.write(Definition("seen", "observation", "invented", 1, (), observation, nodes.Lit(1)))
    ready(lib, mul_definition())
    lib.verify("mul", replace(exhaustive((range(2), range(2)), "pairs"), reference=lambda a, b: a * b))
    assert lib.get("mul").evidence.content_hash == lib.content_hash("mul")
    assert lib.by_hash(lib.content_hash("mul")) == lib.get("mul")
    assert lib.by_hash("unknown") is None
    lib.write(definition("forward", nodes.Call("later", (nodes.Var("arg0"),)),
                         ("later",), 2, ("arg0",)))
    assert lib.by_hash("unknown") is None
    square = definition("square", nodes.Call("mul", (nodes.Var("arg0"), nodes.Var("arg0"))),
                        ("mul",), 2, ("arg0",))
    lib.write(square)
    original = lib.content_hash("square")
    lib._definitions["mul"] = replace(lib.get("mul"), body=nodes.Lit(9))
    assert lib.content_hash("square") != original
    with pytest.raises(PipelineError, match="content hash changed"):
        lib.promote("mul", Contract("multiply"))


def test_checker_open_nodes_recursion_arity_sorts_and_cycle():
    lib = fixture()
    bad = definition("bad", nodes.Call("add", (nodes.Lit("bad"),)), ("add",), 1)
    lib.write(bad)
    with pytest.raises(PipelineError, match="expects 2 arguments"):
        lib.check("bad")
    assert lib.get("bad").status == "written"
    mismatch = definition("mismatch", nodes.Call("add", (nodes.Lit("text"), nodes.Lit(3))), ("add",), 1)
    lib.write(mismatch)
    with pytest.raises(PipelineError, match="expected int, got str"):
        lib.check("mismatch")
    lib = fixture()
    lib.world = replace(lib.world, combinators={"nodes": ["Var", "Lit", "Call"], "recursion": "measure"})
    lib.write(mul_definition())
    with pytest.raises(PipelineError, match="not opened"):
        lib.check("mul")
    lib = fixture()
    invalid_measure = replace(mul_definition(), body=replace(mul_definition().body, measure="unknown"))
    lib.write(invalid_measure)
    with pytest.raises(PipelineError, match="recursion measure must be a node"):
        lib.check("mul")
    lib = fixture()
    first = definition("first", nodes.Call("second", (nodes.Var("arg0"),)), ("second",), 2, ("arg0",))
    second = definition("second", nodes.Call("first", (nodes.Var("arg0"),)), ("first",), 2, ("arg0",))
    lib.write(first)
    lib.write(second)
    with pytest.raises(PipelineError, match="cycle"):
        lib.check("first")


def test_kind_hooks():
    lib = fixture()
    name = "hooked"
    defn = definition(name, nodes.Var("arg0"), (), 1, ("arg0",))
    previous = library_module._CHECKERS.get("operation")
    register_kind("operation", checker=lambda definition, library: ["kind rejected"] if definition.name == name else [])
    try:
        lib.write(defn)
        with pytest.raises(PipelineError, match="kind rejected"):
            lib.check(name)
    finally:
        if previous is None:
            library_module._CHECKERS.pop("operation", None)
        else:
            register_kind("operation", checker=previous)

    observation = ObservationSpec("seen", (), nodes.Lit(1))
    seen = Definition("seen", "observation", "invented", 1, (), observation, nodes.Lit(1))
    lib.world = replace(lib.world, open_kinds=("operation", "observation"))
    previous_verifier = library_module._VERIFIERS.get("observation")
    register_kind("observation", verifier=lambda definition, library, request:
                  VerifyResult(True, ("dependency", "facts_unchanged", "non_interference", "reference"), [], [0]))
    try:
        lib.write(seen)
        lib.check("seen")
        lib.make_callable("seen", ((None,),))  # observation samples are truth states
        lib.verify("seen", replace(exhaustive((), "the singleton observation"), reference=lambda state: 1))
        lib.promote("seen", Contract("always one"))
        assert lib.get("seen").status == "promoted"
    finally:
        if previous_verifier is None:
            library_module._VERIFIERS.pop("observation", None)
        else:
            register_kind("observation", verifier=previous_verifier)


def test_load_rejects_stale_transitive_dependency():
    lib = fixture()
    ready(lib, mul_definition())
    lib.verify("mul", replace(exhaustive((range(2), range(2)), "binary inputs"), reference=lambda a, b: a * b))
    lib.promote("mul", Contract("multiply"))
    square = definition("square", nodes.Call("mul", (nodes.Var("arg0"), nodes.Var("arg0"))),
                        ("mul",), 2, ("arg0",))
    ready(lib, square, ((2,),))
    lib.verify("square", replace(exhaustive((range(2),), "binary inputs"), reference=lambda a: a * a))
    records = lib.to_dict()
    records["definitions"][0]["contract"]["guarantees"] = "changed"
    loaded = Library.from_dict(records, lib.world, lib.atoms)
    assert loaded.get("square").status == "callable" and loaded.get("square").evidence is None


def test_byte_mul_blocks_bounded_timing():
    lib = fixture(byte=True)
    body = nodes.Blocks((("count", nodes.Var("arg1")), ("total", nodes.Lit(0))), "loop", (
        ("loop", nodes.Block((), nodes.CondJump(nodes.Test(nodes.Call("is_zero", (nodes.Var("count"),))),
                                                     "end", "add"))),
        ("add", nodes.Block((("total", nodes.Call("add", (nodes.Var("total"), nodes.Var("arg0")))),
                              ("count", nodes.Call("pred", (nodes.Var("count"),)))), nodes.Jump("loop"))),
        ("end", nodes.Block((), nodes.Halt(nodes.Var("total"))))))
    ready(lib, definition("byte_mul", body, ("is_zero", "add", "pred"), 1, sort="byte"), ((3, 2),))
    request = replace(bounded((range(256), range(16)), "bounded: second byte <= 15"),
                      reference=lambda left, right: left * right % 256)
    start = perf_counter()
    lib.verify("byte_mul", request)
    duration = perf_counter() - start
    assert lib.get("byte_mul").evidence.method == "bounded"
    lib.account("byte_mul")
    lib.promote("byte_mul", Contract("product modulo 256"))
    print(f"byte_mul 256 x 16 bounded verification: {duration:.2f}s")



def test_verification_is_fuel_bounded():
    lib = fixture()
    ready(lib, mul_definition())
    request = exhaustive(((2,), (3, -1)), "left 2, right in {3, -1}")
    request = replace(request, reference=lambda left, right: left * right, extra={"fuel": 10_000})
    with pytest.raises(PipelineError, match="Unknown"):
        lib.verify("mul", request)
