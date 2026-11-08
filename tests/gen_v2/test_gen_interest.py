import time

from opulse.atoms import nodes as n
from opulse.atoms.spec import (
    CombinatorSpec,
    Definition,
    Edge,
    ObjectSpec,
    ObservationSpec,
    OperationSpec,
)
from opulse.atoms.values import Bottom, Card, Ok
from opulse.gen_v2.base import Candidate, Entry, GenState, Signature
from opulse.gen_v2.interest import (
    degenerate,
    fingerprint,
    fingerprints_extra,
    score_entries,
)
from opulse.gen_v2.library import GenLibrary
from opulse.gen_v2.worlds.toy import gen_world


def state():
    world = gen_world()
    return GenState(world, GenLibrary(world.decl, world.atoms), dict(world.sorts))


def operation(name, body, ins=("int", "int"), out="int"):
    spec = OperationSpec(name, "combine", tuple(Edge(sort) for sort in ins), Edge(out), "generated")
    return Candidate(Definition(name, "operation", "invented", 1, (), spec, body), Signature(ins, out), "test")


def obj(name, form, **kwargs):
    spec = ObjectSpec(name, form, **kwargs)
    return Candidate(Definition(name, "object", "invented", 1, (), spec, spec.body), None, "test")


def comb(name, body):
    spec = CombinatorSpec(name, ("fn", "x"), ("fn",), body)
    return Candidate(Definition(name, "combinator", "invented", 1, (), spec, body),
                     Signature(("int",), "int", (Signature(("int",), "int"),)), "test")


def observation(name, body):
    spec = ObservationSpec(name, ("probe",), body)
    return Candidate(Definition(name, "observation", "invented", 1, (), spec, body),
                     Signature(("truth",), "int"), "test")


def test_operation_canonical_permutation_and_degeneracy():
    world = state()
    first = operation("f1", n.Call("add", (n.Var("x"), n.Var("y"))))
    second = operation("f2", n.Call("add", (n.Var("y"), n.Var("x"))))
    grid = [(args, Ok(args[0] + 2 * args[1]), 1) for args in ((0, 0), (0, 1), (1, 0), (1, 1))]
    swapped = [(args, Ok(2 * args[0] + args[1]), 1) for args, _, _ in grid]
    assert fingerprint(world, first, grid) == fingerprint(world, second, swapped)
    assert first.meta["fingerprint_raw"] != second.meta["fingerprint_raw"]
    assert fingerprints_extra(world, first, grid)["fingerprint_canonical"] == fingerprint(world, first, grid)
    world.entries["f1"] = Entry("f1", "operation", 1, first.signature, "test", (),
                                fingerprint(world, first, grid), meta=dict(first.meta))
    world.fingerprints[world.entries["f1"].fingerprint] = "f1"
    assert "argument order" in degenerate(world, second, swapped)
    assert fingerprint(world, first, grid) != fingerprint(world, first, grid[:-1])
    assert degenerate(world, operation("f3", n.Lit(0)), [(args, Bottom("a"), 0) for args, _, _ in grid])
    assert degenerate(world, operation("f4", n.Var("x")), [(args, Ok(args[0]), 0) for args, _, _ in grid])
    assert degenerate(world, operation("f5", n.Call("inc", (n.Var("x"),))),
                      [(args, Ok(args[0] ** 2), 0) for args, _, _ in grid])
    assert degenerate(world, operation("f6", n.Call("add", (n.Var("x"), n.Var("y")))),
                      [(args, Ok(sum(args)), 1) for args, _, _ in grid]) == "same as given atom add"


def test_object_partition_and_trivial_forms():
    world = state()
    valid = n.Call("is_pos", (n.Var("value"),))
    object_a = obj("A1", "refine", base="int", valid=valid, canon=n.Var("value"))
    object_b = obj("A2", "refine", base="int", valid=valid, canon=n.Var("value"))
    results = [((number,), Ok(number % 2) if number >= 0 else Bottom("invalid"), 2)
               for number in range(-1, 4)]
    assert fingerprint(world, object_a, results) == fingerprint(world, object_b, results)
    assert degenerate(world, object_a, results) is None
    trivial = [((number,), Ok(number), 1) for number in range(3)]
    assert degenerate(world, object_a, trivial)
    record = obj("A3", "compose", tags={"record": [("item", "int")]})
    assert degenerate(world, record, [])
    variant = obj("A4", "compose", tags={"none": [], "some": [("item", "int")]})
    assert degenerate(world, variant, []) is None
    cards = [((), Ok(Card("A4", "none")), 1), ((1,), Ok(Card("A4", "some", (1,))), 1)]
    assert fingerprint(world, variant, cards)[-2] == (("none", ()), ("some", ("int",)))
    second = obj("A5", "compose", tags={"none": [], "some": [("item", "int")]})
    other_cards = [((), Ok(Card("A5", "none")), 1), ((1,), Ok(Card("A5", "some", (1,))), 1)]
    assert fingerprint(world, variant, cards) == fingerprint(world, second, other_cards)


