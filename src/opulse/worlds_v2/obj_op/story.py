"""Eight sequential object/operation inventions for idealized CRT scheduling."""

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.library import bounded
from opulse.atoms.spec import Contract, Definition, Edge, ObjectSpec, OperationSpec

from . import hosts
from .world import new_library


def var(name):
    return n.Var(name)


def call(name, *args):
    return n.Call(name, args)


def let(name, value, body):
    return n.Let(name, value, body)


def choose(condition, yes, no):
    return n.Case(((n.Test(condition), yes),), no)


def field(value, sort, arity, index):
    return call("record_field", value, n.Lit(sort), n.Lit(arity), n.Lit(index))


def sealed(name, value):
    candidate = call(f"{name}.make", field(value, name, 1, 0))
    return choose(call("is_defined", candidate), call("eq", candidate, value), n.Lit(False))


def all_items(items, predicate):
    remaining = var("remaining")
    return n.Rec("check_items", ("remaining",),
                 choose(call("is_empty", remaining), n.Lit(True),
                        choose(predicate(call("head", remaining)),
                               call("check_items", call("tail", remaining)), n.Lit(False))),
                 (items,), call("list_length", remaining))


def object_def(name, layer, base, valid, canon=None, dependencies=()):
    accessors = {"Cycle": ("residue", "period"), "Plan": ("cycles",),
                 "Window": ("plan", "lo", "hi", "compiled"),
                 "Blackout": ("window", "bands")}[name]
    spec = ObjectSpec(name, "refine", base=base, valid=valid, canon=canon,
                      sealed=True, interface=(f"{name}.make", *(f"{name}.{field}" for field in accessors)),
                      extra={"design_layer": layer})
    return Definition(name, "object", "invented", layer, tuple(sorted(set(dependencies) |
                      n.references(valid) | (n.references(canon) if canon else set()))), spec, None)


def operation(name, layer, inputs, output, body):
    spec = OperationSpec(name, "transform", tuple(Edge(sort, name=param) for param, sort in inputs),
                         Edge(output), f"Derived bounded {name} through counted kernel calls.",
                         extra={"input_names": [param for param, _ in inputs], "design_layer": layer})
    return Definition(name, "operation", "invented", layer, tuple(sorted(n.references(body))), spec, body)


