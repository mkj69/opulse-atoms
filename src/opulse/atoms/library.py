"""Definition library and promotion pipeline (docs/spec/atoms-v2.md, sections 4, 8-12).

Invented operations enter at input and output edges inside their kernel definition:
bottom rejects invalid values, normalize canonicalizes before validating,
saturate clamps, and legacy-v1 fold applies the named legacy bound. Entry work
is charged at the edge, including when the definition is unfolded (invariant I1).
Unrestricted refine sorts backed by given base-valued host operations retain their
existing base representation on default bottom edges.
Evidence without a checked scope is invalidated. World-local verifiers must
record checked inputs; ``Library.verify`` computes and marks its own scope.
"""

from __future__ import annotations

import functools
import hashlib
import inspect
import itertools
import json
import random
import re
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import asdict, dataclass, field, is_dataclass, replace
from types import CodeType, MappingProxyType, ModuleType

from opulse.atoms import kernel, nodes
from opulse.atoms.check import all_dependencies, check_definition, validation_problems
from opulse.atoms.spec import (
    BridgeSpec,
    CombinatorSpec,
    Contract,
    Cost,
    Definition,
    Edge,
    Evidence,
    ObjectSpec,
    ObservationSpec,
    OperationSpec,
    advance,
    content_hash,
    is_host_rule,
    reset,
)
from opulse.atoms.values import (
    Bottom,
    Card,
    Ok,
    Unknown,
    encode,
    outcome_equal,
    truth,
)
from opulse.atoms.world import DerivedWorld, WorldDecl
from opulse.core.semantics import Semantics

DEFAULT_VERIFY_FUEL = 1_000_000  # layer-0 steps per checked input; Unknown(fuel) fails the check


def atoms_digest(atoms: Sequence[kernel.Atom]) -> str:
    visiting: set[int] = set()
    code_cache: dict[CodeType, tuple] = {}
    reachable: list[object] = []
    reference_ids: dict[int, int] = {}
    implementations: list[tuple] = []
    own_modules = {getattr(getattr(value, "func", value), "__module__", "")
                   for atom in atoms for value in (atom.fn, atom.cost) if callable(value)}

    def allowed(value):
        module = getattr(value, "__module__", type(value).__module__)
        return module.startswith("opulse") or module in own_modules

    def reference(value):
        identity = id(value)
        if identity not in reference_ids:
            reference_ids[identity] = len(reachable)
            reachable.append(value)
        return ("reference", reference_ids[identity])

    def stable(value):
        kind = (type(value).__module__, type(value).__qualname__)
        if value is None or type(value) in (str, int, bool, float, bytes):
            return (type(value).__name__, value.hex() if isinstance(value, bytes) else value)
        if isinstance(value, CodeType):
            if value not in code_cache:
                code_cache[value] = (value.co_code.hex(), tuple(stable(item) for item in value.co_consts),
                                     value.co_names, value.co_varnames, value.co_freevars, value.co_cellvars)
            return code_cache[value]
        if inspect.isfunction(value) or inspect.ismethod(value):
            function = getattr(value, "__func__", value)
            if not allowed(function):
                return ("function", function.__module__, function.__qualname__)
            return (reference(function), stable(value.__self__) if inspect.ismethod(value) else None)
        if isinstance(value, type):
            return (reference(value) if allowed(value) else ("class", value.__module__, value.__qualname__))
        if isinstance(value, functools.partial):
            return ("partial", stable(value.func), stable(value.args), stable(value.keywords))
        if isinstance(value, ModuleType):
            return ("module", value.__name__)
        if id(value) in visiting:
            return ("cycle", kind)
        visiting.add(id(value))
        try:
            if isinstance(value, (tuple, list)):
                return (type(value).__name__, tuple(stable(item) for item in value))
            if isinstance(value, dict):
                return ("dict", tuple((stable(key), stable(item))
                                      for key, item in sorted(value.items(), key=lambda pair: repr(pair[0]))))
            if isinstance(value, (set, frozenset)):
                return ("set", tuple(stable(item) for item in sorted(value, key=repr)))
            if hasattr(value, "__dict__") and allowed(value):
                return (*kind, stable(vars(value)), stable(type(value)) if callable(value) else None)
            return kind
        finally:
            visiting.remove(id(value))

    records = []
    for atom in sorted(atoms, key=lambda item: item.name):
        records.append((atom.name, atom.arity, stable(atom.cost), atom.kind, atom.strict, atom.metered,
                        stable(atom.fn), atom.cost_rule))
    index = 0
    while index < len(reachable):
        target = reachable[index]
        index += 1
        if inspect.isfunction(target):
            code = target.__code__
            globals_ = target.__globals__
            referenced = []
            for name in dict.fromkeys(code.co_names):
                helper = globals_.get(name)
                if (inspect.isfunction(helper) or isinstance(helper, type)) and allowed(helper):
                    referenced.append((name, stable(helper)))
                elif isinstance(helper, ModuleType):
                    referenced.extend((f"{name}.{member}", stable(member_helper))
                                      for member in code.co_names
                                      if (inspect.isfunction(member_helper := vars(helper).get(member)) or
                                          isinstance(member_helper, type)) and allowed(member_helper))
            implementations.append(("function", target.__module__, target.__qualname__, stable(code),
                                    tuple(stable(cell.cell_contents) for cell in (target.__closure__ or ())),
                                    stable(target.__defaults__), stable(target.__kwdefaults__), tuple(referenced)))
        else:
            methods = ((name, method.__func__ if isinstance(method, (staticmethod, classmethod)) else method)
                       for name, method in vars(target).items())
            implementations.append(("class", target.__module__, target.__qualname__,
                                    tuple((name, stable(method)) for name, method in methods
                                          if inspect.isfunction(method))))
    return hashlib.sha256(repr((tuple(records), tuple(implementations))).encode()).hexdigest()


def _apply_rule(context, name: str, rule, value):
    """Run a valid/canon rule at an edge: a kernel node over x, or a layer-0 host rule (spec 4.1)."""
    if is_host_rule(rule):
        from opulse.atoms.objects import _host_callable

        target = _host_callable(rule)
        try:
            return kernel._outcome(target(value))
        except (TypeError, ValueError) as error:
            return Bottom(f"invalid: {error}")
    return context.call(kernel.Defn(name, ("x",), rule, "object"), (value,))


class _Records(dict):
    """The library's records; every write bumps ``version`` so derived caches know when to rebuild."""

    version = 0

    def _bump(self):
        self.version += 1

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        self._bump()

    def __delitem__(self, key):
        super().__delitem__(key)
        self._bump()

    def pop(self, *args):
        result = super().pop(*args)
        self._bump()
        return result

    def update(self, *args, **kwargs):
        super().update(*args, **kwargs)
        self._bump()

    def clear(self):
        super().clear()
        self._bump()


