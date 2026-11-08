"""Twelve-path depth tower and its independent finite reference."""

import json
import re
from dataclasses import replace
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from opulse.atoms import kernel, nodes, notation
from opulse.atoms.boundary import Boundary, flatten_calls
from opulse.atoms.library import PipelineError, checked_scope, sampled
from opulse.atoms.observations import judge
from opulse.atoms.spec import Contract, compute_layer
from opulse.atoms.values import Bottom, Card, Ok, Unknown
from opulse.atoms.verify import unfold_equivalent
from opulse.atoms.world import WorldDecl
from opulse.tasks_v2.decl import load, validate
from opulse.worlds_v2 import export_util
from opulse.worlds_v2.versions import hosts
from opulse.worlds_v2.versions.export import (
    OUTPUT,
    build_export,
    encode_input,
    expression,
    render,
)
from opulse.worlds_v2.versions.story import (
    build_library,
    definitions,
    entrypoint,
    from_reference,
    reference,
    reference_result,
    samples,
    to_reference,
    verification_cases,
)
from opulse.worlds_v2.versions.world import FILE, decl, new_library

DESIGN = Path(__file__).resolve().parents[3] / "worlds/catalogue/depth/versions.json"


def decode_input(value):
    if value["t"] == "fn":
        return kernel.FnRef(value["v"])
    if value["t"] == "List" and value.get("tag") == "items":
        return tuple(decode_input(item) for item in value["f"])
    if "tag" in value:
        return Card(value["t"], value["tag"], tuple(decode_input(item) for item in value["f"]))
    return value["v"]


@pytest.fixture(scope="module")
def library():
    return build_library()


@pytest.fixture(scope="module")
def catalogue():
    return json.loads(OUTPUT.read_text(encoding="utf-8"))


def test_declaration_locks_and_full_twelve_path_history():
    document = json.loads(FILE.read_text(encoding="utf-8"))
    assert validate(load(FILE)) == []
    assert WorldDecl.from_dict(document).to_dict() == decl().to_dict()
    assert decl().to_dict() == document
    assert decl().world_hash()
    assert len(hosts.PATHS) == 12
    initial = hosts.history()
    first = hosts.fork(initial, 0, "/a", "x")
    second = hosts.fork(first, 0, "/b", "y")
    third = hosts.fork(second, 1, "/c", "z")
    assert hosts.read_version(third, 2).fields[2] == hosts.edit(hosts.base12(), "/b", "y")
    assert hosts.read_version(third, 3).fields[2] == hosts.edit(hosts.edit(hosts.base12(), "/a", "x"), "/c", "z")
    assert initial == hosts.history()
    assert hosts.fork(third, 99, "/a", "x") == Bottom("domain")
    assert hosts.edit(hosts.base12(), "/l", hosts.GONE).fields[-1] == hosts.GONE
    assert hosts.valid_doc(hosts.base12()) and hosts.valid_history(initial)
    illegitimate = Card("History", "history", (*initial.fields,
                        Card("Version", "version", (1, 0,
                            hosts.edit(hosts.edit(hosts.base12(), "/a", "x"), "/b", "y")))))
    assert not hosts.valid_history(illegitimate)
    assert hosts.valid_choices(from_reference(reference().Choices((("/a", "right"),))))
    assert not hosts.valid_choices(Card("Choices", "choices", ((("/b", "left"), ("/a", "right")),)))
    assert hosts.base12() == new_library().run("base12", ()).outcome.value
    assert hosts.history() == new_library().run("history", ()).outcome.value


def test_given_fix_unfolds_through_the_kernel(library):
    action = samples()["apply"][0]
    direct = library.run("apply", action)
    bound = library.run("fix", (kernel.FnRef("apply"), *action), trace=True)
    assert bound.outcome == direct.outcome and bound.steps == direct.steps
    assert library.get("fix").origin == "given" and library.get("fix").layer == 0
    assert unfold_equivalent(bound.trace, [Boundary.unfold_all()]).ok


