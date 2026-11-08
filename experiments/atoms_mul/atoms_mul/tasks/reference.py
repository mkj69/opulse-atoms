"""Plain-Python answers, independent of the AML interpreter."""

from random import Random

CONSTANT_COUNTS = tuple(Random(11).sample(range(3, 13), 8))
DOT_SIZES = (2, 3, 4, 2, 3, 4, 2, 3, 4, 2, 3, 4, 2, 3, 2, 4)


def constant_scale(count: int, value: int) -> int:
    return sum(value for _ in range(count))


def variable_scale(count: int, value: int) -> int:
    return sum(value for _ in range(count))


def compound(template: int, args: tuple[int, ...]) -> int:
    if template == 0:
        count, value, extra = args
        return variable_scale(count, value) + extra
    if template == 1:
        count, first, second = args
        return variable_scale(count, first + second)
    if template == 2:
        (side,) = args
        return variable_scale(side, side)
    if template == 3:
        count, value = args
        return constant_scale(3, variable_scale(count, value))
    if template == 4:
        count, first, second = args
        return variable_scale(count, first) + variable_scale(count, second)
    if template == 5:
        count, value = args
        return variable_scale(count + 2, value)
    if template == 6:
        side, extra = args
        return variable_scale(side, side) + extra
    if template == 7:
        count, value, extra = args
        return variable_scale(count, value) + value + extra
    raise ValueError(f"Unknown compound template: {template}")


def dot(args: tuple[int, ...], weights: tuple[int, ...] = ()) -> int:
    if weights:
        if len(args) != len(weights):
            raise ValueError("Expected one quantity per weight")
        return sum(variable_scale(quantity, weight) for quantity, weight in zip(args, weights))
    if len(args) % 2:
        raise ValueError("Expected quantity-value pairs")
    return sum(variable_scale(args[index], args[index + 1]) for index in range(0, len(args), 2))


def expected(task: dict, args: list[int] | tuple[int, ...]) -> int:
    """Evaluate a frozen task using its id and independent template rules."""
    number = int(task["id"].split("_t")[1]) - 1
    values = tuple(args)
    if task["stage"] == 2:
        return dot(values)
    if number < 8:
        return constant_scale(CONSTANT_COUNTS[number], values[0])
    if number < 16:
        return variable_scale(*values)
    return compound(number - 16, values)