class PipelineError(ValueError):
    def __init__(self, problems: str | Sequence[str]):
        self.problems = [problems] if isinstance(problems, str) else list(problems)
        super().__init__("; ".join(self.problems))


@dataclass(frozen=True)
class VerifyRequest:
    method: str
    domain: Sequence[tuple]
    scope: dict
    seed: int | None = None
    reference: Callable | str | None = None
    extra: dict = field(default_factory=dict)


@dataclass
class VerifyResult:
    ok: bool
    checks: tuple[str, ...]
    problems: list[str]
    steps: list[int]


KindChecker = Callable[[Definition, "Library"], list[str]]
KindVerifier = Callable[[Definition, "Library", VerifyRequest], VerifyResult]
_CHECKERS: dict[str, KindChecker] = {}
_VERIFIERS: dict[str, KindVerifier] = {}


def register_kind(kind: str, checker: KindChecker | None = None,
                  verifier: KindVerifier | None = None) -> None:
    if checker is not None:
        _CHECKERS[kind] = checker
    if verifier is not None:
        _VERIFIERS[kind] = verifier


def exhaustive(domains: Sequence[Sequence[object]], description: str) -> VerifyRequest:
    domain = tuple(itertools.product(*domains))
    return VerifyRequest("exhaustive", domain, {"domain": description, "description": description, "size": len(domain)})


def bounded(domains: Sequence[Sequence[object]], description: str) -> VerifyRequest:
    if not description or not re.search(r"\d", description) or not any(
        word in description.lower() for word in ("bound", "up to", "≤", "<=")):
        raise ValueError("bounded description must state the bound")
    domain = tuple(itertools.product(*domains))
    return VerifyRequest("bounded", domain, {"domain": description, "description": description, "size": len(domain)})


def sampled(generator, count: int, seed: int, description: str) -> VerifyRequest:
    randomizer = random.Random(seed)
    domain = tuple(tuple(item) for item in (generator(randomizer) for _ in range(count)))
    return VerifyRequest("sampled", domain, {"domain": description, "description": description, "size": count}, seed)