@pytest.mark.parametrize("operation,cases", (
    ("Patch.patch", (("/unknown", "0", "x"), ("/a", "no spaces", "x"), ("/a", "0", 7))),
    ("Merge.merge", ((hosts.base12(), (("not a clash",),)),
                     (hosts.base12(), (Card("Clash", "clash", ("/a", "0", "x", "x")),)),
                     (hosts.base12(), (Card("Clash", "clash", ("/a", "0", "x", "y")),) * 2))),
    ("Replay.replay", ((hosts.base12(), 0, 37, ()), (hosts.base12(), -1, 0, ()),
                       (hosts.base12(), 0, 1, ()))),
))
def test_invented_constructors_reject_invalid_inputs(library, operation, cases):
    for args in cases:
        assert isinstance(library.run(operation, args).outcome, Bottom)


def test_generic_card_cannot_forge_invented_objects(library):
    base = hosts.base12()
    for sort, name, arguments in (("Patch", "patch", ("/a", "0", "x")),
                                   ("Merge", "merge", (base, ())),
                                   ("Replay", "replay", (base, 0, 0, ()))):
        assert library.run("card", (sort, name, arguments)).outcome == Bottom("domain")


@given(path=st.sampled_from(hosts.PATHS), value=st.sampled_from(("x", "y", hosts.GONE)))
def test_patch_constructor_boundary_equivalence(library, path, value):
    run = library.run("Patch.patch", (path, "0", value), trace=True)
    assert run.outcome == Ok(Card("Patch", "patch", (path, "0", value)))
    assert unfold_equivalent(run.trace, [Boundary(), Boundary.unfold_all()]).ok


@pytest.mark.parametrize("name", ("three_way", "rebase"))
def test_combinator_slots_have_bounded_two_operation_families(library, name):
    definition = library.get(name)
    assert len(definition.spec.op_params) == 2
    assert definition.evidence.scope["op_family"] == ["read", "identity_doc"]
    assert definition.evidence.scope["size"] == 61
    arguments = samples()[name][0]
    alternative = (kernel.FnRef("identity_doc"), kernel.FnRef("read"), *arguments[2:])
    assert library.run(name, arguments).outcome == library.run(name, alternative).outcome


@pytest.mark.parametrize("name", ("merge_idem", "merge_symmetric"))
def test_promoted_law_witnesses_hold(library, name):
    from opulse.worlds_v2.versions.story import law_cases

    definition = library.get(name)
    assert definition.kind == "law" and definition.status == "promoted"
    assert {k: v for k, v in definition.evidence.scope["checked"].items() if k != "by"} == checked_scope(law_cases(name))
    for arguments in law_cases(name):
        assert library.run(name, arguments).outcome == Ok(True)


def test_every_tower_example_and_independent_reference(library, catalogue):
    design = json.loads(DESIGN.read_text(encoding="utf-8"))
    assert [card["kind"] for card in catalogue["story"][:12]] == [card["kind"] for card in design["tower"]]
    assert {card["symbol"] for card in catalogue["story"][12:]} == {
        "#merge_idem", "#merge_symmetric"}
    assert len(reference().examples()) == 12
    for card, source, oracle_value in zip(catalogue["story"], design["tower"], reference().examples()):
        assert card["layer"] == source["layer"] and card["kind"] == source["kind"]
        assert card["status"] == "promoted" and card["def_layer"] == library.get(card["name"]).layer
        assert card["examples"][0]["text"] == expression(card["name"], card["kind"], samples()[card["name"]][0])
        assert card["title"] and card["definition"]
        assert reference().display(oracle_value) == source["value"]
        assert card["examples"][0]["inputs"] != card["examples"][1]["inputs"]
        for index, example in enumerate(card["examples"]):
            args = tuple(decode_input(item) for item in example["inputs"])
            assert example["text"] == expression(card["name"], card["kind"], args)
            actual = library.run(entrypoint(card["name"]), args, trace=True)
            if isinstance(actual.outcome, Ok):
                assert encode_input(actual.outcome.value) == example["outcome"]["ok"]
            else:
                assert example["outcome"] == {"bottom": actual.outcome.reason}
            assert actual.steps == example["steps"]
            if isinstance(actual.outcome, Ok):
                if index == 0:
                    assert render(actual.outcome.value) == source["value"]
                assert actual.outcome.value == reference_result(card["name"], args)


