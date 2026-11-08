"""Executable builder@1 evidence, from layer-0 meters to exhaustive challenges."""

import hashlib
import inspect
import json
import os
import subprocess
import sys
from itertools import product

import pytest

from opulse.atoms import kernel, laws, library, notation
from opulse.atoms import nodes as n
from opulse.atoms.boundary import Boundary
from opulse.atoms.values import Bottom, Card, Ok, Unknown, decode, outcome_equal
from opulse.atoms.world import WorldDecl
from opulse.meta import code as C
from opulse.meta import engine
from opulse.meta.builder import world_value as V
from opulse.meta.builder.instantiate import WorldError, domain, extend, instantiate
from opulse.meta.builder.wf import wf
from opulse.meta.check import _split_example
from opulse.meta.code_world import code_hash
from opulse.meta.export_util import (
    parse_meta_definition,
    parse_meta_expr,
    parse_meta_object_call,
    parse_meta_value,
)
from opulse.meta.notation import show_world
from opulse.meta.worlds.builder import export, hosts, showcase, story, world


@pytest.fixture(scope="module")
def created():
    return story.creation()


def test_declaration_and_given_primitives():
    declaration = WorldDecl.from_dict(json.loads(export.DECL.read_text()))
    assert declaration == world.declaration()
    assert declaration.combinators["recursion"] == "measure"
    assert {atom.name for atom in hosts.atoms()} == {spec.name for spec in declaration.operations}
    for spec in declaration.operations:
        if spec.impl is not None and "table" in spec.impl:
            continue
        rule = (hosts.call_in if spec.name == "call_in" else
                {"code_hash": code_hash, "eval": engine.eval_atom, "run": engine.run_atom}.get(
                    spec.name, hosts.RULES.get(spec.name, (None,))[0]))
        assert spec.impl["digest"] == hashlib.sha256(inspect.getsource(rule).encode()).hexdigest()
    assert hosts.tag_of(story.z(1)) == "z1"
    assert hosts.field(story.z(1), 0) == Bottom("invalid")
    assert hosts.with_field(story.z(1), 0, 0) == Bottom("invalid")
    assert hosts.mk("z", "z1", C.lst(())) == story.z(1)
    assert hosts.list_get(C.lst((0, 1)), 2) == Bottom("invalid")
    assert hosts.list_len(C.lst((0, 1))) == 2
    assert hosts.list_append(C.lst((0,)), 1) == C.lst((0, 1))
    assert hosts.list_concat(C.lst((0,)), C.lst((1,))) == C.lst((0, 1))
    assert hosts.int_add(2, 3) == 5 and hosts.int_sub(3, 2) == 1
    assert hosts.int_eq(2, 2) == Card("bool", "true")
    assert hosts.eq(story.z(2), story.z(2)) == Card("bool", "true")
    assert hosts.eq(story.z(2), story.z(3)) == Card("bool", "false")
    assert hosts.int_lt(2, 1) == Card("bool", "false")
    assert hosts.str_eq("a", "a") == Card("bool", "true")
    assert hosts.int_mul(3, 4) == 12 and hosts.int_div(7, 3) == 2
    assert hosts.int_mod(7, 3) == 1 and hosts.int_text(12) == "12"
    assert hosts.str_len("sort") == 4
    assert hosts.list_index(C.lst(("a", "b")), "b") == 1
    assert hosts.list_contains(C.lst(("a", "b")), "c") == Card("bool", "false")
    assert hosts.domain_values(story.z5(), "z") == C.lst(story.z(index) for index in range(5))
    assert hosts.size(Card("test", "node", (story.z(1), 4))) == 2
    assert hosts.wf(story.z5()) == Card("report", "ok")
    assert hosts.world_hash(story.z5()) == V.world_hash(story.z5())


