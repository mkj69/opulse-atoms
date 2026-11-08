"""The twelve-layer, kernel-executed motif-cover construction."""

import importlib.util
from pathlib import Path

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.check import all_dependencies
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
from opulse.atoms.values import Bottom, Card

from . import hosts
from .world import new_library


def var(name):
    return n.Var(name)


def lit(value):
    return n.Lit(value)


def call(name, *args):
    return n.Call(name, args)


def test(name, *args):
    return n.Test(call(name, *args))


def branch(condition, yes, no):
    return n.Case(((condition, yes),), no)


def get(items, index):
    return call("list_get", items, index)


def length(items):
    return call("list_length", items)


def plus(left, right):
    return call("add", left, right)


def minus(left, right):
    return call("sub", left, right)


def op(name, params, body, output="unknown"):
    spec = OperationSpec(name, "transform", tuple(Edge("unknown", name=p) for p in params),
                         Edge(output), f"Kernel expansion of {name}.", extra={"input_names": list(params)})
    return definition(name, "operation", spec, body)


def comb(name, params, slots, body):
    return definition(name, "combinator", CombinatorSpec(name, params, slots, body), body)


def obs(name, reads, body):
    return definition(name, "observation", ObservationSpec(name, reads, body), body)


def definition(name, kind, spec, body):
    return Definition(name, kind, "invented", 1, (), spec, body)


def motif(value):
    return Card("Motif", "val", (tuple(value),))


def score(source, library):
    return Card("Score", "val", ((source, tuple(library)),))


def oracle():
    path = Path(__file__).resolve().parents[4] / "worlds/catalogue/depth/melody.py"
    spec = importlib.util.spec_from_file_location("melody_depth_oracle", path)
    module = importlib.util.module_from_spec(spec)
    import sys
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def reference_value(reference, value):
    if isinstance(value, Card) and value.sort == "Melody":
        return reference.melody(*value.fields)
    if isinstance(value, Card) and value.sort == "Motif":
        return reference.motif(*value.fields[0])
    if isinstance(value, Card) and value.sort == "Score":
        source, library = value.fields[0]
        return reference.score(reference_value(reference, source),
                               *(reference_value(reference, item) for item in library))
    if isinstance(value, tuple):
        return tuple(reference_value(reference, item) for item in value)
    return value


def kernel_value(value):
    if value is None:
        return "NONE"
    if type(value) is bool:
        return value
    if hasattr(value, "steps"):
        return motif(value.steps)
    if hasattr(value, "events"):
        return hosts.melody(*value.events)
    if hasattr(value, "library"):
        return score(kernel_value(value.melody), tuple(kernel_value(item) for item in value.library))
    if isinstance(value, tuple):
        return tuple(kernel_value(item) for item in value)
    return value


def reference_for(name):
    reference = oracle()
    def check(*arguments):
        try:
            args = tuple(reference_value(reference, arg) for arg in arguments
                         if not isinstance(arg, kernel.FnRef))
            if name in ("scan", "count_covers", "perform"):
                chosen = arguments[0].name
                implementation = (lambda *_: False) if chosen == "never_match" else getattr(reference, "realize" if name == "perform" else "occurs")
                args = (implementation, *args)
            if name in ("Motif", "Score"):
                if name == "Motif":
                    return kernel_value(reference.motif(*args[0]))
                return kernel_value(reference.score(args[0][0], *args[0][1]))
            return kernel_value(getattr(reference, name)(*args))
        except reference.Bottom as error:
            return Bottom(str(error))
    return check


def motif_steps(item):
    return call("Motif.base", item)


def score_parts(item):
    return call("Score.base", item)


def score_melody(item):
    return call("first", score_parts(item))


def score_library(item):
    return call("second", score_parts(item))


