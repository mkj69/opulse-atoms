"""Checked families and independently verified template instances."""

import json
import os
import random
import subprocess
import sys
import time
from dataclasses import replace

import pytest

from opulse.atoms import nodes as n
from opulse.atoms.spec import Definition, Edge, ObjectSpec, OperationSpec, TemplateSpec
from opulse.atoms.values import Card
from opulse.gen_v2.admit import admit
from opulse.gen_v2.base import Candidate, Entry, GenState, Rejection, Signature
from opulse.gen_v2.library import GenLibrary
from opulse.gen_v2.moves.object import _candidate as object_candidate
from opulse.gen_v2.moves.observation import _candidate as observation_candidate
from opulse.gen_v2.moves.registry import discover_moves
from opulse.gen_v2.moves.templates import MOVES, TemplateMove, _families
from opulse.gen_v2.run import generate, load, save
from opulse.gen_v2.templates import (
    TemplateRecord,
    _build,
    instance_notation,
    instantiate_template,
    invent_template,
    template_candidate,
    template_export_payload,
    template_notation,
    template_summary_md,
    templates_for,
    templates_from_json,
    templates_to_json,
)
from opulse.gen_v2.worlds import geometry, integer, pixels, toy_truth
from opulse.gen_v2.worlds.toy import gen_world


def state():
    world = gen_world()
    return GenState(world, GenLibrary(world.decl, world.atoms), dict(world.sorts))


def operation(current, sort, body):
    name = current.names.fresh("operation")
    spec = OperationSpec(name, "transform", (Edge(sort),), Edge(sort), "Normalize the input.",
                         extra={"input_names": ["x"]})
    dependencies = tuple(sorted(n.references(body)))
    layer = 1 + max((current.layer(ref) for ref in dependencies), default=0)
    definition = Definition(name, "operation", "invented", layer, dependencies, spec, body)
    entry = admit(current, Candidate(definition, Signature((sort,), sort), "op.test"))
    assert isinstance(entry, Entry), entry
    return entry.name


def prepare():
    current = state()
    clamp_zero = operation(current, "int", n.Call("maxv", (n.Var("x"), n.Lit(0))))
    clamp_two = operation(current, "int", n.Call("maxv", (n.Var("x"), n.Lit(2))))
    return current, [("int", "absv"), ("int", clamp_zero), ("int", clamp_two)]


def test_template_exports_core_record_without_claiming_pipeline_status():
    current, family = prepare()
    record = invent_template(current, "Quot", family)
    assert record is not None
    spec = record.core_spec()
    assert isinstance(spec, TemplateSpec)
    assert TemplateSpec.from_dict(spec.to_dict()) == spec
    assert template_export_payload(current)["templates"][0]["spec"] == spec.to_dict()


@pytest.mark.parametrize("mutation", ["arguments", "spec", "body", "record", "family"])
def test_checkpoint_refuses_falsified_template_provenance(tmp_path, mutation):
    current, family = prepare()
    template = invent_template(current, "Quot", family)
    path = tmp_path / "template.json"
    save(current, path)
    data = json.loads(path.read_text())
    entry = next(item for item in data["entries"] if item["name"] == template.instances[0])
    definition = next(item for item in data["library"]["definitions"]
                      if item["name"] == template.instances[0])
    if mutation == "arguments":
        entry["meta"]["template"]["arguments"] = ["str", "fake_canon"]
        entry["meta"]["arguments"] = ["str", "fake_canon"]
    elif mutation == "spec":
        definition["spec"]["template"]["digest"] = "0" * 64
    elif mutation == "body":
        definition["body"] = n.to_json(n.Lit(17))
    elif mutation == "record":
        entry["meta"]["template_record"]["pattern"] = "Interval"
    else:
        data["templates"][0]["family"][0] = ["str", "fake_canon"]
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="template|invalid stored definition"):
        load(current.world, path)


def test_template_identity_and_dependency_hash_cover_family(tmp_path):
    current, family = prepare()
    template = invent_template(current, "Quot", family)
    instance = template.instances[0]
    definition = current.library.get(instance)
    assert definition.spec.extra["template"]["digest"] == template.digest
    original = current.library.content_hash(instance), current.library._deps_hash(instance)
    assert original[0] == definition.evidence.content_hash
    assert original[1] == definition.evidence.deps_hash
    save(current, tmp_path / "family.json")
    restored = load(current.world, tmp_path / "family.json")
    assert restored.library.content_hash(instance) == original[0]
    assert restored.library._deps_hash(instance) == original[1]


