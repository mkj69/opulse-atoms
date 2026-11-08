"""Declarable objects (docs/spec/atoms-v2.md, section 4)."""

from __future__ import annotations

import itertools
import random
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import replace

from opulse.atoms import nodes as n
from opulse.atoms.check import check_definition
from opulse.atoms.kernel import Atom, Defn, evaluate
from opulse.atoms.library import VerifyRequest, VerifyResult
from opulse.atoms.spec import ObjectSpec, OperationSpec, compute_layer, is_host_rule
from opulse.atoms.values import (
    Bottom,
    Card,
    Ok,
    Unknown,
    outcome_equal,
    truth,
    value_equal,
)


def _host_callable(rule):
    """The Python callable named by a layer-0 host rule {"host": "module:qualname", ...}."""
    import importlib

    module, _, qualname = rule["host"].partition(":")
    target = importlib.import_module(module)
    for part in qualname.split("."):
        target = getattr(target, part)
    return target


def _tags(spec) -> dict:
    """Tags with named fields as (name, sort) pairs; only ``{"items": sort}`` stays a dict (spec 4.1)."""
    return {tag: fields if isinstance(fields, dict) and set(fields) == {"items"}
            else list(fields.items()) if isinstance(fields, dict) else fields
            for tag, fields in (spec.tags or {}).items()}


def _objects(lib):
    objects = {obj.name: obj for obj in getattr(lib.world, "objects", ())}
    for definition in getattr(lib, "records", lambda: lib.definitions)().values():
        if definition.kind == "object" and isinstance(definition.spec, ObjectSpec):
            objects[definition.spec.name] = definition.spec
    return objects


def _is_public(spec, name):
    if name in spec.interface:
        return True
    if name == f"{spec.name}.make":
        return "make" in spec.interface or f"make_{spec.name.lower()}" in spec.interface
    return name.startswith(spec.name + ".") and name.removeprefix(spec.name + ".") in spec.interface


def sealed_private_names(lib) -> set[str]:
    """Generated operations that are not public interfaces of sealed objects."""
    private = set()
    for spec in _objects(lib).values():
        if spec.sealed:
            private.update(item.name for item in object_atoms(spec, lib)
                           if not _is_public(spec, item.name))
    return private


def _interface_positions(spec, lib, name):
    for operation in getattr(lib.world, "operations", ()):
        if operation.name == name:
            return tuple(index for index, edge in enumerate(operation.inputs)
                         if edge.sort == spec.name)
    definition = getattr(lib, "records", lambda: lib.definitions)().get(name)
    if definition is not None and isinstance(definition.spec, OperationSpec):
        return tuple(index for index, edge in enumerate(definition.spec.inputs)
                     if edge.sort == spec.name)
    generated = {item.name: item for item in object_atoms(spec, lib)}
    if name in generated:
        if spec.form == "refine":
            return (0,) if name != f"{spec.name}.make" and not name.endswith("._invalid") else ()
        if spec.form == "compose":
            suffix = name.removeprefix(spec.name + ".")
            if suffix in spec.tags:
                fields = _tags(spec)[suffix]
                return ((0,) if fields["items"] == spec.name else ()) if isinstance(fields, dict) else tuple(
                    index for index, (_, sort) in enumerate(fields) if sort == spec.name)
            if suffix == "fold":
                return (len(generated[name].params) - 1,)
            return (0,) if suffix == "size" or suffix.startswith(("is_",)) or suffix in {
                field for fields in _tags(spec).values() if not isinstance(fields, dict)
                for field, _ in fields} or suffix == "_items" else ()
    return None


def _group_problems(spec, lib):
    if not spec.group:
        return []
    members = set(spec.group) | {spec.name}
    objects = _objects(lib) | {spec.name: spec}
    problems = []
    if members - objects.keys():
        problems.append(f"group missing sorts: {sorted(members - objects.keys())}")
    base = False
    for name in members & objects.keys():
        member = objects[name]
        if member.form != "compose" or set(member.group) | {name} != members:
            problems.append(f"{name}: inconsistent compose group")
            continue
        for fields in _tags(member).values():
            sorts = (fields["items"],) if isinstance(fields, dict) else (pair[1] for pair in fields)
            sorts = tuple(sorts)
            base |= not any(sort in members for sort in sorts)
            if any(any(part in sort for part in ("->", "→")) and
                   any(name in sort for name in members) for sort in sorts):
                problems.append(f"{name}: group sort in a negative function position")
    if not base:
        problems.append("recursive group needs a base tag")
    return problems


