"""Task-kind kernel adapter (docs/spec/atoms-v2.md, sections 4, 6, 7 and 10)."""

from __future__ import annotations

import json
from functools import lru_cache
from math import gcd
from pathlib import Path

from opulse.atoms import kernel
from opulse.atoms.values import (
    Bottom,
    Card,
    Ok,
    boolean,
    decode,
    encode,
    encode_outcome,
)
from opulse.config import Settings
from opulse.tasks_v2 import decl
from opulse.tasks_v2.decl import WorldFile
from opulse.worlds import action


@lru_cache(maxsize=5)
def world(name: str) -> WorldFile:
    path = Path(__file__).resolve().parents[3] / "worlds" / "decl" / f"{name}.json"
    return WorldFile.from_dict(json.loads(path.read_text(encoding="utf-8")))


def fraction(num: int, den: int) -> Card:
    return Card("fraction", "fraction", (num, den))


def canonical(value: Card) -> Card | Bottom:
    if not isinstance(value, Card) or value.sort != "fraction" or value.tag != "fraction" or len(value.fields) != 2:
        return Bottom("invalid")
    num, den = value.fields
    if type(num) is not int or type(den) is not int or den == 0:
        return Bottom("invalid")
    divisor = gcd(num, den)
    return fraction(num // divisor * (1 if den > 0 else -1), abs(den) // divisor)


def positive_fraction(value: Card) -> Card | Bottom:
    normalized = canonical(value)
    if isinstance(normalized, Bottom):
        return normalized
    return fraction(abs(normalized.fields[0]), normalized.fields[1])


def ilist(items: tuple[int, ...]) -> Card:
    result = Card("ilist", "nil")
    for item in reversed(items):
        result = Card("ilist", "cons", (item, result))
    return result


def list_items(value: Card) -> tuple[int, ...]:
    result = []
    while isinstance(value, Card) and value.sort == "ilist" and value.tag == "cons":
        head, value = value.fields
        result.append(head)
    if not isinstance(value, Card) or value.sort != "ilist" or value.tag != "nil":
        raise ValueError("invalid ilist")
    return tuple(result)


def to_card(state: action.State) -> Card:
    """Encode a valid robot state as a finite, sealed kernel value."""
    if not isinstance(state, action.State):
        raise TypeError("expected action state")
    return Card("robot_state", "robot_state", (json.dumps(state.to_dict(), sort_keys=True),))


def from_card(value: Card) -> action.State:
    if not isinstance(value, Card) or value.sort != "robot_state" or value.tag != "robot_state" or len(value.fields) != 1:
        raise TypeError("expected state card")
    return action.State.from_dict(json.loads(value.fields[0]))


def _action_host(operation: str):
    def apply(value):
        state = from_card(value) if isinstance(value, Card) else value
        result = action.apply_atom(operation, state)
        return to_card(result) if isinstance(value, Card) and isinstance(result, action.State) else result
    return apply


def _fraction_binary(op):
    def run(left, right):
        first, second = canonical(left), canonical(right)
        if isinstance(first, Bottom) or isinstance(second, Bottom):
            return Bottom("invalid")
        return op(first, second)
    return run


@lru_cache(maxsize=16)
def scope(name: str, definitions=()) -> kernel.DictScope:
    declaration = world(name)
    semantics = Settings.from_dict({"preset": declaration.world}).semantics.build().operations() if name != "action@1" else {}
    atoms = []
    for spec in declaration.operations:
        if name == "action@1":
            fn = _action_host(spec.name)
        else:
            semantic_name = {"natural_succ": "succ", "natural_pred": "pred"}.get(spec.name, spec.name)
            if semantic_name not in semantics:
                continue
            fn = semantics[semantic_name]
            if name == "clock@2" and any(edge.sort == "hour" for edge in spec.inputs):
                host = fn
                def fn(*values, host=host):
                    return host(*(value.fields[0] if isinstance(value, Card) and value.sort == "hour"
                                  and value.tag == "val" and len(value.fields) == 1 else value
                                  for value in values))
        kind = "observation" if name == "action@1" and spec.name in {probe.name for probe in declaration.probes} else "operation"
        atoms.append(kernel.Atom(spec.name, len(spec.inputs), fn, spec.cost, kind, spec.strict))
    if name == "clock@2":
        atoms.extend(kernel.Atom(spec.name, 1, getattr(decl, spec.name), spec.cost,
                                 strict=spec.strict)
                     for spec in declaration.operations
                     if spec.name in ("int_mod_twelve", "nonnegative", "below_twelve"))
    extras = [
        kernel.Atom("fraction_valid", 1, lambda value: boolean(not isinstance(canonical(value), Bottom))),
        kernel.Atom("fraction_canon", 1, canonical),
        kernel.Atom("fraction_raw_base", 1, lambda value: value),
        kernel.Atom("fraction_positive_base", 1, positive_fraction),
        kernel.Atom("raw_fraction_eq", 2, lambda left, right: boolean(left == right)),
        kernel.Atom("positive_fraction_eq", 2, lambda left, right: boolean(
            positive_fraction(left) == positive_fraction(right))),
        kernel.Atom("make_fraction", 2, lambda num, den: canonical(fraction(num, den))),
        kernel.Atom("num", 1, lambda value: canonical(value).fields[0] if not isinstance(canonical(value), Bottom) else Bottom("invalid")),
        kernel.Atom("raw_num", 1, lambda value: value.fields[0] if isinstance(value, Card) and value.sort == "fraction" and len(value.fields) == 2 else Bottom("invalid")),
        kernel.Atom("den", 1, lambda value: canonical(value).fields[1] if not isinstance(canonical(value), Bottom) else Bottom("invalid")),
        kernel.Atom("fraction_eq", 2, lambda left, right: boolean(canonical(left) == canonical(right))),
        kernel.Atom("frac_add_base", 2, _fraction_binary(lambda left, right: canonical(fraction(left.fields[0] * right.fields[1] + right.fields[0] * left.fields[1], left.fields[1] * right.fields[1])))),
        kernel.Atom("frac_mul_base", 2, _fraction_binary(lambda left, right: canonical(fraction(left.fields[0] * right.fields[0], left.fields[1] * right.fields[1])))),
        kernel.Atom("raw_frac_add", 2, lambda left, right: fraction(left.fields[0] + right.fields[0],
                                                                    left.fields[1] + right.fields[1])),
        kernel.Atom("nil", 0, lambda: ilist(())),
        kernel.Atom("cons", 2, lambda head, tail: Card("ilist", "cons", (head, tail))),
        kernel.Atom("is_nil", 1, lambda value: boolean(value.tag == "nil")),
        kernel.Atom("head", 1, lambda value: value.fields[0] if value.tag == "cons" else Bottom("empty")),
        kernel.Atom("tail", 1, lambda value: value.fields[1] if value.tag == "cons" else Bottom("empty")),
        kernel.Atom("size", 1, lambda value: len(list_items(value))),
        kernel.Atom("zero", 0, lambda: 0),
        kernel.Atom("zero_test", 1, lambda value: boolean(value == 0)),
        kernel.Atom("add", 2, lambda left, right: left + right) if name == "action@1" else None,
    ]
    atoms.extend(item for item in extras if item is not None)
    return kernel.DictScope(atoms, tuple(definitions))


def run(name: str, node, definitions=(), fuel=20000, trace=False):
    return kernel.evaluate(node, scope=scope(name, definitions), limits=kernel.Limits(fuel=fuel),
                           trace=trace, dialect=world(name).dialect)


def wire(value):
    if isinstance(value, action.State):
        baseline = action.initial_state(4, 4, 2).to_dict()
        return {"state_delta": {key: item for key, item in value.to_dict().items()
                                if item != baseline.get(key)}}
    return encode(value)


def unwire(value):
    if "state_delta" in value:
        baseline = action.initial_state(4, 4, 2).to_dict()
        return action.State.from_dict({**baseline, **value["state_delta"]})
    if "state" in value:
        return action.State.from_dict(value["state"])
    decoded = decode(value)
    return from_card(decoded) if isinstance(decoded, Card) and decoded.sort == "robot_state" else decoded


def outcome_wire(outcome):
    if isinstance(outcome, Ok) and isinstance(outcome.value, action.State):
        return {"ok": wire(outcome.value)}
    return encode_outcome(outcome)


def _notation(value):
    if isinstance(value, dict) and ("state_delta" in value or
                                    "state" in value and isinstance(value["state"], dict) and
                                    "width" in value["state"]):
        return _notation(unwire(value))
    if isinstance(value, dict) and "t" in value:
        return _notation(unwire(value))
    if isinstance(value, action.State):
        rows = "/".join(value.terrain)
        return (f"rows {rows} R@({value.robot[0]},{value.robot[1]}) facing {value.facing} "
                f"holding {value.held or '-'}")
    if isinstance(value, Card):
        if value.sort == "fraction":
            return f"Frac<{value.fields[0]}, {value.fields[1]}>"
        if value.sort == "ilist":
            return "List<" + ", ".join(map(str, list_items(value))) + ">"
        if value.sort == "bool":
            return value.tag
        if value.sort == "list[int]":
            return "List<" + ", ".join(map(str, value.fields)) + ">"
        return value.tag + "<" + ", ".join(map(_notation, value.fields)) + ">"
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(map(_notation, value)) + "]"
    if isinstance(value, dict):
        return "{" + ", ".join(f"{key}: {_notation(item)}" for key, item in value.items()) + "}"
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)