def test_audit_refuses_template_metadata_mutation():
    from opulse.gen_v2.audit import audit

    current, family = prepare()
    template = invent_template(current, "Quot", family)
    entry = current.entries[template.instances[0]]
    entry.meta["template"]["arguments"] = ["str", "fake_canon"]
    assert any(failure.name == entry.name and failure.invariant == "I4"
               for failure in audit(current).failures)


def test_quot_family_and_record_instance():
    start = time.monotonic()
    current, family = prepare()
    template = invent_template(current, "Quot", family)
    assert template is not None and len(template.instances) == 3
    assert len(templates_for(current)) == 1
    assert all(current.library.get(name).evidence is not None for name in template.instances)
    assert all(current.entries[name].meta["template"]["name"] == template.name
               for name in template.instances)
    for index, name in enumerate(template.instances):
        entry = current.entries[name]
        assert entry.meta["template"]["digest"] == template.digest
        assert tuple(entry.meta["template"]["arguments"]) == template.family[index]
        assert entry.meta["template_family_covered"] is True
        assert entry.meta["template_family_index"] == index
    invented = current.entries[template.instances[1]]
    assert family[1][1] in invented.depends_on
    assert invented.layer == current.entries[family[1][1]].layer + 1
    assert invented.meta["template"]["dependency_hashes"][family[1][1]] == current.library.content_hash(family[1][1])

    record_name = current.names.fresh("object")
    spec = ObjectSpec(record_name, "compose", tags={"pair": [["left", "int"], ["right", "int"]]})
    values = tuple(Card(record_name, "pair", (left, right))
                   for left in (-2, 0, 2) for right in (-1, 0, 3))
    record = object_candidate(current, spec, "obj.test",
                              n.Call(f"{record_name}.pair", (n.Lit(0), n.Lit(0))), values)
    assert isinstance(admit(current, record), Entry)
    normalize = operation(current, record_name, n.Call(f"{record_name}.pair", (
        n.Call("absv", (n.Call(f"{record_name}.left", (n.Var("x"),)),)),
        n.Call("absv", (n.Call(f"{record_name}.right", (n.Var("x"),)),)))))
    instance = instantiate_template(current, template.name, (record_name, normalize))
    assert isinstance(instance, Entry), instance
    assert instance.meta["arguments"] == (record_name, normalize)
    assert instance.meta["display"] == f"Quot[{record_name}, {normalize}]"
    assert instance.meta["template_digest"] == template.digest
    assert instance.meta["template_family_covered"] is False
    assert instance.meta["template_family_index"] is None
    assert instance.meta["template"]["dependency_hashes"][normalize]
    assert normalize in instance.depends_on
    assert record_name in instance.depends_on
    assert instance.layer == current.entries[normalize].layer + 1
    assert instance_notation(instance).startswith(f"obj {instance.name} = {template.name}[")
    assert template_notation(template).startswith(f"obj {template.name}[")
    assert current.library.get(instance.name).evidence is not None
    assert instance.name in template.instances
    assert time.monotonic() - start < 20


def test_failed_family_is_refused_without_partial_admission():
    current, family = prepare()
    previous = tuple(current.entries)
    bad = family[:2] + [("int", "inc")]
    assert invent_template(current, "Quot", bad) is None
    assert tuple(current.entries) == previous
    assert not templates_for(current)
    assert current.rejections[-1].move == "tmpl.invent"
    assert "canon_idempotent" in current.rejections[-1].reason
    assert isinstance(invent_template(current, "Quot", family), TemplateRecord)
    refusal = instantiate_template(current, next(iter(templates_for(current))), ("int", "inc"))
    assert isinstance(refusal, Rejection)


def test_deterministic_family_and_move_discovery():
    def run():
        current, family = prepare()
        template = invent_template(current, "Quot", family)
        return template.name, template.instances, tuple(
            (entry.name, entry.layer, entry.meta["arguments"]) for entry in current.entries.values()
            if entry.move == "tmpl.instantiate")

    assert run() == run()
    moves = discover_moves()
    assert all(any(move.name == "tmpl.invent" for move in moves[kind])
               for kind in ("object", "operation", "combinator", "observation"))
    current, _ = prepare()
    assert next(move for move in moves["object"] if move.name == "tmpl.instantiate")(
        current, random.Random(2)) is None


def test_quot_move_discovers_canonicalizers_by_behaviour():
    current, _ = prepare()
    assert TemplateMove("tmpl.invent", "object")(current, random.Random(1)) is None
    template = next(iter(templates_for(current).values()))
    assert template.pattern == "Quot" and len(template.instances) == 3
    assert TemplateMove("tmpl.instantiate", "object")(current, random.Random(1)) is None