def test_combinator_plug_vector_and_observation_partition():
    world = state()
    double = comb("k1", n.Call("fn", (n.Call("fn", (n.Var("x"),)),)))
    single = comb("k2", n.Call("fn", (n.Var("x"),)))
    results = [(('inc', 0), Ok(2), 2), (('neg', 0), Ok(0), 2),
               (('inc', 1), Ok(3), 2), (('neg', 1), Ok(1), 2)]
    assert fingerprint(world, double, results) != fingerprint(world, double, results[1:])
    assert degenerate(world, double, results) is None
    assert degenerate(world, single, results) == "single call of plugged operation"
    flat = [(('inc', 0), Ok(0), 1), (('neg', 0), Ok(0), 1),
            (('inc', 1), Ok(1), 1), (('neg', 1), Ok(1), 1)]
    assert "independent" in degenerate(world, double, flat)
    plugged_once = [(('inc', 0), Ok(1), 1), (('neg', 0), Ok(0), 1),
                    (('inc', 1), Ok(2), 1), (('neg', 1), Ok(-1), 1)]
    assert "one call" in degenerate(world, double, plugged_once)
    observe = observation("q1", n.Var("probe"))
    truth = [((0,), Ok(1), 1), ((1,), Ok(1), 1), ((2,), Ok(2), 1)]
    assert fingerprint(world, observe, truth)[-2] == (0, 0, 1)
    assert degenerate(world, observe, truth) is None
    assert degenerate(world, observe, [((0,), Ok(1), 1), ((1,), Ok(1), 1)])
    world.world.probes = ("inc",)
    assert degenerate(world, observe, [((0,), Ok(1), 1), ((1,), Ok(2), 1)]) == "same as given probe inc"


def test_score_entries_1000_entries_under_ten_seconds():
    world = state()
    for index in range(1000):
        name = f"f{index}"
        previous = (f"f{index - 1}",) if index else ()
        world.entries[name] = Entry(name, "operation", 1 + index // 75,
                                    Signature(("int",), "int"), "test", previous,
                                    ("operation", ("int",), "int", ((("int", str(index)), ("ok", ("int", str(index)))),)),
                                    2, 3, 4, 0)
    started = time.perf_counter()
    score_entries(world)
    assert time.perf_counter() - started < 10
    assert all(0 <= entry.interest["total"] <= 1 for entry in world.entries.values())
    assert world.entries["f0"].interest["distinct_dependents"] == 1


def test_card_regularities_and_observation_partition():
    world = state()
    cards = (Card("token", "first"), Card("token", "second"))
    candidate = operation("f9", n.Var("x"), ins=("token", "token"), out="token")
    results = [((left, right), Ok(left if left == right else cards[0]), 2)
               for left in cards for right in cards]
    key = fingerprint(world, candidate, results)
    world.entries["f9"] = Entry("f9", "operation", 2, candidate.signature, "combine", (), key,
                                  2, 2, 3, meta=dict(candidate.meta))
    observer = observation("q10", n.Var("probe"))
    observations = [((index,), Ok(cards[index % 2]), 1) for index in range(4)]
    key = fingerprint(world, observer, observations)
    world.entries["q10"] = Entry("q10", "observation", 2, observer.signature, "partition", (), key,
                                   1, 1, 3, meta=dict(observer.meta))
    score_entries(world)
    assert "commutative" in world.entries["f9"].interest["regularities"]
    assert "idempotent" in world.entries["f9"].interest["regularities"]
    assert "balanced partition" in world.entries["q10"].interest["regularities"]