def definitions():
    steps = var("x")
    first_step = get(steps, lit(0))
    cursor = var("cursor")
    step = get(steps, cursor)
    valid_steps = n.Rec("check_steps", ("cursor",),
                        branch(test("eq", cursor, length(steps)), lit(True),
                               branch(n.And(test("le", lit(-36), call("first", step)),
                                            test("le", call("first", step), lit(36))),
                                      branch(n.And(test("le", lit(1), call("second", step)),
                                                   test("le", call("second", step), lit(4))),
                                             call("check_steps", plus(cursor, lit(1))), lit(False)), lit(False))),
                        (lit(0),), minus(length(steps), cursor))
    valid = n.Case(((test("lt", length(steps), lit(2)), lit(False)),
                    (test("lt", lit(8), length(steps)), lit(False))),
                   branch(test("eq", call("first", first_step), lit(0)), valid_steps, lit(False)))
    yield definition("Motif", "object", ObjectSpec("Motif", "refine", base="List", valid=valid), None)

    melody_events = call("events", var("m"))
    pattern_steps = motif_steps(var("p"))
    index = var("i")
    position = var("j")
    event = get(melody_events, plus(index, position))
    pattern = get(pattern_steps, position)
    root = call("first", get(melody_events, index))
    matches = n.Rec("compare", ("j",),
                    branch(test("eq", position, length(pattern_steps)), lit(True),
                           branch(test("eq", event, call("pair", plus(root, call("first", pattern)),
                                                              call("second", pattern))),
                                  call("compare", plus(position, lit(1))), lit(False))),
                    (lit(0),), minus(length(pattern_steps), position))
    occurs = branch(test("lt", index, lit(0)), lit(Bottom("range")),
                    branch(test("lt", lit(63), index), lit(Bottom("range")),
                           branch(test("lt", length(melody_events), plus(index, length(pattern_steps))),
                                  lit(False), matches)))
    yield op("occurs", ("m", "p", "i"), occurs, "bool")

    scan_index = var("start")
    scan_limit = minus(length(call("events", var("m"))), length(motif_steps(var("p"))))
    scan_body = branch(test("lt", scan_limit, scan_index), lit(()),
                       n.Let("tail", call("scan_local", plus(scan_index, lit(1))),
                             branch(test("match", var("m"), var("p"), scan_index),
                                    call("list_cons", scan_index, var("tail")), var("tail"))))
    yield comb("scan", ("match", "m", "p"), ("match",),
               n.Rec("scan_local", ("start",), scan_body, (lit(0),),
                     plus(minus(scan_limit, scan_index), lit(1))))

    notes = var("events")
    cursor = var("cursor")
    left = get(notes, cursor)
    right = get(notes, plus(cursor, lit(1)))
    intervals_body = branch(test("le", length(notes), plus(cursor, lit(1))), lit(()),
                            call("list_cons", call("pair", minus(call("first", right), call("first", left)),
                                                         call("second", left)),
                                 call("interval_local", plus(cursor, lit(1)))))
    yield obs("intervals", ("events",), n.Rec("interval_local", ("cursor",), intervals_body,
                                            (lit(0),), minus(length(notes), cursor)))

    root_value = var("root")
    offset_note = get(motif_steps(var("p")), cursor)
    pitch = plus(root_value, call("first", offset_note))
    emitted = branch(test("lt", pitch, lit(48)), lit(Bottom("pitch")),
                     branch(test("lt", lit(84), pitch), lit(Bottom("pitch")),
                            call("pair", pitch, call("second", offset_note))))
    realize_body = n.Rec("realize_local", ("cursor",),
                         branch(test("eq", cursor, length(motif_steps(var("p")))), lit(()),
                                call("list_cons", emitted, call("realize_local", plus(cursor, lit(1))))),
                         (lit(0),), minus(length(motif_steps(var("p"))), cursor))
    realize = branch(test("lt", root_value, lit(48)), lit(Bottom("pitch")),
                     branch(test("lt", lit(84), root_value), lit(Bottom("range")),
                            call("Melody.make", realize_body)))
    yield op("realize", ("p", "root"), realize, "Melody")

    segment = call("events", call("slice_events", var("m"), var("start"), var("length")))
    base_pitch = call("first", get(segment, lit(0)))
    normalized = n.Rec("normalize_local", ("cursor",),
                       branch(test("eq", cursor, length(segment)), lit(()),
                              call("list_cons", call("pair", minus(call("first", get(segment, cursor)), base_pitch),
                                                           call("second", get(segment, cursor))),
                                   call("normalize_local", plus(cursor, lit(1))))),
                       (lit(0),), minus(length(segment), cursor))
    motif_at = branch(test("lt", var("length"), lit(2)), lit(Bottom("motif_length")),
                      branch(test("lt", lit(8), var("length")), lit(Bottom("motif_length")),
                             n.Let("segment", segment, call("Motif.make", normalized))))
    yield op("motif_at", ("m", "start", "length"), motif_at, "Motif")

    parts = var("x")
    library = call("second", parts)
    score_cursor = var("cursor")
    score_item = get(library, score_cursor)
    valid_members = n.Rec("check_library", ("cursor",),
                          branch(test("eq", score_cursor, length(library)), lit(True),
                                 branch(test("eq", score_item,
                                             call("Motif.make", call("Motif.base", score_item))),
                                        call("check_library", plus(score_cursor, lit(1))), lit(False))),
                          (lit(0),), minus(length(library), score_cursor))
    valid_score = branch(test("eq", length(parts), lit(2)),
                         branch(test("le", lit(1), length(call("events", call("first", parts)))),
                                branch(test("lt", length(library), lit(1)), lit(False),
                                       branch(test("lt", lit(12), length(library)), lit(False),
                                              branch(test("list_unique", library), valid_members, lit(False)))),
                                lit(False)), lit(False))
    yield definition("Score", "object", ObjectSpec("Score", "refine", base="List", valid=valid_score), None)

    case = var("s")
    score_notes = call("events", score_melody(case))
    library = score_library(case)
    start = var("start")
    option = var("option")
    current = get(library, option)
    extent = length(motif_steps(current))
    found = call("list_contains", get(var("hits"), option), start)
    count_options = n.Rec("options", ("option",),
                          branch(test("eq", option, length(library)), lit(0),
                                 plus(branch(n.Test(found), call("count_suffix", plus(start, extent)), lit(0)),
                                      call("options", plus(option, lit(1))))),
                          (lit(0),), minus(length(library), option))
    count_body = branch(test("eq", start, length(score_notes)), lit(1), count_options)
    scans = n.Rec("scan_lib", ("option",),
                  branch(test("eq", option, length(library)), lit(()),
                         call("list_cons", call("scan", var("match"), score_melody(case), current),
                              call("scan_lib", plus(option, lit(1))))),
                  (lit(0),), minus(length(library), option))
    count_covers = n.Let("hits", scans,
                         n.Rec("count_suffix", ("start",), count_body, (lit(0),),
                               minus(length(score_notes), start), memo=True))
    yield comb("count_covers", ("match", "s"), ("match",), count_covers)

    yield obs("cover_count", ("score_view",),
              call("count_covers", lit(kernel.FnRef("occurs")), var("score_view")))

    start = var("start")
    option = var("option")
    current = get(library, option)
    extent = length(motif_steps(current))
    candidate = n.Let("suffix", call("best_suffix", plus(start, extent)),
                      branch(test("eq", var("suffix"), lit("NONE")), lit("NONE"),
                             call("list_cons", call("pair", option, call("first", get(score_notes, start))),
                                  var("suffix"))))
    choose = n.Rec("choose", ("option", "best"),
                   branch(test("eq", option, length(library)), var("best"),
                          n.Let("next", branch(test("occurs", score_melody(case), current, start),
                                               candidate, lit("NONE")),
                                call("choose", plus(option, lit(1)),
                                     branch(test("eq", var("next"), lit("NONE")), var("best"),
                                            branch(test("eq", var("best"), lit("NONE")), var("next"),
                                                   branch(test("lt", length(var("next")), length(var("best"))), var("next"),
                                                          branch(test("eq", length(var("next")), length(var("best"))),
                                                                 branch(test("list_lex_lt", var("next"), var("best")),
                                                                        var("next"), var("best")), var("best")))))))),
                   (lit(0), lit("NONE")), minus(length(library), option))
    best_body = branch(test("eq", start, length(score_notes)), lit(()), choose)
    best = n.Rec("best_suffix", ("start",), best_body, (lit(0),),
                 minus(length(score_notes), start), memo=True)
    yield op("best_cover", ("s",),
             branch(test("eq", call("count_covers", lit(kernel.FnRef("occurs")), case), lit(0)),
                    lit(Bottom("no_cover")), best), "List")

    plan = var("plan")
    step = get(plan, cursor)
    index = call("first", step)
    part = call("emit", get(library, index), call("second", step))
    perform_body = n.Rec("perform_local", ("cursor", "rendered"),
                         branch(test("eq", cursor, length(plan)), var("rendered"),
                                call("perform_local", plus(cursor, lit(1)),
                                     call("concat", var("rendered"), part))),
                         (lit(1), call("emit", get(library, call("first", get(plan, lit(0)))),
                                         call("second", get(plan, lit(0))))),
                         minus(length(plan), cursor))
    yield comb("perform", ("emit", "s", "plan"), ("emit",),
               branch(test("eq", length(plan), lit(0)), lit(Bottom("plan")),
                      n.Let("rendered", perform_body,
                            branch(test("eq", var("rendered"), score_melody(case)), var("rendered"),
                                   lit(Bottom("mismatch"))))))

    checked = call("perform", lit(kernel.FnRef("realize")), var("score_view"),
                   call("best_cover", var("score_view")))
    yield obs("cover_report", ("score_view", "beats"),
              n.Let("count", call("cover_count", var("score_view")),
                    n.Let("plan", branch(test("eq", var("count"), lit(0)), lit("NONE"),
                                         call("best_cover", var("score_view"))),
                          n.Let("checked", branch(test("eq", var("count"), lit(0)), lit("NONE"), checked),
                                call("list_cons", var("count"),
                                     call("list_cons", var("plan"),
                                          call("list_cons", var("beats"), lit(()))))))))