def _field_matches(value, sort, objects):
    expected = {"int": int, "str": str, "bool": bool}.get(sort)
    if expected is not None:
        return type(value) is expected or (sort == "bool" and isinstance(value, Card)
                                                   and value.sort == "bool" and value.tag in ("true", "false")
                                                   and not value.fields)
    if sort in objects:
        if isinstance(value, Card):
            return value.sort == sort or (sort.lower() in ("value", "any")
                                          and objects[sort].form == "given")
        return objects[sort].form == "given"
    return True


def object_atoms(spec: ObjectSpec, lib) -> list[Atom | Defn]:
    """Generate operations; ``items`` takes a tuple, and refinement binds the base to ``x``."""
    if spec.form == "constant":
        return [Defn(spec.name, (), spec.body, kind="object")]
    if spec.form == "given":
        return []
    if spec.form == "compose":
        problems = _group_problems(spec, lib)
        if problems:
            raise ValueError("; ".join(problems))
        result: list[Atom | Defn] = []
        group = set(spec.group) | {spec.name}
        members = _objects(lib) | {spec.name: spec}
        if any(isinstance(fields, dict) and fields["items"] in group
               for fields in _tags(spec).values()):
            result.extend((Atom(f"{spec.name}._empty", 1, lambda items: not items, kind="object"),
                           Atom(f"{spec.name}._head", 1, lambda items: items[0], kind="object"),
                           Atom(f"{spec.name}._tail", 1, lambda items: items[1:], kind="object"),
                           Atom(f"{spec.name}._length", 1, len, kind="object"),
                           Atom(f"{spec.name}._cons", 2, lambda head, tail: (head, *tail), kind="object")))

        def size(value):
            if not isinstance(value, Card) or value.sort not in group:
                return Bottom("wrong_tag")
            member = members.get(value.sort)
            if member is None or value.tag not in _tags(member):
                return Bottom("wrong_tag")
            fields = _tags(member)[value.tag]
            sorts = ((fields["items"],) * len(value.fields) if isinstance(fields, dict)
                     else tuple(sort for _, sort in fields))
            if len(value.fields) != len(sorts):
                return Bottom("wrong_tag")
            total = 1
            for item, sort in zip(value.fields, sorts):
                if sort in group:
                    child = size(item)
                    if isinstance(child, Bottom):
                        return child
                    total += child
            return total

        result.append(Atom(f"{spec.name}.size", 1, size, kind="object"))
        fields_by_name = defaultdict(list)
        for tag, fields in _tags(spec).items():
            items = isinstance(fields, dict)
            arity = 1 if items else len(fields)
            sorts = (fields["items"],) if items else tuple(sort for _, sort in fields)

            def construct(*values, tag=tag, items=items, sorts=sorts):
                if items and not isinstance(values[0], tuple):
                    return Bottom("invalid")
                fields_to_check = values[0] if items else values
                if any(not _field_matches(value, sort, members)
                       for value, sort in zip(fields_to_check, itertools.repeat(sorts[0]) if items else sorts)):
                    return Bottom("invalid")
                return Card(spec.name, tag, values[0] if items else values)

            result.append(Atom(f"{spec.name}.{tag}", arity, construct,
                               cost=0 if arity == 0 else 1, kind="object"))
            result.append(Atom(f"{spec.name}.is_{tag}", 1,
                               lambda value, tag=tag: isinstance(value, Card) and
                               value.sort == spec.name and value.tag == tag, kind="object"))
            if not items:
                for index, (field, _) in enumerate(fields):
                    fields_by_name[field].append((tag, index))
        for field, locations in fields_by_name.items():
            positions = dict(locations)

            def accessor(value, positions=positions):
                if not isinstance(value, Card) or value.sort != spec.name or value.tag not in positions:
                    return Bottom("wrong_tag")
                return value.fields[positions[value.tag]]

            result.append(Atom(f"{spec.name}.{field}", 1, accessor, kind="object"))
        item_tags = {tag for tag, fields in _tags(spec).items() if isinstance(fields, dict)}
        if item_tags:
            result.append(Atom(f"{spec.name}._items", 1,
                               lambda value: value.fields if isinstance(value, Card)
                               and value.sort == spec.name and value.tag in item_tags
                               else Bottom("wrong_tag"), kind="object"))
        result.append(_fold_defn(spec, lib))
        return result

    members = _objects(lib)
    base = members.get(spec.base)

    def unbox(value):
        if not isinstance(value, Card) or value.sort != spec.name:
            return Bottom("wrong_tag")
        if value.tag != "val" or len(value.fields) != 1 or not _field_matches(
                value.fields[0], spec.base, members):
            return Bottom("invalid")
        if base is not None and base.form == "compose":
            stored = value.fields[0]
            fields = _tags(base).get(stored.tag)
            if fields is None:
                return Bottom("invalid")
            if isinstance(fields, dict):
                valid_fields = all(_field_matches(item, fields["items"], members)
                                   for item in stored.fields)
            else:
                valid_fields = len(stored.fields) == len(fields) and all(
                    _field_matches(item, field_sort, members)
                    for item, (_, field_sort) in zip(stored.fields, fields))
            if not valid_fields:
                return Bottom("invalid")
        return value.fields[0]

    result = [Atom(f"{spec.name}._stored", 1, unbox, kind="object")]
    # A given layer-0 object may state valid/canon as a host rule: expose it as a counted atom.
    host_rules = {}
    for field_name in ("valid", "canon"):
        rule = getattr(spec, field_name)
        if is_host_rule(rule):
            atom = Atom(f"{spec.name}._host_{field_name}", 1, _host_callable(rule), kind="object")
            result.append(atom)
            host_rules[field_name] = n.Call(atom.name, (n.Var("x"),))
    if host_rules:
        spec = replace(spec, **host_rules)

    def bind(node):
        return n.Let("x", n.Var("_value"), node)

    if spec.canon is not None and spec.canon_cost == "free":
        def free_canon(value):
            return evaluate(spec.canon, {"x": value}, lib.scope(), dialect=lib.dialect).outcome

        result.append(Atom(f"{spec.name}._canon_free", 1, free_canon, cost=0, kind="object"))
    canonical = (n.Var("_value") if spec.canon is None else
                 n.Call(f"{spec.name}._canon_free", (n.Var("_value"),)) if spec.canon_cost == "free" else
                 bind(spec.canon))
    result.extend((Atom(f"{spec.name}._pack", 1,
                        lambda value: Card(spec.name, "val", (value,)), kind="object"),
                   Atom(f"{spec.name}._invalid", 0, lambda: Bottom("invalid"),
                        cost=0, kind="object")))
    result.append(Defn(f"{spec.name}.make", ("_value",),
                       n.Case(((n.Test(bind(spec.valid)),
                                n.Call(f"{spec.name}._pack", (canonical,))),),
                              n.Call(f"{spec.name}._invalid")), kind="object"))
    result.append(Defn(f"{spec.name}.base", ("item",),
                       n.Let("x", n.Call(f"{spec.name}._stored", (n.Var("item"),)),
                             n.Case(((n.Test(spec.valid), n.Var("x")),),
                                    n.Lit(Bottom("invalid")))), kind="object"))
    base_spec = _objects(lib).get(spec.base)
    base_tags = list(_tags(base_spec).values()) if base_spec and base_spec.tags else []
    fields = spec.extra.get("fields", ())
    if not fields and len(base_tags) == 1 and not isinstance(base_tags[0], dict):
        fields = [field for field, _ in base_tags[0]]
    for field in fields:
        unwrapped = n.Call(f"{spec.name}.base", (n.Var("item"),))
        canonical_item = n.Call(f"{spec.name}.make", (unwrapped,))
        canonical_base = n.Call(f"{spec.name}.base", (canonical_item,))
        result.append(Defn(f"{spec.name}.{field}", ("item",),
                           n.Call(f"{spec.base}.{field}", (canonical_base,)),
                           kind="object"))
    return result


