"""``GenLibrary``: the core ``Library`` with the speed and storage the generator needs.

The generator stores hundreds to thousands of definitions in one library. The core library
rebuilds its kernel scope on every ``run`` and hashes the whole world declaration on every
``get``. ``GenLibrary`` keeps the core pipeline unchanged (write, check, make_callable, verify,
account, promote) and only adds:

* a scope cache, invalidated whenever a definition record changes;
* an immutable copy of the world declaration, with full checks at verification and export;
* extra atoms (constructors, accessors and testers of invented objects; given combinators);
* a per-definition JSON cache for the dependency hash.
"""

from __future__ import annotations

import copy
from collections.abc import Sequence
from dataclasses import fields, replace

from opulse.atoms import kernel, nodes
from opulse.atoms.check import check_definition
from opulse.atoms.library import (
    _CHECKERS,
    DEFAULT_VERIFY_FUEL,
    REQUIRED_CHECKS,
    Library,
    PipelineError,
    _ensure_kind,
    atoms_digest,
    checked_scope,
)
from opulse.atoms.spec import (
    Contract,
    Definition,
    Edge,
    Evidence,
    OperationSpec,
    content_hash,
)
from opulse.atoms.values import Bottom, Ok, Unknown, outcome_equal
from opulse.atoms.world import WorldDecl


class _FrozenDict(dict):
    def __deepcopy__(self, memo):
        return self

    def _immutable(self, *args, **kwargs):
        raise TypeError("generator world declarations are immutable")

    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = _immutable
    __ior__ = _immutable


class _FrozenList(list):
    def __deepcopy__(self, memo):
        return self

    def _immutable(self, *args, **kwargs):
        raise TypeError("generator world declarations are immutable")

    __setitem__ = __delitem__ = append = clear = extend = insert = pop = remove = reverse = sort = _immutable
    __iadd__ = __imul__ = _immutable


