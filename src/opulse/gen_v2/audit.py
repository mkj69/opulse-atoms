"""Independent invariant checks for a generated atoms-v2 library."""

from __future__ import annotations

import copy
import itertools
import random
import time
from collections import Counter
from dataclasses import dataclass, field, replace

from opulse.atoms import kernel, nodes
from opulse.atoms.boundary import Boundary, flatten_calls
from opulse.atoms.library import PipelineError
from opulse.atoms.spec import Contract
from opulse.atoms.values import Card, Ok, Unknown, outcome_equal, value_equal
from opulse.atoms.verify import unfold_equivalent_calls
from opulse.gen_v2.admit import hook_for
from opulse.gen_v2.base import KINDS, Candidate, GenState
from opulse.gen_v2.codec import (
    encode_outcome,  # the same encoder admit uses for examples
)
from opulse.gen_v2.library import evidence_checked_scope


@dataclass(frozen=True)
class AuditFailure:
    name: str
    invariant: str
    detail: str


@dataclass
class AuditReport:
    checked: dict[str, int] = field(default_factory=dict)
    failures: list[AuditFailure] = field(default_factory=list)
    timings: dict[str, float] = field(default_factory=dict)
    skipped: list[AuditFailure] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures


def _domain(state: GenState, entry, record):
    request = state.requests.get(entry.name)
    if request is not None:
        if record.kind == "combinator":
            families = entry.meta.get("slot_families")
            if families:
                from opulse.gen_v2.kinds.combinators import _arguments, _assignments

                candidate = Candidate(record, entry.signature, entry.move, request, meta=dict(entry.meta))
                return tuple(_arguments(record.spec, assignment, values)
                             for assignment in _assignments(candidate) for values in request.domain)
        else:
            return request.domain
    signature = entry.signature
    if signature is None:
        if record.kind == "object":
            if record.spec.form == "constant":
                return ((),)
            sort = record.spec.base if record.spec.form == "refine" else record.name
            return tuple((value,) for value in state.sorts[sort].values)
        return tuple(tuple(args) for args, _, _ in entry.examples)
    bound = record.evidence.scope.get("bound") if record.evidence else None
    if bound is None and record.kind == "combinator" and record.evidence:
        bound = record.evidence.scope["size"]
    domains = [state.sorts[sort].values[:bound] for sort in signature.inputs]
    values = tuple(itertools.product(*domains))
    if signature.op_inputs:
        family = record.evidence.scope.get("op_family", ()) if record.evidence else ()
        if not family:
            raise ValueError("combinator evidence lacks an operation family")
        spec = record.spec

        def call_args(names, args):
            operations = iter(kernel.FnRef(name) for name in names)
            inputs = iter(args)
            return tuple(next(operations) if param in spec.op_params else next(inputs)
                         for param in spec.params)

        values = tuple(call_args(names, args)
                       for names in itertools.product(family, repeat=len(signature.op_inputs))
                       for args in values)
    return values


def _boundaries(rng, records):
    names = list(records)
    selected = rng.sample(names, min(3, len(names)))
    return [Boundary(), Boundary.unfold_all(), Boundary(
        depth=rng.choice([None, 1, 2, 4, 8]),
        open_names=frozenset(selected[:1]),
        keep_names=frozenset(selected[1:2]),
        open_paths=frozenset({(0, 0)}),
        kinds=frozenset(rng.sample(["object", "operation", "combinator", "observation"],
                                    rng.randint(1, 4))))]


