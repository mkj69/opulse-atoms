"""Generator-side object constructors and finite-domain obligations.

The core treats mapping tags as variable-length ``items`` tags. Record-shaped
mapping tags are normalized before a generated definition enters the library.
"""

from __future__ import annotations

import itertools
from collections import defaultdict
from dataclasses import replace

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms import objects as core_objects
from opulse.atoms.library import VerifyRequest
from opulse.atoms.spec import ObjectSpec
from opulse.atoms.values import Card, Ok, outcome_equal, truth, value_equal
from opulse.gen_v2.admit import KindHook, register_hook
from opulse.gen_v2.base import Signature


def normalize_object_spec(spec: ObjectSpec) -> ObjectSpec:
    """Convert record mappings to ordered field pairs without modifying the core."""
    if spec.form == "compose" and any(isinstance(fields, dict) and "items" not in fields
                                      for fields in spec.tags.values()):
        return replace(spec, tags={tag: list(fields.items()) if isinstance(fields, dict)
                                   and "items" not in fields else fields
                                   for tag, fields in spec.tags.items()})
    return spec


def object_atoms(spec: ObjectSpec, state) -> tuple[list, dict[str, Signature]]:
    """Return the kernel operations and typed signatures introduced by an object."""
    if spec.form == "constant":
        return [kernel.Defn(spec.name, (), spec.body, kind="object")], {}
    if spec.form == "given":
        return [], {}
    spec = normalize_object_spec(spec)
    atoms = core_objects.object_atoms(spec, state.library)
    if spec.form == "refine":
        atoms = [replace(atom, layer=0) if isinstance(atom, kernel.Defn) and
                 atom.name == f"{spec.name}.make" else atom for atom in atoms]
    signatures = {}
    if spec.form == "compose":
        fields = defaultdict(list)
        signatures[f"{spec.name}.size"] = Signature((spec.name,), "int")
        for tag, members in spec.tags.items():
            sorts = (members["items"],) if isinstance(members, dict) else tuple(sort for _, sort in members)
            signatures[f"{spec.name}.{tag}"] = Signature(sorts, spec.name)
            signatures[f"{spec.name}.is_{tag}"] = Signature((spec.name,), "bool")
            if not isinstance(members, dict):
                for field, sort in members:
                    fields[field].append(sort)
        for field, sorts in fields.items():
            signatures[f"{spec.name}.{field}"] = Signature((spec.name,), sorts[0])
    else:
        signatures[f"{spec.name}.make"] = Signature((spec.base,), spec.name)
        signatures[f"{spec.name}.base"] = Signature((spec.name,), spec.base)
        for atom in atoms:
            field = atom.name.removeprefix(spec.name + ".")
            if field not in ("make", "base") and not field.startswith("_"):
                base_signature = state.signature(f"{spec.base}.{field}")
                if base_signature:
                    signatures[atom.name] = Signature((spec.name,), base_signature.output)
    return atoms, signatures


def sealed_violation(defn, state) -> str | None:
    """Report a non-interface reference to a sealed representation."""
    objects = list(state.library.world.objects)
    objects += [item.spec for item in state.library.definitions.values()
                if item.kind == "object" and isinstance(item.spec, ObjectSpec)]
    if defn.kind == "object" and all(obj.name != defn.spec.name for obj in objects):
        objects.append(defn.spec)
    for obj in objects:
        if not obj.sealed or defn.name in obj.interface:
            continue
        for reference in n.references(defn.body):
            if reference.startswith(obj.name + ".") and reference not in obj.interface:
                return f"sealed: {defn.name} reads {reference} outside {obj.name} interface"
    return None