def definitions():
    residue = field(var("x"), "CycleRaw", 2, 0)
    period = field(var("x"), "CycleRaw", 2, 1)
    positive = call("lt", n.Lit(0), period)
    yield object_def("Cycle", 1, "CycleRaw",
                     choose(call("is_defined", call("add", residue, n.Lit(0))),
                            choose(call("is_defined", positive), positive, n.Lit(False)), n.Lit(False)),
                     call("cycle_raw", call("mod", residue, period), period))

    left, right = var("a"), var("b")
    delta = call("sub", call("Cycle.residue", right), call("Cycle.residue", left))
    left_period, right_period = call("Cycle.period", left), call("Cycle.period", right)
    body = let("bezout", call("egcd", left_period, right_period),
               let("g", call("head", var("bezout")),
                   choose(call("eq", call("mod", delta, var("g")), n.Lit(0)),
                          let("quotient", call("div_floor", right_period, var("g")),
                              call("Cycle.make", call("cycle_raw",
                                   call("add", call("Cycle.residue", left),
                                        call("mul", left_period,
                                             call("mul_mod", call("div_floor", delta, var("g")),
                                                  call("head", call("tail", var("bezout"))),
                                                  var("quotient")))),
                                   call("mul", left_period, var("quotient"))))),
                          call("incompatible"))))
    yield operation("join", 2, (("a", "Cycle"), ("b", "Cycle")), "Cycle", body)

    cycles = field(var("x"), "PlanRaw", 1, 0)
    plan_valid = choose(call("is_defined", call("list_length", cycles)),
                        choose(call("le", n.Lit(1), call("list_length", cycles)),
                               choose(call("le", call("list_length", cycles), n.Lit(32)),
                                      all_items(cycles, lambda item: sealed("Cycle", item)), n.Lit(False)),
                               n.Lit(False)), n.Lit(False))
    yield object_def("Plan", 3, "PlanRaw", plan_valid, var("x"))
    yield operation("compile", 4, (("plan", "Plan"),), "Cycle",
                    call("fold", n.Lit(kernel.FnRef("join")),
                         call("head", call("Plan.cycles", var("plan"))),
                         call("tail", call("Plan.cycles", var("plan")))))

    raw_plan = field(var("x"), "WindowRaw", 4, 0)
    raw_lo = field(var("x"), "WindowRaw", 4, 1)
    raw_hi = field(var("x"), "WindowRaw", 4, 2)
    raw_compiled = field(var("x"), "WindowRaw", 4, 3)
    ordered = call("le", raw_lo, raw_hi)
    window_valid = choose(call("is_defined", raw_plan),
                          choose(sealed("Plan", raw_plan),
                                 choose(call("is_defined", ordered),
                                        choose(ordered, choose(sealed("Cycle", raw_compiled),
                                                               call("eq", call("compile", raw_plan), raw_compiled),
                                                               n.Lit(False)), n.Lit(False)), n.Lit(False)),
                                 n.Lit(False)), n.Lit(False))
    yield object_def("Window", 5, "WindowRaw", window_valid, var("x"),
                     dependencies=("compile",))
    window = var("w")
    first = call("mod_sub", call("Cycle.residue", call("Window.compiled", window)),
                 call("Window.lo", window), call("Cycle.period", call("Window.compiled", window)))
    yield operation("first_hit", 6, (("w", "Window"),), "int",
                    let("offset", first,
                        choose(call("offset_fits", call("Window.lo", window), var("offset"),
                                    call("Window.hi", window)),
                               call("add", call("Window.lo", window), var("offset")), call("no_hit"))))

    raw_window = field(var("x"), "BlackoutRaw", 2, 0)
    raw_bands = field(var("x"), "BlackoutRaw", 2, 1)
    band_item = var("item")
    band_start = field(band_item, "Band", 2, 0)
    band_end = field(band_item, "Band", 2, 1)
    band_ok = choose(call("is_defined", band_start),
                     choose(call("is_defined", call("band", band_start, band_end)),
                            call("eq", call("band", band_start, band_end), band_item), n.Lit(False)),
                     n.Lit(False))
    blackout_valid = choose(call("is_defined", raw_window),
                            choose(sealed("Window", raw_window),
                                   choose(call("is_defined", call("list_length", raw_bands)),
                                          choose(call("le", call("list_length", raw_bands), n.Lit(4096)),
                                                 all_items(raw_bands, lambda item: let("item", item, band_ok)),
                                                 n.Lit(False)), n.Lit(False)), n.Lit(False)), n.Lit(False))

    current = call("head", var("ordered"))
    new = var("new")
    new_lo, new_hi = call("band_lo", new), call("band_hi", new)
    cur_lo, cur_hi = call("band_lo", current), call("band_hi", current)
    minimum = choose(call("lt", new_lo, cur_lo), new_lo, cur_lo)
    maximum = choose(call("lt", new_hi, cur_hi), cur_hi, new_hi)
    insert = n.Rec("insert", ("ordered", "new"),
                   choose(call("is_empty", var("ordered")), call("cons", new, n.Lit(())),
                          choose(call("lt", new_hi, cur_lo),
                                 choose(call("eq", call("add", new_hi, n.Lit(1)), cur_lo),
                                        call("insert", call("tail", var("ordered")),
                                             call("band", minimum, maximum)),
                                        call("cons", new, var("ordered"))),
                                 choose(call("lt", cur_hi, new_lo),
                                        choose(call("eq", call("add", cur_hi, n.Lit(1)), new_lo),
                                               call("insert", call("tail", var("ordered")),
                                                    call("band", minimum, maximum)),
                                               call("cons", current,
                                                    call("insert", call("tail", var("ordered")), new))),
                                        call("insert", call("tail", var("ordered")),
                                             call("band", minimum, maximum))))),
                   (var("merged"), var("clipped")), call("list_length", var("ordered")))
    band_value = call("head", var("remaining"))
    start, end = call("band_lo", band_value), call("band_hi", band_value)
    lo, hi = call("Window.lo", raw_window), call("Window.hi", raw_window)
    clipped = call("band", choose(call("lt", start, lo), lo, start),
                   choose(call("lt", hi, end), hi, end))
    canonical_bands = n.Rec("normalize", ("remaining", "merged"),
                            choose(call("is_empty", var("remaining")), var("merged"),
                                   call("normalize", call("tail", var("remaining")),
                                        choose(call("le", start, hi),
                                               choose(call("le", lo, end),
                                                      let("clipped", clipped, insert), var("merged")),
                                               var("merged")))),
                            (raw_bands, n.Lit(())), call("list_length", var("remaining")))
    yield object_def("Blackout", 7, "BlackoutRaw", blackout_valid,
                     call("blackout_raw", raw_window, canonical_bands))
    masked = var("x")
    window = call("Blackout.window", masked)
    lo = call("Window.lo", window)
    hi = call("Window.hi", window)
    band = call("head", var("remaining"))
    gap = call("first_hit", call("Window.make", call("window_raw", call("Window.plan", window),
                                                   var("cursor"), hi,
                                                   call("Window.compiled", window))))
    loop = n.Rec("scan", ("remaining", "cursor"),
                 choose(call("eq", call("list_length", var("remaining")), n.Lit(0)),
                        choose(call("lt", hi, var("cursor")), call("no_hit"),
                               call("first_hit", call("Window.make", call("window_raw",
                                    call("Window.plan", window), var("cursor"), hi,
                                    call("Window.compiled", window))))),
                        choose(call("lt", hi, var("cursor")), call("no_hit"),
                               let("candidate", gap,
                                    choose(call("lt", var("candidate"), call("band_lo", band)),
                                          var("candidate"),
                                          choose(call("le", hi, call("band_hi", band)), call("no_hit"),
                                                 call("scan", call("tail", var("remaining")),
                                                      call("add", call("band_hi", band), n.Lit(1)))))))),
                 (call("Blackout.bands", masked), lo), call("list_length", var("remaining")))
    yield operation("clear_hit", 8, (("x", "Blackout"),), "int", loop)


