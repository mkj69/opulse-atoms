"""Transitive atom evidence regressions (atoms-v2 spec section 9)."""

import os
import subprocess
import sys

from opulse.atoms import kernel, nodes
from opulse.atoms.library import Library, VerifyRequest, atoms_digest
from opulse.atoms.spec import Contract, Definition, Edge, ObjectSpec, OperationSpec
from opulse.atoms.world import WorldDecl


def _fifth(value):
    return value + 1


def _fourth(value):
    return _fifth(value)


def _third(value):
    return _fourth(value)


def _second(value):
    return _third(value)


def _first(value):
    return _second(value)


def _library():
    operation = OperationSpec("first", "transform", (Edge("int"),), Edge("int"), "first")
    world = WorldDecl("deep-digest", 1, "atoms-v2", {}, {}, (ObjectSpec("int", "given"),),
                      (operation,), {"nodes": list(nodes.NODE_NAMES), "recursion": "fuel"}, {}, {})
    return Library(world, (kernel.Atom("first", 1, _first),))


def test_digest_changes_when_fifth_helper_changes(monkeypatch):
    atom = kernel.Atom("first", 1, _first)
    before = atoms_digest((atom,))
    assert _first(1) == 2
    monkeypatch.setitem(globals(), "_fifth", lambda value: value + 10)
    assert _first(1) == 11
    assert atoms_digest((atom,)) != before


def test_digest_follows_deep_cost_helper(monkeypatch):
    atom = kernel.Atom("costed", 1, lambda value: value, cost=_first)
    before = atoms_digest((atom,))
    monkeypatch.setitem(globals(), "_fifth", lambda value: value + 10)
    assert atoms_digest((atom,)) != before


def test_promoted_definition_drops_to_callable_after_deep_change(monkeypatch):
    lib = _library()
    body = nodes.Call("first", (nodes.Var("arg0"),))
    lib.write(Definition("derived", "operation", "invented", 1, ("first",),
                         OperationSpec("derived", "transform", (Edge("int"),), Edge("int"), "derived"), body))
    lib.check("derived")
    lib.make_callable("derived", ((1,),))
    lib.verify("derived", VerifyRequest("bounded", ((1,),), {"domain": "bound <= 1", "size": 1},
                                        reference=lambda value: value + 1))
    assert lib.promote("derived", Contract("increments one integer")).status == "promoted"
    monkeypatch.setitem(globals(), "_fifth", lambda value: value + 10)
    assert lib.get("derived").status == "callable"
    assert lib.get("derived").evidence is None


def test_mutually_recursive_and_recursive_helpers_terminate():
    def even(value):
        return value == 0 or odd(value - 1)

    def odd(value):
        return value != 0 and even(value - 1)

    atom = kernel.Atom("even", 1, even)
    assert atoms_digest((atom,)) == atoms_digest((atom,))

    def recursive(value):
        return value == 0 or recursive(value - 1)

    atom = kernel.Atom("recursive", 1, recursive)
    assert atoms_digest((atom,)) == atoms_digest((atom,))


def test_transitive_digest_is_stable_across_processes():
    script = ("from opulse.atoms.kernel import Atom; from opulse.atoms.library import atoms_digest; "
              "exec('def first(value): return second(value)\\n"
              "def second(value): return first(value) if value else 0'); "
              "print(atoms_digest((Atom('first', 1, first),)))")
    environment = {**os.environ, "PYTHONPATH": "src"}
    first = subprocess.check_output([sys.executable, "-c", script], env=environment)
    second = subprocess.check_output([sys.executable, "-c", script], env=environment)
    assert first == second