def _mixed_expression(state, entry, args, rng):
    """Wrap a matching value argument with zero to two admitted unary operations."""
    arguments = [nodes.Lit(arg) for arg in args]
    signature = entry.signature
    if signature is None:
        return nodes.Call(entry.name, tuple(arguments))
    params = getattr(state.library.get(entry.name).spec, "params", ())
    value_positions = ([index for index, param in enumerate(params)
                        if param not in state.library.get(entry.name).spec.op_params]
                       if signature.op_inputs else list(range(len(signature.inputs))))
    positions = [index for index in value_positions
                 if index < len(arguments) and not isinstance(args[index], kernel.FnRef)]
    if positions:
        position = rng.choice(positions)
        sort = signature.inputs[value_positions.index(position)]
        compatible = [other.name for other in state.entries.values()
                      if other.name != entry.name and other.kind == "operation" and other.signature
                      and other.signature.inputs == (sort,) and other.signature.output == sort]
        original = args[position]
        current = original
        count = min(rng.randint(0, 2), len(compatible))
        scope = state.library.scope()
        for _ in range(count):
            for name in rng.sample(compatible, min(8, len(compatible))):
                request = state.requests.get(name)
                if request is None or not any(len(row) == 1 and value_equal(row[0], current)
                                              for row in request.domain):
                    continue
                try:
                    outcome = kernel.call(name, (current,), scope, kernel.Limits(fuel=state.world.fuel),
                                          dialect=state.library.dialect).outcome
                except (TypeError, ValueError, KeyError, RecursionError, AttributeError, IndexError):
                    continue
                if not isinstance(outcome, Ok) or not any(value_equal(outcome.value, probe)
                                                            for probe in state.sorts[sort].values):
                    continue
                changed = (*args[:position], outcome.value, *args[position + 1:])
                verified = state.requests.get(entry.name)
                if verified is not None:
                    value_args = tuple(value for value in changed if not isinstance(value, kernel.FnRef))
                    if not any(all(value_equal(left, right) for left, right in zip(value_args, row))
                               and len(value_args) == len(row) for row in verified.domain):
                        continue
                arguments[position] = nodes.Call(name, (arguments[position],))
                current = outcome.value
                break
            else:
                break
    return nodes.Call(entry.name, tuple(arguments))


def _check_boundary_trace(name, run, boundaries, fail):
    if run.trace is None:
        fail(name, "I2", "trace unavailable")
        return
    check = unfold_equivalent_calls(run.trace, boundaries)
    if not check.ok:
        fail(name, "I2", "; ".join(check.problems))
    leaves = flatten_calls(run.trace, Boundary.unfold_all())
    if any(not call.given for call in leaves) or sum(call.steps for call in leaves) + run.jumps != run.steps:
        fail(name, "I1", "flattened trace contains invented calls or loses steps")


def _object_call(record, args):
    if record.spec.form == "constant":
        return record.name, ()
    if record.spec.form == "refine":
        return f"{record.name}.make", args
    value = args[0]
    members = record.spec.tags[value.tag]
    return f"{record.name}.{value.tag}", ((value.fields,) if isinstance(members, dict) else value.fields)