def _fold_defn(spec: ObjectSpec, lib) -> Defn:
    """A structural catamorphism with a single measured recursion over a mutual group."""
    objects = _objects(lib) | {spec.name: spec}
    group = tuple(sorted(set(spec.group) | {spec.name}))
    params = tuple(f"on_{sort}_{tag}" for sort in group for tag in objects[sort].tags)

    def folded_field(sort, value):
        return n.Call("fold_local", (value,)) if sort in group else value

    cases = []
    for sort in group:
        for tag, fields in _tags(objects[sort]).items():
            if isinstance(fields, dict):
                item_sort = fields["items"]
                items = n.Call(f"{sort}._items", (n.Var("item"),))
                if item_sort in group:
                    item_body = n.Case(((n.Test(n.Call(f"{sort}._empty", (n.Var("rest"),))), n.Lit(())),),
                                       n.Call(f"{sort}._cons", (n.Call("fold_local", (
                                           n.Call(f"{sort}._head", (n.Var("rest"),)),)),
                                           n.Call("fold_items", (n.Call(f"{sort}._tail", (n.Var("rest"),)),)))))
                    items = n.Rec("fold_items", ("rest",), item_body, (items,),
                                  n.Call(f"{sort}._length", (n.Var("rest"),)))
                args = (items,)
            else:
                args = tuple(folded_field(field_sort, n.Call(f"{sort}.{field}", (n.Var("item"),)))
                             for field, field_sort in fields)
            cases.append((n.Test(n.Call(f"{sort}.is_{tag}", (n.Var("item"),))),
                          n.Call(f"on_{sort}_{tag}", args)))
    body = n.Rec("fold_local", ("item",),
                 n.Case(tuple(cases), n.Lit(Bottom("wrong_tag"))), (n.Var("value"),),
                 n.Call(f"{spec.name}.size", (n.Var("item"),)))
    return Defn(f"{spec.name}.fold", (*params, "value"), body, kind="combinator")