def _check(defn, lib):
    spec = defn.spec
    problems = []
    expected_layer = 1 + max((getattr(lib.resolve(name), "layer", 0)
                              for name in n.references(defn.body)), default=0)
    if defn.layer != expected_layer:
        problems.append(f"layer must be {expected_layer}, got {defn.layer}")
    if spec.form == "compose":
        members = set(spec.group) | {spec.name}
        if len(members) > 1:
            problems.append("recursive group requires atomic multi-sort admission")
        for fields in spec.tags.values():
            sorts = fields.values() if isinstance(fields, dict) else (sort for _, sort in fields)
            for sort in sorts:
                if "->" in sort or any(mark in sort for mark in ("[", "]")) and sort in members:
                    problems.append("strictly_positive: function field in recursive group")
                if sort not in members and sort not in {obj.name for obj in lib.world.objects} and sort not in lib.definitions:
                    problems.append(f"unknown field sort: {sort}")
        if not any(all(sort not in members for sort in (fields.values() if isinstance(fields, dict)
                        else (item[1] for item in fields))) for fields in spec.tags.values()):
            problems.append("finite_values: recursive sort needs a base tag")
    if spec.form == "refine":
        if spec.base not in {obj.name for obj in lib.world.objects} and spec.base not in lib.definitions:
            problems.append(f"unknown base sort: {spec.base}")
        for rule in (spec.valid, spec.canon):
            if rule is not None and (not isinstance(rule, n.NODE_TYPES) or any(
                    isinstance(node, n.Blocks) or isinstance(node, n.Rec) and
                    (node.measure is None or isinstance(node.measure, str)) for node in n.walk(rule))):
                problems.append("valid and canon need terminating kernel nodes")
    if spec.sealed:
        for name in spec.interface:
            if lib.scope().resolve(name) is None:
                problems.append(f"sealed: missing interface operation {name}")
    class View:
        library = lib
    violation = sealed_violation(defn, View())
    if violation:
        problems.append(violation)
    return problems


def _request(state, candidate):
    spec = candidate.defn.spec
    values = (state.sorts[spec.base].values if spec.form == "refine" else
              candidate.new_sorts[0].values if candidate.new_sorts else ())
    if spec.form == "constant":
        values = (None,)
    domain = tuple((value,) for value in values)
    return VerifyRequest("exhaustive", domain,
                         {"domain": f"all {len(values)} probe values of {spec.base if spec.form == 'refine' else spec.name}",
                          "size": len(domain)})


def _eval(state, node, value):
    return kernel.evaluate(node, {"x": value}, state.library.scope(),
                           kernel.Limits(fuel=state.world.fuel), dialect=state.world.dialect)


def _run(state, candidate, request):
    if candidate.request is None:
        request = _request(state, candidate)
        candidate.request = request
    spec = candidate.defn.spec
    if spec.form == "constant":
        result = kernel.call(spec.name, (), state.library.scope(),
                             kernel.Limits(fuel=state.world.fuel), dialect=state.world.dialect)
        return [((), result.outcome, result.steps)]
    results = []
    for (value,) in request.domain:
        if spec.form == "refine":
            validity = _eval(state, spec.valid, value).outcome
            try:
                if not isinstance(validity, Ok) or not truth(validity.value):
                    continue
            except TypeError:
                continue
            result = kernel.call(f"{spec.name}.make", (value,), state.library.scope(),
                                 kernel.Limits(fuel=state.world.fuel), dialect=state.world.dialect)
            if not isinstance(result.outcome, Ok):
                continue
            outcome, steps = result.outcome, result.steps
        else:
            if not isinstance(value, Card) or value.sort != spec.name or value.tag not in spec.tags:
                results.append(((value,), kernel.Bottom("invalid"), 0))
                continue
            fields = spec.tags[value.tag]
            args = (value.fields,) if isinstance(fields, dict) else value.fields
            if not isinstance(fields, dict) and len(args) != len(fields):
                results.append(((value,), kernel.Bottom("invalid"), 0))
                continue
            result = kernel.call(f"{spec.name}.{value.tag}", args, state.library.scope(),
                                 kernel.Limits(fuel=state.world.fuel), dialect=state.world.dialect)
            outcome, steps = result.outcome, result.steps
        results.append(((value,), outcome, steps))
    return results


