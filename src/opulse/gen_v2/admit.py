"""Admission: one candidate through the library pipeline, then the degeneracy filters.

``admit(state, candidate)`` returns an ``Entry`` (the definition is promoted and catalogued) or
a ``Rejection`` (the definition and its extra atoms are removed again). The steps are the
spec's pipeline (section 9): written -> checked -> callable -> verified -> accounted ->
promoted, followed by the generator's own filters: no ``Unknown`` on the scope, not constant,
not an identity, not all failures, not a behavioural duplicate, not too expensive.

Kind hooks. The core library verifies operations and combinators. For kinds whose core
verifier is missing or world-specific (objects; observations over a non-robot truth), a module
in ``opulse.gen_v2.kinds`` registers a ``KindHook`` with ``register_hook``. A hook replaces the
core check / callable / verify steps for its kind; evidence is stored with
``GenLibrary.record_evidence`` in the same format.
"""

from __future__ import annotations

import copy
import itertools
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace

from opulse.atoms import kernel, nodes
from opulse.atoms.library import PipelineError, VerifyRequest
from opulse.atoms.spec import Contract, Definition
from opulse.atoms.values import Bottom, Card, Ok, Unknown, outcome_equal, value_equal
from opulse.gen_v2 import fast
from opulse.gen_v2.base import Candidate, Entry, GenState, Rejection, Signature
from opulse.gen_v2.codec import encode_outcome


@dataclass
class KindHook:
    """Generator-side pipeline steps for one kind.

    * ``check(defn, lib) -> list[str]``: extra type/kind problems (empty when fine).
    * ``run(state, candidate, request) -> list[(inputs, Outcome, steps)]``: run the definition
      on ``request.domain`` (used for callable, fingerprints and examples).
    * ``verify(state, candidate, request, results) -> (checks, problems)``: the kind's
      obligations; the ``checks`` names are stored in the evidence.
    """

    check: Callable | None = None
    run: Callable | None = None
    verify: Callable | None = None


_HOOKS: dict[str, KindHook] = {}


def register_hook(kind: str, hook: KindHook) -> None:
    _HOOKS[kind] = hook


def hook_for(kind: str) -> KindHook | None:
    _load_kind_modules()
    return _HOOKS.get(kind)


def _load_kind_modules() -> None:
    import importlib
    import pkgutil

    if getattr(_load_kind_modules, "done", False):
        return
    _load_kind_modules.done = True
    try:
        package = importlib.import_module("opulse.gen_v2.kinds")
    except ImportError:
        return
    for info in pkgutil.iter_modules(package.__path__):
        importlib.import_module(f"opulse.gen_v2.kinds.{info.name}")


# ---------------------------------------------------------------------------- domains


def domain_request(state: GenState, signature: Signature, reference=None) -> VerifyRequest:
    """Default verification request over the probe values of the input sorts.

    Exhaustive when every sort has a certified finite universe and its full product fits;
    otherwise bounded: every argument among the first ``m`` probe values of its sort (the
    values of a sort are ordered by size), with ``m`` the largest bound that fits.
    """
    domains = [tuple(state.sorts[sort].values) for sort in signature.inputs]
    limit = state.world.max_scope
    total = 1
    for values in domains:
        total *= max(1, len(values))
    names = ", ".join(f"{sort} in {_describe(state.sorts[sort].values)}" for sort in signature.inputs)
    if total <= limit:
        tuples = tuple(itertools.product(*domains))
        finite = all(state.sorts[sort].finite for sort in signature.inputs)
        description = (f"all inputs with {names}" if names else "the single nullary call") if finite else (
            f"bounded: full probe product ({names}) ordered by size")
        return VerifyRequest("exhaustive" if finite else "bounded", tuples,
                             {"domain": description, "description": description, "size": len(tuples)},
                             reference=reference)
    bound = max(len(values) for values in domains)
    while bound > 1:
        size = 1
        for values in domains:
            size *= min(bound, len(values))
        if size <= limit:
            break
        bound -= 1
    tuples = tuple(itertools.product(*(values[:bound] for values in domains)))
    description = (f"bounded: every argument among the first {bound} probe values of its sort "
                   f"(up to {bound} per argument; sorts {', '.join(signature.inputs)})")
    return VerifyRequest("bounded", tuples, {"domain": description, "description": description,
                                             "size": len(tuples), "bound": bound}, reference=reference)


