"""Partial and cross-world bridges (atoms-v2 spec 0.4, kind bridge)."""

from __future__ import annotations

import itertools
from dataclasses import dataclass

from opulse.atoms import kernel, nodes
from opulse.atoms.library import (
    DEFAULT_VERIFY_FUEL,
    Library,
    VerifyRequest,
    VerifyResult,
)
from opulse.atoms.spec import BridgeSpec, Definition, _free_vars
from opulse.atoms.values import (
    Bottom,
    Card,
    Ok,
    Unknown,
    outcome_equal,
    truth,
    value_equal,
)


@dataclass(frozen=True)
class BridgeContext:
    """Source and target libraries; a single Library denotes a same-world bridge."""

    source_lib: Library
    target_lib: Library


def _context(lib: Library | BridgeContext) -> BridgeContext:
    return lib if isinstance(lib, BridgeContext) else BridgeContext(lib, lib)


def _scope(context: BridgeContext) -> kernel.DictScope:
    source, target = context.source_lib, context.target_lib
    if source is target:
        return source.scope()
    target_id = f"{target.world.world}@{target.world.version}"
    active = source.scope()
    if source._attached_worlds.get(target_id) is target and isinstance(active, kernel.ChainScope):
        return active
    source_id = f"{source.world.world}@{source.world.version}"
    return kernel.ChainScope(source._runtime_local_scope(), source_id,
                             {target_id: target._runtime_local_scope()})


def runtime_bridge_defn(spec: BridgeSpec, context: BridgeContext) -> kernel.Defn:
    """Resolve map calls on the target side, and domain calls on the source side."""
    source, target = context.source_lib, context.target_lib
    if source is target:
        return bridge_defn(spec)
    source_id = f"{source.world.world}@{source.world.version}"
    target_id = f"{target.world.world}@{target.world.version}"
    source_scope, target_scope = source.local_scope(), target.local_scope()
    source_names = set(source_scope.atoms) | set(source_scope.defns)
    target_names = set(target_scope.atoms) | set(target_scope.defns)
    if source._attached_worlds.get(target_id) is target:
        mapped = kernel.qualify_calls(spec.map, source_id, source_names - target_names)
        mapped = kernel.qualify_calls(mapped, target_id, target_names)
    else:
        mapped = kernel.qualify_calls(spec.map, target_id, target_names - source_names)
        mapped = kernel.qualify_calls(mapped, source_id, source_names)
    domain = (kernel.qualify_calls(spec.domain, source_id, source_names)
              if spec.domain is not None else None)
    return bridge_defn(BridgeSpec(spec.name, spec.source, spec.target, mapped, domain))


def target_definition_names(spec: BridgeSpec, context: BridgeContext) -> set[str]:
    """Target records reached by a cross-world map or its commuting interface."""
    target = context.target_lib
    target_id = f"{target._world.world}@{target._world.version}"
    pending = [name for _, name in spec.interface]
    pending.extend(nodes.all_dependencies(spec.map))
    seen = set()
    while pending:
        name = pending.pop()
        if ":" in name:
            namespace, name = name.split(":", 1)
            if namespace != target_id:
                continue
        if name not in target._definitions:
            name = name.split(".", 1)[0]
        if name not in target._definitions or name in seen:
            continue
        seen.add(name)
        pending.extend(target._dependency_names(target._definitions[name]))
    return seen


def _sort_exists(sort: str, lib: Library) -> bool:
    return sort in {"int", "str", "bool"} or any(obj.name == sort for obj in lib.world.objects) or any(
        definition.kind == "object" and definition.name == sort for definition in lib.records().values()
    )


def _sort_matches(reference: str, lib: Library) -> bool:
    if ":" in reference:
        world, reference = reference.rsplit(":", 1)
        if world != f"{lib.world.world}@{lib.world.version}":
            return False
    return _sort_exists(reference, lib)


