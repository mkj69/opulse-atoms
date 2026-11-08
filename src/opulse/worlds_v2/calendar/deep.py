"""Measured kernel definitions for the finite Gregorian calendar tower."""

from functools import cache

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
    compute_layer,
)
from opulse.atoms.values import Bottom, Card, boolean

from . import hosts
from .world import new_library


def v(name):
    return n.Var(name)


def c(name, *args):
    return n.Call(name, args)


def lit(value):
    return n.Lit(value)


def test(name, *args):
    return n.Test(c(name, *args))


def choose(condition, yes, no):
    return n.Case(((condition, yes),), no)


def op(name, args, output, body, rule):
    spec = OperationSpec(name, "transform", tuple(Edge(sort, name=param) for param, sort in args),
                         Edge(output), rule, extra={"input_names": [param for param, _ in args]})
    return spec, body


def entry(name, kind, spec, body, previous, *, dependencies=None):
    provisional = Definition(name, kind, "invented", 0, tuple(dependencies or ()), spec, body)
    dependencies = ((all_dependencies(provisional) - set(spec.op_params)
                     if kind == "combinator" else all_dependencies(provisional))
                    if body is not None else set(dependencies or ()))
    dependencies = tuple(sorted(dependencies))
    layer = compute_layer(dependencies, lambda dep: previous[dep].layer if dep in previous else
                          previous[dep.split(".", 1)[0]].layer if dep.split(".", 1)[0] in previous else 0)
    return Definition(name, kind, "invented", layer, dependencies, spec, body)


def span_value(year, month):
    start = hosts.to_card(year, month, 1)
    end = hosts.to_card(year, month, hosts.month_length(year, month))
    return Card("MonthSpan", "val", (hosts.pair(start, end),))


def holiday_scope():
    from datetime import date

    result = []
    for year in range(2000, 2010):
        january = date(year, 1, 1)
        third_monday = 1 + (7 - january.weekday()) % 7 + 14
        may_last = 31 - date(year, 5, 31).weekday()
        for month, day in ((1, 1), (1, third_monday), (5, may_last), (7, 4), (2, 1)):
            result.append((hosts.to_card(year, month, day),))
    return tuple(result)


