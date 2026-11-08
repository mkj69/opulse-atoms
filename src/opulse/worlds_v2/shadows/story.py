"""Depth tower: every invented rule is a kernel node, verified before promotion."""

import json
from functools import lru_cache
from pathlib import Path

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.library import VerifyRequest
from opulse.atoms.spec import (
    CombinatorSpec,
    Contract,
    Definition,
    Edge,
    ObjectSpec,
    ObservationSpec,
    OperationSpec,
)
from opulse.atoms.values import Card, Ok, decode

from . import deep_hosts as hosts
from .world import new_library


def call(name, *args):
    return n.Call(name, args)


@lru_cache(maxsize=1)
def source():
    judge = Path(__file__).resolve().parents[4] / "worlds/judge/shadows.json"
    return decode(json.loads(judge.read_text(encoding="utf-8"))["examples"][0]["inputs"][0])


def public_mask():
    return hosts.mask(*(hosts.cell(x, y, z) for x in (1, 2) for y in (0, 2, 4, 6) for z in (1, 2)))


def family():
    return tuple(hosts.volume(*(hosts.cell(x, y, z) for index, (x, y, z) in
                                enumerate(((1, 0, 1), (1, 0, 2), (2, 0, 1), (2, 0, 2),
                                           (1, 2, 1), (2, 4, 2), (1, 6, 1), (2, 6, 2))) if bits & (1 << index)))
                 for bits in range(256))