def test_dispatch_meter_and_trace():
    args = (story.z(2), story.z(4))
    outer = kernel.DictScope(hosts.atoms())
    run = engine.call("call_in", (story.z5(), "add5", C.lst(args)), outer, trace=True)
    assert run.outcome == Ok(story.z(1)) and run.steps == 2
    assert [(node.name, node.steps) for node in run.trace.children] == [("call_in", 2)]
    assert [(node.name, node.steps) for node in run.trace.children[0].children] == [
        ("_builder_dispatch", 1)]
    assert [(node.name, node.steps) for node in run.trace.children[0].children[0].children] == [
        ("add5", 1)]
    assert engine.call("call_in", (story.z5(), "add5", C.lst(args)), outer,
                       kernel.Limits(fuel=1)).outcome == Unknown("fuel")
    assert engine.call("call_in", (story.broken_world(0), "f", C.lst((story.z(1),))),
                       outer).outcome == Bottom("world")


def test_body_dispatch_is_reentrant():
    script = """from opulse.meta.worlds.builder import hosts, showcase
from opulse.meta import engine, code as C
from opulse.atoms import kernel
from opulse.atoms.values import Bottom, Ok
value = showcase.chain_world('transform')
run = engine.call('call_in', (value, 'observe', C.lst((0,))),
                  kernel.DictScope(hosts.atoms()), kernel.Limits(fuel=2), trace=True)
assert run.outcome == Ok(1) and run.steps == 2
assert [(node.name, node.steps) for node in run.trace.children[0].children[0].children] == [('observe', 1)]
invalid = showcase.chain_world('act')
rejected = engine.call('call_in', (invalid, 'observe', C.lst((0,))), kernel.DictScope(hosts.atoms()))
assert rejected.outcome == Bottom('world') and rejected.steps == 0
"""
    result = subprocess.run([sys.executable, "-c", script], env=os.environ.copy(),
                            capture_output=True, text=True, timeout=20, check=False)
    assert result.returncode == 0, result.stderr


def test_story_evidence_is_copied_on_store_and_return(created):
    lib, _ = created
    independent, _ = story.creation()
    assert lib is not independent
    independent._definitions["hide"].evidence.scope["size"] = 99
    assert lib.get("hide").evidence.scope["size"] == 2
    original = lib.get("hide").evidence.scope["domain_hash"]
    returned = lib.get("hide")
    returned.evidence.scope["domain_hash"] = "changed"
    lib.definitions["hide"].evidence.scope["domain_hash"] = "changed"
    assert lib.get("hide").evidence.scope["domain_hash"] == original
    assert lib.get("hide").evidence.scope["size"] == 2

    fresh = story.BuilderLibrary(world.declaration(), hosts.atoms())
    fresh.write(next(item for item in story.definitions() if item.name == "count_row"))
    fresh.check("count_row")
    sample = (0, V.row([0], V.val(1)))
    fresh.make_callable("count_row", [sample])
    request = library.VerifyRequest("bounded", [sample], {"domain": "up to one row", "size": 1},
                                    reference=lambda *args: story.reference("count_row", *args))
    returned = fresh.verify("count_row", request)
    request.scope["size"] = 99
    returned.evidence.scope["size"] = 99
    assert fresh.get("count_row").evidence.scope["size"] == 1
    assert fresh.get("count_row").evidence.scope["domain_hash"] != "changed"