def test_other_kinds_and_interval_use_independent_evidence():
    current = state()
    interval = invent_template(current, "Interval", (("int", "lt", -2, 3),
                                                  ("int", "lt", -1, 4), ("int", "lt", 0, 5)))
    assert interval is not None
    outside = instantiate_template(current, interval.name, ("int", "lt", 1, 6))
    assert isinstance(outside, Entry)
    assert outside.meta["template_family_covered"] is False
    iteration = invent_template(current, "Iterate", (("int", 2), ("int", 3), ("int", 4)))
    assert iteration is not None
    assert all(current.library.get(name).evidence.method == "bounded" for name in iteration.instances)

    record_name = current.names.fresh("object")
    spec = ObjectSpec(record_name, "compose", tags={"pair": [["left", "int"], ["right", "int"]]})
    values = tuple(Card(record_name, "pair", (left, right))
                   for left in (-2, 0, 2) for right in (-1, 0, 3))
    record = object_candidate(current, spec, "obj.test",
                              n.Call(f"{record_name}.pair", (n.Lit(0), n.Lit(0))), values)
    assert isinstance(admit(current, record), Entry)
    lift = invent_template(current, "Lift", ((record_name, "inc"), (record_name, "neg"),
                                              (record_name, "absv")))
    assert lift is not None
    assert all(current.library.get(name).evidence.method == "bounded" for name in lift.instances)
    assert all(operator in current.entries[name].depends_on
               for name, (_, operator) in zip(lift.instances, lift.family))

    world = toy_truth.gen_world()
    observed = GenState(world, GenLibrary(world.decl, world.atoms), dict(world.sorts))
    count = invent_template(observed, "Count", (("read_x",), ("read_y",), ("read_z",)))
    assert count is not None
    assert all(observed.library.get(name).evidence.method == "bounded" for name in count.instances)


def test_count_instance_tracks_invented_probe_and_derivation(tmp_path):
    world = toy_truth.gen_world()
    current = GenState(world, GenLibrary(world.decl, world.atoms), dict(world.sorts))
    probe = admit(current, observation_candidate(
        current, "obs.test", n.Call("sub", (n.Var("read_x"), n.Lit(1))), ("read_x",), "int"))
    assert isinstance(probe, Entry)
    template = invent_template(current, "Count", ((probe.name,), ("read_y",), ("read_z",)))
    assert template is not None
    instance = current.entries[template.instances[0]]
    indices = current.requests[instance.name].scope["history_state_indices"]
    assert any(world.truth_states[index].fields[2] == 1 and
               world.truth_states[index].fields[1] == 0 for index in indices)
    assert probe.name in instance.depends_on
    assert instance.layer == probe.layer + 1
    assert instance.meta["template"]["dependency_hashes"][probe.name]
    path = tmp_path / "count.json"
    save(current, path)
    restored = load(world, path)
    record = templates_for(restored)[template.name]
    saved = restored.entries[record.instances[0]]
    assert saved.depends_on == instance.depends_on
    assert saved.meta["template_family_covered"] is True
    assert saved.meta["template_family_index"] == 0
    assert saved.meta["template"]["dependency_hashes"][probe.name] == instance.meta["template"]["dependency_hashes"][probe.name]


def test_card_worlds_instantiate_quot_and_interval():
    for module, sort, pattern in ((pixels, "grid", "Quot"),
                                  (pixels, "point", "Interval")):
        world = module.gen_world()
        current = GenState(world, GenLibrary(world.decl, world.atoms, world.dialect,
                                             world.extra_scope), dict(world.sorts))
        families = list(_families(current))
        family = next(family for name, family in families
                      if name == pattern and family[0][0] == sort)
        template = invent_template(current, pattern, family)
        assert template is not None
        assert len(template.instances) == 3
        assert all(current.library.get(name).evidence is not None for name in template.instances)


def test_card_interval_family_survives_checkpoint(tmp_path):
    world = pixels.gen_world()
    current = GenState(world, GenLibrary(world.decl, world.atoms, world.dialect,
                                         world.extra_scope), dict(world.sorts))
    family = next(family for pattern, family in _families(current)
                  if pattern == "Interval" and family[0][0] == "point")
    record = invent_template(current, "Interval", family)
    assert record is not None
    path = tmp_path / "card_interval.json"
    save(current, path)
    restored = load(world, path)
    saved = templates_for(restored)[record.name]
    assert saved.family == record.family
    assert saved.digest == record.digest
    instance = template_candidate(restored, saved, saved.family[0])
    assert instance is not None
    assert instance.meta["template"]["digest"] == record.digest