def check_object(defn, lib) -> list[str]:
    spec = defn.spec
    problems = _group_problems(spec, lib) if defn.kind == "object" else []
    if defn.kind == "object" and spec.form == "refine":
        expressions = tuple(node for node in (spec.valid, spec.canon) if node is not None)
        called = set().union(*(n.references(node) for node in expressions))
        declared = set(defn.depends_on)
        scope = lib.scope()
        records = getattr(lib, "records", lambda: lib.definitions)()
        # Compatibility (round 7): an object may list more dependencies than valid/canon use
        # (helpers of its interface); the computed references are added for layers and hashes.
        if defn.body is None and len(declared) != len(defn.depends_on):
            problems.append("depends_on lists a name twice")

        def resolve(name):
            return records.get(name) or scope.resolve(name)

        for node in expressions:
            surrogate = replace(defn, body=node, depends_on=tuple(n.references(node)))
            # valid/canon get name, node and dependency checks; sort comparisons stay with the
            # object's own verification (declared helper sorts are often approximate).
            problems.extend(problem for problem in check_definition(surrogate, lib.world, resolve)
                            if problem != "depends_on does not match body references" and
                            not problem.startswith("layer must be ") and " argument " not in problem
                            and not problem.startswith("output: "))
        try:
            def layer_of(name):
                if any(op.name == name for op in lib.world.operations):
                    return 0
                owner = records.get(name.split(".", 1)[0]) if "." in name else None
                if owner is not None and owner.kind == "object":
                    return owner.layer
                target = resolve(name)
                return target.layer if hasattr(target, "layer") else 0

            expected = compute_layer(declared | called if defn.body is None else called, layer_of)
            if defn.layer < expected:  # a definition may sit higher than its dependencies require
                problems.append(f"layer must be {expected}, got {defn.layer}")
        except (AttributeError, KeyError, TypeError):
            pass
        if spec.canon is not None and spec.valid is None:
            problems.append("canon requires valid")
        for name, node in (("valid", spec.valid), ("canon", spec.canon)):
            if node is None:
                continue
            for item in n.walk(node):
                if isinstance(item, n.Blocks):
                    problems.append(f"{name} may not use Blocks")
                if isinstance(item, n.Rec) and (isinstance(item.measure, str) or item.measure is None):
                    problems.append(f"{name} Rec needs a measure node")
    stored = list(getattr(lib, "records", lambda: lib.definitions)().values())
    for candidate in (defn, *stored):
        if not isinstance(candidate.body, n.NODE_TYPES):
            continue
        references = n.references(candidate.body)
        for obj in _objects(lib).values():
            if not obj.sealed or _is_public(obj, candidate.name):
                continue
            private = sealed_private_names(lib) | {
                item.name for item in object_atoms(obj, lib) if not _is_public(obj, item.name)}
            for reference in references:
                if reference in private or (reference.startswith(obj.name + ".") and
                                            not _is_public(obj, reference)):
                    problems.append(f"{candidate.name}: private sealed operation {reference}")
            for item in n.walk(candidate.body):
                if (isinstance(item, n.Call) and item.fn.startswith(str(obj.base) + ".") and
                        any(isinstance(arg, n.Call) and arg.fn == f"{obj.name}.base"
                            for arg in item.args)):
                    problems.append(f"{candidate.name}: reads sealed representation")
    return problems