def test_pipeline_and_unfold_recorded_family(created):
    lib, families = created
    assert len(families) == 14
    assert {lib.get(name).kind for name in families} == {
        "object", "operation", "combinator", "law", "bridge"}
    assert {lib.get(name).layer for name in families} == {1, 2, 3, 4, 5}
    assert len(families["product"]) >= 12 and len(families["repair"]) == 20
    assert lib.get("embed_z5").evidence.scope["pairs_checked"] == 25
    assert lib.get("embed_z5").evidence.scope["domain_size"] == 5
    assert lib.get("embed_z5").spec.target == "z5xbool@1:int"
    assert lib.get("embed_z5").evidence.scope["attached"]["z5xbool@1"]["world_hash"] == (
        story.bridge_context().target_lib.world.world_hash())
    assert lib.get("embed_z5").evidence.checks == (
        "commutes", "total_on_domain", "unfold_equivalence", "reference")
    for name, inputs in families.items():
        definition = lib.get(name)
        assert definition.status == "promoted" and definition.evidence.method == "bounded"
        assert definition.evidence.scope["size"] == len(inputs)
        if definition.kind == "law":
            assert definition.evidence.checks == ("holds", "equation")
            assert len(inputs) == definition.evidence.scope["size"] == 125
            for args in inputs:
                result = kernel.evaluate(definition.spec.statement,
                                         dict(zip((variable for variable, _ in definition.spec.vars), args)),
                                         lib.scope())
                assert result.outcome == Ok(Card("bool", "true"))
            continue
        for args in inputs:
            run = lib.run(name, args, trace=True)
            assert run.outcome == Ok(story.reference(name, *args))
            unfolded = engine.evaluate(kernel.inline(n.Call(name, tuple(n.Lit(arg) for arg in args)),
                                                      lib.scope()), scope=lib.scope(), trace=True)
            assert outcome_equal(run.outcome, unfolded.outcome) and run.steps == unfolded.steps
            assert run.trace.steps == run.steps
            frame = kernel.CallNode(name, definition.kind, definition.layer,
                                    False, (), args, run.outcome, run.steps)
            assert Boundary.unfold_all().opens(frame)
            assert not Boundary.unfold_none().opens(frame)
    assert {name: lib.get(name).cost.steps["min"] for name in families
            if name not in ("add5_assoc", "mul5_distributes", "embed_z5")} == {
        "base_z5": 0, "hide": 11, "repair": 44, "product": 797,
        "count_row": 1, "for_each_tuple": 25, "table_total": 25,
        "product_table_total": 822, "audit_product": 832, "same_verdict": 14,
        "audit_hidden_product": 1645}  # same_verdict compares whole reports (review 14)