def test_combinator_and_observation_permutation_keys():
    world = state()
    slot = Signature(("int",), "int")
    signature = Signature(("int",), "int", (slot, slot))
    first = Candidate(Definition("k21", "combinator", "invented", 1, (),
                                 CombinatorSpec("k21", ("left", "right", "x"),
                                                ("left", "right"), n.Var("x")), n.Var("x")),
                      signature, "test")
    second = Candidate(Definition("k22", "combinator", "invented", 1, (),
                                  CombinatorSpec("k22", ("left", "right", "x"),
                                                 ("left", "right"), n.Var("x")), n.Var("x")),
                       signature, "test")
    results = [((left, right, number), Ok(number + (left == "inc") + 2 * (right == "inc")), 2)
               for left in ("inc", "neg") for right in ("inc", "neg") for number in (0, 1)]
    swapped = [((left, right, number), Ok(number + (right == "inc") + 2 * (left == "inc")), 2)
               for (left, right, number), _, _ in results]
    assert fingerprint(world, first, results) == fingerprint(world, second, swapped)
    assert first.meta["fingerprint_raw"] != second.meta["fingerprint_raw"]
    world.entries[first.defn.name] = Entry(first.defn.name, "combinator", 1, signature, "test", (),
                                          first.meta["fingerprint_canonical"], meta=dict(first.meta))
    world.fingerprints[first.meta["fingerprint_canonical"]] = first.defn.name
    assert "argument order" in degenerate(world, second, swapped)
    assert fingerprint(world, first, results) != fingerprint(world, first, results[:-1])

    obs_signature = Signature(("truth", "truth"), "int")
    first_obs = observation("q21", n.Var("probe"))
    second_obs = observation("q22", n.Var("probe"))
    first_obs.signature = second_obs.signature = obs_signature
    observations = [((left, right), Ok(left + 2 * right), 1)
                    for left in (0, 1) for right in (0, 1)]
    reversed_results = [((left, right), Ok(right + 2 * left), 1)
                        for (left, right), _, _ in observations]
    assert fingerprint(world, first_obs, observations) == fingerprint(world, second_obs, reversed_results)
    assert first_obs.meta["fingerprint_raw"] != second_obs.meta["fingerprint_raw"]
    world.entries[first_obs.defn.name] = Entry(first_obs.defn.name, "observation", 1, obs_signature, "test", (),
                                              first_obs.meta["fingerprint_canonical"], meta=dict(first_obs.meta))
    world.fingerprints[first_obs.meta["fingerprint_canonical"]] = first_obs.defn.name
    assert "argument order" in degenerate(world, second_obs, reversed_results)


def test_score_entries_1500_and_all_kind_compression():
    world = state()
    kinds = ("object", "operation", "combinator", "observation")
    for index in range(1500):
        name = f"f{index}"
        kind = kinds[index % 4]
        dependencies = (f"f{index - 4}",) if index >= 4 else ()
        world.entries[name] = Entry(name, kind, 1 + index // 100, None, "test", dependencies,
                                    (kind, index), 2, 3, 4)
    started = time.perf_counter()
    score_entries(world)
    assert time.perf_counter() - started < 10
    assert all(0 <= entry.interest["compression"] <= 1 for entry in world.entries.values())
    assert all(world.entries[f"f{index}"].interest["compression"] > 0 for index in range(4, 8))


def test_small_bodies_inline_across_all_kinds():
    from types import SimpleNamespace

    from opulse.atoms import kernel

    world = state()
    base_body = n.Call("inc", (n.Var("x"),))
    dependent_body = n.Call("f1", (n.Var("x"),))
    records = {
        "f1": SimpleNamespace(body=base_body),
        "f2": SimpleNamespace(body=dependent_body),
        "k3": SimpleNamespace(body=dependent_body),
        "A4": SimpleNamespace(body=dependent_body,
                              spec=SimpleNamespace(form="refine", valid=dependent_body,
                                                   canon=dependent_body, sealed=False, interface=())),
        "q5": SimpleNamespace(body=dependent_body,
                              spec=SimpleNamespace(memory={"step": dependent_body})),
    }

    class Library:
        definitions = records

        def get(self, name):
            return records[name]

        def scope(self):
            return kernel.DictScope(defns=[kernel.Defn(name, ("x",), record.body)
                                           for name, record in records.items()])

    world.library = Library()
    for index, (name, kind) in enumerate((("f1", "operation"), ("f2", "operation"),
                                          ("k3", "combinator"), ("A4", "object"),
                                          ("q5", "observation"))):
        world.entries[name] = Entry(name, kind, 1 + (index > 0), None, "test",
                                    ("f1",) if index else (), (kind, index), 2, 2, 2)
    score_entries(world)
    assert all(world.entries[name].interest["unfolded_length_estimate"] > 2
               for name in ("f2", "k3", "A4", "q5"))
    assert all(world.entries[name].interest["compression"] > 0
               for name in ("f2", "k3", "A4", "q5"))
