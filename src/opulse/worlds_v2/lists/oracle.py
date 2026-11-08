"""Independent catalogue reference conversions for bounded evidence."""

import importlib.util
from pathlib import Path

from opulse.atoms import kernel, values
from opulse.worlds_v2.lists import hosts

REFERENCE_PATH = Path(__file__).resolve().parents[4] / "worlds/catalogue/depth/lists.py"
spec = importlib.util.spec_from_file_location("lists_depth_reference", REFERENCE_PATH)
reference = importlib.util.module_from_spec(spec)
import sys

sys.modules[spec.name] = reference
spec.loader.exec_module(reference)


def convert(value):
    if isinstance(value, values.Card):
        if value.sort == "list":
            return tuple(convert(item) for item in hosts.from_card(value))
        if value.sort == "Run":
            return reference.Run(*value.fields[0].fields)
        if value.sort == "NonEmpty":
            return reference.NonEmpty(hosts.from_card(value.fields[0]))
        if value.sort == "pair":
            return reference.Pair(*(convert(field) for field in value.fields))
    return value


def encode(value):
    if isinstance(value, reference.NonEmpty):
        return values.Card("NonEmpty", "val", (hosts.to_card(value.values),))
    if isinstance(value, reference.Run):
        return values.Card("Run", "val", (hosts.pair(value.key, value.count),))
    if isinstance(value, reference.Pair):
        return hosts.pair(encode(value.first), encode(value.second))
    if isinstance(value, tuple):
        return hosts.to_card(tuple(encode(item) for item in value))
    if type(value) is bool:
        return values.boolean(value)
    return value


def expected(name, args):
    operation = next((arg.name for arg in args if isinstance(arg, kernel.FnRef)), "cons" if name == "fold" else "le")
    args = tuple(convert(arg) for arg in args if not isinstance(arg, kernel.FnRef))
    builders = {"cons": reference.cons, "snoc": lambda item, acc: acc + (item,)}
    comparisons = {"le": reference.le, "ge": lambda left, right: left >= right}
    aliases = {"NonEmpty.make": reference.NonEmpty, "Run.make": lambda pair: reference.Run(pair.first, pair.second),
               "fold": lambda row, seed: reference.fold(builders[operation], row, seed),
               "stable_merge": lambda left, right: reference.stable_merge(comparisons[operation], left, right),
               "merge_count": lambda left, right: reference.merge_count(comparisons[operation], left, right)}
    try:
        result = (aliases[name] if name in aliases else getattr(reference, name))(*args)
        return encode(result)
    except reference.Bottom:
        return values.Bottom("invalid")


def rle_step(item, accumulator):
    runs = convert(accumulator)
    if runs and runs[0].key == item:
        return encode((reference.Run(item, runs[0].count + 1), *runs[1:]))
    return encode((reference.Run(item, 1), *runs))