def definitions():
    ink = call("size", call("top", n.Var("v")))
    views_valid = n.Case(((n.Test(call("valid_views_raw", n.Var("x"))),
                           call("same", call("views_area", n.Var("x")),
                                call("size", call("views_top", call("normalize_views", n.Var("x")))))),), n.Lit(False))
    capture = call("Views.make", call("views_record", call("top_probe", n.Var("v")),
                                                        call("side_probe", n.Var("v")),
                                                        call("ink", n.Var("v"))))
    matches = call("same", call("capture", n.Lit(kernel.FnRef("top")),
                                         n.Lit(kernel.FnRef("side")), n.Var("arg0")), n.Var("arg1"))
    all_candidates_valid = n.Rec("check_each", ("remaining",),
                                 n.Case(((n.Test(call("empty", n.Var("remaining"))), n.Lit(True)),),
                                        n.Case(((n.Test(call("within_mask", call("first", n.Var("remaining")),
                                                                      call("pool_mask", n.Var("x")))),
                                                 n.Case(((n.Test(call("matches", call("first", n.Var("remaining")),
                                                                              call("pool_views", n.Var("x")))),
                                                          call("check_each", call("rest", n.Var("remaining")))),),
                                                        n.Lit(False))),), n.Lit(False))),
                                 (call("pool_volumes", n.Var("x")),),
                                 measure=call("size", n.Var("remaining")))
    raw_pool_views = call("unwrap_views", call("pool_views", n.Var("x")))
    valid_pool_views = n.Case(((n.Test(call("valid_views_raw", raw_pool_views)),
                               n.Case(((n.Test(call("same", call("views_area", raw_pool_views),
                                                         call("size", call("views_top", raw_pool_views)))),
                                        call("same", raw_pool_views, call("normalize_views", raw_pool_views))),),
                                      n.Lit(False))),), n.Lit(False))
    candidate_valid = n.Case(((n.Test(call("valid_pool", n.Var("x"))),
                               n.Case(((n.Test(valid_pool_views),
                                        n.Case(((n.Test(call("ordered_volumes", call("pool_volumes", n.Var("x")))),
                                                 all_candidates_valid),), n.Lit(False))),), n.Lit(False))),), n.Lit(False))
    enumerate_body = n.Blocks((("row", n.Lit(0)),
                               ("partials", n.Lit(Card("List", "items", (hosts.volume(),))))), "loop", (
        ("loop", n.Block((), n.CondJump(n.Test(call("same", n.Var("row"), n.Lit(8))), "done", "extend"))),
        ("extend", n.Block((("partials", call("slice_extend", n.Var("arg0"), n.Var("arg1"),
                                                  n.Var("partials"), n.Var("row"))),
                            ("row", call("add", n.Var("row"), n.Lit(1)))), n.Jump("loop"))),
        ("done", n.Block((), n.Halt(call("pack_enumerated", n.Var("arg0"), n.Var("arg1"),
                                      n.Var("partials"))))),
    ))
    make_candidates = call("Candidates.make", call("enumerate_raw", n.Var("arg0"), n.Var("arg1")))
    retained_pool = call("Candidates.make", call("pack_raw",
                         call("pool_mask", call("pool_raw", n.Var("c"))),
                         call("pool_views", call("pool_raw", n.Var("c"))), n.Var("kept")))
    retain = n.Blocks((("remaining", call("pool_volumes", call("pool_raw", n.Var("c")))),
                       ("kept", n.Lit(Card("List", "items")))), "loop", (
        ("loop", n.Block((), n.CondJump(n.Test(call("empty", n.Var("remaining"))), "done", "check"))),
        ("check", n.Block((("current", call("first", n.Var("remaining"))),
                           ("remaining", call("rest", n.Var("remaining")))),
                          n.CondJump(n.Test(call("same", call("probe", n.Var("current")), n.Var("shadow"))),
                                     "keep", "loop"))),
        ("keep", n.Block((("kept", call("snoc", n.Var("kept"), n.Var("current"))),), n.Jump("loop"))),
        ("done", n.Block((), n.Halt(retained_pool))),
    ))
    original_top = call("views_top", call("unwrap_views", call("pool_views", call("pool_raw", n.Var("c")))))
    consistent = call("retain", n.Lit(kernel.FnRef("top")), n.Var("c"), original_top)
    forced = call("forced_cells", consistent)
    least = call("minimum_raw", n.Var("arg0"), call("forced", n.Var("arg0")))
    ambiguity = call("size", call("pool_volumes", call("pool_raw", consistent)))
    add_view = n.Let("before", call("ambiguity", n.Var("c")), retain)
    possible_probes = n.Lit(Card("List", "items", ("front", "diag", "anti")))
    best_probe = n.Let("example", call("add_view", n.Lit(kernel.FnRef("diag")), n.Var("arg0"),
                                       call("diag", call("first", call("pool_volumes", call("pool_raw", n.Var("arg0")))))),
                       n.Let("front_score", call("probe_score", n.Var("arg0"), n.Lit("front")),
                             n.Let("diag_score", call("probe_score", n.Var("arg0"), n.Lit("diag")),
                                   n.Let("anti_score", call("probe_score", n.Var("arg0"), n.Lit("anti")),
                                         n.Let("candidate", n.Case(((n.Test(call("less", call("choice_worst", n.Var("diag_score")),
                                                                                 call("choice_worst", n.Var("front_score")))),
                                                                      n.Var("diag_score")),), n.Var("front_score")),
                                               n.Case(((n.Test(call("less", call("choice_worst", n.Var("anti_score")),
                                                                          call("choice_worst", n.Var("candidate")))),
                                                        n.Var("anti_score")),), n.Var("candidate")))))))
    first_candidate = call("first", call("pool_volumes", call("pool_raw", n.Var("c"))))
    fold_groups = n.Rec("fold_groups", ("buckets", "depth"),
                        n.Case(((n.Test(call("empty", n.Var("buckets"))), n.Var("depth")),),
                               n.Let("branch", call("solve", call("first", n.Var("buckets")),
                                                            n.Var("tail_probes")),
                                     n.Case(((n.Test(call("less", call("plan_depth", n.Var("branch")), n.Lit(0))),
                                              n.Lit(-1)),),
                                            call("fold_groups", call("rest", n.Var("buckets")),
                                                 n.Case(((n.Test(call("less", n.Var("depth"),
                                                                           call("plan_depth", n.Var("branch")))),
                                                          call("plan_depth", n.Var("branch"))),),
                                                        n.Var("depth")))))),
                        (n.Var("groups"), n.Lit(0)), measure="fuel")
    choose_probes = n.Rec("choose_probes", ("options", "selected"),
                          n.Case(((n.Test(call("empty", n.Var("options"))), n.Var("selected")),),
                                 n.Let("probe_name", call("first_probe", n.Var("options")),
                                       n.Let("groups", call("probe_groups", n.Var("state"), n.Var("probe_name")),
                                             n.Let("tail_probes", call("without_probe", n.Var("remaining"),
                                                                         n.Var("probe_name")),
                                                   n.Let("depth", n.Case(((n.Test(call("same", call("size", n.Var("groups")),
                                                                                     n.Lit(1))), n.Lit(-1)),), fold_groups),
                                                         call("choose_probes", call("rest", n.Var("options")),
                                                              call("choose_plan", n.Var("selected"),
                                                                   call("make_plan", n.Case(((n.Test(call("less", n.Var("depth"),
                                                                                                     n.Lit(0))), n.Lit(-1)),),
                                                                                             call("add", n.Var("depth"), n.Lit(1))),
                                                                        n.Var("probe_name"),
                                                                        call("choice_worst", call("probe_score", n.Var("state"),
                                                                                                   n.Var("probe_name"))))))))))),
                          (n.Var("remaining"), n.Lit(Card("Plan", "plan", (-1, "none", 0)))), measure="fuel")
    solve = n.Rec("solve", ("state", "remaining"),
                  n.Case(((n.Test(call("less", call("size", call("pool_volumes", n.Var("state"))),
                                            n.Lit(2))),
                           call("make_plan", n.Lit(0), n.Lit("none"),
                                call("size", call("pool_volumes", n.Var("state"))))),
                          (n.Test(call("empty", n.Var("remaining"))),
                           call("make_plan", n.Lit(-1), n.Lit("none"),
                                call("size", call("pool_volumes", n.Var("state")))))),
                         choose_probes),
                  (call("pool_raw", n.Var("c")), possible_probes), measure="fuel", memo=True)
    plan = n.Case(((n.Test(call("empty", call("pool_volumes", call("pool_raw", n.Var("c"))))),
                    n.Lit(hosts.Bottom("empty_candidates"))),),
                  n.Let("choice", call("best_probe", n.Var("c")),
                        n.Let("front_shadow", call("front_probe", first_candidate),
                              n.Let("diag_shadow", call("diag_probe", first_candidate),
                                    n.Let("anti_shadow", call("anti_probe", first_candidate), solve)))))
    return (
        Definition("ink", "observation", "invented", 1, ("top", "size"),
                   ObservationSpec("ink", ("top",), ink, extra={"subject": "v"}), ink),
        Definition("Views", "object", "invented", 1,
                   ("normalize_views", "same", "size", "valid_views_raw", "views_area", "views_top"),
                   ObjectSpec("Views", "refine", base="ViewsRaw", valid=views_valid,
                              canon=call("normalize_views", n.Var("x"))), None),
        Definition("capture", "combinator", "invented", 2,
                   ("Views.make", "views_record", "ink"),
                   CombinatorSpec("capture", ("top_probe", "side_probe", "v"),
                                  ("top_probe", "side_probe"), capture), capture),
        Definition("matches", "operation", "invented", 3, ("same", "capture"),
                   OperationSpec("matches", "decide", (Edge("Volume"), Edge("ViewsRaw")), Edge("bool"),
                                 "Compare only the two granted projections.", extra={"input_names": ("arg0", "arg1")}), matches),
        Definition("enumerate_raw", "operation", "invented", 1,
                   ("same", "slice_extend", "add", "pack_enumerated"),
                   OperationSpec("enumerate_raw", "transform", (Edge("Mask"), Edge("ViewsRaw")),
                                 Edge("CandidatesRaw"), "Enumerate compatible volumes one public y slice at a time.",
                                 extra={"input_names": ("arg0", "arg1")}), enumerate_body),
        Definition("Candidates", "object", "invented", 4,
                   ("valid_pool", "ordered_volumes", "empty", "pool_volumes", "first", "matches",
                    "pool_views", "within_mask", "pool_mask", "rest", "size", "unwrap_views",
                    "valid_views_raw", "views_area", "views_top", "normalize_views", "same"),
                   ObjectSpec("Candidates", "refine", base="CandidatesRaw", valid=candidate_valid), None),
        Definition("candidates", "operation", "invented", 5, ("Candidates.make", "enumerate_raw"),
                   OperationSpec("candidates", "transform", (Edge("Mask"), Edge("ViewsRaw")), Edge("CandidatesRaw"),
                                 "Enumerate each public y slice and keep its exact edge covers.",
                                 extra={"input_names": ("arg0", "arg1")}), make_candidates),
        Definition("retain", "combinator", "invented", 5,
                   ("pool_volumes", "pool_raw", "empty", "first", "rest", "same", "snoc",
                    "Candidates.make", "pack_raw", "pool_mask", "pool_views"),
                   CombinatorSpec("retain", ("probe", "c", "shadow"), ("probe",), retain), retain),
        Definition("forced", "observation", "invented", 6,
                   ("forced_cells", "retain", "views_top", "unwrap_views", "pool_views", "pool_raw"),
                   ObservationSpec("forced", ("top",), forced, extra={"subject": "c"}), forced),
        Definition("least", "operation", "invented", 7, ("minimum_raw", "forced"),
                   OperationSpec("least", "transform", (Edge("CandidatesRaw"),), Edge("Min"),
                                 "Count minimum volume using the proved forced-cell bound."), least),
        Definition("ambiguity", "observation", "invented", 6,
                   ("size", "pool_volumes", "pool_raw", "retain", "views_top", "unwrap_views", "pool_views"),
                   ObservationSpec("ambiguity", ("top",), ambiguity, extra={"subject": "c"}), ambiguity),
        Definition("add_view", "combinator", "invented", 7,
                   ("ambiguity", "pool_volumes", "pool_raw", "empty", "first", "rest", "same", "snoc",
                    "Candidates.make", "pack_raw", "pool_mask", "pool_views"),
                   CombinatorSpec("add_view", ("probe", "c", "shadow"), ("probe",), add_view), add_view),
        Definition("best_probe", "operation", "invented", 8,
                   ("add_view", "diag", "first", "pool_volumes", "pool_raw", "probe_score", "choice_worst", "less"),
                   OperationSpec("best_probe", "decide", (Edge("CandidatesRaw"),), Edge("Choice"),
                                 "Choose the permitted shadow probe minimizing the largest partition."), best_probe),
        Definition("plan", "combinator", "invented", 9,
                   ("best_probe", "first", "first_probe", "pool_volumes", "pool_raw", "empty", "less", "same", "size",
                    "rest", "add", "probe_groups", "without_probe", "plan_depth", "make_plan", "choose_plan",
                    "choice_worst", "probe_score"),
                   CombinatorSpec("plan", ("front_probe", "diag_probe", "anti_probe", "c"),
                                  ("front_probe", "diag_probe", "anti_probe"), plan), plan),
    )