def _unfold_witness(state, candidate, checks, problems):
    if problems:
        return
    spec = candidate.defn.spec
    scope = state.library.scope()
    if scope.resolve(spec.name) is None:
        scope = scope.extend([kernel.Defn(spec.name, (), candidate.defn.body,
                                          kind="object", layer=candidate.defn.layer)])
    limits = kernel.Limits(fuel=state.world.fuel)
    direct = kernel.evaluate(candidate.defn.body, {}, scope, limits,
                             dialect=state.world.dialect)
    promoted = kernel.call(spec.name, (), scope, limits, dialect=state.world.dialect)
    if outcome_equal(direct.outcome, promoted.outcome) and direct.steps == promoted.steps:
        checks.append("unfold_equivalence")
    else:
        problems.append("unfold_equivalence: object witness disagrees with its body")
    value = direct.outcome.value if isinstance(direct.outcome, Ok) else None
    if spec.form == "constant":
        return
    # The witness must inhabit the declared object sort.
    if not _value_in_sort(state, spec.name, value, {spec.name: spec}):
        problems.append(f"witness_value: the witness is not a value of {spec.name}: {direct.outcome!r}")
    else:
        checks.append("witness_value")


def _value_in_sort(state, sort, value, specs):
    if sort == "int":
        return type(value) is int
    if sort == "str":
        return type(value) is str
    if sort == "bool":
        return (type(value) is bool or isinstance(value, Card) and value.sort == "bool"
                and value.tag in ("true", "false") and not value.fields)
    spec = specs.get(sort)
    if spec is None:
        definition = state.library.definitions.get(sort)
        spec = definition.spec if definition is not None and definition.kind == "object" else next(
            (item for item in state.library.world.objects if item.name == sort), None)
        if spec is not None:
            specs[sort] = spec
    if spec is None or spec.form == "given":
        return sort in state.sorts and any(value_equal(value, probe) for probe in state.sorts[sort].values)
    if spec.form == "refine" and sort in state.sorts and state.sorts[sort].origin == "given":
        return any(value_equal(value, probe) for probe in state.sorts[sort].values)
    if not isinstance(value, Card) or value.sort != sort:
        return False
    if spec.form == "compose":
        if value.tag not in spec.tags:
            return False
        fields = spec.tags[value.tag]
        sorts = ([fields["items"]] * len(value.fields) if isinstance(fields, dict)
                 else [part for _, part in fields])
        return len(value.fields) == len(sorts) and all(
            _value_in_sort(state, field_sort, field, specs)
            for field, field_sort in zip(value.fields, sorts))
    if spec.form != "refine" or value.tag != "val" or len(value.fields) != 1:
        return False
    base = value.fields[0]
    if not _value_in_sort(state, spec.base, base, specs):
        return False
    try:
        validity = _eval(state, spec.valid, base).outcome
        canonical = _eval(state, spec.canon, base).outcome if spec.canon is not None else Ok(base)
        return (isinstance(validity, Ok) and truth(validity.value) and
                isinstance(canonical, Ok) and value_equal(canonical.value, base))
    except (KeyError, TypeError, ValueError, RecursionError):
        return False