def build_library():
    library = new_library()
    for definition in definitions():
        library.write(definition)
        library.check(definition.name)
        if definition.kind == "object":
            if definition.name == "Cycle":
                sample = (hosts.cycle_raw(0, 7),)
            else:
                cycle = library.run("Cycle.make", (hosts.cycle_raw(0, 7),)).outcome.value
                plan = library.run("Plan.make", (hosts.plan_raw((cycle,)),)).outcome.value if definition.layer > 3 else None
                if definition.name == "Plan":
                    sample = (hosts.plan_raw((cycle,)),)
                elif definition.name == "Window":
                    sample = (hosts.window_raw(plan, 0, 20, cycle),)
                else:
                    window = library.run("Window.make", (hosts.window_raw(plan, 0, 20, cycle),)).outcome.value
                    sample = (hosts.blackout_raw(window, ()),)
            reference = None
        else:
            cycle = library.run("Cycle.make", (hosts.cycle_raw(0, 7),)).outcome.value
            plan = (library.run("Plan.make", (hosts.plan_raw((cycle,)),)).outcome.value
                    if definition.layer >= 4 else None)
            window = (library.run("Window.make", (hosts.window_raw(plan, 0, 20, cycle),)).outcome.value
                      if definition.layer >= 6 else None)
            if definition.name == "join":
                sample = (cycle, cycle)
            elif definition.name == "compile":
                sample = (plan,)
            elif definition.name == "first_hit":
                sample = (window,)
            else:
                sample = (library.run("Blackout.make", (hosts.blackout_raw(window, ()),)).outcome.value,)
            reference = {"join": hosts.reference_join,
                         "compile": lambda value, expected=cycle: expected,
                         "first_hit": lambda value: 0,
                         "clear_hit": lambda value: 0}[definition.name]
        library.make_callable(definition.name, (sample,))
        request = bounded(tuple((item,) for item in sample), "bound up to 1 design witness per field")
        if definition.kind == "operation":
            from dataclasses import replace
            request = replace(request, reference=reference)
        library.verify(definition.name, request)
        library.account(definition.name)
        library.promote(definition.name, Contract(f"{definition.name}: checked on finite bounded samples"))
    return library