def _describe(values) -> str:
    if values and all(type(value) is int for value in values) and list(values) == list(range(min(values), max(values) + 1)):
        return f"{min(values)}..{max(values)}"
    return f"{len(values)} probe values"


# ---------------------------------------------------------------------------- admission


def run_on_domain(state: GenState, name: str, domain: Sequence[tuple],
                  work: list[int] | None = None) -> list[tuple]:
    lib = state.library
    defn = lib.get(name)
    scope = lib.scope()
    if scope.resolve(name) is None:  # checked, not yet callable: run it next to the library
        scope = scope.extend([kernel.Defn(name, lib._params(defn), defn.body, defn.kind, defn.layer)])
    results = []
    for args in domain:
        inputs = copy.deepcopy(args)
        run = fast.call(name, inputs, scope, state.world.fuel, lib.dialect)
        if inputs != args:
            raise ValueError("impure atom mutates its argument")
        results.append((args, run.outcome, run.steps))
        if work is not None:
            work.append(run.work)
    return results


def admit(state: GenState, candidate: Candidate, *, _import_token=None) -> Entry | Rejection:
    """Admit a candidate through the common pipeline."""
    defn = candidate.defn
    lib = state.library
    world = state.world

    def refuse(stage: str, reason: str) -> Rejection:
        lib._exhaustive_scope.pop(defn.name, None)
        lib.discard(defn.name)
        lib.remove_atoms([item.name for item in candidate.extra_atoms])
        for sort in candidate.new_sorts:
            state.sorts.pop(sort.name, None)
        for name in candidate.extra_signatures:
            state.extra_signatures.pop(name, None)
        rejection = Rejection(candidate.move, defn.kind, stage, reason[:300])
        state.rejections.append(rejection)
        if not lib.has_name(defn.name):
            state.names.release(defn.name)
        return rejection

    if defn.kind not in world.open_kinds:
        return Rejection(candidate.move, defn.kind, "closed_kind", f"{defn.kind} is closed in {world.name}")
    if lib.has_name(defn.name):
        return Rejection(candidate.move, defn.kind, "check", f"name taken: {defn.name}")
    # Nothing a candidate brings may replace an existing name (a replaced atom would change the
    # meaning of promoted definitions without touching their evidence).
    clashes = ([item.name for item in candidate.extra_atoms
                if lib.has_name(item.name) or state.world.signatures.get(item.name)]
               + [sort.name for sort in candidate.new_sorts if sort.name in state.sorts]
               + [name for name in candidate.extra_signatures
                  if name in state.extra_signatures or name in state.world.signatures])
    if clashes:
        rejection = Rejection(candidate.move, defn.kind, "check", f"names already taken: {sorted(set(clashes))}")
        state.rejections.append(rejection)
        return rejection

    # Store what a checkpoint will restore: the record after one round trip through the core
    # codec (it reads bool cards back as Python bools, for example), and the same for the
    # Defns a candidate brings (object witnesses), so a reloaded library behaves identically.
    try:
        defn = Definition.from_dict(defn.to_dict())
        candidate.extra_atoms = tuple(
            replace(item, body=nodes.from_json(nodes.to_json(item.body)))
            if isinstance(item, kernel.Defn) else item for item in candidate.extra_atoms)
    except (TypeError, ValueError) as error:
        rejection = Rejection(candidate.move, defn.kind, "check", f"definition has no JSON form: {error}")
        state.rejections.append(rejection)
        state.names.release(defn.name)
        return rejection
    candidate.defn = defn

    hook = hook_for(defn.kind)
    try:
        unique_atoms = {}
        for item in candidate.extra_atoms:
            previous = unique_atoms.get(item.name)
            if (previous is not None and previous != item and not (
                    isinstance(item, kernel.Defn) and isinstance(previous, kernel.Defn) and
                    replace(previous, layer=item.layer) == item and item.name == defn.name)):
                raise ValueError(f"conflicting extra atom: {item.name}")
            unique_atoms[item.name] = (replace(item, layer=defn.layer) if
                                       isinstance(item, kernel.Defn) and item.name == defn.name else item)
        lib.add_atoms(tuple(unique_atoms.values()))
        for sort in candidate.new_sorts:
            state.sorts[sort.name] = sort
        state.extra_signatures.update(candidate.extra_signatures)
        lib.write(defn)
        if defn.kind != "object":
            from opulse.gen_v2.kinds.objects import sealed_violation

            violation = sealed_violation(defn, state)
            if violation:
                raise PipelineError(violation)
        lib.check(defn.name, kind_checker=hook.check if hook and hook.check else None)
    except (PipelineError, ValueError, TypeError, KeyError) as error:
        return refuse("check", str(error))
    try:  # every admitted record must be storable and exportable with the core node codec
        defn.to_dict()
    except (TypeError, ValueError) as error:
        return refuse("check", f"definition has no JSON form: {error}")
    request = candidate.request
    if request is None:
        if candidate.signature is None:
            return refuse("verify", "no verification request and no signature")
        request = domain_request(state, candidate.signature)
    elif request.method == "exhaustive":
        if defn.kind == "object":
            spec = defn.spec
            finite = (spec.form == "constant" and tuple(request.domain) == ((),) or
                      spec.form == "refine" and state.sorts[spec.base].finite and
                      tuple(request.domain) == tuple((value,) for value in state.sorts[spec.base].values) or
                      spec.form == "compose" and bool(spec.tags) and
                      all(not fields for fields in spec.tags.values()) and
                      len(request.domain) == len(spec.tags) and
                      all(len(args) == 1 and isinstance(args[0], Card) and
                          args[0].sort == spec.name and not args[0].fields for args in request.domain) and
                      {args[0].tag for args in request.domain} == set(spec.tags))
            if not finite:
                description = f"bounded: {len(request.domain)} size-ordered probe values of {spec.base or spec.name}"
                request = VerifyRequest("bounded", request.domain,
                                        {**request.scope, "domain": description, "description": description},
                                        request.seed, request.reference, request.extra)
        elif defn.kind == "observation":
            truth = state.world.truth_sort
            finite = (candidate.signature is not None and
                      all(sort == truth and state.sorts[sort].finite for sort in candidate.signature.inputs) and
                      tuple(request.domain) == tuple((value,) for value in state.sorts[truth].values))
            if not finite:
                description = f"bounded: {len(request.domain)} size-ordered truth probes"
                request = VerifyRequest("bounded", request.domain,
                                        {**request.scope, "domain": description, "description": description},
                                        request.seed, request.reference, request.extra)
        elif defn.kind == "law":
            variables = defn.spec.vars
            expected = tuple(itertools.product(*(state.sorts[sort].values for _, sort in variables)))
            if not all(state.sorts[sort].finite for _, sort in variables) or tuple(request.domain) != expected:
                return refuse("verify", "exhaustive law requires the full certified finite product")
        elif defn.kind == "bridge":
            source = state.sorts[defn.spec.source]
            if not source.finite or tuple(request.domain) != tuple((value,) for value in source.values):
                return refuse("verify", "exhaustive bridge requires the full certified source sort")
        elif candidate.signature is None or not all(state.sorts[sort].finite for sort in candidate.signature.inputs):
            return refuse("verify", "exhaustive evidence requires certified finite input sorts")
        else:
            trusted = domain_request(state, candidate.signature)
            if trusted.method != "exhaustive" or tuple(request.domain) != tuple(trusted.domain):
                return refuse("verify", "exhaustive evidence must cover the full probe domain of every input sort")
            request = VerifyRequest("exhaustive", request.domain, trusted.scope, request.seed,
                                    request.reference, request.extra)
    if callable(request.reference) and request.extra.get("reference_origin") not in ("oracle", "table"):
        return refuse("verify", "callable reference requires oracle or table provenance")
    if (request.reference is not None and not isinstance(request.reference, str) and
            not callable(request.reference) and request.extra.get("reference_origin") != "table"):
        return refuse("verify", "reference table requires table provenance")
    if isinstance(request.reference, str):
        reference_defn = lib._definitions.get(request.reference)
        if (request.reference == defn.name or reference_defn is not None and
                reference_defn.origin != "given" and reference_defn.body == defn.body):
            return refuse("verify", "reference is not independent of the candidate")
        resolved = lib.resolve(request.reference)
        if (reference_defn is None or reference_defn.origin != "given") and not (
                isinstance(resolved, kernel.Atom) and request.reference in state.world.signatures):
            return refuse("verify", "reference must name a given atom")
    if request.method == "exhaustive":
        lib._exhaustive_scope[defn.name] = (tuple(request.domain), request.scope)
    memo_work: list[int] = []
    try:
        if hook and hook.run:
            results = hook.run(state, candidate, request)
        else:
            results = run_on_domain(state, defn.name, request.domain,
                                    memo_work if candidate.meta.get("memo_of") else None)
    except (ValueError, TypeError, KeyError, RecursionError, IndexError, AttributeError) as error:
        return refuse("callable", f"{type(error).__name__}: {error}")
    if defn.kind == "object" and defn.spec.form == "compose" and (len(results) != len(request.domain) or any(
            not isinstance(outcome, Ok) or not value_equal(outcome.value, args[0])
            for args, outcome, _ in results)):
        return refuse("verify", "values_in_sort: a constructor rejects a declared probe value")
    unknown = [item for item in results if isinstance(item[1], Unknown)]
    if unknown:
        return refuse("callable", f"Unknown({unknown[0][1].resource}) on {unknown[0][0]!r}")
    steps = [item[2] for item in results]
    mean = sum(steps) / len(steps) if steps else 0.0
    if mean > world.max_steps:
        return refuse("cost", f"mean layer-0 steps {mean:.1f} > {world.max_steps}")

    # The filters read only the run results, so they run before the (costlier) verification.
    from opulse.gen_v2 import interest

    fingerprint = interest.fingerprint(state, candidate, results)
    problem = interest.degenerate(state, candidate, results)
    owner = state.fingerprints.get(fingerprint)
    if owner is not None and defn.kind == "observation" and (
            lib.get(owner).spec.reads != defn.spec.reads):
        owner = None
    # Published classic operators (legacy import) are kept even when a filter would refuse them;
    # the filter verdict is recorded in the entry's meta instead.
    from opulse.gen_v2.legacy_import import _valid_import_token

    keep = _valid_import_token(_import_token, state, candidate)
    if owner is not None and owner == candidate.meta.get("memo_of") and not problem:
        from opulse.atoms.nodes import Rec

        plain = lib.get(owner)
        if (any(isinstance(node, Rec) and node.memo for node in nodes.walk(defn.body)) and
                plain.body == nodes.map_nodes(defn.body, lambda node: replace(node, memo=False)
                                               if isinstance(node, Rec) else node) and
                plain.evidence is not None and owner in state.requests and
                state.requests[owner].method == request.method and
                state.requests[owner].domain == request.domain and
                {key: value for key, value in state.requests[owner].scope.items() if key != "reference"} ==
                {key: value for key, value in request.scope.items() if key != "reference"} and
                state.entries[owner].signature == candidate.signature and
                not any(entry.meta.get("memo_of") == owner and
                        lib.get(entry.name).body == defn.body for entry in state.entries.values())):
            params = tuple(defn.spec.extra.get("input_names") or
                           (f"arg{index}" for index in range(len(candidate.signature.inputs))))
            scope = lib.scope()
            limits = kernel.Limits(fuel=world.fuel)
            different_work = False
            for index, args in enumerate(request.domain):
                env = dict(zip(params, args))
                original_run = kernel.evaluate(plain.body, env, scope, limits, dialect=lib.dialect)
                if index < len(memo_work):
                    memo_outcome, memo_steps = results[index][1:]
                    current_work = memo_work[index]
                else:
                    memo_run = kernel.evaluate(defn.body, env, scope, limits, dialect=lib.dialect)
                    memo_outcome, memo_steps, current_work = memo_run.outcome, memo_run.steps, memo_run.work
                if not outcome_equal(original_run.outcome, memo_outcome) or original_run.steps != memo_steps:
                    break
                different_work |= original_run.work != current_work
            else:
                if different_work:
                    owner = None
    if problem and not keep:
        return refuse("degenerate", problem)
    if owner is not None and not keep:
        return refuse("duplicate", f"same behaviour as {owner}")
    if keep and (problem or owner is not None):
        candidate.meta["filter_verdict"] = problem or f"same behaviour as {owner}"

    try:
        if hook and hook.verify and defn.kind not in ("law", "bridge"):
            lib.mark_callable(defn.name, steps)
            checks, problems = hook.verify(state, candidate, request, results)
            if problems:
                return refuse("verify", "; ".join(problems))
            if request.reference is None:
                checks = tuple(check for check in checks if check != "reference")
            lib.record_evidence(defn.name, request, checks, steps)
        else:
            if defn.kind in ("law", "bridge"):
                lib.mark_callable(defn.name, steps)
            else:
                lib.make_callable(defn.name, request.domain[:1] or ((),))
            if request.reference is None:
                # A generated definition has no independent oracle: its claim is its own unfolding.
                # The verifier then checks unfold equivalence only and records no "reference" check.
                table = {args: outcome for args, outcome, _ in results}
                request = VerifyRequest(request.method, request.domain,
                                        {**request.scope, "reference": "none"},
                                        request.seed, None, {**request.extra, "self_reference": True,
                                                             "table": table})
            if defn.kind == "operation":
                runs = {}
                for args, outcome, steps_ in results:
                    try:
                        if copy.deepcopy(args) != args:
                            continue
                        hash(args)
                    except (TypeError, ValueError):
                        continue
                    runs[args] = kernel.Run(outcome, steps_, 0, None)
                request = VerifyRequest(request.method, request.domain, request.scope, request.seed,
                                        request.reference, {**request.extra, "precomputed": runs,
                                                            "precomputed_scope": id(lib.scope()),
                                                            "precomputed_fuel": state.world.fuel,
                                                            "fuel": state.world.fuel})
            if defn.kind == "bridge":
                from opulse.gen_v2.kinds.bridges import typed_request

                lib.verify(defn.name, typed_request(state, request))
            else:
                lib.verify(defn.name, request)
        lib.account(defn.name)
        lib.promote(defn.name, Contract(guarantees=candidate.contract or
                                        "Equal outcome, state and layer-0 steps as its unfolding on the recorded scope."))
    except (PipelineError, ValueError, TypeError, KeyError, RecursionError) as error:
        return refuse("verify", str(error))

    lib._exhaustive_scope.pop(defn.name, None)
    record = lib.get(defn.name)
    entry = Entry(defn.name, defn.kind, defn.layer, candidate.signature, candidate.move, tuple(defn.depends_on),
                  fingerprint, mean, max(steps) if steps else 0, record.cost.length, 0, {},
                  [(args, encode_outcome(outcome) if not isinstance(outcome, Unknown) else None, steps_)
                   for args, outcome, steps_ in results[:8]], dict(candidate.meta))
    state.entries[defn.name] = entry
    state.fingerprints.setdefault(fingerprint, defn.name)
    state.requests[defn.name] = VerifyRequest(request.method, request.domain, request.scope, request.seed,
                                              request.reference,
                                              {key: value for key, value in request.extra.items() if key != "precomputed"})
    for dependency in defn.depends_on:
        if dependency in state.entries:
            state.entries[dependency].reuse += 1
    return entry


def outcomes_only(results) -> tuple:
    return tuple(outcome for _, outcome, _ in results)


__all__ = [
    "Bottom",
    "KindHook",
    "Ok",
    "admit",
    "domain_request",
    "hook_for",
    "nodes",
    "outcomes_only",
    "register_hook",
    "run_on_domain",
]