def test_promotion_scopes_and_fresh_inputs(library):
    for definition in definitions():
        stored = library.get(definition.name)
        domain = verification_cases(definition.name, samples()[definition.name])
        if definition.kind == "combinator":
            domain = tuple(args[2:] for args in domain)
        assert {k: v for k, v in stored.evidence.scope["checked"].items() if k != "by"} == checked_scope(domain)
        assert stored.status == "promoted" and stored.contract and stored.evidence
        assert set(stored.depends_on) == (nodes.all_dependencies(stored.body) - set(getattr(stored.spec, "op_params", ()))
                                           if stored.body is not None else set())
        assert stored.layer == compute_layer(stored.depends_on,
                                             lambda name: 0 if name in ("Patch.patch", "Merge.merge", "Replay.replay")
                                             else library.get(name).layer)
        expected = 192 if definition.name == "patch" else 61
        assert stored.evidence.scope["size"] == expected
        assert stored.evidence.method == ("exhaustive" if definition.name == "patch" else "bounded")
        assert stored.evidence.world_hash == library.world.world_hash()
        for args in verification_cases(definition.name, samples()[definition.name]):
            run = library.run(entrypoint(definition.name), args)
            expected_value = reference_result(definition.name, args)
            assert run.outcome == (expected_value if isinstance(expected_value, Bottom) else Ok(expected_value))


def test_generated_constructors_accept_scalar_and_card_fields(library):
    assert "Any" in {obj.name for obj in library.world.objects}
    for name in ("patch", "merge", "replay"):
        definition = library.get(name)
        assert all(sort == "Value" for _, sort in definition.spec.tags[name])
        args = samples()[name][0]
        assert library.run(entrypoint(name), args).outcome == Ok(reference_result(name, args))


def test_guard_atomicity_conflict_values_and_resolution(library):
    base = hosts.base12()
    ref = reference()
    transaction = from_reference(ref.patches(ref.Patch("/a", "0", "x"), ref.Patch("/b", "wrong", "y")))
    assert library.run("apply", (base, transaction)).outcome == Bottom("guard")
    assert base == hosts.base12()
    repeated = Card("Patches", "patches", ((from_reference(ref.Patch("/a", "0", "x")),) * 2,))
    assert library.run("apply", (base, repeated)).outcome == Bottom("domain")
    assert library.run("commute", (base, repeated, repeated)).outcome == Ok(False)
    deletion = from_reference(ref.patches(ref.Patch("/l", "0", None)))
    deleted = library.run("apply", (base, deletion)).outcome.value
    inverse = library.run("invert", (deletion,)).outcome.value
    assert library.run("apply", (deleted, inverse)).outcome == Ok(base)
    invalid_clash = from_reference(ref.Clash("/a", "0", "x", "y"))
    assert library.run("Merge.merge", (base, (invalid_clash,))).outcome == Ok(Card("Merge", "merge", (base, (invalid_clash,))))
    assert library.run("Replay.replay", (base, 0, 0, ())).outcome == Ok(Card("Replay", "replay", (base, 0, 0, ())))
    for left, right in (("x", "y"), ("x", "x"), (hosts.GONE, "y"), ("0", "y")):
        left_doc, right_doc = hosts.edit(base, "/a", left), hosts.edit(base, "/a", right)
        merge = library.run("three_way", (kernel.FnRef("read"), kernel.FnRef("identity_doc"),
                                           base, left_doc, right_doc)).outcome.value
        assert merge == from_reference(ref.three_way(lambda _, doc=left_doc: to_reference(doc, ref),
                                                       lambda _, doc=right_doc: to_reference(doc, ref), ref.BASE))
        if left != right and left != "0" and right != "0":
            choices = from_reference(ref.Choices((("/a", "right"),)))
            assert library.run("resolve", (merge, choices)).outcome == Ok(right_doc)
        else:
            assert not merge.fields[1]