def definitions():
    result = []
    known = {}

    def add(name, kind, spec, body=None, dependencies=None):
        item = entry(name, kind, spec, body, known, dependencies=dependencies)
        result.append(item)
        known[name] = item

    leap_valid = n.And(test("eq", c("month_of", v("x")), lit(2)),
                       test("eq", c("day_of", v("x")), lit(29)))
    add("LeapDay", "object", ObjectSpec("LeapDay", "refine", base="date", valid=choose(
        leap_valid, lit(boolean(True)), lit(boolean(False))), sealed=True,
        interface=("LeapDay.make", "LeapDay.base")),
        dependencies=("month_of", "day_of", "eq"))

    spec, body = op("week_later", (("date", "date"),), "date",
                    c("repeat", lit(kernel.FnRef("next_date")), v("date"), lit(7)),
                    "Walk exactly seven Gregorian successors.")
    add("week_later", "operation", spec, body)

    body = c("lt", c("weekday", v("s")), lit(5))
    add("workday", "observation", ObservationSpec("workday", ("weekday",), body), body)

    for weekday in range(7):
        name = f"weekday_is_{weekday}"
        spec, body = op(name, (("date", "date"),), "bool",
                        c("eq", c("weekday", v("date")), lit(weekday)),
                        "Match a weekday using the granted weekday probe.")
        add(name, "operation", spec, body)

    search_body = n.Rec("seek_local", ("current", "remaining"),
                        choose(test("le", v("remaining"), lit(0)), lit(Bottom("not_found")),
                               n.Let("following", c("step", v("current")),
                                     choose(test("accept", v("following")), v("following"),
                                            c("seek_local", v("following"), c("subtract", v("remaining"), lit(1)))))),
                        (v("date"), v("limit")), v("remaining"))
    body = choose(n.Or(test("lt", v("limit"), lit(1)), test("lt", lit(7), v("limit"))),
                  lit(Bottom("seek_limit")), search_body)
    add("seek", "combinator", CombinatorSpec("seek", ("step", "accept", "date", "limit"),
                                             ("step", "accept"), body), body)

    start = c("first", v("x"))
    end = c("second", v("x"))
    same_month = n.And(test("eq", c("year_of", start), c("year_of", end)),
                       test("eq", c("month_of", start), c("month_of", end)))
    end_valid = n.Or(test("eq", end, lit(hosts.to_card(2099, 12, 31))),
                     n.Not(test("eq", c("month_of", c("next_date", end)),
                                    c("month_of", start))))
    valid = choose(n.And(test("eq", c("day_of", start), lit(1)), same_month),
                   choose(end_valid, lit(boolean(True)), lit(boolean(False))), lit(boolean(False)))
    add("MonthSpan", "object", ObjectSpec("MonthSpan", "refine", base="pair", valid=valid,
        sealed=True, interface=("MonthSpan.make", "MonthSpan.base")),
        dependencies=("first", "second", "year_of", "month_of", "day_of", "next_date", "eq"))

    month_walk = n.Rec("walk_month", ("cursor",),
                       choose(test("eq", v("cursor"), lit(hosts.to_card(2099, 12, 31))),
                              c("MonthSpan.make", c("pair", v("start"), v("cursor"))),
                              n.Let("following", c("next_date", v("cursor")),
                                    choose(test("eq", c("month_of", v("following")), v("month")),
                                           c("walk_month", v("following")),
                                           c("MonthSpan.make", c("pair", v("start"), v("cursor")))))),
                       (v("start"),), c("subtract", lit(32), c("day_of", v("cursor"))))
    spec, body = op("month_span", (("year", "int"), ("month", "int")), "MonthSpan",
                    n.Let("start", c("date", v("year"), v("month"), lit(1)), month_walk),
                    "Walk to the inclusive end and construct a validated MonthSpan.")
    add("month_span", "operation", spec, body)

    spec, body = op("month_end", (("year", "int"), ("month", "int")), "date",
                    c("second", c("MonthSpan.base", c("month_span", v("year"), v("month")))),
                    "Return the checked end of the month span.")
    add("month_end", "operation", spec, body)

    body = c("repeat", lit(kernel.FnRef("next_date")), v("date"), lit(1))
    spec, body = op("next_via_repeat", (("date", "date"),), "date", body,
                    "Advance one date through the given bounded repeat.")
    add("next_via_repeat", "operation", spec, body)

    body = c("add", v("total"), c("indicator", c("workday", v("date"))))
    spec, body = op("count_workday", (("total", "int"), ("date", "date")), "int", body,
                    "Add the observed workday indicator.")
    add("count_workday", "operation", spec, body)

    spec, body = op("count_every_day", (("total", "int"), ("date", "date")), "int",
                    c("add", v("total"), lit(1)), "Increment for every visited date.")
    add("count_every_day", "operation", spec, body)

    fold_loop = n.Rec("fold_month", ("cursor", "result"),
                      n.Let("updated", c("accumulate", v("result"), v("cursor")),
                            choose(test("eq", v("cursor"), v("end")), v("updated"),
                                   c("fold_month", c("step", v("cursor")), v("updated")))),
                      (v("start"), v("initial")), c("subtract", lit(32), c("day_of", v("cursor"))))
    body = n.Let("base", c("MonthSpan.base", v("span")),
                 n.Let("start", c("first", v("base")),
                       n.Let("end", c("second", v("base")), fold_loop)))
    add("month_fold", "combinator", CombinatorSpec(
        "month_fold", ("step", "accumulate", "span", "initial"), ("step", "accumulate"), body), body)

    spec, body = op("weekday_count", (("year", "int"), ("month", "int")), "int",
                    c("month_fold", lit(kernel.FnRef("next_date")), lit(kernel.FnRef("count_workday")),
                      c("month_span", v("year"), v("month")), lit(0)),
                    "Count Monday through Friday in the inclusive month.")
    add("weekday_count", "operation", spec, body)

    matches = tuple((test("eq", v("target_weekday"), lit(weekday)),
                     c("seek", lit(kernel.FnRef("next_date")),
                       lit(kernel.FnRef(f"weekday_is_{weekday}")), v("start"), lit(6)))
                    for weekday in range(7))
    first_match = choose(test("eq", c("weekday", v("start")), v("target_weekday")),
                         v("start"), n.Case(matches, lit(Bottom("invalid_nth"))))
    nth = n.Rec("advance_week", ("cursor", "remaining"),
                choose(test("eq", v("remaining"), lit(1)), v("cursor"),
                       choose(test("lt", c("day_of", v("end")),
                                   c("add", c("day_of", v("cursor")), lit(7))), lit(Bottom("no_occurrence")),
                              c("advance_week", c("week_later", v("cursor")),
                                c("subtract", v("remaining"), lit(1))))),
                (v("first_match"), v("ordinal")), v("remaining"))
    body = choose(n.Or(test("lt", v("ordinal"), lit(1)), test("lt", lit(5), v("ordinal"))),
                  lit(Bottom("invalid_nth")),
                  choose(n.Or(test("lt", v("target_weekday"), lit(0)), test("lt", lit(6), v("target_weekday"))),
                         lit(Bottom("invalid_nth")),
                         n.Let("span", c("MonthSpan.base", c("month_span", v("year"), v("month"))),
                               n.Let("start", c("first", v("span")),
                                     n.Let("end", c("second", v("span")),
                                           n.Let("first_match", first_match, nth))))))
    spec, body = op("nth_weekday", (("year", "int"), ("month", "int"), ("ordinal", "int"),
                                    ("target_weekday", "int")), "date", body,
                    "Find the requested weekday occurrence or fail if absent.")
    add("nth_weekday", "operation", spec, body)
    from .deep_extra import extra_definitions

    result.extend(extra_definitions(known))
    return result


