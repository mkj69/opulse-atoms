"""Finite, timezone-free Gregorian calendar, 2000-01-01 through 2099-12-31.

All bounds and failures are explicit.  Monday=0, ..., Sunday=6.  The only
holiday policy is the six rules stated in calendar.json; this is not a claim
to model every statutory holiday or a real financial institution's calendar.
"""

from dataclasses import dataclass
from datetime import date as OracleDate, timedelta
from functools import lru_cache
import json
from pathlib import Path


class DomainError(ValueError):
    pass


@dataclass(frozen=True, order=True)
class Date:
    year: int
    month: int
    day: int

    def __post_init__(self):
        if not (2000 <= self.year <= 2099 and 1 <= self.month <= 12
                and 1 <= self.day <= month_length(self.year, self.month)):
            raise DomainError("invalid_date")

    def __str__(self):
        return f"Date<{self.year:04d}-{self.month:02d}-{self.day:02d}>"


def leap_year(year):
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def month_length(year, month):
    if not 1 <= month <= 12:
        raise DomainError("invalid_month")
    return (31, 29 if leap_year(year) else 28, 31, 30, 31, 30,
            31, 31, 30, 31, 30, 31)[month - 1]


def next_day(date):
    if date == Date(2099, 12, 31):
        raise DomainError("range")
    if date.day < month_length(date.year, date.month):
        return Date(date.year, date.month, date.day + 1)
    if date.month < 12:
        return Date(date.year, date.month + 1, 1)
    return Date(date.year + 1, 1, 1)


def repeat(step, date, count):
    if not 0 <= count <= 7:
        raise DomainError("repeat_limit")
    for _ in range(count):
        date = step(date)
    return date


def eq(left, right):
    return left == right


def lt(left, right):
    return left < right


def le(left, right):
    return lt(left, right) or eq(left, right)


def add(left, right):
    return left + right


def indicator(value):
    return 1 if value else 0


def _days_before_year(year):
    previous = year - 1
    return 365 * previous + previous // 4 - previous // 100 + previous // 400


def _serial(date):
    return (_days_before_year(date.year)
            + sum(month_length(date.year, month) for month in range(1, date.month))
            + date.day - 1)


ANCHOR = Date(2000, 1, 1)


def weekday(date):
    return (5 + _serial(date) - _serial(ANCHOR)) % 7


@dataclass(frozen=True)
class LeapDay:
    date: Date

    def __post_init__(self):
        if (self.date.month, self.date.day) != (2, 29):
            raise DomainError("not_leap_day")

    def __str__(self):
        return f"LeapDay<{self.date.year:04d}-02-29>"


def leap_date(leap_day):
    return leap_day.date


def week_later(date):
    return repeat(next_day, date, 7)


def workday(date):
    return lt(weekday(date), 5)


def seek(step, predicate, date, limit):
    if not 1 <= limit <= 7:
        raise DomainError("seek_limit")
    for _ in range(limit):
        date = step(date)
        if predicate(date):
            return date
    raise DomainError("not_found")


@dataclass(frozen=True)
class MonthSpan:
    start: Date
    end: Date

    def __post_init__(self):
        if (self.start.day != 1 or self.start.year != self.end.year
                or self.start.month != self.end.month
                or self.end.day != month_length(self.start.year, self.start.month)):
            raise DomainError("invalid_span")

    def __str__(self):
        return f"MonthSpan<{self.start.year:04d}-{self.start.month:02d}>"


def month_span(year, month):
    start = Date(year, month, 1)
    cursor = start
    while True:
        try:
            following = next_day(cursor)
        except DomainError as error:
            if str(error) != "range":
                raise
            return MonthSpan(start, cursor)
        if following.month != month:
            return MonthSpan(start, cursor)
        cursor = following


def month_end(year, month):
    return month_span(year, month).end


def month_fold(step, accumulate, span, initial):
    """At most 31 inclusive visits; transitions use bounded atomic repeat."""
    if step is not next_day:
        raise DomainError("invalid_step")
    cursor = span.start
    result = initial
    for index in range(31):
        result = accumulate(result, cursor)
        if cursor == span.end:
            return result
        cursor = repeat(step, cursor, 1)
        if (cursor.year, cursor.month) != (span.start.year, span.start.month):
            raise DomainError("left_month")
    raise DomainError("fold_limit")


def weekday_count(year, month):
    return month_fold(next_day, lambda total, date: add(total, indicator(workday(date))),
                      month_span(year, month), 0)


def nth_weekday(year, month, ordinal, day_of_week):
    if not 1 <= ordinal <= 5 or not 0 <= day_of_week <= 6:
        raise DomainError("invalid_nth")
    span = month_span(year, month)
    if weekday(span.start) == day_of_week:
        found = span.start
    else:
        found = seek(next_day, lambda date: weekday(date) == day_of_week,
                     span.start, 6)
    for _ in range(ordinal - 1):
        if found.day + 7 > span.end.day:
            raise DomainError("no_occurrence")
        found = week_later(found)
    if found > span.end:
        raise DomainError("no_occurrence")
    return found


def _previous_day(date):
    if date == ANCHOR:
        raise DomainError("range")
    if date.day == 1:
        if date.month == 1:
            return month_end(date.year - 1, 12)
        return month_end(date.year, date.month - 1)
    return month_fold(next_day,
                      lambda prior, candidate: candidate if candidate < date else prior,
                      month_span(date.year, date.month), date)


def _observed(date):
    if weekday(date) == 5:
        try:
            return _previous_day(date)
        except DomainError as error:
            if str(error) != "range":
                raise
            return None
    if weekday(date) == 6:
        return next_day(date)
    return date


