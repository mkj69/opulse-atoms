"""Gregorian layer-zero date arithmetic, without platform calendars or time zones."""

from opulse.atoms.values import Bottom, Card, boolean, truth


def leap(year):
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def month_length(year, month):
    if month == 2:
        return 29 if leap(year) else 28
    return 30 if month in (4, 6, 9, 11) else 31


def valid_date(value):
    return (isinstance(value, Card) and value.sort == "date" and value.tag == "ymd"
            and len(value.fields) == 3 and all(type(field) is int for field in value.fields)
            and 2000 <= value.fields[0] <= 2099 and 1 <= value.fields[1] <= 12
            and 1 <= value.fields[2] <= month_length(value.fields[0], value.fields[1]))


def to_card(year, month, day):
    value = Card("date", "ymd", (year, month, day))
    return value if valid_date(value) else Bottom("invalid")


def from_card(value):
    if not valid_date(value):
        raise ValueError("invalid date")
    return value.fields


def next_date(value):
    if not valid_date(value):
        return Bottom("invalid")
    year, month, day = value.fields
    if (year, month, day) == (2099, 12, 31):
        return Bottom("range")
    if day < month_length(year, month):
        return to_card(year, month, day + 1)
    if month < 12:
        return to_card(year, month + 1, 1)
    return to_card(year + 1, 1, 1)


def weekday(value):
    """Monday=0 through Sunday=6; the January 2000 anchor is Saturday."""
    if not valid_date(value):
        return Bottom("invalid")
    year, month, day = value.fields
    days = sum(366 if leap(previous) else 365 for previous in range(2000, year))
    days += sum(month_length(year, previous) for previous in range(1, month)) + day - 1
    return (5 + days) % 7


def year_of(value):
    return value.fields[0] if valid_date(value) else Bottom("invalid")


def month_of(value):
    return value.fields[1] if valid_date(value) else Bottom("invalid")


def day_of(value):
    return value.fields[2] if valid_date(value) else Bottom("invalid")


def equal_int(left, right):
    return boolean(left == right) if type(left) is type(right) is int else Bottom("invalid")


def less_int(left, right):
    return boolean(left < right) if type(left) is type(right) is int else Bottom("invalid")


def decrement(value):
    return value - 1 if type(value) is int and 0 < value <= 7 else Bottom("invalid")


def fail(reason):
    return Bottom(reason) if isinstance(reason, str) else Bottom("invalid")


def dates():
    return tuple(to_card(year, month, day) for year in range(2000, 2100)
                 for month in range(1, 13) for day in range(1, month_length(year, month) + 1))


def eq(left, right):
    return boolean(left == right)


def lt(left, right):
    if type(left) is type(right) is int:
        return boolean(left < right)
    if valid_date(left) and valid_date(right):
        return boolean(left.fields < right.fields)
    return Bottom("invalid")


def le(left, right):
    result = lt(left, right)
    return boolean(truth(result) or left == right) if not isinstance(result, Bottom) else result


def add(left, right):
    return left + right if type(left) is type(right) is int else Bottom("invalid")


def subtract(left, right):
    return left - right if type(left) is type(right) is int else Bottom("invalid")


def indicator(value):
    if type(value) is bool:
        return int(value)
    if isinstance(value, Card) and value.sort == "bool" and value.tag in ("true", "false"):
        return int(value.tag == "true")
    return Bottom("invalid")


def date(year, month, day):
    return to_card(year, month, day)


def pair(left, right):
    return Card("pair", "pair", (left, right))


def first(value):
    return value.fields[0] if isinstance(value, Card) and value.sort == "pair" else Bottom("invalid")


def second(value):
    return value.fields[1] if isinstance(value, Card) and value.sort == "pair" else Bottom("invalid")


def some(value):
    return Card("maybe_date", "some", (value,)) if valid_date(value) else Bottom("invalid")


def optional_date(value):
    return value.fields[0] if isinstance(value, Card) and value.sort == "maybe_date" and value.tag == "some" else Bottom("no_open_day")