def _run_node(node, value, lib):
    return evaluate(node, {"x": value}, lib.scope(), dialect=lib.dialect)


def _invoke(lib, name, args):
    return lib.run(name, tuple(args))


def _map_value(mapping, value, lib):
    if isinstance(mapping, str):
        return _invoke(lib, mapping, (value,)).outcome
    result = mapping(value)
    return result if isinstance(result, (Ok, Bottom, Unknown)) else Ok(result)


def _verify_compose(spec, lib, request):
    """Check constructors using domain values and ``extra['witnesses']`` values.

    Supply a sequence of values for field sorts missing from the domain, such as
    ``extra={'witnesses': (1,)}`` for a list of ints. Successful constructors
    supply witnesses for later recursive tags (for example nil before cons).
    """
    problems = _group_problems(spec, lib)
    if problems:
        return VerifyResult(False, (), problems, [])
    objects = _objects(lib) | {spec.name: spec}
    candidates = []

    def add_witness(value):
        if not any(value_equal(value, candidate) for candidate in candidates):
            candidates.append(value)
        if isinstance(value, Card):
            for field in value.fields:
                add_witness(field)
        elif isinstance(value, (tuple, list)):
            for item in value:
                add_witness(item)

    for row in request.domain:
        for item in row:
            add_witness(item)
    for value in request.extra.get("witnesses", ()):
        add_witness(value)
    steps = []
    untested = []
    built = 0
    field_sorts = {sort for fields in _tags(spec).values()
                   for sort in ((fields["items"],) if isinstance(fields, dict)
                                else (field_sort for _, field_sort in fields))}
    for name, member in objects.items():
        if member.form != "compose" or name != spec.name and name not in field_sorts:
            continue
        for tag, fields in _tags(member).items():
            if fields:
                continue
            outcome = lib.run(f"{name}.{tag}", ())
            steps.append(outcome.steps)
            if (isinstance(outcome.outcome, Ok) and isinstance(outcome.outcome.value, Card)
                    and outcome.outcome.value.sort == name and outcome.outcome.value.tag == tag
                    and not outcome.outcome.value.fields):
                add_witness(outcome.outcome.value)
                if name == spec.name:
                    built += 1
            elif name == spec.name:
                problems.append(f"finite_values constructor {tag} failed: {outcome.outcome!r}")
    for tag, fields in _tags(spec).items():
        if not fields:
            continue
        sorts = (fields["items"],) if isinstance(fields, dict) else tuple(sort for _, sort in fields)
        choices = []
        for sort in sorts:
            matching = [value for value in candidates if _field_matches(value, sort, objects)]
            if not matching:
                untested.append(tag)
                break
            choices.append(matching)
        if len(choices) != len(sorts):
            continue
        successful = False
        known_rows = (value.fields for value in candidates if isinstance(value, Card)
                      and value.sort == spec.name and value.tag == tag
                      and (isinstance(fields, dict) or len(value.fields) == len(sorts)))
        for arguments in itertools.chain(known_rows, itertools.product(*choices)):
            supplied = (tuple(arguments),) if isinstance(fields, dict) else arguments
            result = lib.run(f"{spec.name}.{tag}", supplied)
            steps.append(result.steps)
            fields_out = result.outcome.value.fields if isinstance(result.outcome, Ok) and isinstance(
                result.outcome.value, Card) else ()
            if isinstance(result.outcome, Bottom):
                continue
            if (not isinstance(result.outcome, Ok) or
                    not isinstance(result.outcome.value, Card) or
                    result.outcome.value.sort != spec.name or result.outcome.value.tag != tag or
                    len(fields_out) != len(arguments) or
                    not all(_field_matches(value, sort, objects) for value, sort in
                            zip(fields_out, sorts if not isinstance(fields, dict)
                                else itertools.repeat(sorts[0])))):
                problems.append(f"finite_values constructor {tag} failed: {result.outcome!r}")
                break
            add_witness(result.outcome.value)
            successful = True
            break
        if problems:
            break
        if not successful:
            problems.append(f"finite_values constructor {tag} has no successful witness")
            break
        if not any(sort in set(spec.group) | {spec.name} for sort in sorts):
            built += 1
    if not built:
        problems.append("finite_values requires a built base tag")
    request.scope["untested_tags"] = untested
    checks = ["finite_values" if not untested else "finite_values_partial"] if not problems else []
    if spec.extra.get("same_as") is not None:
        checks.append("same_as")
        canonical = [(value, value) for value in candidates if isinstance(value, Card)
                     and value.sort == spec.name]
        interface_ops = {name: _interface_positions(spec, lib, name) or () for name in spec.interface}
        interface_ops.update(request.extra.get("interface_ops", {}))
        if request.method == "sampled":
            sampled_problems, sampled_steps = _sampled_problems(lib, request, canonical,
                                                                 interface_ops, lambda value: value)
            problems.extend(sampled_problems)
            steps.extend(sampled_steps)
            if not sampled_problems:
                checks.append("sampled")
        elif request.extra.get("abs") is None:
            problems.append("same_as requires abs_commutes for exhaustive or bounded verification")
        else:
            abs_problems = _abstraction_problems(spec, lib, request, canonical, interface_ops,
                                                 lambda value: value)
            problems.extend(abs_problems)
            if not abs_problems:
                checks.append("abs_commutes")
    return VerifyResult(not problems, tuple(checks), problems, steps)