def request(method, domain, description, reference=None, family_names=None):
    scope = {"domain": description, "description": description, "size": len(domain)}
    extra = {}
    if family_names:
        scope["op_family"] = ({key: list(names) for key, names in family_names.items()} if isinstance(family_names, dict)
                              else list(family_names))
        extra["op_family"] = family_names
    return VerifyRequest(method, domain, scope, reference=reference, extra=extra)


def build_library(upto=None):
    library = new_library()
    bodies = family()
    sample_views = hosts.views_record(hosts.top(source()), hosts.side(source()), hosts.size(hosts.top(source())))
    full_views = Card("Views", "val", (sample_views,))
    test_cells = public_mask().fields[:6]
    small_mask = hosts.mask(*test_cells)
    small_bodies = tuple(hosts.volume(*(item for index, item in enumerate(test_cells) if bits & (1 << index)))
                         for bits in range(50))
    small_views = tuple(Card("Views", "val", (hosts.views_record(hosts.top(body), hosts.side(body),
                                      hosts.size(hosts.top(body))),)) for body in small_bodies)
    raw_pools = tuple(hosts.enumerate_raw(small_mask, views) for views in small_views)
    small_pools = tuple(Card("Candidates", "val", (pool,)) for pool in raw_pools)
    canonical_pool = Card("Candidates", "val", (hosts.enumerate_raw(public_mask(), full_views),))
    plan = (
        ("ink", ((source(),),), request("exhaustive", tuple((body,) for body in bodies),
                                      "all 256 subsets of eight bounded public cells", lambda body: hosts.size(hosts.top(body)))),
        ("Views", ((sample_views,),), request("bounded", tuple((hosts.views_record(hosts.top(body), hosts.side(body),
                                                hosts.size(hosts.top(body))),) for body in bodies[:50]),
                                           "50 bounded public projection records; canonical inputs and valid area")),
        ("capture", ((kernel.FnRef("top"), kernel.FnRef("side"), source()),),
         request("bounded", tuple((body,) for body in bodies[:50]),
                 "50 bounded subsets of eight public cells, with two probe-slot operations", family_names=("top", "side"))),
        ("matches", ((source(), Card("Views", "val", (sample_views,))),),
         request("bounded", tuple((body, Card("Views", "val", (hosts.views_record(hosts.top(body), hosts.side(body),
                                      hosts.size(hosts.top(body))),))) for body in bodies[:50]),
                 "50 bounded public volume and matching projection pairs",
                 lambda body, views: hosts.same(Card("Views", "val", (hosts.views_record(hosts.top(body),
                               hosts.side(body), hosts.size(hosts.top(body))),)), views))),
        ("enumerate_raw", ((public_mask(), full_views),), request("bounded",
                tuple((small_mask, views) for views in small_views),
                "50 bounded six-cell public-mask and projection pairs across eight slice extensions",
                lambda mask, views: hosts.enumerate_raw(mask, views))),
        ("Candidates", ((raw_pools[1],),), request("bounded", tuple((pool,) for pool in raw_pools),
                "50 bounded public masks and paired projections (six possible cells)")),
        ("candidates", ((public_mask(), full_views),), request("bounded",
                tuple((small_mask, views) for views in small_views),
                "50 bounded six-cell public-mask and projection pairs",
                lambda public_mask, views: Card("Candidates", "val", (hosts.enumerate_raw(public_mask, views),)))),
        ("retain", ((kernel.FnRef("diag"), Card("Candidates", "val", (raw_pools[3],)),
                     hosts.diag(small_bodies[3])),),
         request("bounded", tuple((Card("Candidates", "val", (pool,)), hosts.diag(body))
                                  for pool, body in zip(raw_pools, small_bodies)),
                 "50 bounded six-cell candidate pools, two authorized probe operations",
                 lambda assignments, inputs: Card("Candidates", "val", (
                     hosts.retain_raw(inputs[0], assignments["probe"], inputs[1]),)),
                 family_names=("diag", "anti"))),
        ("forced", ((small_pools[3],),), request("bounded", tuple((pool,) for pool in small_pools),
                "50 bounded six-cell candidate pools, all sharing an authorized top view",
                lambda pool: hosts.forced_cells(pool))),
        ("least", ((small_pools[3],),), request("bounded", tuple((pool,) for pool in small_pools),
                "50 bounded six-cell candidate pools and their minimum occupancy",
                lambda pool: hosts.minimum_raw(pool, hosts.forced_cells(pool)))),
        ("ambiguity", ((small_pools[3],),), request("bounded", tuple((pool,) for pool in small_pools),
                "50 bounded six-cell candidate pools and exact multiplicities",
                lambda pool: hosts.size(hosts.pool_volumes(hosts.pool_raw(pool))))),
        ("add_view", ((kernel.FnRef("diag"), small_pools[3], hosts.diag(small_bodies[3])),),
         request("bounded", tuple((pool, hosts.diag(body)) for pool, body in zip(small_pools, small_bodies)),
                 "50 bounded six-cell candidate pools, two authorized supplementary probes",
                 lambda assignments, inputs: Card("Candidates", "val", (
                     hosts.retain_raw(inputs[0], assignments["probe"], inputs[1]),)),
                 family_names=("diag", "anti"))),
        ("best_probe", ((small_pools[3],),),
         request("bounded", tuple((pool,) for pool in small_pools),
                 "50 bounded six-cell candidate pools, three complete probe partitions",
                 lambda pool: hosts.best_raw(pool, Card("List", "items", ("front", "diag", "anti"))))),
        ("plan", ((kernel.FnRef("front"), kernel.FnRef("diag"), kernel.FnRef("anti"), small_pools[3]),),
         request("bounded", tuple((pool,) for pool in small_pools),
                 "50 bounded six-cell candidate pools with fixed front/diag/anti slots",
                 lambda assignments, inputs: hosts.plan_raw(inputs[0], Card("List", "items", ("front", "diag", "anti"))),
                 family_names={"front_probe": ("front",), "diag_probe": ("diag",),
                               "anti_probe": ("anti",)})),
    )
    for index, (definition, (name, samples, evidence)) in enumerate(zip(definitions(), plan)):
        if upto is not None and index >= upto:
            break
        if name in ("best_probe", "plan"):
            library.agent = "extra"
        library.write(definition)
        library.check(name)
        library.make_callable(name, samples)
        library.verify(name, evidence)
        library.account(name)
        library.promote(name, Contract(f"Exact {name} on the stated bounded family"))
        if name == "Candidates":
            canonical_raw = canonical_pool.fields[0]
            canonical_run = library.run("Candidates.make", (canonical_raw,))
            if canonical_run.outcome != Ok(canonical_pool):
                raise ValueError("canonical candidate constructor differs from its reference")
            library._fast_candidates = kernel.FastPath(
                "Candidates.make",
                lambda raw: library.run("Candidates._pack", (raw,)).outcome,
                lambda raw, steps=canonical_run.steps: steps,
                lambda raw, expected=canonical_raw: raw == expected,
            )
    if upto is None or upto >= len(plan):
        slots = tuple(kernel.FnRef(name) for name in ("front", "diag", "anti"))
        canonical_run = library.run("plan", (*slots, canonical_pool))
        if canonical_run.outcome != Ok(hosts.plan_raw(
                canonical_pool, Card("List", "items", ("front", "diag", "anti")))):
            raise ValueError("canonical plan fast path differs from kernel unfolding")
        exact_steps = canonical_run.steps
        fast_plan = kernel.FastPath(
            "plan", lambda *args: hosts.plan_raw(args[3], Card("List", "items", ("front", "diag", "anti"))),
            lambda *args: exact_steps,
            lambda *args: len(args) == 4 and args[:3] == slots and args[3] == canonical_pool,
        )
        library._fast_plan = fast_plan
    return library