def _freeze(value):
    if isinstance(value, dict):
        return _FrozenDict({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return _FrozenList(_freeze(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze(item) for item in value)
    return copy.deepcopy(value)


def _freeze_object(value):
    return replace(value, **{item.name: _freeze(getattr(value, item.name))
                             for item in fields(value) if isinstance(getattr(value, item.name), (dict, list))})


def evidence_checked_scope(domain):
    """Hash variable-length observation histories as single, complete input values."""
    rows = tuple(tuple(row) for row in domain)
    if rows and any(len(row) != len(rows[0]) for row in rows):
        rows = tuple((row,) for row in rows)
    return checked_scope(rows)


def turns_helpers() -> list[kernel.Atom]:
    """The core's turn-taking combinator needs schedule and list primitives (spec 0.3); the
    library provides them under generator-private names so combinators can use them."""
    from dataclasses import replace as replace_atom

    from opulse.atoms import combinators

    helpers = combinators.turns_atoms() + combinators.list_atoms() + [
        atom for atom in combinators.counter_atoms() if atom.name == "comb_equal"]
    return ([replace_atom(atom, name=f"_gen_turns_{atom.name}") for atom in helpers] +
            [kernel.Atom("_gen_turns_apply_move", 3, lambda move, agent, state: move),
             kernel.Atom("_gen_turns_apply_state", 3, lambda move, agent, state: state)])


class _Versioned(dict):
    """A dict that counts its changes (the core library assigns records in place)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.version = 0

    def __setitem__(self, key, value):
        self.version += 1
        super().__setitem__(key, value)

    def __delitem__(self, key):
        self.version += 1
        super().__delitem__(key)

    def pop(self, *args):
        self.version += 1
        return super().pop(*args)


class GenLibrary(Library):
    def __init__(self, world: WorldDecl, atoms: Sequence[kernel.Atom], dialect: str = "atoms-v2",
                 extra_scope: Sequence[kernel.Defn] = (), signatures=None):
        """``signatures`` (name -> base.Signature, from the world adapter) types the given atoms the
        declaration leaves untyped (probes are declared under ``observation``, not as operations,
        so the core gives them ``unknown`` edges and fixed-argument reads fail the type check)."""
        world = replace(world, **{name: _freeze(getattr(world, name)) for name in
                                  ("params", "constants", "combinators", "observation", "lock", "extra")},
                        objects=tuple(_freeze_object(obj) for obj in world.objects),
                        operations=tuple(_freeze_object(op) for op in world.operations))
        super().__init__(world, atoms, dialect)
        self._definitions = _Versioned(self._definitions)
        self._synced = world
        self._extra_atoms: dict[str, kernel.Atom] = {}
        self._extra_defns: dict[str, kernel.Defn] = {defn.name: defn for defn in extra_scope}
        self._extra_atoms.update({atom.name: atom for atom in turns_helpers()
                                  if atom.name not in self._definitions})
        self._dirty = True
        self._scope_version = -1
        self._scope_cache = None
        self._json_cache: dict[int, tuple[object, dict]] = {}
        self._exhaustive_scope: dict[str, tuple] = {}
        for name, signature in (signatures or {}).items():
            given = self._definitions.get(name)
            if (given is None or given.origin != "given" or not isinstance(given.spec, OperationSpec)
                    or any(edge.sort != "unknown" for edge in (*given.spec.inputs, given.spec.output))
                    or len(signature.inputs) != len(given.spec.inputs)):
                continue
            spec = replace(given.spec, inputs=tuple(Edge(sort) for sort in signature.inputs),
                           output=Edge(signature.output))
            self._definitions[name] = replace(given, spec=spec)

    # ---- world ---------------------------------------------------------------------------

    def _sync_world(self, full: bool = False) -> None:
        """Identity check on cached accesses; full hash before verification and export."""
        if self._world is self._synced and not full:
            return
        before = self._world_hash
        super()._sync_world()
        self._synced = self._world
        if self._world_hash != before:
            self._dirty = True

    @property
    def definitions(self):
        self._sync_world()
        return super().definitions

    def get(self, name):
        self._sync_world()
        return super().get(name)

    def promote(self, name, contract):
        self._sync_world(full=True)
        defn = self.get(name)
        generated_observation = (defn.kind == "observation" and defn.evidence is not None
                                 and defn.evidence.scope.get("reference") == "none")
        if generated_observation or defn.kind in ("law", "bridge"):
            # The core's law and bridge verifiers report their own obligations, but
            # core promotion still defaults to operation's unfold_equivalence.
            # Generator rule (board 11-05): a generated observation has no oracle.
            if defn.status != "verified":
                raise PipelineError("promote requires verified status")
            evidence = defn.evidence
            problems = []
            if evidence.method == "sampled":
                problems.append("sampled evidence cannot be promoted")
            if evidence.world_hash != self.world.world_hash():
                problems.append("world hash changed")
            if evidence.deps_hash != self._deps_hash(name):
                problems.append("dependency hash changed")
            if evidence.content_hash != self.content_hash(name):
                problems.append("content hash changed")
            if evidence.atoms_hash != atoms_digest(self.atoms):
                problems.append("atoms hash changed")
            if not self._checked_match(defn):
                problems.append("checked scope missing")
            if not self._attached_match(defn):
                problems.append("attached world changed")
            if generated_observation:
                required = (REQUIRED_CHECKS["observation"] - {"reference"}) | {"unfold_equivalence"}
            else:
                required = {"holds"} if defn.kind == "law" else {"commutes", "total_on_domain"}
            missing = required - set(evidence.checks)
            if missing:
                problems.append(f"obligations not checked: {sorted(missing)}")
            if not isinstance(contract, Contract):
                problems.append("promotion needs a contract")
            if problems:
                raise PipelineError(problems)
            self._definitions[name] = replace(defn, contract=contract)
            return self._advance(name, "promoted")
        return super().promote(name, contract)

    def derived_world(self):
        self._sync_world(full=True)
        return super().derived_world()

    def to_dict(self):
        self._sync_world(full=True)
        return super().to_dict()

    # ---- extra atoms ---------------------------------------------------------------------

    def add_atoms(self, items: Sequence[kernel.Atom | kernel.Defn]) -> None:
        """Add extra atoms or Defns. A name that already resolves is refused: replacing it would
        change promoted definitions without invalidating their evidence."""
        seen = set()
        for item in items:
            if item.name in seen:
                raise ValueError(f"duplicate extra atom: {item.name}")
            seen.add(item.name)
            if self.has_name(item.name) or item.name in {atom.name for atom in self.atoms}:
                raise ValueError(f"extra atom would replace an existing name: {item.name}")
        for item in items:
            if isinstance(item, kernel.Atom):
                self._extra_atoms[item.name] = item
            else:
                self._extra_defns[item.name] = item
        self._dirty = True

    def remove_atoms(self, names: Sequence[str]) -> None:
        for name in names:
            self._extra_atoms.pop(name, None)
            self._extra_defns.pop(name, None)
        self._dirty = True

    def has_name(self, name: str) -> bool:
        return name in self._definitions or name in self._extra_atoms or name in self._extra_defns

    def discard(self, name: str) -> None:
        """Remove a refused invented definition (never a given atom)."""
        defn = self._definitions.get(name)
        if defn is not None and defn.origin == "invented":
            del self._definitions[name]
            self._steps.pop(name, None)

    # ---- scope ---------------------------------------------------------------------------

    def scope(self) -> kernel.DictScope:
        self._sync_world()
        if not self._dirty and self._scope_version == self._definitions.version:
            return self._scope_cache
        base = super().scope()
        self._scope_cache = kernel.DictScope({**base.atoms, **self._extra_atoms},
                                             {**self._extra_defns, **base.defns})
        self._scope_version = self._definitions.version
        self._dirty = False
        return self._scope_cache

    # ---- dependency hash -----------------------------------------------------------------

    def _record_json(self, name: str) -> dict:
        defn = self.get(name)
        cached = self._json_cache.get(id(defn))
        if cached is not None and cached[0] is defn:
            return cached[1]
        data = defn.to_dict()
        self._json_cache[id(defn)] = (defn, data)
        return data

    def content_hash(self, name: str) -> str:
        """The core content identity (spec 0.3), with two generator facts: names a definition
        references that are not definitions (operations generated for an object, given atoms of
        the world) bind to their owning object's content identity or the world hash; and
        identities are cached per definition record."""
        cache = self.__dict__.setdefault("_content_cache", {})
        stack = []

        def compute(current):
            definition = self.get(current)
            cached = cache.get(current)
            if cached is not None and cached[0] is definition:
                return cached[1]
            if current in stack:
                raise PipelineError(f"dependency cycle at {current}")
            stack.append(current)
            # Operations generated for an object are fixed by that object's own record (hashed with
            # it), so they enter the identity by name.
            dependencies = {}
            for dependency in definition.depends_on:
                owner = dependency.split(".", 1)[0]
                if dependency in self._definitions and dependency != current:
                    dependencies[dependency] = compute(dependency)
                elif owner in self._definitions and owner != current:
                    dependencies[dependency] = f"generated:{dependency}:{compute(owner)}"
                else:
                    dependencies[dependency] = f"generated:{dependency}"
            stack.pop()
            digest = definition.content_hash(dependencies)
            cache[current] = (definition, digest)
            return digest

        return compute(name)

    def _uses(self, name: str) -> tuple[str, ...]:
        """Include literal operations omitted by older records in the dependency hash.

        New proposals list these operations in depends_on; older records may not.
        """
        defn = self.get(name)
        plugged = tuple(sorted(nodes.operation_literals(defn.body))) if isinstance(
            defn.body, nodes.NODE_TYPES) else ()
        dependencies = tuple(defn.depends_on) + tuple(item for item in plugged if item not in defn.depends_on)
        owners = tuple(dependency.split(".", 1)[0] for dependency in dependencies
                       if "." in dependency and dependency.split(".", 1)[0] != name)
        return dependencies + tuple(owner for owner in owners if owner not in dependencies)

    def _deps_hash(self, name: str) -> str:
        seen: set[str] = set()
        stack = [name]
        while stack:
            current = stack.pop()
            for dependency in self._uses(current):
                if dependency == name or dependency in seen or dependency not in self._definitions:
                    continue
                seen.add(dependency)
                stack.append(dependency)
        digest = content_hash({dependency: self._record_json(dependency) for dependency in sorted(seen)})
        record = self.get(name)
        template = getattr(record.spec, "extra", {}).get("template")
        if template:
            digest = content_hash({"dependencies": digest, "template_digest": template["digest"]})
        if record.kind != "bridge" or ":" not in record.spec.target:
            return digest
        target_id = record.spec.target.rsplit(":", 1)[0]
        target = self._attached_worlds.get(target_id)
        if target is None or record.spec.extra.get("target_world_hash") != target.world.world_hash():
            raise PipelineError("bridge target world missing or changed")
        hashes = {operation: target.content_hash(operation)
                  for _, operation in record.spec.interface if operation in target.records()}
        if hashes != record.spec.extra.get("target_dependency_hashes"):
            raise PipelineError("bridge target dependencies changed")
        return content_hash({"source_deps": digest, "target_world": target.world.world_hash(),
                             "target_deps": hashes})

    # ---- check ---------------------------------------------------------------------------

    def resolve(self, name: str):
        """A definition record, or an extra atom / Defn (constructors of invented objects)."""
        return self._definitions.get(name) or self._extra_atoms.get(name) or self._extra_defns.get(name)

    def check(self, name: str, kind_checker=None) -> Definition:
        """The core check with extra atoms resolvable. ``kind_checker(defn, lib) -> problems``
        replaces the core kind checker when given (generic observation and object checks)."""
        defn = self.get(name)
        if defn.kind == "bridge" and ":" in defn.spec.target:
            return Library.check(self, name)
        if defn.status != "written":
            raise PipelineError("check requires written status")
        problems = check_definition(defn, self.world, self.resolve)
        if isinstance(defn.body, nodes.NODE_TYPES):
            for dependency in nodes.operation_literals(defn.body):
                if self.resolve(dependency) is None:
                    problems.append(f"unresolved literal operation: {dependency}")
        def dependency_layer(dependency):
            owner = dependency if dependency in self._definitions else dependency.split(".", 1)[0]
            record = self._definitions.get(owner)
            return record.layer if record is not None and record.origin == "invented" and owner != name else 0

        expected_layer = 1 + max((dependency_layer(dependency) for dependency in defn.depends_on), default=0)
        problems = [problem for problem in problems if not problem.startswith("layer must be ")]
        if defn.layer != expected_layer:
            problems.append(f"layer must be {expected_layer}, got {defn.layer}")
        if kind_checker is None:
            _ensure_kind(defn.kind)
            kind_checker = _CHECKERS.get(defn.kind)
        if kind_checker is not None:
            problems.extend(kind_checker(defn, self))
        if problems:
            raise PipelineError(problems)
        return self._advance(name, "checked")

    def record_evidence(self, name: str, request, checks: Sequence[str], steps: Sequence[int]) -> Definition:
        """Store evidence from a generator-side verifier (kinds the core cannot verify yet),
        with the same fields the core ``verify`` writes; status callable -> verified."""
        self._sync_world(full=True)
        defn = self.get(name)
        if defn.status != "callable":
            raise PipelineError("verify requires callable status")
        if request.method not in ("exhaustive", "bounded", "sampled") or request.method == "sampled" and request.seed is None:
            raise PipelineError("invalid verification method or missing sampled seed")
        if not request.domain or request.scope.get("size") != len(request.domain) or "domain" not in request.scope:
            raise PipelineError("verification scope must describe the exact domain")
        certified = self._exhaustive_scope.get(name)
        # The certificate fixes the domain and its description; admission may add notes to the
        # scope afterwards (reference provenance), which do not widen the claim.
        if request.method == "exhaustive" and (
                certified is None or certified[0] != tuple(request.domain)
                or any(certified[1].get(key) != request.scope.get(key) for key in ("domain", "size"))):
            raise PipelineError("exhaustive evidence requires a certified finite domain")
        if "reference" in checks:
            reference = request.reference
            other = self._definitions.get(reference) if isinstance(reference, str) else None
            if (reference is None or reference == name or
                    other is not None and (other.origin != "given" or other.body == defn.body) or
                    isinstance(reference, str) and other is None and not (
                        isinstance(self.resolve(reference), kernel.Atom) and
                        reference in {atom.name for atom in self.atoms}) or
                    callable(reference) and request.extra.get("reference_origin") not in ("oracle", "table") or
                    not isinstance(reference, str) and not callable(reference) and
                    request.extra.get("reference_origin") != "table"):
                raise PipelineError("reference check requires independent provenance")
        scope = {**request.scope, "checked": {**evidence_checked_scope(copy.deepcopy(request.domain)),
                                              "by": "generator"}}
        attached = self._attached_hashes(defn)
        if attached:
            scope["attached"] = attached
        evidence = Evidence(request.method, scope, request.seed, tuple(checks),
                            self.world.world_hash(), self._deps_hash(name), self.content_hash(name),
                            atoms_digest(self.atoms))
        self._steps[name] = list(steps)
        return super().record_evidence(name, evidence)

    def mark_callable(self, name: str, steps: Sequence[int] = ()) -> Definition:
        """checked -> callable after a generator-side run (observations over non-robot truths)."""
        if self.get(name).status != "checked":
            raise PipelineError("make_callable requires checked status")
        self._steps[name] = list(steps)
        return self._advance(name, "callable")

    # ---- verify --------------------------------------------------------------------------

    def verify(self, name: str, request) -> Definition:
        """The core verifiers; operations reuse a single precomputed unfolding."""
        self._sync_world(full=True)
        kind = self.get(name).kind
        if kind in ("law", "bridge"):
            from opulse.atoms import bridges, laws

            if self.get(name).status != "callable":
                raise PipelineError("verify requires callable status")
            if (request.method not in ("exhaustive", "bounded", "sampled") or
                    request.method == "sampled" and request.seed is None):
                raise PipelineError("invalid verification method or missing sampled seed")
            if not request.domain or request.scope.get("size") != len(request.domain) or "domain" not in request.scope:
                raise PipelineError("verification scope must describe the exact domain")
            verifier = laws.verify_law if kind == "law" else bridges.verify_bridge
            record = self.get(name)
            if kind == "bridge" and ":" in record.spec.target:
                from opulse.atoms.bridges import BridgeContext

                target_id = record.spec.target.rsplit(":", 1)[0]
                target = self._attached_worlds.get(target_id)
                if target is None:
                    raise PipelineError("bridge target world not attached")
                context = BridgeContext(self, target)
                request = replace(request, extra={key: value for key, value in request.extra.items()
                                                  if key != "bridge_context"})
            else:
                context = self
            result = verifier(record, context, request)
            if not result.ok:
                raise PipelineError(result.problems)
            return self.record_evidence(name, request, result.checks, result.steps)
        if kind != "operation":
            return super().verify(name, request)
        defn = self.get(name)
        if defn.status != "callable":
            raise PipelineError("verify requires callable status")
        if request.method not in ("exhaustive", "bounded", "sampled") or request.method == "sampled" and request.seed is None:
            raise PipelineError("invalid verification method or missing sampled seed")
        if request.scope.get("size") != len(request.domain) or "domain" not in request.scope:
            raise PipelineError("verification scope must describe the exact domain")
        checks, problems, steps = self._operation_verifier_once(defn, request)
        if problems:
            raise PipelineError(problems)
        return self.record_evidence(name, request, checks, steps)

    def _operation_verifier_once(self, defn: Definition, request):
        """The core operation verifier (reference + unfold equivalence on every input), with
        the full unfolding built ONCE over the parameter variables instead of once per input.
        For every input: the call by name, the reference and the unfolded layer-0 body bound to
        the input must agree on the outcome; the call and the unfolding on the layer-0 steps.
        ``request.extra["precomputed"]`` may hold the calls by name already run by ``admit`` on the
        same scope (they are not run twice)."""
        from opulse.gen_v2 import fast

        if isinstance(request.reference, str):
            reference_defn = self._definitions.get(request.reference)
            if (request.reference == defn.name or reference_defn is not None and
                    (reference_defn.origin != "given" or reference_defn.body == defn.body)):
                return (), ["reference is not independent of the candidate"], []
            resolved = self.resolve(request.reference)
            if (reference_defn is None or reference_defn.origin != "given") and not (
                    isinstance(resolved, kernel.Atom) and
                    request.reference in {atom.name for atom in self.atoms}):
                return (), ["reference must name a given atom"], []
        if callable(request.reference) and request.extra.get("reference_origin") not in ("oracle", "table"):
            return (), ["callable reference requires oracle or table provenance"], []
        scope = self.scope()
        fuel = request.extra.get("fuel", DEFAULT_VERIFY_FUEL)
        params = self._params(defn)
        unfolded = kernel.inline(nodes.Call(defn.name, tuple(nodes.Var(param) for param in params)), scope)
        problems, steps = [], []
        precomputed = (request.extra.get("precomputed") or {}) if (
            request.extra.get("precomputed_scope") == id(scope) and
            request.extra.get("precomputed_fuel") == fuel) else {}
        for args in request.domain:
            try:
                def checked(run, original=args):
                    inputs = copy.deepcopy(original)
                    result = run(inputs)
                    if inputs != original:
                        raise ValueError("impure atom mutates its argument")
                    return result

                try:
                    actual = precomputed.get(args) if precomputed else None
                except TypeError:
                    actual = None
                if actual is None:
                    actual = checked(lambda inputs: fast.call(defn.name, inputs, scope, fuel, self.dialect))
                expected = (checked(lambda inputs: fast.call(request.reference, inputs, scope, fuel, self.dialect).outcome)
                            if isinstance(request.reference, str) else
                            checked(lambda inputs: request.reference(*inputs)) if callable(request.reference) else
                            actual.outcome)
                if not isinstance(expected, (Ok, Bottom, Unknown)):
                    expected = Ok(expected)
                if not outcome_equal(actual.outcome, expected):
                    problems.append(f"reference counterexample {args!r}: {actual.outcome!r} != {expected!r}")
                    break
                inline_run = checked(lambda inputs: fast.evaluate(
                    unfolded, dict(zip(params, inputs)), scope, fuel, self.dialect))
                if not outcome_equal(actual.outcome, inline_run.outcome) or actual.steps != inline_run.steps:
                    problems.append(f"unfold_equivalence counterexample {args!r}: {actual!r} != {inline_run!r}")
                    break
                steps.append(actual.steps)
            except (ValueError, TypeError, KeyError, RecursionError) as error:
                problems.append(f"counterexample {args!r}: {error}")
                break
        own = request.reference is None or request.extra.get("self_reference", False)
        checks = (() if problems else ("unfold_equivalence",) if own else ("reference", "unfold_equivalence"))
        return checks, problems, steps