def _abstraction_problems(spec, lib, request, canonical, interface_ops, wrapped):
    problems = []
    if request.method not in ("exhaustive", "bounded"):
        problems.append("abs_commutes requires exhaustive verification")
    pairs = request.extra.get("interface_pairs", ())
    if not pairs:
        problems.append("abs_commutes needs at least one interface pair")
    if not canonical:
        problems.append("abs_commutes needs at least one valid input")
    declared = set(spec.interface)
    supplied = [invented for invented, _ in pairs]
    if declared - set(supplied):
        problems.append(f"abs_commutes missing interface operations {sorted(declared - set(supplied))}")
    for invented, given in pairs:
        positions = interface_ops.get(invented, (0,))
        operation = lib.scope().resolve(invented)
        reference = lib.scope().resolve(given)
        if operation is None or reference is None:
            problems.append(f"abs_commutes unknown interface pair {invented}/{given}")
            continue
        arity = len(operation.params) if isinstance(operation, Defn) else operation.arity
        reference_arity = len(reference.params) if isinstance(reference, Defn) else reference.arity
        if (arity != reference_arity or any(type(position) is not int or position < 0 or position >= arity
                                            for position in positions)):
            problems.append(f"abs_commutes invalid interface pair {invented}/{given}")
            continue
        for inputs in itertools.product((item[0] for item in canonical), repeat=len(positions)):
            arguments = list(request.extra.get("op_args", {}).get(invented, (0,) * arity))
            if len(arguments) != arity:
                problems.append(f"abs_commutes invalid arguments for {invented}")
                break
            for position, item in zip(positions, inputs):
                arguments[position] = wrapped(item)
            invented_result = _invoke(lib, invented, arguments).outcome
            mapped = [_map_value(request.extra["abs"], wrapped(value), lib) for value in inputs]
            if any(not isinstance(item, Ok) for item in mapped):
                problems.append(f"abs_commutes {invented} input {inputs!r}")
                break
            given_args = arguments.copy()
            for position, item in zip(positions, mapped):
                given_args[position] = item.value
            given_result = _invoke(lib, given, given_args).outcome
            actual = (_map_value(request.extra["abs"], invented_result.value, lib)
                      if isinstance(invented_result, Ok) and
                      isinstance(invented_result.value, Card) and
                      invented_result.value.sort == spec.name else invented_result)
            if not outcome_equal(actual, given_result):
                problems.append(f"abs_commutes {invented}/{given} at {inputs!r}: {actual!r} != {given_result!r}")
                break
    return problems