def _verify(state, candidate, request, results):
    spec = candidate.defn.spec
    checks, problems = [], []
    if spec.form == "constant":
        if not results or not isinstance(results[0][1], Ok):
            problems.append("constant: closed term must evaluate Ok")
        else:
            checks.append("constant_ok")
        _unfold_witness(state, candidate, checks, problems)
        return checks, problems
    if spec.form == "compose":
        if not candidate.new_sorts or not candidate.new_sorts[0].values:
            problems.append("finite_values: no finite values")
        else:
            checks.append("finite_values")
    if spec.form in ("compose", "refine"):
        values = candidate.new_sorts[0].values if candidate.new_sorts else ()
        if (not candidate.new_sorts or candidate.new_sorts[0].name != spec.name or
                any(not _value_in_sort(state, spec.name, value, {spec.name: spec}) for value in values) or
                (spec.form == "compose" and tuple((value,) for value in values) != request.domain)):
            problems.append("values_in_sort: probe values do not match the declared object sort")
        else:
            checks.append("values_in_sort")
        if spec.form == "compose" and (len(results) != len(request.domain) or any(
                not isinstance(outcome, Ok) or not value_equal(outcome.value, args[0])
                for args, outcome, _ in results)):
            problems.append("values_in_sort: a constructor rejects a declared probe value")
    if spec.form == "refine":
        valid_values = []
        for (value,) in request.domain:
            validity = _eval(state, spec.valid, value).outcome
            try:
                if not isinstance(validity, Ok):
                    raise TypeError("not total")
                is_valid = truth(validity.value)
            except TypeError:
                problems.append(f"valid_bool: invalid result at {value!r}")
                continue
            if is_valid:
                valid_values.append(value)
        if not problems:
            checks.append("valid_bool")
        canonical = []
        for value in valid_values:
            result = _eval(state, spec.canon, value).outcome if spec.canon is not None else Ok(value)
            if not isinstance(result, Ok) or not _base_value(state, spec.base, result.value):
                problems.append(f"canon_total: {value!r} -> {result!r}")
                continue
            canonical.append((value, result.value))
        if not any(problem.startswith("canon_total") for problem in problems):
            checks.append("canon_total")
        for value, normalized in canonical:
            again = _eval(state, spec.canon, normalized).outcome if spec.canon is not None else Ok(normalized)
            if not isinstance(again, Ok) or not value_equal(again.value, normalized):
                problems.append(f"canon_idempotent: at {value!r}")
                break
        if not any(problem.startswith("canon_idempotent") for problem in problems):
            checks.append("canon_idempotent")
        for value, normalized in canonical:
            result = _eval(state, spec.valid, normalized).outcome
            try:
                kept = isinstance(result, Ok) and truth(result.value)
            except TypeError:
                kept = False
            if not kept:
                problems.append(f"canon_keeps_valid: at {value!r}")
                break
        if not any(problem.startswith("canon_keeps_valid") for problem in problems):
            checks.append("canon_keeps_valid")
        for name in spec.interface:
            signature = state.signature(name)
            if signature is None:
                signature = candidate.extra_signatures.get(name)
            if signature is None:
                problems.append(f"interface_respects_canon: missing signature {name}")
                continue
            for index, sort in enumerate(signature.inputs):
                if sort not in (spec.name, spec.base):
                    continue
                other = [state.sorts[part].values[:2] if part in state.sorts else ()
                         for position, part in enumerate(signature.inputs) if position != index]
                for left, left_canon in canonical:
                    for right, right_canon in canonical:
                        if not value_equal(left_canon, right_canon):
                            continue
                        for companions in itertools.product(*other):
                            args = list(companions)
                            left_args, right_args = args.copy(), args.copy()
                            left_args.insert(index, Card(spec.name, "val", (left_canon,)) if sort == spec.name else left)
                            right_args.insert(index, Card(spec.name, "val", (right_canon,)) if sort == spec.name else right)
                            scope = state.library.scope()
                            first = kernel.call(name, left_args, scope).outcome
                            second = kernel.call(name, right_args, scope).outcome
                            if not outcome_equal(first, second):
                                problems.append(f"interface_respects_canon: {name} argument {index + 1}")
                                break
                        if problems and problems[-1].startswith("interface_respects_canon"):
                            break
                    if problems and problems[-1].startswith("interface_respects_canon"):
                        break
        if not any(problem.startswith("interface_respects_canon") for problem in problems):
            checks.append("interface_respects_canon")
    if spec.sealed:
        violation = sealed_violation(candidate.defn, state)
        if violation:
            problems.append(violation)
        else:
            checks.append("sealed")
    _unfold_witness(state, candidate, checks, problems)
    return checks, problems


def _base_value(state, sort, value):
    if sort == "int":
        return type(value) is int
    if sort == "bool":
        return type(value) is bool or isinstance(value, Card) and value.sort == "bool"
    return isinstance(value, Card) and value.sort == sort


register_hook("object", KindHook(_check, _run, _verify))