def test_circuits_template_provenance_survives_name_renaming(tmp_path):
    from opulse.gen_v2.audit import audit
    from opulse.gen_v2.worlds import circuits

    world = circuits.gen_world()
    current = GenState(world, GenLibrary(world.decl, world.atoms, world.dialect,
                                         world.extra_scope), dict(world.sorts))
    family = next(family for pattern, family in _families(current) if pattern == "Quot")
    template = invent_template(current, "Quot", family)
    assert template is not None
    assert any(any(dependency.startswith(name + ".") for dependency in
                   current.library.get(name).depends_on) for name in template.instances)
    assert audit(current).ok
    path = tmp_path / "circuits.json"
    save(current, path)
    restored = load(world, path)
    assert audit(restored).ok

    data = json.loads(path.read_text())
    entry = next(item for item in data["entries"] if item["name"] == template.instances[0])
    entry["meta"]["template"]["arguments"] = ["str", "fake_canon"]
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="template"):
        load(world, path)


@pytest.mark.skipif(not os.environ.get("OPULSE_GEN_SLOW"), reason="slow acceptance run")
def test_circuits_cli_and_checkpoint_150(tmp_path):
    from opulse.gen_v2.audit import audit
    from opulse.gen_v2.worlds import circuits

    output = tmp_path / "export"
    result = subprocess.run([sys.executable, "-m", "opulse.gen_v2", "run", "--world", "circuits",
                             "--target", "150", "--seed", "1", "--out", str(output)],
                            capture_output=True, text=True, timeout=1800, check=False)
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert (output / "circuits.json").is_file()

    world = circuits.gen_world()
    current = generate(world, 150, 1)
    assert audit(current).ok
    path = tmp_path / "circuits-checkpoint.json"
    save(current, path)
    restored = load(world, path)
    assert audit(restored).ok


def test_count_on_deep_world_probe_families():
    for module, probe in ((pixels, "area"), (geometry, "points")):
        world = module.gen_world()
        current = GenState(world, GenLibrary(world.decl, world.atoms, world.dialect,
                                             world.extra_scope), dict(world.sorts))
        candidate = _build(current, "Count", (probe,))
        assert candidate is not None
        instance = admit(current, candidate)
        assert isinstance(instance, Entry), instance
        assert current.library.get(instance.name).evidence.method == "bounded"


def test_count_move_invents_deep_integer_probe_family():
    world = integer.gen_world()
    current = GenState(world, GenLibrary(world.decl, world.atoms, world.dialect,
                                         world.extra_scope), dict(world.sorts))
    TemplateMove("tmpl.invent", "observation")(current, random.Random(1))
    record = next(iter(templates_for(current).values()))
    assert record.pattern == "Count"
    assert record.family[0] == (world.probes[0],)
    assert len(record.instances) == 3
    assert sum(entry.move == "tmpl.probe" for entry in current.entries.values()) == 2


def test_lift_move_uses_invented_card_record():
    world = pixels.gen_world()
    current = GenState(world, GenLibrary(world.decl, world.atoms, world.dialect,
                                         world.extra_scope), dict(world.sorts))
    for name, offset in (("add", 1), ("sub", 1), ("max_int", 8)):
        operation(current, "int", n.Call(name, (n.Var("x"), n.Lit(offset))))
    TemplateMove("tmpl.invent", "object")(current, random.Random(1))
    TemplateMove("tmpl.invent", "operation")(current, random.Random(1))
    record = next(record for record in templates_for(current).values() if record.pattern == "Lift")
    assert len(record.instances) == 3
    assert current.entries[record.family[0][0]].move == "tmpl.record"
    assert all(current.entries[name].signature.inputs == (record.family[0][0],)
               for name in record.instances)


def test_quot_content_identity_changes_with_canonicalizer():
    current, family = prepare()
    template = invent_template(current, "Quot", family)
    assert template is not None
    original = current.entries[template.instances[1]]
    old_hash = original.meta["template"]["dependency_hashes"][family[1][1]]
    canon = current.library.get(family[1][1])
    current.library._definitions[canon.name] = replace(canon, body=n.Call("maxv", (n.Var("x"), n.Lit(4))))
    candidate = template_candidate(current, template, family[1])
    assert candidate.meta["template"]["dependency_hashes"][canon.name] != old_hash


