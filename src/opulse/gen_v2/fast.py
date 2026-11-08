"""Kernel evaluation without the per-call thread hop, for generator runs.

``opulse.atoms.kernel.evaluate`` runs every evaluation on a shared big-stack worker thread
(``run_with_deep_stack``). A generator run evaluates hundreds of thousands of small calls, and
the thread hop costs more than the evaluation. ``deep(fn)`` runs a whole generator run on one
thread with a big stack and a high recursion limit; inside it, ``evaluate`` and ``call`` use the
same kernel engine directly (same outcome, steps and jumps; no trace). Outside such a thread
they fall back to ``kernel.evaluate``. Passing ``cacheable`` opts pure definitions only into
a cache local to that thread and scope; the default does not cache. Host atoms are
never inferred pure from promotion alone.
"""

from __future__ import annotations

import sys
import threading
import weakref
from collections.abc import Mapping, Sequence

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.values import Card, Ok, Unknown
from opulse.gen_v2.codec import value_key as _value_key

_THREAD_NAME = "opulse-gen-v2-deep"
_local = threading.local()


def promoted_names(library) -> frozenset[str]:
    """Promoted definitions whose complete static call graph has no host atoms."""
    scope = library.scope()
    names_by_scope = getattr(_local, "promoted", None)
    if names_by_scope is None:
        names_by_scope = _local.promoted = weakref.WeakKeyDictionary()
    if scope not in names_by_scope:
        names_by_scope[scope] = frozenset(name for name, definition in library._definitions.items()
                                          if definition.origin == "invented" and definition.status == "promoted"
                                          and _pure_definition(name, scope, set()))
    return names_by_scope[scope]


def _immutable(value) -> bool:
    if type(value) in (bool, int, float, str, bytes, type(None)):
        return True
    if type(value) is tuple:
        return all(_immutable(item) for item in value)
    return isinstance(value, Card) and all(_immutable(item) for item in value.fields)


def _pure_definition(name: str, scope: kernel.Scope, visiting: set[str]) -> bool:
    target = scope.resolve(name)
    if not isinstance(target, kernel.Defn) or name in visiting:
        return False
    visiting.add(name)
    try:
        if any(isinstance(node, n.Lit) and not _immutable(node.value)
               for node in n.walk(target.body)):
            return False
        return all(_pure_definition(reference, scope, visiting)
                   for reference in n.references(target.body))
    finally:
        visiting.remove(name)


class _CachedEngine(kernel._Engine):
    def __init__(self, scope, limits, dialect, cacheable, cache):
        super().__init__(scope, limits, False, dialect)
        self.cacheable = cacheable
        self.cache = cache

    def invoke(self, name, args, env, local, layer, initial=False):
        if name in local:
            return super().invoke(name, args, env, local, layer, initial)
        target = self.scope.resolve(name)
        if target is None:
            return super().invoke(name, args, env, local, layer, initial)
        if not isinstance(target, kernel.Defn) or target.name not in self.cacheable:
            return super().invoke(name, args, env, local, layer, initial)
        if len(args) != len(target.params):
            return super().invoke(name, args, env, local, layer, initial)

        outcomes = []
        for arg in args:
            outcome = self.eval(arg, env, local, layer)
            outcomes.append(outcome)
            if isinstance(outcome, Unknown) and (self.dialect == "legacy-v1" or
                                                 outcome.resource in ("fuel", "depth", "nodes")):
                return outcome
            if not isinstance(outcome, Ok) and self.dialect != "legacy-v1":
                return outcome
        literals = tuple(n.Lit(item.value if isinstance(item, Ok) else item) for item in outcomes)
        if not all(isinstance(item, Ok) for item in outcomes):
            return super().invoke(name, literals, env, local, layer, initial)
        if not all(_immutable(item.value) for item in outcomes):
            return super().invoke(name, literals, env, local, layer, initial)
        try:
            key = (target.name, tuple(_value_key(item.value) for item in outcomes),
                   self.depth, self.limits.max_depth)
            hash(key)
        except TypeError:
            return super().invoke(name, literals, env, local, layer, initial)

        recorded = self.cache.get(key)
        if recorded is not None:
            outcome, steps, jumps, _work = recorded
            if self.limits.fuel is None or self.steps + steps <= self.limits.fuel:
                self.steps += steps
                self.jumps += jumps
                return outcome
        start_steps, start_jumps, start_work = self.steps, self.jumps, getattr(self, "work", 0)
        outcome = super().invoke(name, literals, env, local, layer, initial)
        if not isinstance(outcome, Unknown) and (not isinstance(outcome, Ok) or _immutable(outcome.value)):
            try:
                if isinstance(outcome, Ok):
                    hash(_value_key(outcome.value))
            except TypeError:
                pass
            else:
                self.cache[key] = (outcome, self.steps - start_steps, self.jumps - start_jumps,
                                   getattr(self, "work", 0) - start_work)
        return outcome


def in_deep_thread() -> bool:
    return threading.current_thread().name == _THREAD_NAME


def deep(fn, *args, **kwargs):
    """Run ``fn`` on a fresh thread with a 512 MiB stack; return its result or raise its error."""
    if in_deep_thread():
        return fn(*args, **kwargs)
    result: dict = {}

    def target():
        previous = sys.getrecursionlimit()
        sys.setrecursionlimit(max(previous, 200_000))
        try:
            result["value"] = fn(*args, **kwargs)
        except Exception as error:  # noqa: BLE001 - carry worker failures across the thread boundary
            result["error"] = error
        finally:
            sys.setrecursionlimit(previous)

    old = threading.stack_size()
    threading.stack_size(512 * 1024 * 1024)
    try:
        thread = threading.Thread(target=target, name=_THREAD_NAME)
        thread.start()
    finally:
        threading.stack_size(old)
    thread.join()
    if "error" in result:
        raise result["error"]
    return result.get("value")


def evaluate(node: n.Node, env: Mapping[str, object], scope: kernel.Scope, fuel: int | None,
             dialect: str = "atoms-v2", cacheable: frozenset[str] = frozenset()) -> kernel.Run:
    if dialect not in ("atoms-v2", "legacy-v1"):
        raise ValueError(f"unknown dialect: {dialect!r}")
    limits = kernel.Limits(fuel=fuel)
    if not in_deep_thread():
        return kernel.evaluate(node, env, scope, limits, dialect=dialect)
    if cacheable:
        cacheable = frozenset(name for name in cacheable if _pure_definition(name, scope, set()))
    if cacheable:
        scopes = getattr(_local, "scopes", None)
        if scopes is None:
            scopes = _local.scopes = weakref.WeakKeyDictionary()
        try:
            by_dialect = scopes.setdefault(scope, {})
        except TypeError:
            engine = kernel._Engine(scope, limits, False, dialect)
        else:
            cache = by_dialect.setdefault(dialect, {})
            engine = _CachedEngine(scope, limits, dialect, cacheable, cache)
    else:
        engine = kernel._Engine(scope, limits, False, dialect)
    outcome = engine.eval(node, env, {}, 1)
    return kernel.Run(outcome, engine.steps, engine.jumps, None, getattr(engine, "work", 0))


def call(name: str, args: Sequence[object], scope: kernel.Scope, fuel: int | None,
         dialect: str = "atoms-v2", cacheable: frozenset[str] = frozenset()) -> kernel.Run:
    return evaluate(n.Call(name, tuple(n.Lit(arg) for arg in args)), {}, scope, fuel, dialect, cacheable)