def _sampled_problems(lib, request, canonical, interface_ops, wrapped):
    problems = []
    steps = []
    reference_ops = request.extra.get("reference_ops", {})
    arities = {name: len(positions) for name, positions in interface_ops.items()}
    count = request.extra.get("count", 32)
    if (not arities or set(arities) != set(reference_ops) or request.seed is None or
            not canonical or type(count) is not int or count <= 0):
        return ["sampled needs a seed, valid input and reference for each interface operation"], steps
    programs = random_interface_programs(arities, count,
                                         request.seed, request.extra.get("depth", 3))

    def rename(node):
        if isinstance(node, n.Call):
            return n.Call(reference_ops[node.fn], tuple(rename(arg) for arg in node.args))
        return node

    for value, _ in canonical:
        for program in programs:
            actual = evaluate(program, {"x": wrapped(value)}, lib.scope(), dialect=lib.dialect)
            expected = evaluate(rename(program), {"x": wrapped(value)}, lib.scope(),
                                dialect=lib.dialect)
            steps.append(actual.steps + expected.steps)
            if not outcome_equal(actual.outcome, expected.outcome):
                problems.append(f"sampled interface mismatch at {value!r}, {program!r}")
                break
        if problems:
            break
    return problems, steps


def verify_object(defn, lib, request: VerifyRequest) -> VerifyResult:
    spec = defn.spec
    checks = []
    problems = []
    steps = []
    if spec.form == "compose":
        return _verify_compose(spec, lib, request)
    if spec.form != "refine":
        return VerifyResult(True, (), [], [])
    domain = [row[0] if len(row) == 1 else row for row in request.domain]
    canonical = []
    for value in domain:
        validity = _run_node(spec.valid, value, lib)
        steps.append(validity.steps)
        if not isinstance(validity.outcome, Ok):
            problems.append(f"valid not total at {value!r}: {validity.outcome!r}")
            continue
        try:
            is_valid = truth(validity.outcome.value)
        except TypeError:
            problems.append(f"valid not boolean at {value!r}")
            continue
        if not is_valid:
            continue
        canon = _run_node(spec.canon, value, lib) if spec.canon is not None else None
        if canon is not None:
            steps[-1] += canon.steps if spec.canon_cost != "free" else 0
        outcome = canon.outcome if canon is not None else Ok(value)
        if not isinstance(outcome, Ok):
            problems.append(f"canon_total at {value!r}: {outcome!r}")
            continue
        canonical.append((value, outcome.value))
    if not problems:
        checks.append("canon_total")
    for value, normalized in canonical:
        again = _run_node(spec.canon, normalized, lib).outcome if spec.canon is not None else Ok(normalized)
        if not isinstance(again, Ok) or not value_equal(again.value, normalized):
            problems.append(f"canon_idempotent at {value!r}: {again!r}")
            break
    else:
        checks.append("canon_idempotent")
    for value, normalized in canonical:
        result = _run_node(spec.valid, normalized, lib).outcome
        try:
            still_valid = isinstance(result, Ok) and truth(result.value)
        except TypeError:
            still_valid = False
        if not still_valid:
            problems.append(f"canon_keeps_valid at {value!r}: {result!r}")
            break
    else:
        checks.append("canon_keeps_valid")
    groups = []
    for value, normalized in canonical:
        for norm, members in groups:
            if value_equal(norm, normalized):
                members.append(value)
                break
        else:
            groups.append((normalized, [value]))
    interface_ops = {}
    for name in spec.interface:
        positions = _interface_positions(spec, lib, name)
        if positions is None:
            problems.append(f"respects_canon unknown positions for {name}")
        else:
            interface_ops[name] = tuple(positions)
    for name, positions in request.extra.get("interface_ops", {}).items():
        if name in interface_ops:
            interface_ops[name] = tuple(sorted(set(interface_ops[name]) | set(positions)))
        elif name not in spec.interface:
            interface_ops[name] = tuple(positions)
    def wrapped(value):
        return Card(spec.name, "val", (value,))

    for name, positions in interface_ops.items():
        operation = lib.scope().resolve(name)
        if operation is None:
            problems.append(f"respects_canon missing operation {name}")
            continue
        arity = len(operation.params) if isinstance(operation, Defn) else operation.arity
        if any(type(position) is not int or position < 0 or position >= arity for position in positions):
            problems.append(f"respects_canon invalid positions for {name}")
            continue
        if isinstance(operation, Defn) and f"{spec.name}.base" in n.references(operation.body):
            continue
        for index in positions:
            for normalized, members in groups:
                others = [position for position in positions if position != index]
                for context in itertools.product((item[0] for item in groups), repeat=len(others)):
                    args = list(request.extra.get("op_args", {}).get(name, (0,) * arity))
                    for position, item in zip(others, context):
                        args[position] = wrapped(item)
                    baseline = None
                    for value in members:
                        args[index] = wrapped(value)
                        outcome = _invoke(lib, name, args).outcome
                        if baseline is not None and not outcome_equal(baseline, outcome):
                            problems.append(f"respects_canon {name} at {args!r}: {baseline!r} != {outcome!r}")
                            break
                        baseline = outcome
                    if problems and problems[-1].startswith("respects_canon"):
                        break
                if problems and problems[-1].startswith("respects_canon"):
                    break
            if problems and problems[-1].startswith("respects_canon"):
                break
    if not any(item.startswith("respects_canon") for item in problems):
        checks.append("respects_canon")
    abstraction = request.extra.get("abs")
    same_as = spec.extra.get("same_as")
    if same_as is not None:
        checks.append("same_as")
        if abstraction is None and request.method != "sampled":
            problems.append("same_as requires abs_commutes for exhaustive or bounded verification")
        elif abstraction is None and not request.extra.get("reference_ops"):
            problems.append("same_as sampled comparison needs reference_ops")
    if abstraction is not None:
        abs_problems = _abstraction_problems(spec, lib, request, canonical, interface_ops, wrapped)
        problems.extend(abs_problems)
        if not abs_problems:
            checks.append("abs_commutes")
    elif request.extra.get("reference_ops"):
        sampled_problems, sampled_steps = _sampled_problems(lib, request, canonical, interface_ops,
                                                             wrapped)
        problems.extend(sampled_problems)
        steps.extend(sampled_steps)
        if not sampled_problems:
            checks.append("sampled")
    elif request.method == "sampled":
        problems.append("sampled comparison needs reference_ops and a seed")
    return VerifyResult(not problems, tuple(checks), problems, steps)


def random_interface_programs(ops, count: int, seed: int, depth: int) -> list[n.Node]:
    """Create reproducible interface-call trees; ``ops`` maps names to arities."""
    arities = dict(ops) if isinstance(ops, Mapping) else {
        item if isinstance(item, str) else item[0]:
        1 if isinstance(item, str) else item[1] for item in ops}
    if not arities or count < 0 or depth < 0 or any(arity < 0 for arity in arities.values()):
        raise ValueError("need operations, nonnegative count and depth")
    generator = random.Random(seed)

    def build(remaining):
        if not remaining:
            return n.Var("x")
        name = generator.choice(sorted(arities))
        return n.Call(name, tuple(build(remaining - 1) for _ in range(arities[name])))

    return [build(depth) for _ in range(count)]
