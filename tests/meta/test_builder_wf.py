"""Exact ordered reports for builder worlds (atoms-meta section 6.2)."""

from dataclasses import replace

import pytest

from opulse.atoms import nodes as n
from opulse.atoms.values import Card
from opulse.meta import code as C
from opulse.meta.builder import world_value as V
from opulse.meta.builder.instantiate import _assemble, instantiate
from opulse.meta.builder.wf import wf
from opulse.meta.worlds.builder import story


def tags():
    return [V.tag("domain", "math"), V.tag("modalities", ["text"]),
            V.tag("open_kinds", ["operation"]), V.tag("star_kind", "operation"),
            V.tag("reasoning", ["compute"]), V.tag("state", "stateless"),
            V.tag("outcomes", "deterministic"), V.tag("visibility", "full"),
            V.tag("agents", "1"), V.tag("uses", ["teaching"]),
            V.tag("scale", "five states"), V.tag("difficulty", "five levels")]


def base(**changes):
    defaults = {"name": "z5", "version": 1, "sorts": [V.enum("z", ["z0", "z1"])],
                "ops": [V.table("id", "transform", ["z"], "z", [],
                                [V.row([Card("z", value)], V.val(Card("z", value)))
                                 for value in ("z0", "z1")])],
                "nodes": ["Var", "Lit", "Call", "Let", "Case"], "recursion": "none",
                "probes": ["id"], "judge_view": "full_state", "open_kinds": ["operation"], "tags": tags()}
    defaults.update(changes)
    return V.world(**defaults)


def edited(card, position, value):
    fields = list(card.fields)
    fields[position] = C.lst(value) if position in (2, 3, 4, 6, 8, 9) else value
    return replace(card, fields=tuple(fields))


def code_for(card, name="id", body=None, output="z"):
    spec = _assemble(card)[0].operations[0]
    return C.make_code("operation", C.sig_op([("z", "bottom")], (output, "bottom")),
                       ("a",), body or n.Call("id", (n.Var("a"),)),
                       lambda ref: C.Resolved(digest=C.atom_digest(spec)) if ref == "id" else None)


def test_good_world_and_canonical_hash_order():
    card = base()
    assert wf(card) == Card("report", "ok")
    assert V.show(card) == "World<z5@1: sorts z; ops id; probes id>"
    reversed_rows = V.table("id", "transform", ["z"], "z", [],
                            list(reversed(C.items(C.items(card.fields[3])[0].fields[5]))))
    reversed_tags = list(reversed(tags()))
    assert V.world_hash(card) == V.world_hash(base(ops=[reversed_rows], tags=reversed_tags))


@pytest.mark.parametrize(("card", "check", "detail"), [
    (base(sorts=[V.enum("bad-name", ["x"])]), "names", "invalid sort name"),
    (base(sorts=[V.enum("z", ["z0", "z1"]), V.enum("z", ["z2"])]), "names", "duplicate sort name"),
    (base(sorts=[V.enum("z", [])]), "sorts", "invalid enum z"),
    (base(sorts=[V.range_sort("z", 3, 1)]), "sorts", "invalid range z"),
    (base(ops=[V.table("id", "transform", ["missing"], "z", [], [])]),
     "sorts", "unknown sort in id"),
    (base(ops=[V.table("id", "transform", ["z"], "z", [], [])]),
     "tables", "incomplete table: id"),
    (base(ops=[V.table("id", "transform", ["z"], "z", [],
                       [V.row([Card("z", x)], V.val(Card("z", "z0"))) for x in ("z0", "z0")])]),
     "tables", "invalid or duplicate row in id"),
    (base(ops=[V.table("id", "transform", ["z"], "z", [],
                       [V.row([Card("z", x)], V.err("oops")) for x in ("z0", "z1")])]),
     "tables", "unlisted error in id"),
    (base(ops=[V.table("id", "transform", ["z"], "z", [7],
                       [V.row([Card("z", x)], V.val(Card("z", x))) for x in ("z0", "z1")])]),
     "tables", "invalid errors in id"),
    (base(probes=["missing"]), "probes", "invalid probe missing"),
    (base(open_kinds=[]), "kinds", "invalid open_kinds"),
    (base(recursion="none", nodes=["Rec"]), "kinds", "invalid recursion"),
    (base(tags=[]), "tags", "missing, duplicate or unknown tags"),
    (base(tags=[V.tag("domain", "bogus")] + tags()[1:]), "tags", "invalid tag domain"),
])
def test_first_failure_exact(card, check, detail):
    assert wf(card) == Card("report", "bad", (check, detail))


def test_declared_law_checked_on_all_tuples_and_changes_world_hash():
    value = story.z5()
    assert wf(value) == Card("report", "ok")
    declaration, _ = instantiate(value)
    assert [law["name"] for law in declaration.extra["laws"]] == ["add5_assoc", "mul5_distributes"]
    assert declaration.extra["laws"][0]["code_hash"] == C.code_hash(C.items(value.fields[10])[0].fields[1])
    without_law = replace(value, fields=value.fields[:10])
    assert wf(without_law) == Card("report", "ok")
    assert V.world_hash(value) != V.world_hash(without_law)
    operation = C.items(value.fields[3])[0]
    rows = list(C.items(operation.fields[5]))
    rows[0] = V.row([story.z(0), story.z(0)], V.val(story.z(1)))
    altered = replace(operation, fields=(*operation.fields[:5], C.lst(rows), operation.fields[6]))
    changed = replace(value, fields=(*value.fields[:3], C.lst((altered, *C.items(value.fields[3])[1:])),
                                     *value.fields[4:]))
    assert wf(changed) == Card("report", "bad", ("laws", "foreign law atom: add5_assoc"))