def test_moves_and_checkpoint_restore_template_family(tmp_path):
    world = gen_world(open_kinds=("combinator",))
    current = generate(world, 3, 1, per_kind_min=0, layer_target=0, moves=MOVES)
    assert len(current.entries) == 3
    path = tmp_path / "template.json"
    save(current, path)
    restored = load(world, path)
    record = next(iter(templates_for(restored).values()))
    assert record.family == (("int", 2), ("int", 3), ("int", 4))
    assert record.instances == list(restored.entries)
    for index, name in enumerate(record.instances):
        assert restored.entries[name].meta["template_family_covered"] is True
        assert restored.entries[name].meta["template_family_index"] == index
        assert restored.entries[name].meta["template"]["digest"] == record.digest
    outside = instantiate_template(restored, record.name, ("int", 5))
    assert isinstance(outside, Entry)
    assert outside.meta["template_family_covered"] is False


def test_template_catalogue_checkpoint_export_and_instance_links(tmp_path):
    current, family = prepare()
    record = invent_template(current, "Quot", family)
    assert record is not None
    catalogue = templates_to_json(current)
    assert catalogue[0]["id"] == record.name
    assert catalogue[0]["digest"] == record.digest
    assert catalogue[0]["instances"] == record.instances
    assert all(current.entries[name].meta["template_id"] == catalogue[0]["id"]
               for name in record.instances)

    path = tmp_path / "with_templates.json"
    save(current, path)
    checkpoint = json.loads(path.read_text(encoding="utf-8"))
    checkpoint["templates"] = catalogue
    path.write_text(json.dumps(checkpoint, ensure_ascii=True), encoding="utf-8")
    restored = load(current.world, path)
    saved = templates_from_json(restored, checkpoint["templates"])[record.name]
    assert saved.digest == record.digest
    assert saved.instances == record.instances
    assert templates_to_json(restored) == catalogue
    assert isinstance(instantiate_template(restored, record.name, ("int", "maxv")), Rejection)

    payload = template_export_payload(restored)
    assert payload["template_counts"]["total"] == 1
    assert payload["template_counts"]["per_kind"]["object"] == 1
    assert payload["templates"][0]["id"] == record.name
    assert payload["templates"][0]["ascii"].startswith(f"obj {record.name}[T: sort, canon: T -> T]")
    assert payload["templates"][0]["instances"] == record.instances
    assert payload["template_instance_links"][record.instances[0]] == {
        "id": record.name, "digest": record.digest}
    assert "- object: 1" in template_summary_md(restored)
    assert payload["templates"][0]["ascii"] in template_summary_md(restored)
    assert json.loads(json.dumps(payload, ensure_ascii=True)) == payload


def test_template_without_instances_survives_catalogue_roundtrip(tmp_path):
    original = state()
    record = TemplateRecord("Q1", "Quot", "object", ("T:sort", "canon:T->T"), (),
                            lambda current, arguments: None,
                            (("int", "absv"), ("int", "inc"), ("int", "neg")),
                            {"method": "bounded", "scope": {"size": 3}})
    templates_for(original)[record.name] = record
    serialized = json.loads(json.dumps(templates_to_json(original)))
    path = tmp_path / "template_only.json"
    save(original, path)
    checkpoint = json.loads(path.read_text(encoding="utf-8"))
    checkpoint["templates"] = serialized
    path.write_text(json.dumps(checkpoint, ensure_ascii=True), encoding="utf-8")
    restored = load(original.world, path)
    assert templates_from_json(restored, checkpoint["templates"])[record.name].instances == []
    assert templates_to_json(restored) == serialized
    assert record.name in restored.names.taken


def test_template_catalogue_rejects_mismatched_digest_without_replacing_records():
    current, family = prepare()
    record = invent_template(current, "Quot", family)
    original = templates_to_json(current)
    altered = json.loads(json.dumps(original))
    altered[0]["digest"] = "not-the-verified-digest"
    with pytest.raises(ValueError, match="digest"):
        templates_from_json(current, altered)
    assert templates_to_json(current) == original
    assert templates_for(current)[record.name].instances == record.instances


def test_template_moves_run_on_melody_with_given_object_operations():
    """Given object operations carry an OperationSpec under kind object (melody crashed here)."""
    from opulse.gen_v2.run import generate
    from opulse.gen_v2.worlds import melody

    state = generate(melody.gen_world(), 30, 1, per_kind_min=0, layer_target=0, time_limit=120)
    assert state.entries