def checked_scope(domain: Sequence[tuple]) -> dict:
    """Describe the exact checked inputs for evidence (spec section 9)."""
    def serializable(value):
        try:
            return encode(value)
        except TypeError:
            if is_dataclass(value):
                return {"type": type(value).__qualname__, "fields": serializable(asdict(value))}
            if isinstance(value, (list, tuple)):
                return [serializable(item) for item in value]
            if isinstance(value, dict):
                return {str(key): serializable(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
            return {"type": type(value).__qualname__, "value": repr(value)}

    if not domain:
        raise PipelineError("verification domain must be nonempty")
    data = json.dumps([serializable(tuple(row)) for row in domain], sort_keys=True,
                      separators=(",", ":"), ensure_ascii=False)
    width = len(domain[0])
    if any(len(row) != width for row in domain):
        raise PipelineError("verification domain tuples must have equal arity")
    bounds = {str(index): {"min": min(row[index] for row in domain),
                            "max": max(row[index] for row in domain)}
              for index in range(width) if all(type(row[index]) is int for row in domain)}
    return {"size": len(domain), "sha256": hashlib.sha256(data.encode("utf-8")).hexdigest(),
            "bounds": bounds}


_checked_scope = checked_scope


def _operation_verifier(defn: Definition, lib: Library, request: VerifyRequest) -> VerifyResult:
    problems, steps = [], []
    if request.reference is None:
        return VerifyResult(False, (), ["operation verification requires a reference"], [])
    reference_owner = (request.reference.split(".", 1)[0]
                       if isinstance(request.reference, str) else None)
    if isinstance(request.reference, str) and (
            reference_owner == defn.name or
            reference_owner in lib._definitions and
            defn.name in lib._transitive_dependencies(reference_owner)):
        return VerifyResult(False, (), ["operation reference depends on the definition"], [])
    checks = ("reference", "unfold_equivalence")
    scope = lib.scope()
    fuel = request.extra.get("fuel", DEFAULT_VERIFY_FUEL)
    for args in request.domain:
        try:
            actual = lib.run(defn.name, deepcopy(args), fuel=fuel)
            expected = (lib.run(request.reference, deepcopy(args), fuel=fuel).outcome
                        if isinstance(request.reference, str) else request.reference(*deepcopy(args)))
            if not isinstance(expected, (Ok, Bottom, Unknown)):
                expected = Ok(expected)
            if not outcome_equal(actual.outcome, expected):
                problems.append(f"reference counterexample {args!r}: {actual.outcome!r} != {expected!r}")
                break
            unfolded = kernel.inline(nodes.Call(defn.name, tuple(nodes.Lit(arg) for arg in deepcopy(args))), scope)
            inline_run = kernel.evaluate(unfolded, scope=scope, limits=kernel.Limits(fuel=fuel),
                                         dialect=lib.dialect)
            if not outcome_equal(actual.outcome, inline_run.outcome) or actual.steps != inline_run.steps:
                problems.append(f"unfold_equivalence counterexample {args!r}: {actual!r} != {inline_run!r}")
                break
            steps.append(actual.steps)
        except (ValueError, TypeError, KeyError, RecursionError) as error:
            problems.append(f"counterexample {args!r}: {error}")
            break
    return VerifyResult(not problems, checks if not problems else (), problems, steps)


register_kind("operation", verifier=_operation_verifier)

# Obligations a verification must have passed before promotion, per kind (spec 9).
REQUIRED_CHECKS = {"operation": frozenset({"unfold_equivalence"}),
                   "combinator": frozenset({"unfold_equivalence"}),
                   "observation": frozenset({"dependency", "facts_unchanged", "non_interference"}),
                   "object": frozenset(),
                   "law": frozenset({"holds"}),
                   "bridge": frozenset({"commutes"}),
                   "template": frozenset({"family"})}

# Kind modules plug in lazily: importing them pulls in world code (the robot world for probes).
_KIND_MODULES = {"object": ("opulse.atoms.objects", "check_object", "verify_object"),
                 "observation": ("opulse.atoms.observations", "check_observation", "verify_observation"),
                 "combinator": ("opulse.atoms.combinators", "check_combinator", "verify_combinator"),
                 "law": ("opulse.atoms.laws", "check_law", "verify_law"),
                 "bridge": ("opulse.atoms.bridges", "check_bridge", "verify_bridge"),
                 "template": ("opulse.atoms.templates", "check_template", "verify_template")}


def _kind_open(defn: Definition, world: WorldDecl) -> bool:
    """A template is open when the kind it produces is open (spec 19.3)."""
    kind = defn.spec.produces if defn.kind == "template" else defn.kind
    return kind in world.open_kinds


def _ensure_kind(kind: str) -> None:
    if kind in _KIND_MODULES and kind not in _VERIFIERS:
        import importlib

        module_name, checker, verifier = _KIND_MODULES[kind]
        module = importlib.import_module(module_name)
        register_kind(kind, getattr(module, checker), getattr(module, verifier))


class Library:
    def __init__(self, world: WorldDecl, atoms: Sequence[kernel.Atom], dialect: str = "atoms-v2"):
        self._world = world
        self._world_hash = world.world_hash()
        self.atoms = tuple(atoms)
        self._atoms_hash = atoms_digest(self.atoms)
        self.dialect = world.dialect if dialect == "atoms-v2" else dialect
        self._definitions: dict[str, Definition] = _Records()
        self._steps: dict[str, list[int]] = {}
        self._solutions: list[nodes.Node] = []
        self._attached_worlds: dict[str, Library] = {}
        self._library_checked: set[str] = set()
        operations = {op.name: op for op in world.operations}
        for atom in self.atoms:
            op = operations.get(atom.name) or OperationSpec(atom.name, "transform", tuple(Edge("unknown") for _ in range(atom.arity)), Edge("unknown"), atom.name)
            self._definitions[atom.name] = Definition(atom.name, atom.kind, "given", 0, (), op,
                                                      {"host": atom.name}, status="promoted")
        from opulse.atoms.combinators import standard_combinators

        standards = {spec.name: spec for spec in standard_combinators()}
        for entry in world.combinators.get("library", ()):
            spec = (standards.get(entry) if isinstance(entry, str) else
                    entry if isinstance(entry, CombinatorSpec) else CombinatorSpec.from_dict(entry))
            if spec is None:  # a name the world implements itself (e.g. robot repeat_until): left to it
                self.unresolved_combinators = (*getattr(self, "unresolved_combinators", ()), entry)
                continue
            if spec.name in self._definitions:
                raise PipelineError(f"duplicate given combinator: {spec.name}")
            self._definitions[spec.name] = Definition(spec.name, "combinator", "given", 0, (), spec,
                                                       spec.body, status="promoted")

    @property
    def world(self) -> WorldDecl:
        self._sync_world()
        return self._world

    @world.setter
    def world(self, new_world: WorldDecl) -> None:
        self._world = new_world
        self._sync_world()

    def _version(self) -> tuple:
        """Changes whenever a record, the world or the atoms change (records are replaced, never edited)."""
        return (self._world_hash, self.atoms, self._definitions.version)

    def _cached(self, slot: str, build):
        version = self._version()
        cache = self.__dict__.setdefault("_cache", {})
        if cache.get(slot, (None,))[0] != version:
            cache[slot] = (version, build())
        return cache[slot][1]

    def _sync_world(self) -> None:
        if getattr(self, "_sync_suspended", False):
            return
        current = self._world.world_hash()
        atoms_hash = atoms_digest(self.atoms)
        changed = current != self._world_hash or atoms_hash != self._atoms_hash
        if not changed:
            for defn in self._definitions.values():
                if (defn.origin == "invented" and defn.evidence is not None and
                        (not self._checked_match(defn) or not self._attached_match(defn))):
                    changed = True
                    break
        if changed:
            stale = {name for name, defn in self._definitions.items()
                     if defn.origin == "invented" and defn.evidence is not None and
                     (current != self._world_hash or atoms_hash != self._atoms_hash or
                      not self._checked_match(defn) or
                      not self._attached_match(defn))}
            pending = set(stale)
            while pending:
                dependency = pending.pop()
                for name, defn in self._definitions.items():
                    if (name not in stale and defn.origin == "invented" and defn.evidence is not None
                            and dependency in self._dependency_names(defn)):
                        stale.add(name)
                        pending.add(name)
            for name, defn in list(self._definitions.items()):
                if name in stale:
                    self._definitions[name] = replace(defn, status=reset(defn.status), evidence=None, contract=None)
                    self._steps.pop(name, None)
            self._world_hash = current
            self._atoms_hash = atoms_hash
        for name, defn in list(self._definitions.items()):
            if defn.origin == "invented" and defn.status in ("verified", "promoted") and defn.evidence is None:
                self._definitions[name] = replace(defn, status="callable", contract=None)
                self._steps.pop(name, None)

    def _attached_hashes(self, defn: Definition) -> dict:
        if defn.kind != "bridge":
            return {}
        if ":" not in defn.spec.target:
            return {}
        target = defn.spec.target.rsplit(":", 1)[0]
        if target == f"{self._world.world}@{self._world.version}":
            return {}
        other = self._attached_worlds.get(target)
        if other is None:
            return {}
        from opulse.atoms.bridges import BridgeContext, target_definition_names

        names = target_definition_names(defn.spec, BridgeContext(self, other))
        return {target: {"world_hash": other._world.world_hash(), "atoms_hash": atoms_digest(other.atoms),
                         "definitions": {name: other.content_hash(name) for name in sorted(names)}}}

    def _attached_match(self, defn: Definition) -> bool:
        expected = defn.evidence.scope.get("attached", {})
        return expected == self._attached_hashes(defn) and (
            defn.kind != "bridge" or ":" not in defn.spec.target or defn.spec.target.rsplit(":", 1)[0] ==
            f"{self._world.world}@{self._world.version}" or bool(expected))

    def _checked_match(self, defn: Definition) -> bool:
        if defn.evidence is None:
            return False
        return (defn.evidence.checked_recorded() and
                (defn.name not in self._library_checked or
                 defn.evidence.scope["checked"].get("by") == "library"))

    @property
    def definitions(self) -> dict[str, Definition]:
        """Every definition by name (given and invented); a fresh deep copy per access."""
        self._sync_world()
        return deepcopy(self._definitions)

    def records(self):
        """Read-only mapping of internal records for trusted atoms modules; do not mutate records."""
        self._sync_world()
        return MappingProxyType(self._definitions)

    def attach_world(self, world_id: str, other_library: Library) -> None:
        """Register a bridge target by ``world@version`` for check/verify; attach again after reload."""
        if world_id != f"{other_library.world.world}@{other_library.world.version}":
            raise PipelineError(f"attached world does not match {world_id}")
        self._attached_worlds[world_id] = other_library

    def _bridge_context(self, defn: Definition):
        from opulse.atoms.bridges import BridgeContext

        target_id = defn.spec.target.rsplit(":", 1)[0] if ":" in defn.spec.target else None
        if target_id is None or target_id == f"{self.world.world}@{self.world.version}":
            return BridgeContext(self, self)
        if target_id not in self._attached_worlds:
            raise PipelineError(f"bridge target world not attached: {target_id}")
        return BridgeContext(self, self._attached_worlds[target_id])

    @staticmethod
    def _runtime_checked_definition(defn: Definition, context) -> Definition:
        if context is None or context.source_lib is context.target_lib:
            return defn
        from opulse.atoms.bridges import runtime_bridge_defn

        body = runtime_bridge_defn(defn.spec, context).body
        return replace(defn, body=body,
                       depends_on=tuple(sorted(nodes.references(body) | nodes.operation_literals(body))))

    def get(self, name: str) -> Definition:
        self._sync_world()
        return deepcopy(self._definitions[name])

    def content_hash(self, name: str) -> str:
        visiting = set()
        cached = {}

        def compute(current):
            if current in visiting:
                raise PipelineError(f"dependency cycle at {current}")
            if current not in cached:
                visiting.add(current)
                definition = self._definitions[current]
                # Generated operations (object constructors, accessors) and the definition itself
                # are leaves: they are identified by name, like _deps_hash does.
                names = self._dependency_names(definition)
                dependencies = {dependency: compute(dependency)
                                if dependency in self._definitions and dependency != current else
                                compute(dependency.split(".", 1)[0])
                                if dependency.split(".", 1)[0] in self._definitions else dependency
                                for dependency in names}
                cached[current] = replace(definition, depends_on=tuple(sorted(names))).content_hash(dependencies)
                visiting.remove(current)
            return cached[current]

        return compute(name)

    def by_hash(self, digest: str) -> Definition | None:
        for name, definition in self.definitions.items():
            try:
                if self.content_hash(name) == digest:
                    return definition
            except (KeyError, PipelineError):
                continue
        return None

    @staticmethod
    def _dependency_names(defn: Definition) -> set[str]:
        op_params = set(defn.spec.op_params) if isinstance(defn.spec, CombinatorSpec) else set()
        names = set(defn.depends_on) | (all_dependencies(defn) - {defn.name} - op_params)
        if defn.kind == "object" and isinstance(defn.spec, ObjectSpec):
            for expression in (defn.spec.valid, defn.spec.canon):
                if isinstance(expression, nodes.NODE_TYPES):
                    names.update(nodes.all_dependencies(expression) - {defn.name})
        return names

    def _transitive_dependencies(self, name: str) -> set[str]:
        seen = set()
        pending = [name]
        while pending:
            current = pending.pop()
            if current in seen or current not in self._definitions:
                continue
            seen.add(current)
            definition = self._definitions[current]
            dependencies = self._dependency_names(definition)
            if definition.kind == "object" and isinstance(definition.spec, ObjectSpec):
                for expression in (definition.spec.valid, definition.spec.canon):
                    if isinstance(expression, nodes.NODE_TYPES):
                        dependencies.update(nodes.references(expression) | nodes.operation_literals(expression))
            pending.extend(dependencies - seen)
        return seen - {name}

    def _advance(self, name, target):
        definition = self.get(name)
        if target in ("verified", "promoted") and definition.evidence is None:
            raise PipelineError(f"{target} requires evidence")
        try:
            status = advance(definition.status, target)
        except ValueError as error:
            raise PipelineError(str(error)) from error
        self._definitions[name] = replace(definition, status=status)
        return self.get(name)

    def write(self, defn: Definition, replace: bool = False) -> Definition:
        if defn.origin == "invented" and not _kind_open(defn, self.world):
            raise PipelineError(f"kind {defn.kind} is closed in world {self.world.world}")
        if defn.evidence is not None or defn.contract is not None:
            raise PipelineError("written definitions cannot inherit evidence or contracts")
        if defn.name in self._definitions:
            if replace:
                return self.replace(defn.name, defn)
            raise PipelineError(f"definition already exists: {defn.name}")
        if defn.status != "written" or defn.origin != "invented":
            raise PipelineError("write requires a written invented definition")
        problems = validation_problems(defn)
        if problems:
            raise PipelineError(problems)
        self._definitions[defn.name] = defn
        return defn

    def discard(self, name: str) -> Definition:
        """Remove a written or checked invention so the name can be reused."""
        defn = self.get(name)
        if defn.origin != "invented" or defn.status not in ("written", "checked"):
            raise PipelineError("discard requires a written or checked invented definition")
        dependents = sorted(other.name for other in self._definitions.values()
                            if other.name != name and name in self._dependency_names(other))
        if dependents:
            raise PipelineError(f"cannot discard {name}; dependents: {', '.join(dependents)}")
        del self._definitions[name]
        self._steps.pop(name, None)
        return defn

    def check(self, name: str) -> Definition:
        defn = self.get(name)
        if defn.status != "written":
            raise PipelineError("check requires written status")
        scope = self.scope()  # generated object operations resolve too (constructors, accessors, make, fold)
        context = self._bridge_context(defn) if defn.kind == "bridge" else None
        target_scope = context.target_lib.scope() if context is not None else None
        checked_defn = self._runtime_checked_definition(defn, context)
        problems = check_definition(checked_defn, self.world, lambda name: self._definitions.get(name) or scope.resolve(name)
                                    or (context.target_lib.records().get(name) or target_scope.resolve(name)
                                        if context is not None else None))
        from opulse.atoms.objects import sealed_private_names

        problems.extend(f"sealed object private name: {dependency}"
                        for dependency in sorted(self._dependency_names(defn) & sealed_private_names(self)))
        _ensure_kind(defn.kind)
        checker = _CHECKERS.get(defn.kind)
        if checker:
            problems.extend(checker(defn, context if context is not None else self))
        if problems:
            raise PipelineError(problems)
        return self._advance(name, "checked")

    def _params(self, defn: Definition) -> tuple[str, ...]:
        if isinstance(defn.spec, OperationSpec):
            names = defn.spec.extra.get("input_names", ())
            if not names:
                edges = tuple(edge.name for edge in defn.spec.inputs)
                names = edges if all(edges) else ()
            return tuple(names) if len(names) == len(defn.spec.inputs) else tuple(f"arg{index}" for index in range(len(defn.spec.inputs)))
        if isinstance(defn.spec, ObservationSpec):  # ?obs{s}: called with the observed subject
            if "inputs" in defn.spec.extra:
                return tuple(name for name, _ in defn.spec.extra["inputs"])
            subject = defn.spec.subject
            expressions = [defn.body]
            if defn.spec.memory:
                expressions.append(defn.spec.memory["step"])
            uses = any(isinstance(item, nodes.Var) and item.name == subject
                       for expression in expressions for item in nodes.walk(expression))
            return (subject,) if uses else ()
        if isinstance(defn.spec, BridgeSpec):  # ~name(x)
            return ("x",)
        if defn.kind == "law":
            return tuple(name for name, _ in defn.spec.vars)
        return tuple(getattr(defn.spec, "params", ()))

    def _entered_body(self, defn: Definition):
        body = defn.body
        if not isinstance(defn.spec, OperationSpec):
            return body
        if self._edge_needed(defn.spec.output):
            body = nodes.Call(self._edge_name(defn.name, "output"), (body,))
        for index, param in reversed(tuple(enumerate(self._params(defn)))):
            if self._edge_needed(defn.spec.inputs[index]):
                body = nodes.Let(param, nodes.Call(self._edge_name(defn.name, str(index)),
                                                  (nodes.Var(param),)), body)
        return body

    @staticmethod
    def _edge_name(name: str, position: str) -> str:
        return f"__opulse_edge_{name}_{position}"

    @staticmethod
    def _operation_edges(spec: OperationSpec) -> tuple[tuple[str, Edge], ...]:
        return tuple((str(index), edge) for index, edge in enumerate(spec.inputs)) + (("output", spec.output),)

    def _edge_needed(self, edge: Edge) -> bool:
        if edge.enter != "bottom":
            return True
        refined = next((obj for obj in self._world.objects if obj.name == edge.sort and obj.form == "refine"), None)
        if refined is None:
            refined = next((item.spec for item in self._definitions.values()
                            if item.name == edge.sort and item.kind == "object" and item.spec.form == "refine"), None)
        if refined is None:
            return False
        return not (refined.canon is None and refined.valid == nodes.Lit(True)
                    and any(op.output.sort == edge.sort for op in self._world.operations))

    def _edge_atom(self, name: str, position: str, edge: Edge) -> kernel.Atom:
        objects = {obj.name: obj for obj in self._world.objects}
        objects.update({item.name: item.spec for item in self._definitions.values()
                        if item.kind == "object" and item.origin == "invented"})
        refined = objects.get(edge.sort)
        refined = refined if refined is not None and refined.form == "refine" else None
        # Given sorts in host representation (a host valid rule or a declared host codec) keep host values.
        given_objects = {obj.name for obj in self._world.objects
                         if is_host_rule(obj.valid) or is_host_rule(obj.canon) or "host" in obj.extra}
        host_refined = refined is not None and refined.name in {obj.name for obj in self._world.objects} and is_host_rule(refined.valid)
        if host_refined:
            from opulse.atoms.objects import _host_callable

            host_valid = _host_callable(refined.valid)
            host_canon = _host_callable(refined.canon) if is_host_rule(refined.canon) else None
        rule = edge.enter
        dialect = self.dialect
        semantics = self._world.params.get("semantics", {})
        bound = semantics.get("bound")

        def enter(context, value):
            if host_refined and rule in ("bottom", "normalize"):
                if rule == "normalize" and host_canon is not None:
                    if refined.canon_cost != "free":
                        exhausted = context.engine.charge(1)
                        if exhausted is not None:
                            return exhausted
                    value = host_canon(value)
                    if isinstance(value, (Bottom, Unknown)):
                        return value
                valid = host_valid(value)
                if isinstance(valid, (Bottom, Unknown)):
                    return Bottom("invalid") if isinstance(valid, Bottom) else valid
                try:
                    return value if truth(valid) else Bottom("invalid")
                except (TypeError, ValueError):
                    return Bottom("invalid")
            if refined is not None:
                if isinstance(value, Card) and value.sort == edge.sort:
                    stored = context.call(f"{edge.sort}._stored", (value,))
                    if not isinstance(stored, Ok):
                        return Bottom("invalid") if isinstance(stored, Bottom) else stored
                    value = stored.value
                    if rule == "bottom":
                        valid = _apply_rule(context, f"{edge.sort}._edge_valid", refined.valid, value)
                        if not isinstance(valid, Ok):
                            return Bottom("invalid") if isinstance(valid, Bottom) else valid
                        try:
                            if not truth(valid.value):
                                return Bottom("invalid")
                        except (ValueError, TypeError):
                            return Bottom("invalid")
                        return context.call(f"{edge.sort}._pack", (value,))
                if rule == "normalize" and refined.canon is not None:
                    if refined.canon_cost == "free":
                        canonical = context.call(f"{edge.sort}._canon_free", (value,))
                    else:
                        canonical = _apply_rule(context, f"{edge.sort}._edge_canon", refined.canon, value)
                    if not isinstance(canonical, Ok):
                        return canonical
                    value = canonical.value
                    valid = _apply_rule(context, f"{edge.sort}._edge_valid", refined.valid, value)
                    if not isinstance(valid, Ok):
                        return valid
                    try:
                        if not truth(valid.value):
                            return Bottom("invalid")
                    except (ValueError, TypeError):
                        return Bottom("invalid")
                    return context.call(f"{edge.sort}._pack", (value,))
            match = re.fullmatch(r"saturate\((-?\d+),\s*(-?\d+)\)", rule)
            if match:
                if type(value) is not int:
                    return Bottom("invalid")
                value = max(int(match[1]), min(int(match[2]), value))
            if rule.startswith("fold("):
                if dialect != "legacy-v1" or bound is None or type(value) is not int:
                    return Bottom("invalid")
                value = Semantics("legacy", bound).check(value)
            if rule == "normalize" and refined is None and semantics.get("mode") == "modular":
                value = Semantics("modular", bound, modulus=semantics.get("modulus")).enter(value)
            if refined is not None and edge.sort in given_objects and not isinstance(value, Card):
                # Checked, not packed (see given_objects).
                valid = _apply_rule(context, f"{edge.sort}._edge_valid", refined.valid, value)
                if not isinstance(valid, Ok):
                    return Bottom("invalid") if isinstance(valid, Bottom) else valid
                try:
                    return value if truth(valid.value) else Bottom("invalid")
                except (ValueError, TypeError):
                    return Bottom("invalid")
            if refined is not None:
                if rule == "bottom":
                    valid = context.call(kernel.Defn(f"{edge.sort}._edge_valid", ("x",),
                                                     refined.valid, "object"), (value,))
                    if not isinstance(valid, Ok):
                        return Bottom("invalid") if isinstance(valid, Bottom) else valid
                    try:
                        if not truth(valid.value):
                            return Bottom("invalid")
                    except (ValueError, TypeError):
                        return Bottom("invalid")
                    return context.call(f"{edge.sort}._pack", (value,))
                return context.call(f"{edge.sort}.make", (value,))
            return value

        return kernel.Atom(self._edge_name(name, position), 1, enter if refined else
                           lambda value: enter(None, value), cost=0 if refined else 1,
                           kind="object", metered=refined is not None)

    def local_scope(self) -> kernel.DictScope:
        """Trusted scope containing only this world's operations and definitions."""
        self._sync_world()
        cached = self._cached("scope", self._build_scope)
        return kernel.DictScope(dict(cached.atoms), dict(cached.defns))

    def _runtime_local_scope(self) -> kernel.DictScope:
        """Copy local definitions with attached bridge maps bound to their two sides."""
        local = self.local_scope()
        from opulse.atoms.bridges import runtime_bridge_defn

        for defn in self._definitions.values():
            if defn.kind == "bridge" and defn.origin == "invented" and defn.name in local.defns:
                local.defns[defn.name] = replace(runtime_bridge_defn(defn.spec, self._bridge_context(defn)),
                                                 layer=defn.layer)
        return local

    def scope(self) -> kernel.DictScope:
        """Trusted scope with lexical world names for bridge calls; use run for outside calls."""
        if not self._attached_worlds or not any(
                defn.kind == "bridge" and defn.origin == "invented"
                for defn in self._definitions.values()):
            return self.local_scope()
        local = self._runtime_local_scope()
        world_id = f"{self._world.world}@{self._world.version}"
        return kernel.ChainScope(local, world_id,
                                 {name: other._runtime_local_scope()
                                  for name, other in self._attached_worlds.items()})

    def sealed_names(self) -> set[str]:
        from opulse.atoms.objects import sealed_private_names

        self._sync_world()
        return self._cached("sealed", lambda: frozenset(sealed_private_names(self)))

    def _build_scope(self) -> kernel.DictScope:
        callable_ = ("callable", "verified", "promoted")
        objects = [spec for spec in self._world.objects if spec.form != "given"]
        objects += [defn.spec for defn in self._definitions.values()
                    if defn.kind == "object" and defn.origin == "invented" and defn.status in callable_]
        atoms, defns = list(self.atoms), []
        if objects:
            from opulse.atoms.objects import object_atoms

            for spec in objects:
                for item in object_atoms(spec, self):
                    (atoms if isinstance(item, kernel.Atom) else defns).append(item)
        defns += [kernel.Defn(defn.name, defn.spec.params, defn.body, "combinator", 0)
                  for defn in self._definitions.values()
                  if defn.kind == "combinator" and defn.origin == "given"]
        defns += [kernel.Defn(defn.name, self._params(defn), self._entered_body(defn), defn.kind, defn.layer)
                  for defn in self._definitions.values()
                  if defn.origin == "invented" and defn.kind != "object" and defn.status in callable_
                  and isinstance(defn.body, nodes.NODE_TYPES)]
        for defn in self._definitions.values():
            if not isinstance(defn.spec, OperationSpec):
                continue
            if defn.origin == "given":
                special_inputs = tuple(edge.enter != "bottom" for edge in defn.spec.inputs)
                special_output = defn.spec.output.enter != "bottom"
                if not (any(special_inputs) or special_output):
                    continue
                host = next((atom for atom in self.atoms if atom.name == defn.name), None)
                if host is None:
                    continue
                internal = f"__opulse_host_{host.name}"
                atoms = [replace(atom, name=internal) if atom is host else atom for atom in atoms]
                spec = replace(defn.spec, inputs=tuple(edge if special else Edge("unknown")
                                                       for edge, special in zip(defn.spec.inputs, special_inputs)),
                               output=defn.spec.output if special_output else Edge("unknown"))
                params = self._params(defn)
                body = nodes.Call(internal, tuple(nodes.Var(param) for param in params))
                defns.append(kernel.Defn(defn.name, params,
                                         self._entered_body(replace(defn, spec=spec, body=body)),
                                         defn.kind, 0))
            elif defn.status not in callable_:
                continue
            for position, edge in self._operation_edges(defn.spec):
                if self._edge_needed(edge) and (defn.origin == "invented" or edge.enter != "bottom"):
                    atoms.append(self._edge_atom(defn.name, position, edge))
        return kernel.DictScope(atoms, defns)

    def run(self, name: str, args: Sequence[object], fuel: int | None = None,
            trace: bool = False) -> kernel.Run:
        self._sync_world()
        previous_sync = getattr(self, "_sync_suspended", False)
        self._sync_suspended = True
        from opulse.atoms.objects import sealed_private_names

        try:
            scope = self.scope()
            forbidden = self._cached("sealed", lambda: frozenset(sealed_private_names(self)))

            def private_reference(value):
                pending = [value]
                while pending:
                    current = pending.pop()
                    if isinstance(current, kernel.FnRef):
                        if current.name in forbidden:
                            return True
                    elif isinstance(current, Card):
                        pending.extend(current.fields)
                    elif isinstance(current, (tuple, list, set, frozenset)):
                        pending.extend(current)
                    elif isinstance(current, dict):
                        for key, item in current.items():
                            pending.extend((key, item))
                return False

            if name in forbidden or any(private_reference(arg) for arg in args):
                raise PipelineError(f"sealed object private name: {name}")
            return kernel.call(name, args, scope, kernel.Limits(fuel=fuel), trace, self.dialect)
        finally:
            self._sync_suspended = previous_sync

    def make_callable(self, name: str, sample: Sequence[tuple]) -> Definition:
        defn = self.get(name)
        if defn.status != "checked":
            raise PipelineError("make_callable requires checked status")
        if not sample:
            raise PipelineError("make_callable needs at least one input")
        if defn.kind == "law":
            from opulse.atoms.laws import make_law_callable

            try:
                return make_law_callable(defn, self, sample)
            except ValueError as error:
                raise PipelineError(str(error)) from error
        if defn.kind == "template":  # a template is callable once a trial instantiation checks
            return self._advance(name, "callable")
        if defn.kind == "object":  # build the object's operations; a refined sort makes each sample
            from opulse.atoms.objects import object_atoms

            try:
                operations = object_atoms(defn.spec, self)
            except ValueError as error:
                raise PipelineError(str(error)) from error
            maker = f"{defn.spec.name}.make"
            scope = self.scope().extend([item for item in operations if isinstance(item, kernel.Defn)])
            scope.atoms.update({item.name: item for item in operations if isinstance(item, kernel.Atom)})
            steps = []
            for args in sample if scope.resolve(maker) else ():
                run = kernel.call(maker, args, scope, kernel.Limits(fuel=100_000), dialect=self.dialect)
                if isinstance(run.outcome, Unknown):
                    raise PipelineError(f"sample {args!r}: {run.outcome!r}")
                steps.append(run.steps)
            self._steps[name] = steps
            return self._advance(name, "callable")
        if defn.kind == "observation":
            from opulse.atoms.observations import _run, check_observation

            try:
                problems = check_observation(defn, self)
                if problems:
                    raise ValueError("; ".join(problems))
                if "inputs" in defn.spec.extra and any(len(args) != len(defn.spec.extra["inputs"])
                                                       for args in sample):
                    raise ValueError("observation sample has wrong input arity")
                if "inputs" not in defn.spec.extra and any(len(args) != 1 for args in sample):
                    raise ValueError("observation sample requires one truth state")
                outcomes, steps = _run(defn, self, sample if "inputs" in defn.spec.extra
                                        else [args[0] for args in sample])
            except ValueError as error:
                raise PipelineError(str(error)) from error
            unknown = [outcome for outcome in outcomes if isinstance(outcome, Unknown)]
            if unknown:
                raise PipelineError(f"sample gave {unknown[0]!r}")
            self._steps[name] = steps
            return self._advance(name, "callable")
        context = self._bridge_context(defn) if defn.kind == "bridge" else None
        body = (self._runtime_checked_definition(defn, context).body if context is not None
                else self._entered_body(defn))
        scope = self.scope().extend([kernel.Defn(name, self._params(defn), body,
                                                 defn.kind, defn.layer)])
        if isinstance(defn.spec, OperationSpec):
            for position, edge in self._operation_edges(defn.spec):
                if self._edge_needed(edge):
                    atom = self._edge_atom(name, position, edge)
                    scope.atoms[atom.name] = atom
        steps = []
        for args in sample:
            try:
                run = kernel.call(name, args, scope, kernel.Limits(fuel=100_000), dialect=self.dialect)
            except (ValueError, TypeError, KeyError, RecursionError) as error:
                raise PipelineError(f"sample {args!r}: {error}") from error
            if isinstance(run.outcome, Unknown):
                raise PipelineError(f"sample {args!r}: {run.outcome!r}")
            steps.append(run.steps)
        self._steps[name] = steps
        return self._advance(name, "callable")

    def _deps_hash(self, name: str) -> str:
        seen = set()

        def collect(current):
            for dependency in self._dependency_names(self.get(current)):
                if dependency == name or dependency in seen:
                    continue
                seen.add(dependency)
                if dependency in self._definitions:
                    collect(dependency)
                elif dependency.split(".", 1)[0] in self._definitions:
                    owner = dependency.split(".", 1)[0]
                    seen.add(owner)
                    collect(owner)

        collect(name)
        return content_hash({dependency: self.get(dependency).to_dict() for dependency in sorted(seen)
                             if dependency in self._definitions})

    def deps_hash(self, name: str) -> str:
        """Digest of transitive dependencies, including generated object operations."""
        return self._deps_hash(name)

    def verify(self, name: str, request: VerifyRequest) -> Definition:
        defn = self.get(name)
        if defn.status != "callable":
            raise PipelineError("verify requires callable status")
        if request.method not in ("exhaustive", "bounded", "sampled") or request.method == "sampled" and request.seed is None:
            raise PipelineError("invalid verification method or missing sampled seed")
        if not request.domain or request.scope.get("size") != len(request.domain) or "domain" not in request.scope:
            raise PipelineError("verification scope must describe the exact domain")
        _ensure_kind(defn.kind)
        verifier = _VERIFIERS.get(defn.kind)
        if verifier is None:
            raise PipelineError(f"no verifier registered for {defn.kind}")
        context = self._bridge_context(defn) if defn.kind == "bridge" else None
        if context is not None and "bridge_context" in request.extra and request.extra["bridge_context"] != context:
            raise PipelineError("bridge verification context differs from the attached world")
        domain = deepcopy(request.domain)
        checked = checked_scope(domain)
        private_request = replace(request, domain=domain, scope=dict(request.scope),
                                  extra={key: value for key, value in request.extra.items()
                                         if key != "bridge_context"} if context is not None else request.extra)
        result = verifier(defn, context if context is not None else self, private_request)
        if not result.ok:
            raise PipelineError(result.problems)
        if defn.kind == "combinator":
            fixed_ops = sorted(nodes.operation_literals(defn.body))
            if fixed_ops:
                private_request.scope["fixed_ops"] = fixed_ops
        private_request.scope["checked"] = {**checked, "by": "library"}
        attached = self._attached_hashes(defn)
        if attached:
            private_request.scope["attached"] = attached
        else:
            private_request.scope.pop("attached", None)
        evidence = Evidence(request.method, private_request.scope, request.seed, result.checks,
                            self.world.world_hash(), self._deps_hash(name), self.content_hash(name),
                            atoms_digest(self.atoms))
        self._steps[name] = result.steps
        self._library_checked.add(name)
        self._definitions[name] = replace(defn, evidence=evidence)
        return self._advance(name, "verified")

    def record_evidence(self, name: str, evidence: Evidence) -> Definition:
        """Record world-local verifier evidence with a checked-input scope."""
        defn = self.get(name)
        if defn.status != "callable" or not isinstance(evidence, Evidence):
            raise PipelineError("record_evidence requires callable status and evidence")
        evidence = deepcopy(evidence)
        if not evidence.checked_recorded():
            raise PipelineError("record_evidence requires a valid checked scope")
        self._library_checked.discard(name)
        self._definitions[name] = replace(defn, evidence=evidence)
        return self._advance(name, "verified")

    def record_solution(self, node: nodes.Node) -> None:
        self._solutions.append(node)

    def account(self, name: str) -> Definition:
        defn = self.get(name)
        if defn.status not in ("callable", "verified", "promoted"):
            raise PipelineError("account requires callable status")
        steps = self._steps.get(name, [])
        usage = sum(sum(1 for item in nodes.walk(body) if isinstance(item, nodes.Call) and item.fn == name)
                    for body in self._solutions + [other.body for other in self._definitions.values()
                                                   if other.name != name and isinstance(other.body, nodes.NODE_TYPES)])
        cost = Cost(nodes.length(defn.body), {"min": min(steps) if steps else 0,
                                            "max": max(steps) if steps else 0,
                                            "mean": sum(steps) / len(steps) if steps else 0,
                                            "over": defn.evidence.scope if defn.evidence else "samples"}, usage)
        self._definitions[name] = replace(defn, cost=cost)
        return self.get(name)

    def promote(self, name: str, contract: Contract) -> Definition:
        defn = self.get(name)
        if defn.status != "verified":
            raise PipelineError("promote requires verified status")
        evidence = defn.evidence
        if evidence.method == "sampled":
            raise PipelineError("sampled evidence cannot be promoted")
        problems = []
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
        required = REQUIRED_CHECKS.get(defn.kind, frozenset({"unfold_equivalence"}))
        if defn.kind == "observation" and "inputs" in defn.spec.extra:
            required = frozenset({"dependency", "facts_unchanged"})
        if defn.kind == "object" and getattr(defn.spec, "canon", None) is not None:
            required = required | {"canon_total", "canon_idempotent", "canon_keeps_valid"}
        if defn.kind == "object" and defn.spec.form == "compose" and evidence.scope.get("untested_tags"):
            problems.append(f"untested tags: {evidence.scope['untested_tags']}")
        missing = set(required - set(evidence.checks))
        if defn.kind == "observation" and not (
            "reference" in evidence.checks or
            "unfold_equivalence" in evidence.checks and evidence.scope.get("reference") == "none"
        ):
            missing.add("reference or unfold_equivalence (reference: none)")
        if missing or not evidence.checks:
            problems.append(f"obligations not checked: {sorted(missing) or 'none recorded'}")
        if not isinstance(contract, Contract):
            problems.append("promotion needs a contract")
        if problems:
            raise PipelineError(problems)
        self._definitions[name] = replace(defn, contract=contract)
        return self._advance(name, "promoted")

    def replace(self, name: str, defn: Definition, force_new_version: bool = False) -> Definition:
        if name not in self._definitions or name != defn.name or self.get(name).origin == "given":
            raise PipelineError("replace requires an existing invented name")
        if not _kind_open(defn, self.world):
            raise PipelineError(f"kind {defn.kind} is closed in world {self.world.world}")
        if defn.status != "written":
            raise PipelineError("replacement must be written")
        if defn.evidence is not None or defn.contract is not None:
            raise PipelineError("replacement cannot inherit evidence or contracts")
        if self.get(name).status == "promoted":
            if not force_new_version:
                raise PipelineError("promoted definitions are immutable")
            version = 2
            while f"{name}.v{version}" in self._definitions:
                version += 1
            new_name = f"{name}.v{version}"
            return self.write(replace(defn, name=new_name, spec=replace(defn.spec, name=new_name),
                                      id=None, evidence=None, contract=None, cost=Cost()))
        pending = {name}
        while pending:
            more = {other.name for other in self._definitions.values()
                    if other.origin == "invented" and other.name not in pending
                    and any(dependency in pending for dependency in other.depends_on)}
            if not more:
                break
            pending.update(more)
        for dependent in pending - {name}:
            old = self.get(dependent)
            self._definitions[dependent] = replace(old, status=reset(old.status), evidence=None, contract=None)
            self._steps.pop(dependent, None)
        self._steps.pop(name, None)
        self._definitions[name] = defn
        return defn

    def derived_world(self) -> DerivedWorld:
        self._sync_world()
        promoted = tuple(defn for defn in self._definitions.values() if defn.origin == "invented"
                         and defn.status == "promoted" and defn.evidence.world_hash == self.world.world_hash()
                         and defn.evidence.deps_hash == self._deps_hash(defn.name)
                         and defn.evidence.content_hash == self.content_hash(defn.name)
                         and defn.evidence.atoms_hash == atoms_digest(self.atoms)
                         and self._checked_match(defn)
                         and self._attached_match(defn))
        return DerivedWorld.build(self.world, promoted)

    def to_dict(self) -> dict:
        self._sync_world()
        return {"schema": "opulse.library/1", "definitions": [defn.to_dict() for defn in self._definitions.values()
                                                           if defn.origin == "invented"],
                "steps": self._steps, "solutions": [nodes.to_json(node) for node in self._solutions]}

    @classmethod
    def from_dict(cls, data: dict, world: WorldDecl, atoms: Sequence[kernel.Atom],
                  attached_worlds: Mapping[str, Library] | None = None) -> Library:
        """Reload records; supply attached worlds to restore cross-world bridge resolution."""
        if data.get("schema") != "opulse.library/1":
            raise ValueError("invalid library schema")
        lib = cls(world, atoms, world.dialect)
        for world_id, other in (attached_worlds or {}).items():
            lib.attach_world(world_id, other)
        for entry in data["definitions"]:
            defn = Definition.from_dict(entry)
            if (defn.evidence is not None and
                    isinstance(defn.evidence.scope.get("checked"), dict) and
                    defn.evidence.scope["checked"].get("by") == "library"):
                lib._library_checked.add(defn.name)
            if defn.name in lib._definitions or validation_problems(defn):
                raise PipelineError(f"invalid stored definition: {defn.name}")
            if defn.origin == "invented" and not _kind_open(defn, world):
                raise PipelineError(f"kind {defn.kind} is closed in world {world.world}")
            lib._definitions[defn.name] = defn
        scope = lib.scope()
        for name, defn in list(lib._definitions.items()):
            if defn.origin == "given":
                continue
            context = lib._bridge_context(defn) if defn.kind == "bridge" else None
            target_scope = context.target_lib.scope() if context is not None else None
            problems = check_definition(
                lib._runtime_checked_definition(defn, context), world,
                lambda other, bridge_context=context, remote_scope=target_scope:
                lib._definitions.get(other) or scope.resolve(other) or
                (bridge_context.target_lib.records().get(other) or remote_scope.resolve(other)
                 if bridge_context is not None else None),
            )
            from opulse.atoms.objects import sealed_private_names

            problems.extend(f"sealed object private name: {dependency}"
                            for dependency in sorted(lib._dependency_names(defn) & sealed_private_names(lib)))
            if problems:
                raise PipelineError([f"invalid stored definition: {name}", *problems])
        lib._steps = {name: list(steps) for name, steps in data.get("steps", {}).items()}
        lib._solutions = [nodes.from_json(node) for node in data.get("solutions", ())]
        changed = True
        while changed:
            changed = False
            for name, defn in list(lib._definitions.items()):
                if defn.origin == "given" or defn.status not in ("verified", "promoted"):
                    continue
                evidence = defn.evidence
                if (evidence is None or evidence.world_hash != world.world_hash() or
                        evidence.deps_hash != lib._deps_hash(name) or
                        evidence.content_hash != lib.content_hash(name) or
                        evidence.atoms_hash != atoms_digest(lib.atoms) or
                        not lib._checked_match(defn) or
                        not lib._attached_match(defn)):
                    lib._definitions[name] = replace(defn, status="callable", evidence=None, contract=None)
                    lib._steps.pop(name, None)
                    changed = True
        return lib