def test_false_law_reports_first_failing_tuple():
    value = story.z5()
    from opulse.meta.builder.instantiate import instantiate

    decl, _ = instantiate(value)
    digests = {op.name: C.atom_digest(op) for op in decl.operations}
    code = C.make_code("law", C.sig_law((("a", "z"), ("b", "z"))), ("a", "b"),
                       n.Call("eq5", (n.Var("a"), n.Var("b"))),
                       lambda name: C.Resolved(digest=digests[name]))
    changed = replace(value, fields=(*value.fields[:10], C.lst((V.law("all_equal", code),))))
    assert wf(changed) == Card("report", "bad", ("laws", ("law all_equal fails at "
        "(Card(sort='z', tag='z0', fields=()), Card(sort='z', tag='z1', fields=())): "
        "Ok(value=Card(sort='bool', tag='false', fields=()))")))


def test_law_rejects_bottom_and_duplicate_names_exactly():
    value = story.z5()
    declaration, _ = instantiate(value)
    digests = {op.name: C.atom_digest(op) for op in declaration.operations}
    code = C.make_code("law", C.sig_law((("a", "z"),)), ("a",),
                       n.Call("eq5", (n.Var("a"), n.Lit(Card("z", "absent")))),
                       lambda name: C.Resolved(digest=digests[name]))
    card = replace(value, fields=(*value.fields[:10], C.lst((V.law("broken", code),))))
    assert wf(card) == Card("report", "bad", ("laws", ("law broken fails at "
        "(Card(sort='z', tag='z0', fields=()),): Bottom(reason='invalid')")))
    valid = C.items(value.fields[10])[0].fields[1]
    repeated = replace(value, fields=(*value.fields[:10], C.lst((V.law("twice", valid),
                                                                 V.law("twice", valid)))))
    assert wf(repeated) == Card("report", "bad", ("laws", "invalid or duplicate law twice"))


def test_law_order_does_not_change_canonical_world_identity():
    value = story.z5()
    first = C.items(value.fields[10])[0]
    second = V.law("same_statement", first.fields[1])
    left = replace(value, fields=(*value.fields[:10], C.lst((first, second))))
    right = replace(value, fields=(*value.fields[:10], C.lst((second, first))))
    assert wf(left) == wf(right) == Card("report", "ok")
    assert V.world_hash(left) == V.world_hash(right)


def test_malformed_law_reports_laws_before_probes_without_raising():
    value = story.z5()
    fields = list(value.fields)
    fields[6] = C.lst(("missing",))
    fields[10] = C.lst((7,))
    changed = replace(value, fields=tuple(fields))
    assert wf(changed) == Card("report", "bad", ("laws", "invalid law declaration"))
    declared = base(ops=[*C.items(base().fields[3]), V.body("again", code_for(base()))],
                    probes=["missing"])
    malformed = replace(declared, fields=(*declared.fields, C.lst((7,))))
    assert wf(malformed) == Card("report", "bad", ("laws", "invalid law declaration"))


def test_bodies_reject_forward_references_and_closed_nodes():
    card = base()
    code = code_for(card)
    assert wf(base(ops=[V.body("first", code), C.items(card.fields[3])[0]])) == Card(
        "report", "bad", ("bodies", "foreign or forward atom in first"))
    assert wf(base(ops=[C.items(card.fields[3])[0], V.body("again", code)],
                   nodes=["Var", "Lit"])) == Card("report", "bad", ("bodies", "closed node in again"))


def test_bodies_accept_earlier_calls_and_reject_over_budget():
    card = base()
    code = code_for(card)
    assert wf(base(ops=[C.items(card.fields[3])[0], V.body("again", code)])) == Card("report", "ok")
    expensive = V.table("id", "transform", ["z"], "z", [],
                        C.items(C.items(card.fields[3])[0].fields[5]), cost=10_001)
    expensive_world = base(ops=[expensive])
    expensive_code = code_for(expensive_world)
    assert wf(base(ops=[expensive, V.body("again", expensive_code)])) == Card(
        "report", "bad", ("bodies", "body does not terminate: again"))


def test_valid_body_does_not_hash_malformed_later_tags():
    card = base()
    body = V.body("again", code_for(card))
    value = base(ops=[*C.items(card.fields[3]), body], tags=[7])
    assert wf(value) == Card("report", "bad", ("tags", "invalid tag cards"))


def test_probes_reject_transitive_act_dependencies():
    card = base(ops=[V.table("id", "act", ["z"], "z", [],
                             [V.row([Card("z", x)], V.val(Card("z", x))) for x in ("z0", "z1")])],
                probes=[])
    code = code_for(card)
    card = base(ops=[C.items(card.fields[3])[0], V.body("via", code)], probes=["via"])
    assert wf(card) == Card("report", "bad", ("probes", "probe via depends on act id"))
    via_spec = _assemble(card)[0].operations[1]
    indirect = C.make_code("operation", C.sig_op([("z", "bottom")], ("z", "bottom")),
                           ("x",), n.Call("via", (n.Var("x"),)),
                           lambda ref: C.Resolved(digest=C.atom_digest(via_spec)) if ref == "via" else None)
    further = base(ops=[*C.items(card.fields[3]), V.body("further", indirect)], probes=["further"])
    assert wf(further) == Card("report", "bad", ("probes", "probe further depends on act id"))


def test_first_failed_check_precedes_later_checks():
    card = base(sorts=[V.enum("z", [])], ops=[], tags=[])
    assert wf(card) == Card("report", "bad", ("sorts", "invalid enum z"))