def _target_value_matches(value: object, reference: str, lib: Library) -> bool:
    sort = reference.rsplit(":", 1)[-1]
    objects = {obj.name: obj for obj in lib.world.objects}
    objects.update({item.name: item.spec for item in lib.records().values() if item.kind == "object"})
    spec = objects.get(sort)
    if sort.lower() == "bool" and isinstance(value, Card):
        return value.sort == "bool" and value.tag in ("true", "false") and not value.fields
    if isinstance(value, Card) and value.sort == sort and spec is not None:
        return (spec.form == "given" or value.tag in (spec.tags or {}) or
                spec.form == "refine" and value.tag == "val" and len(value.fields) == 1)
    primitive = {"int": int, "str": str, "bool": bool}.get(sort.lower())
    if primitive is not None:
        return type(value) is primitive or (primitive is bool and isinstance(value, Card)
                                            and value.sort == "bool" and value.tag in ("true", "false")
                                            and not value.fields)
    if isinstance(value, Card):
        return False
    return spec is not None and spec.form == "given"


def _arity(operation: kernel.Atom | kernel.Defn) -> int:
    return operation.arity if isinstance(operation, kernel.Atom) else len(operation.params)


def _output_sort(lib: Library, name: str) -> str | None:
    for operation in lib.world.operations:
        if operation.name == name:
            return operation.output.sort
    definition = lib.records().get(name)
    return getattr(getattr(getattr(definition, "spec", None), "output", None), "sort", None)


def bridge_defn(spec: BridgeSpec) -> kernel.Defn:
    """Give ~name(x) exactly the same semantics as its kernel expansion."""
    body = spec.map if spec.domain is None else nodes.Case(
        ((nodes.Test(spec.domain), spec.map),), nodes.Lit(Bottom("outside_domain"))
    )
    return kernel.Defn(spec.name, ("x",), body, "bridge")


def check_bridge(defn: Definition, lib: Library | BridgeContext) -> list[str]:
    context = _context(lib)
    spec = defn.spec
    if not isinstance(spec, BridgeSpec):
        return ["bridge requires a BridgeSpec"]
    problems = []
    if defn.kind != "bridge" or defn.name != spec.name:
        problems.append("bridge name and kind must match its spec")
    if not isinstance(spec.map, nodes.NODE_TYPES) or (
        spec.domain is not None and not isinstance(spec.domain, nodes.NODE_TYPES)
    ):
        return ["bridge map and domain must be kernel nodes"]
    if defn.body != bridge_defn(spec).body:
        problems.append("bridge body must be the expansion of map and domain")
    target_scope = context.target_lib.local_scope()
    source_scope = context.source_lib.local_scope()
    target_id = f"{context.target_lib.world.world}@{context.target_lib.world.version}"
    if context.source_lib._attached_worlds.get(target_id) is context.target_lib:
        preferred, fallback = target_scope, source_scope
    else:
        preferred, fallback = source_scope, target_scope
    atoms, defns = dict(preferred.atoms), dict(preferred.defns)
    for name, atom in fallback.atoms.items():
        if name not in atoms and name not in defns:
            atoms[name] = atom
    for name, definition in fallback.defns.items():
        if name not in atoms and name not in defns:
            defns[name] = definition
    map_scope = kernel.DictScope(atoms, defns)
    for label, expression, scope in (("map", spec.map, map_scope),
                                     ("domain", spec.domain, context.source_lib.local_scope())):
        if expression is None:
            continue
        for name in sorted(_free_vars(expression) - {"x"}):
            problems.append(f"{label} has unbound variable {name}")
        for name in sorted(nodes.references(expression)):
            if scope.resolve(name) is None:
                problems.append(f"{label} has unresolved call {name}")
        for call in (item for item in nodes.walk(expression) if isinstance(item, nodes.Call)):
            target = scope.resolve(call.fn)
            if target is not None and len(call.args) != _arity(target):
                problems.append(f"{label} call {call.fn} expects {_arity(target)} arguments")
    if not _sort_matches(spec.source, context.source_lib):
        problems.append(f"unknown source sort {spec.source}")
    if not _sort_matches(spec.target, context.target_lib):
        problems.append(f"unknown target sort {spec.target}")
    for source_name, target_name in spec.interface:
        source_op, target_op = source_scope.resolve(source_name), target_scope.resolve(target_name)
        if source_op is None or target_op is None:
            problems.append(f"unresolved interface pair {source_name}/{target_name}")
        elif _arity(source_op) != _arity(target_op) or _arity(source_op) not in (1, 2):
            problems.append(f"interface pair {source_name}/{target_name} needs matching unary or binary arity")
    return problems