def _audit_hook(state, entry, record, request, fail, report):
    """Replay a kind's admission obligations on the exact recorded domain."""
    name = entry.name
    hook = hook_for(entry.kind)
    if hook is None or hook.run is None or hook.verify is None:
        fail(name, "I1/I3", f"{entry.kind} verification hook absent")
        return
    request = copy.deepcopy(request)
    candidate = Candidate(record, entry.signature, entry.move, request,
                          new_sorts=(state.sorts[name],) if entry.kind == "object" and
                          record.spec.form != "constant" and name in state.sorts else (),
                          extra_signatures=state.extra_signatures, meta=dict(entry.meta))
    try:
        results = hook.run(state, candidate, request)
        stored_steps = state.library._steps.get(name, ())
        if entry.kind != "bridge" and tuple(result[2] for result in results) != tuple(stored_steps):
            fail(name, "I1", "replayed layer-0 steps differ from admission")
        for (args, outcome, steps), (old_args, old_outcome, old_steps) in zip(results, entry.examples):
            if (args != old_args or encode_outcome(outcome) != old_outcome
                    or steps != old_steps):
                fail(name, "I1", "replayed outcome differs from admission")
                break
        if entry.kind == "observation":
            from opulse.gen_v2.kinds import observations

            scope = observations._scope(state, record)
            for args, outcome, steps in results:
                history = observations._history(args, record.spec.memory)
                unfolded, expanded_steps = observations._evaluate(state, record, history, scope, unfolded=True)
                if not outcome_equal(outcome, unfolded) or steps != expanded_steps:
                    fail(name, "I1", f"observation unfolding differs on {args!r}")
                    break
            if results and not record.spec.memory:
                arguments = observations._read_arguments(state, record, scope)
                for args, _, _ in results:
                    history = observations._history(args, None)
                    values, _, error = observations._probe_values(state, record.spec.reads, history[0],
                                                                   scope, arguments)
                    if error is None:
                        break
                if error is not None:
                    fail(name, "I2", f"observation boundary replay probe failed: {error!r}")
                else:
                    expression = observations._expand(record.body, state, scope, history, {}, arguments)
                    limits = kernel.Limits(fuel=state.world.fuel)
                    run = kernel.evaluate(expression, values, scope, limits, trace=True,
                                          dialect=state.world.dialect)
                    unfolded = kernel.evaluate(kernel.inline(expression, scope), values, scope,
                                               limits, dialect=state.world.dialect)
                    if not outcome_equal(run.outcome, unfolded.outcome) or run.steps != unfolded.steps:
                        fail(name, "I1", "observation expression differs from unfolding")
                    _check_boundary_trace(name, run, _boundaries(random.Random(name),
                                                                state.library.definitions), fail)
            elif not results:
                fail(name, "I2", "observation boundary replay has no recorded inputs")
        if entry.kind == "object":
            scope = state.library.scope()
            limits = kernel.Limits(fuel=state.world.fuel)
            witness = nodes.Call(name, ())
            named = kernel.evaluate(witness, scope=scope, limits=limits, trace=True,
                                    dialect=state.world.dialect)
            unfolded = kernel.evaluate(kernel.inline(witness, scope), scope=scope, limits=limits,
                                       dialect=state.world.dialect)
            if not outcome_equal(named.outcome, unfolded.outcome) or named.steps != unfolded.steps:
                fail(name, "I1", "object witness differs from unfolding")
            if record.spec.form != "constant" and not _in_sort(state, record.spec, named.outcome, scope):
                fail(name, "I1", "object witness is outside its declared sort")
            _check_boundary_trace(name, named, _boundaries(random.Random(name),
                                                           state.library.definitions), fail)
        verification_state = copy.copy(state) if entry.kind == "observation" else state
        if verification_state is not state:
            # Replay against the catalogue as it was at admission: entries admitted before this one.
            earlier = {}
            for key, value in state.entries.items():
                if key == name:
                    break
                earlier[key] = value
            verification_state.entries = earlier
        cross_world = entry.kind == "bridge" and ":" in record.spec.target
        _, problems = ((), ()) if cross_world else hook.verify(verification_state, candidate, request, results)
        for problem in problems:
            fail(name, "I3" if entry.kind == "observation" else "I1", problem)
        if entry.kind in ("bridge", "law"):
            if entry.kind == "bridge":
                from opulse.atoms.bridges import verify_bridge
                from opulse.gen_v2.kinds.bridges import typed_request

                replay = verify_bridge(record, state.library._bridge_context(record) if cross_world
                                       else state.library, request if cross_world else typed_request(state, request))
            else:
                from opulse.atoms.laws import verify_law

                replay = verify_law(record, state.library, request)
            if not replay.ok or tuple(replay.steps) != tuple(stored_steps):
                fail(name, "I1", "verified layer-0 step series differs from admission")
            if entry.kind == "bridge":
                for args in request.domain:
                    witness = nodes.Call(name, (nodes.Lit(args[0]),))
                    named = kernel.evaluate(witness, scope=state.library.scope(),
                                            limits=kernel.Limits(fuel=state.world.fuel), trace=True,
                                            dialect=state.world.dialect)
                    unfolded = kernel.evaluate(kernel.inline(witness, state.library.scope()),
                                               scope=state.library.scope(),
                                               limits=kernel.Limits(fuel=state.world.fuel),
                                               dialect=state.world.dialect)
                    if not outcome_equal(named.outcome, unfolded.outcome) or named.steps != unfolded.steps:
                        fail(name, "I1", "bridge named call differs from unfolding")
                    _check_boundary_trace(name, named, _boundaries(random.Random(name),
                                                                 state.library.definitions), fail)
    except (KeyError, ValueError, TypeError, AttributeError, IndexError, RecursionError) as error:
        fail(name, "I3" if entry.kind == "observation" else "I1", f"hook: {type(error).__name__}: {error}")