@lru_cache(maxsize=None)
def holidays(year):
    if not 2000 <= year <= 2099:
        raise DomainError("range")
    dates = set()
    for base_year in (year, year + 1):
        if base_year > 2099:
            continue
        for month, day in ((1, 1), (7, 4), (12, 25)):
            observed = _observed(Date(base_year, month, day))
            if observed is not None and observed.year == year:
                dates.add(observed)
    dates.add(nth_weekday(year, 1, 3, 0))
    dates.add(nth_weekday(year, 11, 4, 3))
    try:
        dates.add(nth_weekday(year, 5, 5, 0))
    except DomainError as error:
        if str(error) != "no_occurrence":
            raise
        dates.add(nth_weekday(year, 5, 4, 0))
    return frozenset(dates)


@dataclass(frozen=True)
class Holiday:
    date: Date

    def __post_init__(self):
        if self.date not in holidays(self.date.year):
            raise DomainError("not_holiday")

    def __str__(self):
        return f"Holiday<{self.date.year:04d}-{self.date.month:02d}-{self.date.day:02d}>"


def is_holiday(date):
    return date in holidays(date.year)


def open_day(date):
    return workday(date) and not is_holiday(date)


def settle(year, month):
    span = month_span(year, month)
    result = month_fold(next_day,
                        lambda latest, date: date if open_day(date) else latest,
                        span, None)
    if result is None:
        raise DomainError("no_open_day")
    return result


def _value(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        return "List<" + ", ".join(map(_value, value)) + ">"
    return str(value)


def showcase_compute():
    return [settle(year, month) for year, month in
            ((2031, 11), (2031, 12), (2032, 1), (2032, 2), (2032, 3),
             (2032, 4), (2032, 5), (2032, 6), (2032, 7), (2032, 8),
             (2032, 9), (2032, 10), (2032, 11), (2032, 12),
             (2033, 1), (2033, 2))]


def showcase_invert():
    matches = []
    for year in range(2000, 2100):
        try:
            fifth_thursday = nth_weekday(year, 2, 5, 3)
        except DomainError as error:
            if str(error) != "no_occurrence":
                raise
            continue
        if (fifth_thursday == Date(year, 2, 29)
                and settle(year, 2) == fifth_thursday):
            matches.append(year)
    return matches


def showcase_decide():
    for year in range(2000, 2100):
        if weekday_count(year, 12) == 23 and settle(year, 12) != month_end(year, 12):
            return [False, year, weekday_count(year, 12),
                    month_end(year, 12), settle(year, 12)]
    return [True]


def cases():
    return [
        LeapDay(Date(2000, 2, 29)),
        week_later(leap_date(LeapDay(Date(2000, 2, 29)))),
        workday(week_later(leap_date(LeapDay(Date(2000, 2, 29))))),
        seek(next_day, workday, Date(2000, 3, 7), 3),
        month_span(2000, 2),
        month_end(2032, 2),
        month_fold(next_day, lambda total, date: add(total, indicator(workday(date))),
                   month_span(2032, 2), 0),
        weekday_count(2032, 2),
        nth_weekday(2032, 11, 4, 3),
        Holiday(nth_weekday(2032, 11, 4, 3)),
        open_day(nth_weekday(2032, 11, 4, 3)),
        settle(2032, 12),
    ]


def main():
    spec = json.loads(Path(__file__).with_suffix(".json").read_text(encoding="utf-8"))
    assert spec["id"] == "calendar" and len(spec["tower"]) == 12
    assert [entry["layer"] for entry in spec["tower"]] == list(range(1, 13))
    for entry, result in zip(spec["tower"], cases()):
        assert entry["value"] == _value(result), (entry["layer"], _value(result))
    for entry, result in zip(spec["showcase"],
                             (showcase_compute(), showcase_invert(), showcase_decide())):
        assert entry["answer"] == _value(result), (entry["angle"], _value(result))
    assert weekday(ANCHOR) == 5
    assert next_day(Date(2000, 2, 28)) == Date(2000, 2, 29)
    assert next_day(Date(2000, 2, 29)) == Date(2000, 3, 1)
    assert month_length(2100, 2) == 28 and leap_year(2000)
    assert Date(2021, 12, 31) in holidays(2021)
    assert Date(2022, 1, 1) not in holidays(2022)
    assert Date(2004, 12, 31) in holidays(2004)
    assert [day for day in holidays(2021) if day.month == 5] == [Date(2021, 5, 31)]
    oracle = OracleDate(2000, 1, 1)
    while oracle.year <= 2099:
        current = Date(oracle.year, oracle.month, oracle.day)
        assert weekday(current) == oracle.weekday()
        if current != Date(2099, 12, 31):
            following = oracle + timedelta(days=1)
            assert next_day(current) == Date(following.year, following.month, following.day)
        oracle += timedelta(days=1)
    for year in range(2000, 2100):
        for month in range(1, 13):
            close = settle(year, month)
            assert close.month == month and close.year == year and open_day(close)
            span = month_span(year, month)
            assert all(not open_day(Date(year, month, day))
                       for day in range(close.day + 1, span.end.day + 1))
    for callable_value in (lambda: next_day(Date(2099, 12, 31)),
                           lambda: repeat(next_day, ANCHOR, 8),
                           lambda: nth_weekday(2023, 2, 5, 0),
                           lambda: Holiday(Date(2032, 11, 24))):
        try:
            callable_value()
        except DomainError:
            pass
        else:
            raise AssertionError("expected domain failure")
    print("OK")


if __name__ == "__main__":
    main()