def verify_bridge(defn: Definition, lib: Library | BridgeContext,
                  request: VerifyRequest) -> VerifyResult:
    context = _context(request.extra.get("bridge_context", lib))
    problems = check_bridge(defn, context)
    steps: list[int] = []
    if not request.domain:
        problems.append("bridge verification needs a nonempty domain")
    if problems:
        return VerifyResult(False, (), problems, steps)
    spec = defn.spec
    source = context.source_lib
    target = context.target_lib
    scope = _scope(context).extend((runtime_bridge_defn(spec, context),))
    limit = kernel.Limits(fuel=request.extra.get("fuel", DEFAULT_VERIFY_FUEL))
    values = []
    skipped = 0
    for args in request.domain:
        if len(args) != 1:
            problems.append(f"bridge domain needs one source value: {args!r}")
            continue
        value = args[0]
        if not _target_value_matches(value, spec.source, source):
            problems.append(f"source sort {spec.source} at {value!r}")
            continue
        if spec.domain is not None:
            try:
                predicate = kernel.evaluate(spec.domain, {"x": value}, source.local_scope(), limit,
                                            dialect=source.dialect).outcome
                if not isinstance(predicate, Ok):
                    problems.append(f"domain predicate failed at {value!r}: {predicate!r}")
                    continue
                if not truth(predicate.value):
                    skipped += 1
                    continue
            except (ValueError, TypeError, KeyError, RecursionError) as error:
                problems.append(f"domain predicate at {value!r}: {error}")
                continue
        values.append(value)
    if not values:
        problems.append("bridge verification needs a source value inside its domain")
    pairs_checked = 0
    if not problems:
        for value in values:
            try:
                translated = kernel.call(spec.name, (value,), scope, limit, dialect=source.dialect)
            except (ValueError, TypeError, KeyError, RecursionError) as error:
                problems.append(f"total_on_domain at {value!r}: {error}")
                break
            steps.append(translated.steps)
            if not isinstance(translated.outcome, Ok):
                problems.append(f"total_on_domain at {value!r}: {translated.outcome!r}")
                break
            if not _target_value_matches(translated.outcome.value, spec.target, target):
                problems.append(f"target sort {spec.target} at {value!r}: {translated.outcome.value!r}")
                break
    if not problems:
        for source_name, target_name in spec.interface:
            arity = _arity(source.local_scope().resolve(source_name))
            pairs = tuple(request.extra["pairs"]) if arity == 2 and "pairs" in request.extra else None
            inputs = pairs if pairs is not None else itertools.product(values, repeat=arity)
            if arity == 2 and not inputs:
                problems.append(f"interface pair {source_name}/{target_name} has no checked pairs")
                break
            checked_for_interface = 0
            for arguments in inputs:
                arguments = tuple(arguments)
                if len(arguments) != arity:
                    problems.append(f"invalid interface arity: {arguments!r}")
                    break
                try:
                    outside = [argument for argument in arguments
                               if not any(value_equal(argument, value) for value in values)]
                    if outside and spec.domain is not None and all(
                            _target_value_matches(argument, spec.source, source) and
                            isinstance(predicate := kernel.evaluate(
                                spec.domain, {"x": argument}, source.local_scope(), limit,
                                dialect=source.dialect).outcome, Ok) and not truth(predicate.value)
                            for argument in outside):
                            skipped += 1
                            continue
                    if outside:
                        problems.append(f"interface input outside domain: {arguments!r}")
                        break
                    mapped = [kernel.call(spec.name, (item,), scope, limit,
                                          dialect=source.dialect) for item in arguments]
                    source_run = source.run(source_name, arguments, fuel=limit.fuel)
                    output_sort = _output_sort(source, source_name)
                    maps_output = output_sort in (None, "unknown", spec.source,
                                                  spec.source.rsplit(":", 1)[-1])
                    if maps_output and spec.domain is not None and isinstance(source_run.outcome, Ok):
                        predicate = kernel.evaluate(spec.domain, {"x": source_run.outcome.value},
                                                    source.local_scope(), limit, dialect=source.dialect).outcome
                        if not isinstance(predicate, Ok):
                            raise ValueError(f"domain predicate failed on output: {predicate!r}")
                        if not truth(predicate.value):
                            skipped += 1
                            continue
                    translated_run = (kernel.call(spec.name, (source_run.outcome.value,), scope, limit,
                                                  dialect=source.dialect)
                                      if isinstance(source_run.outcome, Ok) and maps_output
                                      else source_run)
                    if maps_output and isinstance(translated_run.outcome, Ok) and not _target_value_matches(
                            translated_run.outcome.value, spec.target, target):
                        problems.append(f"target sort {spec.target} at interface output {arguments!r}")
                        break
                    target_run = target.run(target_name, tuple(item.outcome.value for item in mapped),
                                            fuel=limit.fuel) if all(isinstance(item.outcome, Ok) for item in mapped) else None
                except (ValueError, TypeError, KeyError, RecursionError) as error:
                    problems.append(f"commutes {source_name}/{target_name} at {arguments!r}: {error}")
                    break
                pairs_checked += 1
                checked_for_interface += 1
                steps.extend(item.steps for item in mapped)
                steps.extend((source_run.steps, translated_run.steps))
                if target_run is not None:
                    steps.append(target_run.steps)
                if (target_run is None or isinstance(translated_run.outcome, Unknown) or
                        not outcome_equal(translated_run.outcome, target_run.outcome)):
                    problems.append(f"commutes {source_name}/{target_name} at {arguments!r}: "
                                    f"{translated_run.outcome!r} != {getattr(target_run, 'outcome', None)!r}")
                    break
            if problems:
                break
            if not checked_for_interface:
                problems.append(f"interface pair {source_name}/{target_name} has no checked pairs")
                break
    request.scope.update({"domain_size": len(request.domain), "pairs_checked": pairs_checked,
                          "skipped": skipped})
    return VerifyResult(not problems, ("commutes", "total_on_domain") if not problems else (), problems, steps)


def compose_bridges(first: Definition, second: Definition) -> Definition:
    """Compose maps, never carrying either input's verification evidence."""
    if not isinstance(first.spec, BridgeSpec) or not isinstance(second.spec, BridgeSpec):
        raise TypeError("compose_bridges requires bridge definitions")
    if first.spec.target != second.spec.source:
        raise ValueError("bridge target must match the next bridge source")
    mapped = nodes.Call(first.name, (nodes.Var("x"),))
    body = nodes.Call(second.name, (mapped,))
    name = f"{first.name}_then_{second.name}"
    domain = first.spec.domain
    if second.spec.domain is not None:
        downstream = nodes.Let("x", mapped, second.spec.domain)
        domain = (nodes.Case(((nodes.Test(domain), downstream),), nodes.Lit(False))
                  if domain is not None else downstream)
    spec = BridgeSpec(name, first.spec.source, second.spec.target, body, domain)
    return Definition(name, "bridge", "invented", max(first.layer, second.layer) + 1,
                      (first.name, second.name), spec, bridge_defn(spec).body)
