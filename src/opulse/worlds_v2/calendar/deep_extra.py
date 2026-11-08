"""Holiday and settlement nodes built from public Gregorian definitions."""

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.spec import ObjectSpec, ObservationSpec
from opulse.atoms.values import Card, boolean

from .deep import c, choose, entry, lit, op, test, v


def extra_definitions(known):
    result = []

    def add(name, kind, spec, body=None, dependencies=None):
        definition = entry(name, kind, spec, body, known, dependencies=dependencies)
        known[name] = definition
        result.append(definition)

    base = c("date", v("year"), v("month"), v("day"))
    prior = choose(test("eq", v("day"), lit(1)),
                   choose(test("eq", v("month"), lit(1)),
                          choose(test("eq", v("year"), lit(2000)), lit(boolean(False)),
                                 c("month_end", c("subtract", v("year"), lit(1)), lit(12))),
                          c("month_end", v("year"), c("subtract", v("month"), lit(1)))),
                   c("date", v("year"), v("month"), c("subtract", v("day"), lit(1))))
    body = n.Let("base", base,
                 choose(test("eq", c("weekday", v("base")), lit(5)), prior,
                        choose(test("eq", c("weekday", v("base")), lit(6)),
                               c("next_date", v("base")), v("base"))))
    spec, body = op("observed_fixed", (("year", "int"), ("month", "int"), ("day", "int")),
                    "date", body, "Observe fixed dates, moving weekends into range.")
    add("observed_fixed", "operation", spec, body)

    year, date = v("year"), v("date")
    fixed = [test("eq", date, c("observed_fixed", year, lit(month), lit(day)))
             for month, day in ((1, 1), (7, 4), (12, 25))]
    next_new_year = n.And(n.Not(test("eq", year, lit(2099))),
                          test("eq", date, c("observed_fixed", c("add", year, lit(1)), lit(1), lit(1))))
    floating = [test("eq", date, c("nth_weekday", year, lit(month), lit(ordinal), lit(weekday)))
                for month, ordinal, weekday in ((1, 3, 0), (11, 4, 3))]
    may_fourth = c("nth_weekday", year, lit(5), lit(4), lit(0))
    may_last = choose(test("le", c("add", c("day_of", may_fourth), lit(7)), lit(31)),
                      c("week_later", may_fourth), may_fourth)
    month = c("month_of", date)
    body = n.Case(((test("eq", month, lit(1)), choose(n.Or(fixed[0], floating[0]),
                                                     lit(boolean(True)), lit(boolean(False)))),
                   (test("eq", month, lit(5)), choose(test("eq", date, may_last),
                                                     lit(boolean(True)), lit(boolean(False)))),
                   (test("eq", month, lit(7)), choose(fixed[1],
                                                     lit(boolean(True)), lit(boolean(False)))),
                   (test("eq", month, lit(11)), choose(floating[1],
                                                      lit(boolean(True)), lit(boolean(False)))),
                   (test("eq", month, lit(12)), choose(n.Or(fixed[2], next_new_year),
                                                      lit(boolean(True)), lit(boolean(False))))),
                  lit(boolean(False)))
    spec, body = op("holiday_match", (("date", "date"),), "bool",
                    n.Let("year", c("year_of", date), body),
                    "Check six holiday rules, including observed next January.")
    add("holiday_match", "operation", spec, body)

    add("Holiday", "object", ObjectSpec("Holiday", "refine", base="date",
        valid=c("holiday_match", v("x")), sealed=True,
        interface=("Holiday.make", "Holiday.base")), dependencies=("holiday_match",))

    subject = v("s")
    reconstructed = c("date", c("year_of", subject), c("month_of", subject),
                      c("day_of", subject))
    open_condition = n.And(test("workday", reconstructed),
                           n.Not(test("holiday_match", reconstructed)))
    body = choose(open_condition, lit(boolean(True)), lit(boolean(False)))
    add("open_day", "observation", ObservationSpec(
        "open_day", ("weekday", "year_of", "month_of", "day_of"), body), body)

    body = choose(test("open_day", v("date")), c("some", v("date")), v("latest"))
    spec, body = op("keep_open", (("latest", "maybe_date"), ("date", "date")),
                    "maybe_date", body, "Retain the most recent observed open date.")
    add("keep_open", "operation", spec, body)

    body = n.Let("seed", c("keep_open", lit(Card("maybe_date", "none")),
                                 c("date", v("year"), v("month"), lit(1))),
                 c("optional_date", c("month_fold", lit(kernel.FnRef("next_date")),
                                             lit(kernel.FnRef("keep_open")),
                                             c("month_span", v("year"), v("month")), v("seed"))))
    spec, body = op("settle", (("year", "int"), ("month", "int")), "date", body,
                    "Return the final open date, or fail if no date is open.")
    add("settle", "operation", spec, body)
    return result