def _prompt(kind, angle, question, scope, shape, opened, show):
    concept = question["concept"]
    rules = {
        "fraction": "obj Frac<num, den>: den != 0; canon reduces by gcd and makes den positive; equality compares canonical forms. L1",
        "ilist": "obj List<head, tail>: nil or cons; ilen and isum recurse by tail. L1",
        "three": "obj Three = natural_succ(natural_succ(natural_succ(zero()))). L1",
        "front_free": "obs ?front_free{s} = not(?front_wall{s}) and not(?front_water{s}). L1",
        "front_wall_only": "obs ?front_wall_only{s} = ?front_wall{s}. L1",
        "front_water_only": "obs ?front_water_only{s} = ?front_water{s}. L1",
        "blocked_count": "obs ?blocked_count{s, memory} = memory + 1 if ?front_wall{s} or ?front_water{s}, else 0; initially memory=0. L1",
        "twice": "comb @twice[f](x) = f(f(x)). L1",
        "repeat": "comb @repeat[f](n, x) = f applied n times to x. L1",
        "seq": "comb @seq[f, g](x) = g(f(x)). L1",
        "fold": "comb @fold[f](z, List<items>) = f(head, fold(f, z, tail)); fold on nil is z. L1",
        "isum": "op isum(List<xs>) = recursively add all list items. L2",
        "ilen": "op ilen(List<xs>) = recursively count the list items. L2",
        "num": "op num(Frac<a, b>) = numerator of the canonical pair. L2",
        "raw_num": "op raw_num(Frac<a, b>) = numerator of the raw pair. L2",
        "frac_add": "op frac_add(a, b) = canonical sum of the two pairs. L2",
        "raw_frac_add": "op raw_frac_add(a, b) = pair of raw numerator sums and denominator sums. L2",
    }
    from opulse.atoms.notation import print_expr
    from opulse.tasks_v2.library_defs import records

    definitions = {record.name: record for record in records()[0]}
    parameters = {definition.name: definition.params for definition in records()[1]}
    context = {"kinds": {name: record.kind for name, record in definitions.items()},
               "op_arity": {name: len(record.spec.op_params) for name, record in definitions.items()
                            if record.kind == "combinator"}}
    for name, record in definitions.items():
        if name in rules:
            try:
                body = print_expr(record.body, context)
            except (TypeError, ValueError):
                continue
            if record.kind == "combinator":
                slots = ", ".join(record.spec.op_params)
                args = ", ".join(param for param in parameters[name] if param not in record.spec.op_params)
                head = f"comb @{name}[{slots}]({args})"
            elif record.kind == "observation":
                head = f"obs ?{name}{{{', '.join(parameters[name])}}}"
            elif record.kind == "operation":
                head = f"op {name}({', '.join(parameters[name])})"
            else:
                head = f"obj {name.title()}"
            rules[name] = f"{head} = {body} L{record.layer}"
    if angle == "describe":
        lines = [f"Kind: {kind}.", "Angle: describe.", "Identify the target T from its behavior."]
        lines.append("Observed input -> output examples: " +
                     "; ".join(f"{_notation(sample[0])} -> {_notation(sample[1])}"
                               if isinstance(sample, list) else
                               f"{_notation({key: value for key, value in sample.items() if key != 'output'})} -> "
                               f"{_notation(sample['output'])}" for sample in question["examples"]) + ".")
    else:
        lines = [f"Kind: {kind}.", f"Angle: {angle}.", f"Target definition: {concept}."]
        shown = [] if angle in ("induce", "create") else [concept]
        if kind == "combinator" and angle == "decide":
            shown = (["seq"] if question.get("mode") == "seq_swap" else
                     ["fold", "isum"] if question.get("mode") == "fold_sum" else ["twice", "repeat"])
        if kind == "object" and angle == "decide" and "operation" in question:
            shown.append(question["operation"])
        if kind == "object" and angle == "compute" and question.get("mode") in ("length", "sum"):
            shown.append("ilen" if question["mode"] == "length" else "isum")
        for name in shown:
            lines.append("Opened definition: " + rules[name].rstrip(". ") + ".")
    if kind == "observation":
        lines.append("Rows use '.' for clear terrain, '#' for wall and '~' for water; the front cell is adjacent in the facing direction.")
    if angle == "describe":
        lines.append("Choose the exact description of T from these options.")
        lines.extend(f"{index}) {option}" for index, option in enumerate(question["options"], 1))
    elif kind == "object":
        mode = question.get("mode", "canon")
        if angle == "compute":
            argument = _notation(question["value"]) if "value" in question else "Three"
            lines.append(f"Compute {mode} of {argument}" + (f" then apply natural_succ {question['successors_after']} times" if mode == "three" else "") + ".")
        elif angle == "invert":
            lines.append(f"Find raw Frac<num, den> representations canonicalizing to {_notation(question['target'])}.")
            lines.append("Scope: -6 <= num, den <= 6 and den != 0.")
            lines.append(f"Allowed raw candidates: {', '.join(map(_notation, scope['inputs']))}.")
        elif angle == "decide":
            if mode in ("respects_canon", "respects_binary"):
                lines.append(f"Decide whether {question['operation']} respects Frac canon on the stated pair "
                             f"{_notation(question['left'])}, {_notation(question['right'])}.")
                if mode == "respects_binary":
                    lines.append(f"Use partner {_notation(question['partner'])} as the second argument.")
                lines.append("Give a verified counterexample if false.")
            else:
                lines.append(f"Decide whether {_notation(question['left'])} equals "
                             f"{_notation(question['right'])} after Frac canon.")
    elif kind == "observation":
        symbol = "?" + question["observation"]
        if angle == "compute":
            subject = question.get("states") if question.get("sequence") else question["state"]
            lines.append(f"Compute {symbol} on {'the ordered sequence ' if question.get('sequence') else 'state '}{_notation(subject)}.")
        elif angle == "invert":
            lines.append(f"Find states producing {symbol} = {_notation(question['target'])}.")
            lines.append(f"Allowed candidates: {_notation(scope['inputs'])}.")
        elif angle == "decide":
            if question.get("mode") == "memory_distinguish":
                lines.append(f"Does {symbol} depend on memory rather than current probes alone?")
                lines.append(f"State: {_notation(question['state'])}; compare memories {_notation(question['memories'])}.")
            else:
                lines.append(f"Does {symbol} distinguish these full states?")
                lines.append(f"States: {_notation(question['states'])}.")
    else:
        function = question["function"]
        expression = f"@{concept}[{function}]({question['input']})"
        if concept == "repeat":
            expression = f"@repeat[{function}]({question['count']}, {question['input']})"
        elif concept == "seq":
            expression = f"@seq[{function}, {question['second']}]({question['input']})"
        elif concept == "fold":
            expression = f"@fold[{function}]({question['initial']}, {_notation(question['input'])})"
        if angle == "compute":
            lines.append(f"Compute {expression}.")
        elif angle == "invert":
            lines.append(f"Find f such that @{concept}[f]({question['input']}) = {_notation(question['target'])}.")
            lines.append(f"Candidate operations: {', '.join(scope['inputs'])}.")
        elif angle == "decide":
            lines.append(f"Decide the claim: {question['claim'].rstrip('.')}.")
            lines.append(f"Check passed operations {', '.join(scope['family'])} on inputs {_notation(scope['inputs'])}.")
            lines.append("If false give a [function, input] counterexample.")
    if angle in ("induce", "create"):
        lines.append(f"{'Infer' if angle == 'induce' else 'Design'} {concept} from the evidence and goal: "
                     f"{_notation({key: value for key, value in question.items() if key not in ('state', 'roles')})}.")
        lines.append("Scope: " + _notation({key: value for key, value in scope.items() if key not in ("states", "inputs")}))
    if kind == "observation":
        lines.append("Judging uses full state, even when the display hides input details.")
    formats = {"value": 'JSON {"ok": encoded value} or {"bottom": "reason"}',
               "one_witness": "one exact candidate from the list (JSON value)",
               "all_solutions": "JSON array of all exact candidates from the list",
               "verdict": '{"true": true/false} (add "counterexample" when required)',
               "choice": "one exact option (JSON value)",
               "definition": ("an ASCII kernel expression"
                              if kind == "combinator" or kind == "object" and angle == "induce" else
                              "ASCII equations for valid, canon, abs, and every interface operation"
                              if kind == "object" else
                              "an ASCII observation expression using the granted probes")}
    lines.append("Answer format: " + formats[shape].rstrip(". ") + ".")
    return "\n".join(lines)


def task(kind, angle, seed, index, question, reference, scope, text, *, world_name,
         variant=None, answer_shape=None, show=None, opened=None):
    """Assemble a schema-v2 record while keeping the four settings independent."""
    from opulse.tasks_v2.task import (
        METHODS,
        Task,
        default_boundary,
        default_observation,
    )

    shape = answer_shape or {"compute": "value", "invert": "all_solutions", "decide": "verdict",
                             "describe": "choice", "induce": "definition", "create": "definition"}[angle]
    boundary = default_boundary()
    if opened:
        boundary["open_names"] = [opened]
        boundary["kinds"] = [kind]
    observation = default_observation()
    if show:
        observation["show"] = show
    return Task(f"{world_name}/{kind}/{angle}/{seed}/{index}", world_name, angle, kind,
                question.get("concept", kind), variant, boundary, observation, shape, "full_state",
                question, {"en": _prompt(kind, angle, question, scope, shape, opened, show)}, reference,
                {"method": METHODS[shape], "fuel": 20000, "scope": scope},
                {"generator": f"tasks_v2.angles.{kind}", "seed": seed, "index": index})
