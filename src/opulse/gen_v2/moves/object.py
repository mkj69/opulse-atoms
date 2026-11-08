"""Finite object proposals for open object worlds.

Compose sorts use the core's structural ``S.size`` and ``S.fold`` operations.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.library import VerifyRequest
from opulse.atoms.spec import ObjectSpec
from opulse.atoms.values import Card, Ok, decode, truth, value_equal
from opulse.gen_v2 import vocab
from opulse.gen_v2.base import Candidate, Signature, Sort
from opulse.gen_v2.kinds.combinators import definition as make_definition
from opulse.gen_v2.kinds.objects import normalize_object_spec
from opulse.gen_v2.kinds.objects import object_atoms as _object_atoms


def object_atoms(spec, state=None):
    """Build candidate atoms or restore an object's named witness from a loaded state.

    Core Library.scope rebuilds constructor, accessor, size and fold operations.
    Checkpoint loading also needs the saved Definition.body for the zero-arity witness.
    """
    if state is None:
        return ()
    definition = state.library.definitions.get(spec.name)
    if definition is not None and definition.status == "promoted":
        if spec.form == "constant":
            return ()
        return (kernel.Defn(spec.name, (), definition.body, kind="object", layer=definition.layer),)
    return _object_atoms(spec, state)


def _size(value):
    return 1 + sum(_size(field) for field in value.fields
                   if isinstance(field, Card) and field.sort == value.sort)


def _witness(state, sort):
    known = state.sorts[sort]
    if known.origin == "invented":
        return n.Call(known.defined_by, ())
    value = min(known.values, key=lambda item: (abs(item) if type(item) is int else
                                                int(item) if type(item) is bool else 0,
                                                len(repr(item)), repr(item)))
    return n.Lit(value)


def _refine_witness(spec, witness, opened_nodes):
    """Return the canonical valid representative of a valid base witness.

    Invalid bases remain invalid for ``S.make``; all rule calls contribute to witness steps.
    """
    original = n.Var("_base_witness")
    canonical = n.Let("x", original, spec.canon) if spec.canon is not None else original
    if "Case" in opened_nodes:
        guarded = n.Let("x", original,
                        n.Case(((n.Test(spec.valid), canonical),), original))
    else:
        guarded = n.Let("x", original, n.Let("_valid_rule", spec.valid, canonical))
    return n.Let("_base_witness", witness, guarded)


def release_object_name(state, candidate):
    """Undo an unadmitted object reservation, including the last counter advance."""
    name = candidate.defn.name if isinstance(candidate, Candidate) else candidate
    if (name not in state.names.taken or name in state.entries or
            state.library.has_name(name)):
        return
    state.names.taken.discard(name)
    suffix = str(state.names.counter)
    if name.endswith(suffix) and name[:-len(suffix)] in state.names.LETTERS["object"]:
        state.names.counter -= 1


def _reclaim_refused_name(state):
    pending = getattr(state, "_object_pending_name", None)
    if pending is not None:
        name, previous_rejections = pending
        if len(state.rejections) > previous_rejections:
            release_object_name(state, name)
        state._object_pending_name = None


def _valid_witness(state, base, valid, witness, scope, limits) -> bool:
    """True when the base witness evaluates and satisfies ``valid`` (so ``S.make`` accepts it)."""
    try:
        value = kernel.evaluate(witness, {}, scope, limits, dialect=state.world.dialect).outcome
        if not isinstance(value, Ok):
            return False
        check = kernel.evaluate(valid, {"x": value.value}, scope, limits, dialect=state.world.dialect).outcome
        return isinstance(check, Ok) and truth(check.value)
    except (KeyError, TypeError, ValueError, RecursionError):
        return False


def _witness_value(state, sort):
    result = kernel.evaluate(_witness(state, sort), {}, state.library.scope(),
                             kernel.Limits(fuel=state.world.fuel)).outcome
    return result.value if isinstance(result, Ok) else None


def _operation_witness(state, sort, rng):
    entries = [entry for entry in state.entries.values()
               if entry.kind == "operation" and entry.signature is not None
               and entry.signature.output == sort and all(
                   part in state.sorts and state.sorts[part].values for part in entry.signature.inputs)]
    rng.shuffle(entries)
    entries.sort(key=lambda entry: entry.layer, reverse=True)
    for entry in entries[:12]:
        args = tuple(n.Lit(rng.choice(state.sorts[part].values[:4]))
                     for part in entry.signature.inputs)
        node = n.Call(entry.name, args)
        try:
            result = kernel.evaluate(node, {}, state.library.scope(),
                                     kernel.Limits(fuel=state.world.fuel)).outcome
        except (KeyError, TypeError, ValueError, RecursionError):
            continue
        if isinstance(result, Ok) and _is_base_value(sort, result.value):
            return node, result.value
    return None


def _compose_witness(state, spec, rng):
    tags = list(spec.tags.items())
    rng.shuffle(tags)
    if any(entry.kind == "operation" for entry in state.entries.values()):
        tags.sort(key=lambda item: not bool(item[1]))
    for tag, fields in tags:
        if isinstance(fields, dict) or any(sort == spec.name for _, sort in fields):
            continue
        args = []
        for _, sort in fields:
            generated = _operation_witness(state, sort, rng) if rng.random() < 0.95 else None
            args.append(generated[0] if generated else _witness(state, sort))
        return n.Call(f"{spec.name}.{tag}", tuple(args))
    return None


def _values(spec, state):
    """Enumerate finite constructor trees by size, base tags first, up to 24."""
    result = []
    for depth in range(4):
        for tag, fields in spec.tags.items():
            if isinstance(fields, dict):
                continue
            sorts = [sort for _, sort in fields]
            if depth == 0 and spec.name in sorts:
                continue
            domains = []
            for sort in sorts:
                if sort == spec.name:
                    domains.append(result[:4])
                else:
                    values = state.sorts[sort].values
                    witness = _witness_value(state, sort)
                    domains.append(tuple(dict.fromkeys((witness, *values)))[:3]
                                   if witness is not None else values[:3])
            for values in itertools.product(*domains):
                card = Card(spec.name, tag, values)
                if card not in result:
                    result.append(card)
                if len(result) >= 24:
                    break
            if len(result) >= 24:
                break
        if len(result) >= 24:
            break
    return tuple(sorted(result, key=lambda card: (_size(card), len(repr(card)), repr(card))))


def _candidate(state, spec, move, body, values=(), meta=None):
    spec = normalize_object_spec(spec)
    name = spec.name
    if (spec.form == "refine" and isinstance(body, n.Call) and
            body.fn == f"{name}.make" and len(body.args) == 1 and
            any(rule is not None and not n.references(rule) <= n.references(body)
                for rule in (spec.valid, spec.canon))):
        body = n.Call(body.fn, (_refine_witness(spec, body.args[0],
                                            state.world.decl.opened_nodes()),))
    sort_deps = sorted({part for fields in (spec.tags or {}).values() for part in
                        (fields.values() if isinstance(fields, dict) else (field[1] for field in fields))
                        if part in state.sorts and state.sorts[part].origin == "invented"} |
                       ({spec.base} if spec.base in state.sorts and state.sorts[spec.base].origin == "invented" else set()))
    missing = [sort for sort in sort_deps if sort not in n.references(body)]
    if missing:
        declaration = n.Lit(False)
        for sort in reversed(missing):
            declaration = n.Let(f"_sort_{sort}", n.Call(state.sorts[sort].defined_by), declaration)
        body = n.Case(((n.Always(), body),), declaration)
    defn = make_definition(state, "object", name, spec, body, include_literals=False, fold_layer=False)
    sorts = ()
    if spec.form != "constant":
        atoms, signatures = object_atoms(spec, state)
        constructors = tuple(f"{name}.{tag}" for tag in spec.tags) if spec.form == "compose" else (f"{name}.make",)
        accessors = tuple(f"{name}.{field}" for field in dict.fromkeys(
            field for fields in spec.tags.values() if not isinstance(fields, dict)
            for field, _ in fields)) if spec.form == "compose" else (f"{name}.base",)
        testers = tuple(f"{name}.is_{tag}" for tag in spec.tags) if spec.form == "compose" else ()
        if spec.form == "refine":
            accessors += tuple(atom.name for atom in atoms if atom.name.startswith(f"{name}.") and
                               atom.name not in constructors + accessors and not atom.name.startswith(f"{name}._"))
        sorts = (Sort(name, tuple(values), "invented", name, constructors, accessors, testers,
                      spec.sealed, spec.interface, spec.base),)
    else:
        atoms, signatures = object_atoms(spec, state)
        if meta and meta.get("output"):
            signatures[name] = Signature((), meta["output"])
    if spec.form != "constant":
        atoms.append(kernel.Defn(name, (), body, kind="object", layer=defn.layer))
    metadata = {"sort_deps": sort_deps, **(meta or {})}
    if spec.form == "constant":
        request = VerifyRequest("exhaustive", ((),), {"domain": "the single closed term", "size": 1})
    else:
        domain = tuple((value,) for value in (state.sorts[spec.base].values if spec.form == "refine" else values))
        scope_name = spec.base if spec.form == "refine" else name
        request = VerifyRequest("exhaustive", domain,
                                {"domain": f"all {len(domain)} probe values of {scope_name}", "size": len(domain)})
    return Candidate(defn, None, move, request, atoms, sorts, extra_signatures=signatures, meta=metadata)


def _compose(state, rng, move):
    available = [sort for sort in state.sorts.values() if sort.values and sort.name != state.world.truth_sort and
                 (not sort.sealed or sort.interface)]
    if not available:
        return None
    name = state.names.fresh("object")
    given = [sort for sort in available if sort.origin == "given"]
    invented = [sort for sort in available if sort.origin == "invented"]
    operation_sorts = [sort for sort in available if any(
        entry.kind == "operation" and entry.signature is not None and
        entry.signature.output == sort.name and all(part in state.sorts
            for part in entry.signature.inputs) for entry in state.entries.values())]
    refinements = [sort for sort in invented
                   if state.library.get(sort.defined_by).spec.form == "refine"]
    probe_sorts = [sort for sort in available if any(
        state.signature(probe) is not None and state.signature(probe).output == sort.name
        for probe in state.world.probes)]

    def field_sort():
        if operation_sorts and rng.random() < 0.55:
            return rng.choice(operation_sorts).name
        if refinements and rng.random() < 0.35:
            return rng.choice(refinements).name
        if given and rng.random() < 0.2:
            return rng.choice(given).name
        if rng.random() < 0.55:
            ranked = sorted(available, key=lambda sort: state.layer(sort.defined_by)
                            if sort.defined_by else 0)
            return rng.choice(ranked[-min(10, len(ranked)):]).name
        return rng.choice(available).name

    if move == "obj.record":
        fields = [[f"field{index}", field_sort()] for index in range(rng.randint(2, 3))]
        if operation_sorts and rng.random() < 0.8:
            fields[0][1] = rng.choice(operation_sorts).name
        if probe_sorts and not any(entry.kind == "operation" for entry in state.entries.values()):
            for field in fields:
                field[1] = rng.choice(probe_sorts).name
        tags = {"pair": fields}
    elif move in ("obj.variant", "obj.seal"):
        tags = {"none": []}
        for index in range(rng.randint(1, 2)):
            sort = rng.choice(given).name if index == 0 and given and invented else field_sort()
            if index == 0 and operation_sorts and rng.random() < 0.8:
                sort = rng.choice(operation_sorts).name
            if index == 1 and invented:
                sort = rng.choice(invented).name
            tags[f"some{index}"] = [[f"field{index}", sort]]
    else:
        numeric = next((sort for sort in available if sort.name == "int"), None)
        element = (numeric.name if numeric and rng.random() < 0.5 and len(
            state.callables("operation", inputs=("int", "int"), output="int")) >= 2
                   else field_sort())
        tags = {"nil": [], "cons": [["head", element], ["tail", name]]}
    sealed = move == "obj.seal"
    if sealed:
        base_tag = next(tag for tag, fields in tags.items() if fields)
        interface = tuple(f"{name}.{tag}" for tag in tags) + (f"{name}.{tags[base_tag][0][0]}",)
    else:
        interface = ()
    spec = ObjectSpec(name, "compose", tags=tags, sealed=sealed, interface=interface)
    values = _values(spec, state)
    if not values:
        release_object_name(state, name)
        return None
    body = _compose_witness(state, spec, rng)
    if body is None:
        release_object_name(state, name)
        return None
    evaluated = [kernel.evaluate(argument, {}, state.library.scope(),
                                 kernel.Limits(fuel=state.world.fuel)).outcome
                 for argument in body.args]
    if all(isinstance(result, Ok) for result in evaluated):
        witness = Card(name, body.fn.removeprefix(name + "."),
                       tuple(result.value for result in evaluated))
        if witness not in values:
            values = tuple(sorted((*values[:23], witness),
                                  key=lambda card: (_size(card), len(repr(card)), repr(card))))
    return _candidate(state, spec, move, body, values)


def _register_recursive_hints(state):
    for sort in state.sorts.values():
        entry = state.entries.get(sort.defined_by)
        if sort.origin != "invented" or entry is None or entry.move != "obj.recursive":
            continue
        spec = state.library.get(sort.defined_by).spec
        if (spec.form == "compose" and spec.tags.get("nil") == [] and
                len(spec.tags.get("cons", ())) == 2 and
                spec.tags["cons"][1] == ["tail", sort.name]):
            state.world.measures.setdefault(sort.name, [(f"{sort.name}.tail", f"{sort.name}.size")])
            state.world.bases.setdefault(sort.name, [f"{sort.name}.is_nil"])


def _refine(state, rng, move):
    bases = [sort for sort in state.sorts.values() if len(sort.values) >= 3 and
             sort.name != state.world.truth_sort and
             (not sort.sealed or sort.interface)]
    if not bases:
        return None
    preferred = [sort for sort in bases if sort.origin == "invented" and
                 any(entry.kind == "operation" and entry.signature is not None and
                     sort.name in entry.signature.inputs for entry in state.entries.values())]
    base = rng.choice(preferred if preferred and rng.random() < 0.65 else bases)
    witness = _witness(state, base.name)
    witness_value = _witness_value(state, base.name)
    if witness_value is None:
        return None
    scope = state.library.scope()
    limits = kernel.Limits(fuel=state.world.fuel)

    def evaluate(node, value):
        return kernel.evaluate(node, {"x": value}, scope, limits).outcome

    unary = vocab.deciders(state, base.name)
    predicates = [n.Call(operator, (n.Var("x"),)) for operator in unary
                  if not base.sealed or operator in base.interface]
    for operator in (*vocab.less(state, base.name), *vocab.equal(state, base.name)):
        if base.sealed and operator not in base.interface:
            continue
        for threshold in base.values[:4]:
            predicates.append(n.Call(operator, (n.Var("x"), n.Lit(threshold))))
    if base.origin == "invented" and not base.sealed:
        for accessor in base.accessors:
            signature = state.signature(accessor)
            if signature and signature.output in state.sorts:
                for decider in vocab.deciders(state, signature.output):
                    predicates.append(n.Call(decider, (n.Call(accessor, (n.Var("x"),)),)))
                for decider in vocab.zero_test(state, signature.output):
                    predicate = n.Call(decider, (n.Call(accessor, (n.Var("x"),)),))
                    if predicate not in predicates:
                        predicates.append(predicate)
    rng.shuffle(predicates)
    predicates.sort(key=lambda predicate: not any(
        reference in state.entries and state.entries[reference].kind == "operation"
        for reference in n.references(predicate)))
    rules = list(predicates)
    for predicate in predicates[:3]:
        rules.append(n.Case(((n.Not(n.Test(predicate)), n.Lit(True)),), n.Lit(False)))
    if len(predicates) >= 2:
        rules.append(n.Case(((n.And(n.Test(predicates[0]), n.Test(predicates[1])),
                              n.Lit(True)),), n.Lit(False)))

    valid = None
    valid_values = []
    for rule in rules:
        try:
            results = [evaluate(rule, value) for value in (witness_value, *base.values)]
        except (KeyError, TypeError, ValueError, RecursionError):
            continue
        try:
            flags = [isinstance(result, Ok) and truth(result.value) for result in results]
        except TypeError:
            continue
        if flags[0] and any(flags[1:]) and not all(flags[1:]):
            valid = rule
            valid_values = [value for value, flag in zip(base.values, flags[1:]) if flag]
            break

    canonical = []
    for operator in state.callables(inputs=(base.name,), output=base.name):
        if base.sealed and operator not in base.interface:
            continue
        mapped = []
        for value in (witness_value, *base.values):
            result = kernel.call(operator, (value,), scope, limits).outcome
            if not isinstance(result, Ok) or not _is_base_value(base.name, result.value):
                break
            mapped.append(result.value)
        if len(mapped) != len(base.values) + 1:
            continue
        if any(not isinstance(result := kernel.call(operator, (item,), scope, limits).outcome, Ok) or
               not value_equal(result.value, item) for item in mapped):
            continue
        if valid is not None:
            try:
                if not all(isinstance(result := evaluate(valid, item), Ok) and truth(result.value)
                           for item, source in zip(mapped, (witness_value, *base.values))
                           if source == witness_value or source in valid_values):
                    continue
            except TypeError:
                continue
        if len(set(map(repr, mapped[1:]))) < len(set(map(repr, base.values))):
            canonical.append(operator)

    if valid is None and not canonical:
        return None
    if valid is None:
        valid = n.Lit(True)
        valid_values = list(base.values)
    canon_name = rng.choice(canonical) if canonical else None
    canon = n.Call(canon_name, (n.Var("x"),)) if canon_name else None
    name = state.names.fresh("object")
    sealed = move == "obj.seal"
    interface = (f"{name}.make", f"{name}.base") if sealed else ()
    spec = ObjectSpec(name, "refine", base=base.name, valid=valid, canon=canon,
                      sealed=sealed, interface=interface)
    witness = _refine_witness(spec, witness, state.world.decl.opened_nodes())
    body = n.Call(f"{name}.make", (witness,))
    if not _valid_witness(state, base.name, valid, witness, scope, limits):
        body = n.Call(f"{name}.make", (n.Lit(valid_values[0]),))  # the witness must be a value of the sort
    values = []
    for value in valid_values:
        result = kernel.call(canon_name, (value,), scope, limits).outcome if canon else Ok(value)
        if isinstance(result, Ok):
            card = Card(name, "val", (result.value,))
            if card not in values:
                values.append(card)
    if not values:
        release_object_name(state, name)
        return None
    return _candidate(state, spec, move, body, values)


def _is_base_value(sort, value):
    if sort == "int":
        return type(value) is int
    if sort == "str":
        return type(value) is str
    if sort == "bool":
        return type(value) is bool or isinstance(value, Card) and value.sort == "bool"
    return isinstance(value, Card) and value.sort == sort


def _constant(state, rng):
    high = [entry for entry in state.entries.values() if entry.kind == "operation" and
            entry.signature is not None and entry.layer >= 2 and
            all(sort in state.sorts and state.sorts[sort].values for sort in entry.signature.inputs)]
    if not high:
        return None
    high.sort(key=lambda entry: entry.layer, reverse=True)
    entry = rng.choice(high[:min(16, len(high))])
    observed = {}
    for source in state.entries.values():
        if source.kind != "observation" or source.signature is None:
            continue
        sort = source.signature.output
        if sort == state.world.truth_sort or sort not in state.sorts:
            continue
        for _, result, _ in source.examples:
            if not isinstance(result, dict) or "ok" not in result:
                continue
            try:
                value = decode(result["ok"])
            except (ValueError, TypeError, KeyError):
                continue
            if _is_base_value(sort, value):
                observed.setdefault(sort, []).append((source.name, value))
    used_observations = []
    args = []
    for sort in entry.signature.inputs:
        if observed.get(sort) and rng.random() < 0.6:
            source, value = rng.choice(observed[sort])
            used_observations.append(source)
        else:
            value = rng.choice(state.sorts[sort].values[:4])
        args.append(n.Lit(value))
    body = n.Call(entry.name, args)
    outcome = kernel.evaluate(body, {}, state.library.scope(),
                              kernel.Limits(fuel=state.world.fuel)).outcome
    if not isinstance(outcome, Ok):
        return None
    name = state.names.fresh("object")
    spec = ObjectSpec(name, "constant", body=body)
    return _candidate(state, spec, "obj.constant", body,
                      meta={"output": entry.signature.output,
                            "observation_sources": sorted(set(used_observations))})


@dataclass(frozen=True)
class ObjectMove:
    name: str
    kind: str = "object"

    def __call__(self, state, rng):
        _reclaim_refused_name(state)
        if "object" not in state.world.open_kinds:
            return None
        _register_recursive_hints(state)
        if self.name == "obj.constant":
            proposal = _constant(state, rng)
        elif self.name == "obj.refine" or self.name == "obj.seal" and rng.random() < 0.5:
            proposal = _refine(state, rng, self.name)
        else:
            proposal = _compose(state, rng, self.name)
        if proposal is not None:
            state._object_pending_name = (proposal.defn.name, len(state.rejections))
        return proposal


MOVES = [ObjectMove(name) for name in ("obj.record", "obj.variant", "obj.recursive",
                                            "obj.refine", "obj.seal", "obj.constant")]