def build_library(limit=None):
    library = new_library()
    for definition in definitions()[:limit]:
        library.write(definition)
        library.check(definition.name)
        sample = (hosts.to_card(2000, 2, 29),)
        if definition.kind == "object":
            if definition.name == "MonthSpan":
                sample = (hosts.pair(hosts.to_card(2000, 2, 1), hosts.to_card(2000, 2, 29)),)
            elif definition.name == "Holiday":
                sample = (hosts.to_card(2032, 11, 25),)
        elif definition.name in ("month_span", "month_end", "weekday_count", "settle"):
            sample = (2032, 2)
        elif definition.name == "observed_fixed":
            sample = (2032, 7, 4)
        elif definition.name == "nth_weekday":
            sample = (2032, 11, 4, 3)
        elif definition.name == "keep_open":
            sample = (Card("maybe_date", "none"), hosts.to_card(2032, 11, 25))
        elif definition.name == "month_fold":
            sample = (kernel.FnRef("next_date"), kernel.FnRef("count_workday"), span_value(2032, 2), 0)
        elif definition.name == "seek":
            sample = (kernel.FnRef("next_date"), kernel.FnRef("workday"), hosts.to_card(2000, 3, 7), 3)
        elif definition.name in ("count_workday", "count_every_day"):
            sample = (0, hosts.to_card(2000, 2, 29))
        library.make_callable(definition.name, (sample,))
        if definition.kind == "object":
            domain = tuple((hosts.to_card(year, 2, day),) for year in range(2000, 2100)
                           for day in (28, 29) if not isinstance(hosts.to_card(year, 2, day), Bottom)) if definition.name == "LeapDay" else tuple(
                (hosts.pair(hosts.to_card(year, month, 1), hosts.to_card(year, month, day)),)
                for year in range(2000, 2010) for month in range(1, 13)
                for day in (hosts.month_length(year, month), max(1, hosts.month_length(year, month) - 1))) if definition.name == "MonthSpan" else holiday_scope()
        elif definition.kind == "observation":
            domain = (holiday_scope()
                      if definition.name == "open_day" else
                      tuple((date,) for date in hosts.dates()[::365]))
        elif definition.name in ("month_span", "month_end", "weekday_count", "settle"):
            domain = (tuple((year, 2) for year in range(2000, 2050))
                      if definition.name == "settle" else
                      tuple((year, month) for year in range(2000, 2005) for month in range(1, 13)))
        elif definition.name == "observed_fixed":
            domain = tuple((year, month, day) for year in range(2001, 2021)
                           for month, day in ((1, 1), (7, 4), (12, 25)))
        elif definition.name == "nth_weekday":
            domain = tuple((year, month, ordinal, weekday) for year in range(2000, 2003)
                           for month in (2, 5, 11) for ordinal in (1, 3, 4, 5) for weekday in (0, 3))
        elif definition.name == "month_fold":
            domain = tuple((span_value(year, month), 0) for year in range(2000, 2005)
                           for month in range(1, 13))
        elif definition.name == "seek":
            domain = tuple((date, limit) for date in hosts.dates()[::151] for limit in (2, 7))
        elif definition.name in ("count_workday", "count_every_day"):
            domain = tuple((0, date) for date in hosts.dates()[::365])
        elif definition.name == "keep_open":
            domain = tuple((Card("maybe_date", "none"), date) for date in hosts.dates()[::365])
        else:
            domain = (holiday_scope()
                      if definition.name in ("holiday_match", "Holiday") else
                      tuple((date,) for date in hosts.dates()[::365]))
        descriptions = {
            "LeapDay": "valid February 28 and February 29 dates, 2000..2099",
            "MonthSpan": "2000..2009, 12 months per year, each last and preceding date paired with the first",
            "Holiday": "2000..2009: Jan 1, Jan third Monday, May last Monday, Jul 4, Feb 1",
            "open_day": "2000..2009: Jan 1, Jan third Monday, May last Monday, Jul 4, Feb 1",
            "holiday_match": "2000..2009: Jan 1, Jan third Monday, May last Monday, Jul 4, Feb 1",
            "settle": "February of every year 2000..2049",
            "observed_fixed": "2001..2020, each fixed Jan 1, Jul 4, and Dec 25",
            "nth_weekday": "2000..2002, months 2/5/11, ordinals 1/3/4/5, weekdays 0/3",
            "month_span": "all 12 months in each year 2000..2004",
            "month_end": "all 12 months in each year 2000..2004",
            "month_fold": "all 12 months in each year 2000..2004, two step and two accumulator slots",
            "weekday_count": "all 12 months in each year 2000..2004",
            "seek": "each stride-151 date in 2000..2099, limits 2 and 7, two step and eight accept slots",
        }
        description = descriptions.get(definition.name, "every stride-365 date in 2000..2099"
                                       if definition.name not in ("count_workday", "count_every_day", "keep_open")
                                       else "every stride-365 date in 2000..2099 with initial zero or none")
        scope = {"domain": f"bounded: {len(domain)} tuples; {description}", "size": len(domain)}
        if definition.kind == "combinator":
            family = ({"step": ["next_date", "next_via_repeat"],
                       "accumulate": ["count_workday", "count_every_day"]}
                      if definition.name == "month_fold" else
                      {"step": ["next_date", "week_later"],
                       "accept": ["workday", *(f"weekday_is_{weekday}" for weekday in range(7))]})
            scope["op_family"] = family
            request = VerifyRequest("bounded", domain, scope, extra={"op_family": family})
        elif definition.kind == "observation":
            states = [args[0] for args in domain]
            request = VerifyRequest("bounded", domain, scope,
                                    reference=(lambda date: boolean(hosts.weekday(date) < 5))
                                    if definition.name == "workday" else reference_for("open_day"),
                                    extra={"states": tuple(states[index:index + 7]
                                                           for index in range(0, len(states), 7))})
        elif definition.kind == "object":
            request = VerifyRequest("bounded", domain, scope)
        else:
            reference = reference_for(definition.name)
            request = VerifyRequest("bounded", domain, scope, reference=reference)
        library.verify(definition.name, request)
        library.account(definition.name)
        library.promote(definition.name, Contract(definition.spec.rule if definition.kind == "operation" else
                                                  "Bounded Gregorian kernel definition."))
    return library


