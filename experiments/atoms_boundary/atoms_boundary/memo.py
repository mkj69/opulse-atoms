"""Descriptive memo cost view of the fixed boundary tower; no model prompts."""

import csv
import sys
from dataclasses import replace

from opulse.atoms import kernel, nodes
from opulse.atoms.values import Ok

from .items import frozen_inputs
from .tower import build_tower


def memo_scope(plain_scope):
    """Use a promoted memo binder when present; otherwise switch the diagnostic copy."""
    recursive = {}
    for name, definition in plain_scope.defns.items():
        if not isinstance(definition.body, nodes.Rec) or name.endswith("_memo"):
            continue
        memo_body = replace(definition.body, memo=True)
        promoted = plain_scope.defns.get(f"{name}_memo")
        if promoted is not None and promoted.body != memo_body:
            raise ValueError(f"memo variant differs from {name}")
        recursive[name] = (replace(promoted, name=name) if promoted is not None else
                           replace(definition, body=memo_body))
    if not recursive:
        raise ValueError("tower has no recursive definitions")
    return plain_scope.extend(tuple(recursive.values()))


def compare_runs(plain_scope, cached_scope, args, fuel=None, trace=False, name="score"):
    """Check full outcomes and charged costs before reporting physical work."""
    limits = kernel.Limits(fuel=fuel)
    plain = kernel.call(name, args, plain_scope, limits=limits, trace=trace)
    cached = kernel.call(name, args, cached_scope, limits=limits, trace=trace)
    if (plain.outcome, plain.steps, plain.jumps) != (cached.outcome, cached.steps, cached.jumps):
        raise ValueError(f"memo unfolding differs at {args!r}")
    return plain, cached


def work_rows(library, inputs=None):
    """Report per-item plain unfolding steps and both work measurements."""
    plain_scope = library.scope()
    cached_scope = memo_scope(plain_scope)
    rows = []
    for index, args in enumerate(frozen_inputs() if inputs is None else inputs):
        plain, cached = compare_runs(plain_scope, cached_scope, args)
        if not isinstance(plain.outcome, Ok):
            raise TypeError(f"item {index} has no exact answer")
        rows.append((index, *args, plain.outcome.value, plain.steps, plain.work, cached.work))
    return rows


def main():
    writer = csv.writer(sys.stdout, lineterminator="\n")
    writer.writerow(("id", "a", "b", "c", "value", "steps", "plain_work", "memo_work"))
    writer.writerows(work_rows(build_tower()))


if __name__ == "__main__":
    main()
