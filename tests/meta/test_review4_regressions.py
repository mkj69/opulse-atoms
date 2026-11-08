"""Review-4 regressions for bounded meta-world evidence and code execution."""

import pytest

from opulse.atoms import kernel, library, nodes
from opulse.atoms.boundary import Boundary, flatten_calls
from opulse.atoms.spec import Contract, Definition, Edge, OperationSpec
from opulse.atoms.values import Bottom
from opulse.atoms.verify import unfold_equivalent
from opulse.meta import code, engine
from opulse.meta.export_util import outside_scope
from opulse.meta.worlds.builder import hosts, story, world
from opulse.meta.worlds.builder.showcase import tasks as builder_tasks
from opulse.meta.worlds.code.export import export as code_export
from opulse.meta.worlds.code.showcase import showcase as code_showcase
from opulse.meta.worlds.code.story import build_story


def _identity():
    lib = story.BuilderLibrary(world.declaration(), hosts.atoms())
    definition = Definition("identity", "operation", "invented", 1, (),
                            OperationSpec("identity", "transform", (Edge("int"),), Edge("int"),
                                          "identity"), nodes.Var("arg0"))
    lib.write(definition)
    lib.check("identity")
    lib.make_callable("identity", [(7,)])
    return lib


@pytest.fixture(scope="module")
def code_story():
    """One code-world story per module; the tests below only read it (evidence accessors return copies)."""
    return build_story()


def test_monomorphic_errors_are_not_filtered():
    lib = _identity()
    definition = Definition("bad_add", "operation", "invented", 1, ("int_add",),
                            OperationSpec("bad_add", "transform", (Edge("int"),), Edge("int"),
                                          "test"), nodes.Call("int_add", (nodes.Lit("oops"), nodes.Var("arg0"))))
    lib.write(definition)
    with pytest.raises(library.PipelineError, match="expected int, got str"):
        lib.check("bad_add")


@pytest.mark.parametrize("domain,scope,reference", [
    ([(7,)], {"domain": "int 7", "size": 1}, None),
    ([], {"domain": "all integers", "size": 0}, lambda _: 7),
    ([(7,)], {"domain": "int 7", "size": 2}, lambda _: 7),
    ([(7,)], {"domain": "int 7", "size": 1, "domain_hash": "wrong"}, lambda _: 7),
    ([(7,)], {"domain": "all integers", "size": 1}, lambda _: 7),
    ([(7,)], {"domain": "int 7", "size": 1, "input_hashes": ["wrong"]}, lambda _: 7),
    ([(7,)], {"domain": "int 7", "size": 1}, lambda _: Bottom("wrong")),
])
def test_reference_and_domain_require_actual_evidence(domain, scope, reference):
    lib = _identity()
    with pytest.raises(library.PipelineError):
        lib.verify("identity", library.VerifyRequest("bounded", domain, scope, reference=reference))
    with pytest.raises(library.PipelineError):
        lib.promote("identity", Contract("always 42"))


def test_explicit_bottom_reason_must_match():
    lib = _identity()
    body = nodes.Call("int_div", (nodes.Lit(1), nodes.Lit(0)))
    definition = Definition("error", "operation", "invented", 1, ("int_div",),
                            OperationSpec("error", "transform", (Edge("int"),), Edge("int"),
                                          "division fails"), body)
    lib.write(definition)
    lib.check("error")
    lib.make_callable("error", [(7,)])
    assert lib.run("error", (7,)).outcome == Bottom("int")
    with pytest.raises(library.PipelineError, match="reference mismatch"):
        lib.verify("error", library.VerifyRequest("bounded", [(7,)],
                   {"domain": "recorded input 7", "size": 1},
                   reference=lambda _: Bottom("different")))


def test_code_promoted_evidence_is_defensive(code_story):
    lib, _, _ = code_story
    scope = lib.get("const_fold").evidence.scope
    scope["size"] = 999999
    lib.definitions["const_fold"].evidence.scope["size"] = 999999
    lib.to_dict()["definitions"][3]["evidence"]["scope"]["size"] = 999999
    lib.derived_world().promoted[3].evidence.scope["size"] = 999999
    assert lib.get("const_fold").evidence.scope["size"] == 224
    assert len(lib.get("const_fold").evidence.scope["code_hashes"]) == 224