def test_twenty_four_commit_replay_with_deletion_and_reconstruction(library):
    ref = reference()
    base = hosts.base12()
    old = {path: "0" for path in hosts.PATHS}
    commits = []
    for index in range(24):
        path = hosts.PATHS[index % len(hosts.PATHS)]
        new = None if index == 7 else f"x{index}"
        commits.append(ref.patches(ref.Patch(path, old[path], new)))
        old[path] = new
    arguments = (kernel.FnRef("read"), kernel.FnRef("identity_doc"),
                 base, base, tuple(from_reference(item) for item in commits))
    result = library.run("rebase", arguments)
    expected = ref.rebase(lambda _: ref.BASE, tuple(ref.fix(ref.apply, item) for item in commits), ref.BASE)
    assert result.outcome == Ok(from_reference(expected))
    assert result.outcome.value.fields[1:3] == (24, 0)
    assert result.steps > 9_000


def test_law_rows_have_story_metadata(catalogue):
    rows = catalogue["story"][12:]
    assert [row["name"] for row in rows] == ["merge_idem", "merge_symmetric"]
    for layer, row in enumerate(rows, start=13):
        assert row["layer"] == layer
        assert isinstance(row["def_layer"], int)
        assert all(isinstance(row[key], str) and row[key].strip() for key in
                   ("title", "definition", "title_zh", "definition_zh", "symbol", "design_decl"))
        assert row["symbol"] == "#" + row["name"]
        if "decl" in row:
            assert row["decl"].startswith("law " + row["symbol"] + ": eq(")
            assert row["decl"].isascii()
        assert row["symbol"].isascii()


def test_story_declarations_and_expressions_use_core_notation(library, catalogue):
    kinds = {row["name"]: row["kind"] for row in catalogue["story"]}
    context = {"kinds": kinds,
               "op_arity": {row["name"]: 2 for row in catalogue["story"]
                            if row["kind"] == "combinator"}}
    for row in catalogue["story"]:
        digest = export_util.body_sha256(library.get(row["name"]).body)
        assert row["body_sha256"] == digest
        assert ("ascii" in row) == ("decl" in row)
        if "ascii" in row:
            source = row["decl"]
            parsed = notation.parse_definition(source)
            assert parsed.layer == row["def_layer"]
            assert source.endswith(f" L{row['def_layer']}")
            assert parsed.kind == row["kind"]
            assert row["ascii"] == source
            assert export_util.source_matches(row["ascii"], digest)
        assert row["design_text"] == row["design_decl"]
        for witness in row["examples"]:
            if row["kind"] == "object":
                assert "ascii" not in witness
                continue
            parsed_expr = notation.parse_expr(witness["text"], context if row["kind"] == "combinator" else None)
            assert isinstance(parsed_expr, nodes.Call)
            assert parsed_expr.fn == row["name"]
            assert parsed_expr.args == tuple(nodes.Lit(decode_input(item)) for item in witness["inputs"])
            if row["kind"] == "combinator":
                assert "ascii" not in witness
            else:
                assert witness["ascii"] == witness["text"]


def test_published_ascii_matches_stored_bodies(library, catalogue):
    assert {row["name"] for row in catalogue["story"] if "ascii" not in row} == {
        "patch", "delta", "apply", "merge", "three_way", "conflict_paths", "resolve",
        "invert", "replay", "rebase", "merge_idem", "merge_symmetric",
        "commute",  # round 6: printed subject {s} does not bind the body's base, first, second
    }
    for row in catalogue["story"]:
        digest = export_util.body_sha256(library.get(row["name"]).body)
        assert row["body_sha256"] == digest
        assert ("ascii" in row) == ("decl" in row)
        if "ascii" in row:
            assert export_util.source_matches(row["ascii"], digest)