NAMES = ("Motif", "occurs", "scan", "intervals", "realize", "motif_at", "Score",
         "count_covers", "cover_count", "best_cover", "perform", "cover_report")


def evidence(name):
    motifs = [motif(((0, 1), (offset, 1))) for offset in range(-3, 4)]
    sources = [hosts.melody((60, 1), (60 + index % 7, 1), (61 + index % 7, 2)) for index in range(64)]
    if name == "Motif":
        domain = [(((0, 1), (offset, duration)),) for offset in range(-3, 4) for duration in range(1, 5)]
        domain += [(((0, 1), (offset, duration), (2, 2)),)
                   for offset in range(-3, 4) for duration in range(1, 5)]
    elif name == "Score":
        domain = [((sources[index], (motifs[index % 7], motifs[(index + 1) % 7])),)
                  for index in range(64)]
    elif name == "occurs":
        domain = [(sources[index], motifs[index % 7], start)
                  for index in range(64) for start in (0, 1, 2)]
    elif name == "scan":
        domain = [(sources[index], motifs[index % 7]) for index in range(64)]
    elif name == "intervals":
        domain = [(source,) for source in sources]
    elif name == "realize":
        domain = [(motifs[index % 7], root) for index in range(7) for root in range(56, 65)]
    elif name == "motif_at":
        domain = [(sources[index], 0, 2) for index in range(64)]
    else:
        cases = [score(source, (motifs[index % 7], motifs[(index + 1) % 7]))
                 for index, source in enumerate(sources)]
        if name in ("count_covers", "perform"):
            domain = [(case,) if name == "count_covers" else (case, ((0, 60),)) for case in cases]
        else:
            domain = [(case,) for case in cases]
    domain_labels = {
        "Motif": "two- and three-step lists with first offset zero, second offset -3..3 and duration 1..4",
        "Score": "three-event melodies paired with two adjacent two-step motifs, indexed modulo seven",
        "occurs": "generated three-event melodies, indexed two-step motifs, starts 0, 1 and 2",
        "scan": "generated three-event melodies paired with indexed two-step motifs",
        "intervals": "generated three-event melodies",
        "realize": "seven two-step motifs and roots 56..64",
        "motif_at": "generated three-event melodies sliced at start 0 for length 2",
        "count_covers": "generated three-event scores with two adjacent two-step motifs",
        "cover_count": "generated three-event scores with two adjacent two-step motifs",
        "best_cover": "generated three-event scores with two adjacent two-step motifs",
        "perform": "generated three-event scores with two adjacent two-step motifs and fixed plan ((0,60),)",
        "cover_report": "generated three-event scores with two adjacent two-step motifs",
    }
    slot_family = (("occurs", "never_match") if name in ("scan", "count_covers") else
                   ("realize", "emit_fail") if name == "perform" else ())
    scope = {"domain": f"{len(domain)} listed records: {domain_labels[name]}",
             "description": f"{len(domain)} explicit cases; operation slots: "
                            f"{', '.join(slot_family) if slot_family else 'none'}"
                            + ("; non-interference within consecutive batches of at most eight states"
                               if name in ("intervals", "cover_count", "cover_report") else ""),
             "size": len(domain)}
    if name in ("scan", "count_covers", "perform"):
        scope["fixed_ops"] = []
        scope["op_family"] = list(slot_family)
        def reference(assignment, inputs):
            return reference_for(name)(kernel.FnRef(next(iter(assignment.values()))), *inputs)
    else:
        reference = reference_for(name)
    states = [row[0] for row in domain]
    histories = [states[index:index + 8] for index in range(0, len(states), 8)]
    return VerifyRequest("bounded", domain, scope, reference=reference,
                         extra={"states": histories, "op_family": scope.get("op_family", ())})