def audit(state: GenState, sample: int | None = None, seed: int = 0) -> AuditReport:
    """Audit every admitted entry, or a reproducible subset of entries.

    Recorded requests supply the exact verification domain. Older states without
    requests use a reconstructed domain where possible.
    """
    start = time.monotonic()
    if sample is not None and sample < 0:
        raise ValueError("sample must be non-negative")
    report = AuditReport()
    report.timings = {"metadata_seconds": 0.0, "evaluation_seconds": 0.0}
    rng = random.Random(seed)
    entries = list(state.entries.values())
    if sample is not None:
        entries = rng.sample(entries, min(sample, len(entries)))
    records = state.library.definitions
    scope = state.library.scope()
    limits = kernel.Limits(fuel=state.world.fuel)
    counts = Counter()

    def fail(name, invariant, detail):
        report.failures.append(AuditFailure(name, invariant, str(detail)))

    for entry in entries:
        metadata_start = time.monotonic()
        counts[entry.kind] += 1
        name = entry.name
        record = records.get(name)
        if record is None:
            fail(name, "I4", "admitted entry has no definition")
            continue
        if entry.meta.get("template"):
            from opulse.gen_v2.templates import templates_for, validate_instance

            try:
                template_name = entry.meta["template"]["name"]
                template = templates_for(state)[template_name]
                if name not in template.instances:
                    raise ValueError("instance is not listed by its template")
                validate_instance(state, template, entry)
            except (KeyError, ValueError, TypeError) as error:
                fail(name, "I4", f"template provenance: {error}")
        if isinstance(record.body, nodes.NODE_TYPES) and not nodes.dependencies_match(
                record.depends_on, record.body, getattr(record.spec, "op_params", ())):
            fail(name, "dependency", "depends_on differs from body references")
        missing = [dependency for dependency in record.depends_on
                   if dependency not in records and scope.resolve(dependency) is None]
        if missing:
            fail(name, "dependency", f"unresolved: {missing}")
        def dependency_layer(dependency, current_name=name):
            owner = dependency if dependency in records else dependency.split(".", 1)[0]
            if owner == current_name:
                return 0
            target = records.get(owner)
            return target.layer if target is not None and target.origin == "invented" else 0

        if record.layer != 1 + max((dependency_layer(dependency) for dependency in record.depends_on), default=0):
            fail(name, "layer", f"declared layer {record.layer} differs from dependency layers")

        evidence = record.evidence
        if record.status != "promoted" or evidence is None or evidence.method not in ("exhaustive", "bounded"):
            fail(name, "I4", "entry is not promoted with exhaustive or bounded evidence")
            continue
        families = entry.meta.get("slot_families") if record.kind == "combinator" else None
        family_size = (len(tuple(itertools.product(*(families[slot] for slot in record.spec.op_params))))
                       if families else len(evidence.scope.get("op_family", ())) **
                       len(getattr(record.spec, "op_params", ())))
        expected_size = evidence.scope.get("size")
        steps_size = len(state.library._steps.get(name, ()))
        request = state.requests.get(name)
        if request is None:
            fail(name, "I1/I2/I3", "verification request unavailable for exact replay")
        elif request.extra.get("reference_unavailable"):
            fail(name, "I4", "independent callable reference unavailable for exact replay")
        expected_scope = dict(request.scope) if request is not None else {}
        if request is not None:
            # The provenance is derived from the library, never read back from the evidence.
            checked_by = "library" if name in state.library._library_checked else "generator"
            expected_scope["checked"] = {**evidence_checked_scope(request.domain), "by": checked_by}
            fixed_ops = sorted(nodes.operation_literals(record.body)) if record.kind == "combinator" else []
            if fixed_ops and checked_by == "library":
                expected_scope["fixed_ops"] = fixed_ops
            attached = state.library._attached_hashes(record)
            if attached:
                expected_scope["attached"] = attached
        if (not evidence.scope.get("domain") or
                not isinstance(expected_size, int) or expected_size < 0 or
                (request is not None and (expected_size != len(request.domain) or
                                          evidence.method != request.method or
                                          evidence.scope != expected_scope)) or
                (record.kind == "object" and record.spec.form == "refine" and
                 steps_size > expected_size) or
                (record.kind != "bridge" and
                 not (record.kind == "object" and record.spec.form == "refine") and
                 expected_size * family_size != steps_size)):
            fail(name, "I4", "evidence domain or size differs from verified runs")
        if record.contract is None:
            fail(name, "I4", "missing contract")
        if evidence.world_hash != state.library.world.world_hash():
            fail(name, "I4", "world hash differs")
        try:
            if evidence.deps_hash != state.library._deps_hash(name):
                fail(name, "I4", "dependency hash differs")
        except (KeyError, ValueError) as error:
            fail(name, "I4", f"dependency hash unavailable: {error}")
        report.timings["metadata_seconds"] += time.monotonic() - metadata_start

        evaluation_start = time.monotonic()
        try:
            domain = _domain(state, entry, record)
        except (KeyError, TypeError, ValueError) as error:
            fail(name, "I1/I2", f"domain unavailable: {error}")
            continue
        if request is None and entry.signature is None and entry.kind != "object":
            fail(name, "I1/I2", "no signature; stored examples only")
        if not isinstance(expected_size, int) or len(domain) != expected_size * family_size:
            if record.kind == "object":
                fail(name, "I4", "evidence size differs from the object's verified domain")
            else:
                fail(name, "I1/I2", "reconstructed domain differs from evidence size")
        if request is not None and entry.kind in ("observation", "combinator", "object", "law", "bridge"):
            _audit_hook(state, entry, record, request, fail, report)
        elif entry.kind == "observation":
            fail(name, "I3", "observation request unavailable")
        for index, args in enumerate(() if entry.kind in ("observation", "law", "bridge") else domain):
            try:
                call_name, call_args = (_object_call(record, args) if record.kind == "object"
                                        else (name, args))
                expression = nodes.Call(call_name, tuple(nodes.Lit(arg) for arg in call_args))
                actual = kernel.call(call_name, call_args, scope, limits, dialect=state.library.dialect, trace=True)
                expanded = kernel.inline(expression, scope)
                unfolded = kernel.evaluate(expanded, scope=scope, limits=limits,
                                           dialect=state.library.dialect)
                if record.kind == "object" and record.spec.form == "compose" and not outcome_equal(actual.outcome, Ok(args[0])):
                    fail(name, "I1", f"constructor for {args[0]!r} returned {actual.outcome!r}")
                    break
                if isinstance(actual.outcome, Unknown) or not outcome_equal(actual.outcome, unfolded.outcome) or actual.steps != unfolded.steps:
                    fail(name, "I1", f"input {args!r}: named {actual.outcome!r}/{actual.steps}, unfolded {unfolded.outcome!r}/{unfolded.steps}")
                    break
                leaves = flatten_calls(actual.trace, Boundary.unfold_all())
                if any(not call.given for call in leaves) or sum(call.steps for call in leaves) + actual.jumps != actual.steps:
                    fail(name, "I1", f"input {args!r}: flattened trace loses layer-0 calls or steps")
                    break
                if index == 0:
                    boundaries = _boundaries(rng, records)
                    _check_boundary_trace(name, actual, boundaries, fail)
                    mixed = (_mixed_expression(state, entry, args, rng) if record.kind != "object"
                             else expression)
                    mixed_run = kernel.evaluate(mixed, scope=scope, limits=limits, trace=True,
                                                dialect=state.library.dialect)
                    mixed_inline = kernel.evaluate(kernel.inline(mixed, scope), scope=scope,
                                                   limits=limits, dialect=state.library.dialect)
                    if isinstance(mixed_run.outcome, Unknown) or not outcome_equal(mixed_run.outcome, mixed_inline.outcome) or mixed_run.steps != mixed_inline.steps:
                        fail(name, "I2", "mixed-call expression differs from its unfolding")
                    _check_boundary_trace(name, mixed_run, boundaries, fail)
            except (KeyError, ValueError, TypeError, AttributeError, RecursionError) as error:
                fail(name, "I1/I2", f"input {args!r}: {type(error).__name__}: {error}")
                break
        report.timings["evaluation_seconds"] += time.monotonic() - evaluation_start

    report.checked = {kind: counts.get(kind, 0) for kind in KINDS}
    try:
        derived = state.library.derived_world()
        expected = {name: record.evidence.scope for name, record in records.items()
                    if record.origin == "invented" and record.status == "promoted" and record.evidence is not None}
        if derived.scopes() != expected or len(derived.promoted) != len(expected):
            fail("<library>", "I4", "derived world does not list exactly promoted scopes")
    except (ValueError, TypeError, AttributeError, KeyError) as error:
        fail("<library>", "I4", f"derived world failed: {error}")

    if entries:
        first = next((records[entry.name] for entry in entries if entry.name in records
                      and records[entry.name].status == "promoted"), None)
        if first is not None:
            probe = copy.copy(state.library)
            probe._definitions = dict(records)
            probe._steps = dict(state.library._steps)
            sampled = replace(first.evidence, method="sampled", seed=seed)
            fresh = replace(first, name="__audit_sampled__", status="verified", evidence=sampled)
            probe._definitions[fresh.name] = fresh
            try:
                probe.promote(fresh.name, Contract("audit"))
            except PipelineError:
                pass
            else:
                fail(fresh.name, "I4", "fresh definition with sampled evidence was promoted")
            probe = copy.copy(state.library)
            probe._definitions = dict(records)
            probe._steps = dict(state.library._steps)
            changed_world = replace(state.library.world, constants={**state.library.world.constants,
                                                                       "__audit_constant__": "changed"})
            probe.world = changed_world
            changed_records = probe.definitions
            if any(original.origin == "invented" and original.evidence is not None and
                   (changed_records[name].status != "callable" or
                    changed_records[name].evidence is not None or
                    changed_records[name].contract is not None)
                   for name, original in records.items()):
                fail("<library>", "I4", "world change did not reset invented definitions to callable")
    report.timings["total_seconds"] = time.monotonic() - start
    return report


def _in_sort(state, spec, outcome, scope) -> bool:
    """A witness is a value of its sort: a card of the sort with a declared tag and arity
    (compose), or a canonical valid card that ``S.make`` rebuilds unchanged (refine)."""
    if not isinstance(outcome, Ok) or not isinstance(outcome.value, Card) or outcome.value.sort != spec.name:
        return False
    value = outcome.value
    if spec.form == "compose":
        fields = (spec.tags or {}).get(value.tag)
        return fields is not None and (isinstance(fields, dict) and "items" in fields
                                       or len(fields) == len(value.fields))
    if spec.form == "refine" and len(value.fields) == 1:
        remade = kernel.evaluate(nodes.Call(f"{spec.name}.make", (nodes.Lit(value.fields[0]),)), scope=scope,
                                 limits=kernel.Limits(fuel=state.world.fuel), dialect=state.world.dialect)
        return isinstance(remade.outcome, Ok) and remade.outcome.value == value
    return value in state.sorts[spec.name].values