def test_showcases_ladder_ascii_and_export(library, catalogue):
    assert catalogue == build_export()
    assert OUTPUT.read_text(encoding="utf-8") == json.dumps(catalogue, sort_keys=True, indent=1, ensure_ascii=False) + "\n"
    source = json.loads(DESIGN.read_text(encoding="utf-8"))
    assert len(catalogue["ladder"]) == 5
    assert [item["answer"] for item in catalogue["showcase"]] == [item["answer"] for item in source["showcase"]]
    assert all(item["answer_checked"] for item in catalogue["showcase"])
    assert len(OUTPUT.read_bytes()) < 3_000_000

    def ascii_strings(value, name=""):
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "notation3":  # Notation v3: the generated display block
                    continue
                yield from ascii_strings(item, key)
        elif isinstance(value, list):
            for item in value:
                yield from ascii_strings(item, name)
        elif isinstance(value, str) and not name.endswith("_zh"):
            yield value

    assert all(text.isascii() for text in ascii_strings(catalogue))
    for entry in (*catalogue["layer0"]["objects"], *catalogue["layer0"]["operations"],
                  *catalogue["layer0"]["observation"]["probes"]):
        assert entry["title"] and entry["definition"]
    assert catalogue["layer0"]["combinators"]["title"]
    assert catalogue["layer0"]["combinators"]["definition"]
    assert catalogue["story"][2]["examples"][0]["inputs"][0] == {"t": "fn", "v": "read"}
    assert catalogue["story"][2]["examples"][0]["inputs"][1] == {"t": "fn", "v": "identity_doc"}
    assert len(catalogue["story"][2]["evidence"]["scope"]["op_family"]) == 2
    for item in catalogue["story"]:
        assert all(ord(character) < 128 for character in item.get("decl", "") + item["symbol"])
        for example in item["examples"]:
            assert all(ord(character) < 128 for character in example["text"])
    assert not re.search("[⟨⟩⟦⟧⦅⦆♠♦○◉ℚ𝔹]", json.dumps(catalogue["layer0"], ensure_ascii=False))


def test_I1_I2_I3_I4_and_failed_proof(library):
    for name in ("patch", "delta", "apply", "three_way", "resolve", "rebase"):
        args = samples()[name][0]
        run = library.run(entrypoint(name), args, trace=True)
        assert run.outcome == library.run(entrypoint(name), args).outcome
        assert run.steps == library.run(entrypoint(name), args).steps
        assert unfold_equivalent(run.trace, [Boundary(), Boundary.unfold_all(), Boundary(depth=3)]).ok
        for boundary in (Boundary(), Boundary.unfold_all(), Boundary(depth=3)):
            assert sum(node.steps for node in flatten_calls(run.trace, boundary)) <= run.steps
        inline = kernel.evaluate(kernel.inline(nodes.Call(entrypoint(name), tuple(nodes.Lit(arg) for arg in args)), library.scope()), scope=library.scope())
        assert inline.outcome == run.outcome and inline.steps == run.steps
    assert hosts.read(hosts.base12()) == hosts.base12()
    assert judge("full_state", hosts.base12(), hosts.base12())
    assert not judge("full_state", hosts.base12(), hosts.edit(hosts.base12(), "/l", "x"))
    assert library.run("apply", (hosts.base12(), samples()["apply"][0][1]), fuel=0).outcome == Unknown("fuel")
    pending = new_library()
    pending.write(definitions()[0])
    pending.check("patch")
    pending.make_callable("patch", samples()["patch"])
    with pytest.raises(PipelineError):
        pending.promote("patch", Contract("unverified"))
    request = sampled(lambda _: ("/a", "0", "x"), 3, 11, "three sampled patch inputs")
    pending.verify("patch", replace(request, reference=lambda *args: reference_result("patch", args)))
    with pytest.raises(PipelineError):
        pending.promote("patch", Contract("sampling is insufficient"))