@cache
def reference_for(name):
    from importlib.util import module_from_spec, spec_from_file_location
    from pathlib import Path

    source = Path(__file__).resolve().parents[4] / "worlds/catalogue/depth/calendar.py"
    spec = spec_from_file_location("calendar_depth_reference", source)
    module = module_from_spec(spec)
    import sys
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    def convert(value):
        if isinstance(value, Card) and value.sort == "date":
            return module.Date(*value.fields)
        return value

    if name in ("week_later", "next_via_repeat"):
        reference = module.week_later if name == "week_later" else module.next_day
    elif name == "month_span":
        reference = module.month_span
    elif name == "month_end":
        reference = module.month_end
    elif name == "weekday_count":
        reference = module.weekday_count
    elif name == "nth_weekday":
        reference = module.nth_weekday
    elif name == "observed_fixed":
        reference = lambda year, month, day: module._observed(module.Date(year, month, day))
    elif name == "holiday_match":
        reference = module.is_holiday
    elif name == "open_day":
        reference = module.open_day
    elif name == "keep_open":
        reference = lambda latest, date: hosts.some(hosts.to_card(date.year, date.month, date.day)) if module.open_day(date) else latest
    elif name == "settle":
        reference = module.settle
    elif name == "count_workday":
        reference = lambda total, date: total + int(module.workday(date))
    elif name == "count_every_day":
        reference = lambda total, date: total + 1
    elif name.startswith("weekday_is_"):
        reference = lambda date: module.weekday(date) == int(name.rsplit("_", 1)[1])
    else:
        raise KeyError(name)

    def checked(*args):
        try:
            result = reference(*(convert(arg) for arg in args))
        except module.DomainError as error:
            return Bottom(str(error))
        if isinstance(result, module.Date):
            return hosts.to_card(result.year, result.month, result.day)
        if isinstance(result, module.MonthSpan):
            return span_value(result.start.year, result.start.month)
        if result is None:
            return boolean(False)
        if isinstance(result, bool):
            return boolean(result)
        return result

    return checked