def build_library(limit=None):
    lib = new_library()
    helpers = (op("never_match", ("m", "p", "i"), lit(False), "bool"),
               op("emit_fail", ("p", "root"), lit(Bottom("emit_result")), "Melody"))
    for helper in helpers:
        from dataclasses import replace
        helper = replace(helper, depends_on=())
        lib.write(helper)
        lib.check(helper.name)
        domain = ([(hosts.melody((60, 1), (61, 1)), motif(((0, 1), (1, 1))), index)
                   for index in range(64)] if helper.name == "never_match" else
                  [(motif(((0, 1), (offset, 1))), root)
                   for offset in range(-3, 4) for root in range(56, 65)])
        request = VerifyRequest("bounded", domain,
                                {"domain": f"{len(domain)} explicit helper inputs, bound 64",
                                 "size": len(domain)},
                                reference=lambda *_, name=helper.name:
                                False if name == "never_match" else Bottom("emit_result"))
        lib.make_callable(helper.name, domain[:1])
        lib.verify(helper.name, request)
        lib.account(helper.name)
        lib.promote(helper.name, Contract("Typed negative control for operation-slot evidence."))
    for index, item in enumerate(definitions()):
        if limit is not None and index >= limit:
            break
        dependencies = (tuple(sorted(n.references(item.body) - set(getattr(item.spec, "op_params", ()))))
                        if item.body else tuple(sorted(n.references(item.spec.valid))) if item.kind == "object" else ())
        from dataclasses import replace
        layer_dependencies = (all_dependencies(item) if item.body else set(dependencies))
        lower = [lib.get(dep.split(".", 1)[0]).layer for dep in layer_dependencies
                 if dep.split(".", 1)[0] in lib.definitions]
        item = replace(item, layer=1 + max(lower, default=0), depends_on=dependencies)
        lib.write(item)
        lib.check(item.name)
        request = evidence(item.name)
        sample = request.domain[:1]
        if item.kind == "combinator":
            sample = [(kernel.FnRef(request.scope["op_family"][0]), *sample[0])]
        lib.make_callable(item.name, sample)
        lib.verify(item.name, request)
        lib.account(item.name)
        lib.promote(item.name, Contract(f"Exact kernel implementation of {item.name} on the verified family."))
    return lib