def test_product_all_inputs_and_multi_sort(created):
    lib, families = created
    assert {len(C.items(left.fields[3])) for left, _ in families["product"]} == {1, 2}
    assert {len(C.items(C.items(left.fields[3])[0].fields[2]))
            for left, _ in families["product"]} == {1, 2}
    for left, right in families["product"]:
        built = lib.run("product", (left, right)).outcome.value
        assert wf(built) == Card("report", "ok")
        _, entries = instantiate(built)
        scope = kernel.DictScope([entry for entry in entries if isinstance(entry, kernel.Atom)])
        source_scopes = []
        for value in (left, right):
            _, source_entries = instantiate(value)
            source_scopes.append(kernel.DictScope([entry for entry in source_entries
                                                   if isinstance(entry, kernel.Atom)]))
        source_sorts = [{sort.fields[0]: sort for sort in C.items(value.fields[2])}
                        for value in (left, right)]
        for index, op in enumerate(C.items(built.fields[3])):
            left_op, right_op = C.items(left.fields[3])[index], C.items(right.fields[3])[index]
            for row in C.items(op.fields[5]):
                encoded = C.items(row.fields[0])
                component_args = [[], []]
                for number, left_sort, right_sort in zip(encoded, C.items(left_op.fields[2]),
                                                        C.items(right_op.fields[2])):
                    left_domain = domain(left_sort, source_sorts[0])
                    right_domain = domain(right_sort, source_sorts[1])
                    component_args[0].append(left_domain[number // len(right_domain)])
                    component_args[1].append(right_domain[number % len(right_domain)])
                lhs = kernel.call(left_op.fields[0], component_args[0], source_scopes[0])
                rhs = kernel.call(right_op.fields[0], component_args[1], source_scopes[1])
                assert isinstance(lhs.outcome, Ok) and isinstance(rhs.outcome, Ok)
                expected = (domain(left_op.fields[3], source_sorts[0]).index(lhs.outcome.value) *
                            len(domain(right_op.fields[3], source_sorts[1])) +
                            domain(right_op.fields[3], source_sorts[1]).index(rhs.outcome.value))
                assert row.fields[1] == V.val(expected)
                run = kernel.call(op.fields[0], encoded, scope)
                assert run.outcome == Ok(expected) and run.steps == 1
    left, right = families["product"][-2]
    built = lib.run("product", (left, right)).outcome.value
    assert len(C.items(built.fields[2])) == 4
    assert [len(C.items(op.fields[5])) for op in C.items(built.fields[3])] == [36, 9]
    run = engine.call("call_in", (built, "mix", C.lst((3, 8))),
                      kernel.DictScope(hosts.atoms()), trace=True)
    assert run.outcome == Ok(5) and run.steps == 2
    left, right = families["product"][-1]
    built = lib.run("product", (left, right)).outcome.value
    assert wf(built) == Card("report", "ok")
    assert C.items(built.fields[2])[0].fields == ("p4_bool_digit", 0, 5)
    assert engine.call("call_in", (built, "flip", C.lst((0,))),
                       kernel.DictScope(hosts.atoms())).outcome == Ok(4)
    left = story.boolean_world()
    right = story.three_way_world()
    left = hosts.with_field(left, 2, C.lst((V.range_sort("a", 0, 1),
                                           V.range_sort("a_b", 0, 1))))
    right = hosts.with_field(right, 2, C.lst((V.range_sort("b_c", 0, 1),
                                              V.range_sort("c", 0, 2))))
    left = hosts.with_field(left, 3, C.lst((V.table("flip", "transform", ["a"], "a", [],
                              [V.row([0], V.val(1)), V.row([1], V.val(0))]),)))
    right = hosts.with_field(right, 3, C.lst((V.table("flip", "transform", ["b_c"], "b_c", [],
                               [V.row([0], V.val(1)), V.row([1], V.val(0))]),)))
    assert wf(left) == wf(right) == Card("report", "ok")
    collision_free = lib.run("product", (left, right)).outcome.value
    assert wf(collision_free) == Card("report", "ok")
    assert {sort.fields[0] for sort in C.items(collision_free.fields[2])} == {
        "p1_a_b_c", "p1_a_c", "p3_a_b_b_c", "p3_a_b_c"}


def test_quote_eval_static_members(created):
    lib, families = created
    digests = {op.name: C.atom_digest(op) for op in world.declaration().operations}
    scope = kernel.DictScope([*hosts.atoms(), engine.eval_atom(hosts.atoms(), digests)])
    for name in ("base_z5", "hide", "repair", "product", "count_row", "same_verdict"):
        args = families[name][0]
        quoted = C.quote_from_library(lib, name)
        actual = engine.call("eval", (quoted, C.lst(args)), scope, trace=True)
        direct = lib.run(name, args, trace=True)
        assert actual.outcome == direct.outcome and actual.steps == direct.steps
        assert actual.trace.steps == direct.trace.steps
    quoted = C.quote_from_library(lib, "table_total")
    callback = Card("expr", "fn", ("#" + C.code_hash(
        C.quote_from_library(lib, "count_row")),))
    assert engine.call("eval", (quoted, C.lst((families["table_total"][0][0], 0, callback))),
                       scope).outcome == Bottom("ill_formed")


def test_quoted_bridge_executes_with_direct_meter_and_trace(created):
    lib, _ = created
    quoted = C.quote_from_library(lib, "embed_z5")
    assert C.decode(quoted).kind == "bridge"
    assert quoted.fields[1].tag == "bridge"
    direct = lib.run("embed_z5", (story.z(0),), trace=True)
    evaluated = engine.call("eval", (quoted, C.lst((story.z(0),))),
                            kernel.DictScope(hosts.atoms()), trace=True)
    assert direct.outcome == evaluated.outcome == Ok(0)
    assert direct.steps == evaluated.steps == 3
    assert direct.trace.steps == evaluated.trace.steps == 3


def test_built_world_laws_rewrite_and_false_near_miss(created):
    lib, families = created
    assert [len(families[name]) for name in ("add5_assoc", "mul5_distributes")] == [125, 125]
    for name in ("add5_assoc", "mul5_distributes"):
        evidence = lib.get(name).evidence
        assert evidence.checks == ("holds", "equation")
        assert len(evidence.scope["values"]) == evidence.scope["size"] == 125
        sample = (story.z(1), story.z(2), story.z(3))
        quoted = C.quote_from_library(lib, name)
        evaluated = engine.call("eval", (quoted, C.lst(sample)), kernel.DictScope(hosts.atoms()))
        assert evaluated.outcome == Ok(Card("bool", "true"))
        assert evaluated.steps == {"add5_assoc": 5, "mul5_distributes": 6}[name]
    a, b, c = (n.Lit(story.z(value)) for value in (1, 2, 3))
    before = n.Call("add5", (n.Call("add5", (a, b)), c))
    after = n.Call("add5", (a, n.Call("add5", (b, c))))
    assert laws.rewrite(before, "#add5_assoc", lib) == after
    replay = laws.replay_rewrite(before, after, "#add5_assoc", lib, {})
    assert laws.derivation_length(replay) == 1 and replay.rewrite_steps == 0
    assert replay.charged_steps == 2
    near_miss, witness, rejected = story.cancellation_near_miss(lib)
    assert near_miss.status == "callable" and near_miss.evidence is None
    assert witness == (story.z(0), story.z(0), story.z(1))
    assert rejected.ok is False and rejected.steps == [5]
    assert rejected.problems == [f"law counterexample {witness!r}: {Ok(Card('bool', 'false'))!r}"]


def test_hide_repair_and_real_tuple_fold(created):
    lib, families = created
    for value in (story.z5(), story.binary_world(), story.broken_world(0)):
        probe = "identity" if value == story.z5() else "f"
        hidden = lib.run("hide", (value, C.lst((probe,)))).outcome.value
        assert C.items(hidden.fields[6]) == () and wf(value) == wf(hidden)
        assert V.world_hash(hidden) != V.world_hash(value)
        assert lib.run("same_verdict", (value, C.lst((probe,)))).outcome == Ok(Card("bool", "true"))
    first = C.items(story.binary_world().fields[3])[0]
    second = hosts.with_field(first, 0, "other")
    value = story.binary_world()
    value = hosts.with_field(value, 3, C.lst((first, second)))
    value = hosts.with_field(value, 6, C.lst(("f", "other")))
    assert wf(value) == Card("report", "ok")
    assert C.items(lib.run("hide", (value, C.lst(("other",)))).outcome.value.fields[6]) == ("f",)
    assert C.items(lib.run("hide", (value, C.lst(("other", "f")))).outcome.value.fields[6]) == ()
    for (damaged,) in families["repair"]:
        assert wf(damaged) == Card("report", "bad", ("tables", "incomplete table: mix"))
        repaired = lib.run("repair", (damaged,)).outcome.value
        assert wf(repaired) == Card("report", "ok")
        assert repaired == story.reference("repair", damaged)
        assert C.items(C.items(repaired.fields[3])[0].fields[5])[-1].fields[1] == V.err("missing")
    value = story.finite_world(3)
    assert lib.run("for_each_tuple", (kernel.FnRef("count_row"), value, 0, 7)).outcome == Ok(16)
    assert lib.run("table_total", (value, 0, kernel.FnRef("count_row"))).outcome == Ok(9)


def test_promoted_tower_and_identity():
    value, code, ledger, derived = story.promoted_mul5()
    assert len(derived.promoted) == 1
    assert ledger.status(C.code_hash(code), V.world_hash(value)) == "promoted"
    _, entries = instantiate(value)
    decoded = C.decode(code)
    scope = kernel.DictScope([entry for entry in entries if isinstance(entry, kernel.Atom)], [decoded.main])
    for left, right in product(range(5), repeat=2):
        args = (story.z(left), story.z(right))
        assert kernel.call("mul5", args, scope).outcome == kernel.call(decoded.main.name, args, scope).outcome == Ok(story.z(left * right % 5))
        assert kernel.call("mul5", args, scope).steps == 1
    assert kernel.call(decoded.main.name, (story.z(3), story.z(2)), scope).steps == 7
    operation = C.items(value.fields[3])[0]
    rows = list(C.items(operation.fields[5]))
    rows[0] = V.row([story.z(0), story.z(0)], V.val(story.z(1)))
    changed = Card("world", "world", (*value.fields[:3], C.lst((Card("op", "table", (
        *operation.fields[:5], C.lst(rows), operation.fields[6])), *C.items(value.fields[3])[1:])),
        *value.fields[4:]))
    assert wf(changed) == Card("report", "bad", ("laws", "foreign law atom: add5_assoc"))
    changed = Card("world", "world", changed.fields[:10])
    assert wf(changed) == Card("report", "ok")
    assert V.world_hash(changed) != V.world_hash(value)
    with pytest.raises(WorldError, match="promoted evidence is required"):
        extend(changed, code, ledger)

    tower, power_code, power_ledger, powered, steps = story.promoted_power5()
    assert len(powered.promoted) == 1
    assert power_ledger.status(C.code_hash(power_code), V.world_hash(tower)) == "promoted"
    assert wf(tower) == Card("report", "ok")
    assert steps[3, 2] == 25
    power_table = V.table("pow5", "combine", ["z", "z"], "z", [],
                          [V.row([story.z(left), story.z(right)],
                                 V.val(story.z(pow(left, right, 5))))
                           for left, right in product(range(5), repeat=2)])
    given = Card("world", "world", (*tower.fields[:3],
                  C.lst((*C.items(tower.fields[3]), power_table)), *tower.fields[4:]))
    assert wf(given) == Card("report", "ok")
    _, given_entries = instantiate(given)
    given_scope = kernel.DictScope([entry for entry in given_entries if isinstance(entry, kernel.Atom)],
                                   [entry for entry in given_entries if isinstance(entry, kernel.Defn)])
    _, tower_entries = instantiate(tower)
    derived_scope = kernel.DictScope([entry for entry in tower_entries if isinstance(entry, kernel.Atom)],
                                     [entry for entry in tower_entries if isinstance(entry, kernel.Defn)] +
                                     [C.decode(power_code).main])
    for left, right in product(range(5), repeat=2):
        args = (story.z(left), story.z(right))
        table = kernel.call("pow5", args, given_scope)
        repeated = kernel.call(C.decode(power_code).main.name, args, derived_scope)
        assert table.outcome == repeated.outcome == Ok(story.z(pow(left, right, 5)))
        assert table.steps == 1 and repeated.steps == steps[left, right]


def test_showcase_search_and_export_bytes():
    assert showcase.decide() == Card("report", "bad", ("probes", "probe observe depends on act shift"))
    assert showcase.invert() == [(0, 4, 3, 2, 1)]
    assert showcase.compute() == 11
    tasks = showcase.tasks()
    assert [task["angle"] for task in tasks] == ["Decide", "Invert", "Compute"]
    assert tasks[0]["answer"] == {"tag": "bad", "fields": ["probes", "probe observe depends on act shift"]}
    assert tasks[1]["answer"] == [["z0", "z4", "z3", "z2", "z1"]]
    assert tasks[2]["answer"] == 11
    assert len(showcase.LADDER) == 5 and len(showcase.tasks()) == 3
    built = export.build()
    assert built["near_miss"]["status"] == "callable"
    assert built["near_miss"]["evidence"] is None
    assert built["near_miss"]["counterexample"] == {
        "inputs": [export.value_json(value) for value in (story.z(0), story.z(0), story.z(1))],
        "outcome": {"kind": "Ok", "value": export.value_json(Card("bool", "false"))},
        "steps": 5}
    assert next(member for member in built["story"] if member["name"] == "Zn")[
        "family_scope"]["size"] == 5
    examples = [member["examples"][0] for member in built["story"]]
    assert len({json.dumps((example["inputs"], example["outcome"]), sort_keys=True)
                for example in examples}) == len(examples)
    assert next(member for member in built["story"] if member["name"] == "table_total")[
        "examples"][0]["outside_scope"] is True
    assert "outside_scope" not in next(member for member in built["story"] if member["name"] == "count_row")[
        "examples"][0]
    assert all(isinstance(member["definition"], str) and member["spec"] and member["body"]
               and member["evidence"]["scope"]["domain_hash"] for member in built["story"])
    assert len(built["story"]) == 20
    assert sum(len(member["examples"]) for member in built["story"]) == 63
    for name in ("add5_assoc", "mul5_distributes"):
        member = next(item for item in built["story"] if item["name"] == name)
        assert len(member["examples"]) == 3
        assert member["evidence"]["scope"]["values"]["count"] == 125
        assert len(member["evidence"]["scope"]["values"]["sha256"]) == 64
    assert all(member["ascii"].isascii() and all(example["ascii"].isascii()
               for example in member["examples"]) for member in built["story"])
    hide = next(member for member in built["story"] if member["name"] == "hide")
    assert show_world(story.binary_world()) in hide["examples"][1]["ascii"]
    assert "laws {\n    #add5_assoc = Code<" in hide["examples"][0]["ascii"]
    assert "@for_each_tuple[count_row]" in next(
        member for member in built["story"] if member["name"] == "for_each_tuple")["examples"][0]["ascii"]
    assert "@for_each_tuple[$arg2](arg0, arg1, 0)" in next(
        member for member in built["story"] if member["name"] == "table_total")["ascii"]
    assert json.loads(export.DATA.read_text()) == built
    assert export.DECL.read_text() == json.dumps(world.declaration().to_dict(), sort_keys=True, indent=2) + "\n"
    assert export.DATA.read_text() == json.dumps(built, sort_keys=True, separators=(",", ":")) + "\n"


def test_exported_ascii_round_trips_exactly():
    published = json.loads(export.DATA.read_text())
    checked = 0
    for member in published["story"]:
        name, kind = member["name"], member["kind"]
        definition = parse_meta_definition(member["ascii"])
        assert definition.kind == kind and definition.name == name
        assert definition.layer == member["layer"]
        if kind == "template":
            assert notation.parse_definition(member["ascii"]).spec.pattern == definition.spec.pattern
            assert definition.body == "refine world canon(make_zn)"
            assert definition.spec.pattern == member["source_pattern"]
            assert member["spec"]["pattern"]["body"] == n.to_json(
                n.Call("make_zn", (n.Lit("$n"),)))
            assert definition.spec.params == (("n", "int"),)
            assert definition.spec.produces == member["produces"]
        else:
            assert definition.body == n.from_json(member["body"])
        if kind == "operation":
            assert tuple(edge.sort for edge in definition.spec.inputs) == tuple(
                edge["sort"] for edge in member["spec"]["inputs"])
            assert definition.spec.output.sort == member["spec"]["output"]["sort"]
        if kind == "bridge":
            assert (definition.spec.source, definition.spec.target) == (
                member["spec"]["source"], member["spec"]["target"])
        for example in member["examples"]:
            source, rendered_result = _split_example(example["ascii"])
            if kind == "object":
                actual_inputs = parse_meta_object_call(source, name)
            else:
                if kind == "template":
                    source = name + "(" + source[len(name) + 1:-1] + ")"
                elif kind == "law":
                    source = source[1:]
                parsed = parse_meta_expr(source, {"kinds": {
                    name: "operation" if kind in ("template", "law") else kind}})
                assert parsed.fn == name
                values = tuple(arg.value if isinstance(arg, n.Lit) else kernel.FnRef(arg.name)
                               for arg in parsed.args)
                if kind == "combinator":
                    params = member["spec"]["params"]
                    slots = member["spec"]["op_params"]
                    refs = iter(value for value in values if isinstance(value, kernel.FnRef))
                    args = iter(value for value in values if not isinstance(value, kernel.FnRef))
                    actual_inputs = tuple(next(refs) if param in slots else next(args)
                                          for param in params)
                else:
                    actual_inputs = values
            assert actual_inputs == tuple(kernel.FnRef(item["fn"]) if "fn" in item else decode(item)
                                          for item in example["inputs"])
            outcome = example["outcome"]
            if outcome["kind"] == "Ok":
                assert parse_meta_value(rendered_result) == decode(outcome["value"])
            elif outcome["kind"] == "Bottom":
                assert notation.parse_value(rendered_result) == Bottom(outcome["reason"])
            else:
                assert rendered_result == f'Unknown<{notation.print_value(outcome["resource"])}>'
            checked += 1
    assert checked == 63