def test_builder_quote_eval_all_promoted_members():
    lib, families = story.creation()
    assert {"constant", "world_interface"} <= set(lib.get("base_z5").evidence.checks)
    assert {"operation_family", "reference"} <= set(lib.get("for_each_tuple").evidence.checks)
    invalid_family = library.VerifyRequest("bounded", families["for_each_tuple"],
                                           {"domain": "recorded one callback", "size": 1},
                                           reference=lambda *args: story.reference("for_each_tuple", *args))
    rejected = story._verify_combinator(lib.get("for_each_tuple"), lib, invalid_family)
    assert not rejected.ok and rejected.problems == [
        "combinator needs a declared callable operation family"]
    assert outside_scope(lib.run("for_each_tuple", families["for_each_tuple"][0], trace=True).trace,
                         lib)
    assert outside_scope(lib.run("for_each_tuple", (story.binary_world(), 0, 0,
                                                    kernel.FnRef("count_row")), trace=True).trace, lib)
    scope = kernel.DictScope(hosts.atoms())
    for name, cases in families.items():
        if lib.get(name).kind == "law":
            assert "holds" in lib.get(name).evidence.checks
            continue
        for args in cases[:1]:
            direct = lib.run(name, args, trace=True)
            quoted = engine.call("eval", (code.quote_from_library(lib, name),
                                          code.quote_args(lib, args)), scope)
            if lib.get(name).kind == "bridge":  # bridge code is callable since atoms-meta 0.3 (2.5)
                assert direct.outcome == story.Ok(story.reference(name, *args)) and direct.steps == 3
                assert (quoted.outcome, quoted.steps) == (direct.outcome, direct.steps), name
                continue
            assert (quoted.outcome, quoted.steps) == (direct.outcome, direct.steps), name
            invocation = nodes.Call(name, tuple(nodes.Lit(arg) for arg in args))
            full = engine.evaluate(kernel.inline(invocation, lib.scope()), scope=lib.scope())
            assert (full.outcome, full.steps) == (direct.outcome, direct.steps), name
            for boundary in (Boundary(), Boundary.unfold_all()):
                visible = flatten_calls(direct.trace, boundary)
                assert sum(frame.steps for frame in visible) == direct.steps, name
                assert direct.trace.outcome == full.outcome, name


def test_code_quote_eval_all_promoted_members(code_story):
    lib, family, _ = code_story
    for definition in lib.definitions.values():
        if definition.origin != "invented" or definition.status != "promoted" or definition.kind not in ("operation", "object", "combinator") or definition.name.startswith(("Specialize_member_", "generated_")):
            continue
        scope = definition.evidence.scope
        args = () if definition.name == "poly" else (
            (kernel.FnRef("const_fold"), kernel.FnRef("simplify_safe"), family[0])
            if definition.name == "pipeline" else
            (family[0], 0) if definition.name == "specialize" else
            (family[0].fields[2],) if definition.name == "has_div" else (family[0],))
        if definition.name in ("specialize", "specialize_zero"):
            from opulse.meta.worlds.code.story import specialize_source
            args = (specialize_source(lib), 0) if definition.name == "specialize" else (
                specialize_source(lib),)
        direct = lib.run(definition.name, args, trace=True)
        quoted = lib.run("eval", (code.quote_from_library(lib, definition.name),
                                  code.quote_args(lib, args)))
        assert (quoted.outcome, quoted.steps) == (direct.outcome, direct.steps), definition.name
        invocation = nodes.Call(definition.name, tuple(nodes.Lit(arg) for arg in args))
        unfolded = engine.evaluate(kernel.inline(invocation, lib.scope()), scope=lib.scope())
        assert (unfolded.outcome, unfolded.steps) == (direct.outcome, direct.steps), definition.name
        assert unfold_equivalent(direct.trace, [Boundary(), Boundary.unfold_all()]).ok, definition.name
        assert scope["enumerated_count"] == scope["size"]
        assert len(scope["input_hashes"]) == scope["size"]
        if definition.kind == "combinator":
            assert {"operation_family", "reference"} <= set(definition.evidence.checks)


def test_exported_scope_markers_and_prompts(code_story):
    built = code_story
    lib, family, _ = built
    from opulse.meta.worlds.code.story import specialization_family
    assert not outside_scope(lib.run("const_fold", (family[0],), trace=True).trace, lib)
    assert outside_scope(lib.run("specialize", (specialization_family(lib, family)[0], 3),
                                 trace=True).trace, lib)
    data = code_export(built)
    examples = {entry["name"]: entry["examples"][0] for entry in data["story"]}
    for name in ("stable_simplify", "specialize", "specialize_zero", "pipeline"):
        assert examples[name]["outside_scope"] is True, name
    prompts = [task["prompt"] for task in code_showcase(*built)]
    assert "both children are integer literals" in prompts[0]
    assert "sub(e, e)" in prompts[1] and "mul(e, 0)" in prompts[1]
    assert "strict" in prompts[1].lower() and "step" in prompts[2]
    builder_prompt = builder_tasks()[0]["prompt"]
    assert "names, sorts, tables, bodies, laws, probes, kinds, tags" in builder_prompt
    assert "probe <probe_name> depends on act <operation_name>" in builder_prompt
    assert world.TAGS["agents"] == 1
