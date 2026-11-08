"""Review-14 regressions for ordered builder validation and verdict comparison."""

from dataclasses import replace

import pytest

from opulse.atoms.values import Card, Ok
from opulse.meta import code as C
from opulse.meta.builder import world_value as V
from opulse.meta.builder.wf import wf
from opulse.meta.worlds.builder import story


def changed(value, index, replacement):
    fields = list(value.fields)
    fields[index] = replacement
    return replace(value, fields=tuple(fields))


@pytest.mark.parametrize("star_kind", ["law", "bridge"])
def test_six_open_kinds_accept_law_and_bridge_star(star_kind):
    value = story.z5()
    kinds = ("object", "operation", "combinator", "observation", "law", "bridge")
    tags = [V.tag("open_kinds", kinds) if entry.fields[0] == "open_kinds"
            else V.tag("star_kind", star_kind) if entry.fields[0] == "star_kind" else entry
            for entry in C.items(value.fields[9])]
    value = changed(changed(value, 8, C.lst(kinds)), 9, C.lst(tags))
    assert wf(value) == Card("report", "ok")


def test_valid_laws_do_not_canonicalize_unchecked_tags():
    value = changed(story.z5(), 9, C.lst((7,)))
    assert wf(value) == Card("report", "bad", ("tags", "invalid tag cards"))


def test_laws_precede_probes_and_tags_precede_no_other_checks():
    value = changed(story.z5(), 9, C.lst((7,)))
    assert wf(changed(value, 6, C.lst(("missing",)))) == Card(
        "report", "bad", ("probes", "invalid probe missing"))
    assert wf(changed(value, 10, C.lst((7,)))) == Card(
        "report", "bad", ("laws", "invalid law declaration"))


@pytest.mark.parametrize("key", ["scale", "difficulty"])
def test_required_world_tags_are_not_optional(key):
    value = story.z5()
    tags = [entry for entry in C.items(value.fields[9]) if entry.fields[0] != key]
    assert wf(changed(value, 9, C.lst(tags))) == Card(
        "report", "bad", ("tags", "missing, duplicate or unknown tags"))


def test_published_z5_has_scale_and_difficulty():
    value = story.z5()
    tags = {entry.fields[0]: entry.fields[1] for entry in C.items(value.fields[9])}
    assert tags["scale"] == "five residues and 25 input pairs"
    assert tags["difficulty"] == "five levels from tables to verified composition"
    assert wf(value) == Card("report", "ok")


def test_same_verdict_compares_complete_bad_reports():
    value = story.binary_world()
    left = changed(value, 6, C.lst(("unknown1", "unknown2")))
    right = changed(value, 6, C.lst(("unknown2",)))
    assert wf(left) == Card("report", "bad", ("probes", "invalid probe unknown1"))
    assert wf(right) == Card("report", "bad", ("probes", "invalid probe unknown2"))
    lib, _ = story.creation()
    args = (left, C.lst(("unknown1",)))
    assert story.reference("same_verdict", *args) == Card("bool", "false")
    assert lib.run("same_verdict", args).outcome == Ok(Card("bool", "false"))
    assert lib.get("same_verdict").cost.steps["min"] == 14
    assert lib.get("audit_hidden_product").cost.steps["min"] == 1645
