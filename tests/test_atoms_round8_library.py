"""Library compatibility regressions (atoms-v2 spec sections 4, 9 and 11)."""

import os
import subprocess
import sys
import time
from dataclasses import replace

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from opulse.atoms import kernel, nodes
from opulse.atoms.bridges import bridge_defn
from opulse.atoms.library import (
    Library,
    PipelineError,
    VerifyRequest,
    atoms_digest,
    checked_scope,
)
from opulse.atoms.spec import BridgeSpec, Contract, Definition, ObjectSpec
from opulse.atoms.world import WorldDecl


def library():
    world = WorldDecl("local", 1, "atoms-v2", {}, {}, (ObjectSpec("int", "given"),), (),
                      {"nodes": list(nodes.NODE_NAMES), "recursion": "fuel"}, {}, {},
                      open_kinds=("bridge", "object"))
    return Library(world, ())


def request(value):
    return VerifyRequest("bounded", ((value,),), {"domain": "one integer", "size": 1})


@settings(deadline=None)
@given(st.integers(min_value=-100, max_value=100))
def test_unqualified_bridge_is_local_and_does_not_attach(value):
    lib = library()
    spec = BridgeSpec("identity", "int", "int", nodes.Var("x"))
    lib.write(Definition("identity", "bridge", "invented", 1, (), spec, bridge_defn(spec).body))
    lib.check("identity")
    lib.make_callable("identity", ((value,),))
    verified = lib.verify("identity", request(value))
    assert verified.evidence.scope["checked"]["by"] == "library"
    assert "attached" not in verified.evidence.scope
    assert lib.promote("identity", Contract("identity on one integer")).status == "promoted"


@settings(deadline=None)
@given(st.integers(min_value=-100, max_value=100), st.booleans())
def test_removing_library_checked_scope_invalidates_live_evidence(value, placeholder):
    lib = library()
    spec = ObjectSpec("Box", "compose", tags={"box": (("value", "int"),)})
    lib.write(Definition("Box", "object", "invented", 1, (), spec, None))
    lib.check("Box")
    lib.make_callable("Box", ((value,),))
    lib.verify("Box", request(value))
    if placeholder:
        lib._definitions["Box"].evidence.scope["checked"] = "unrecorded"
    else:
        lib._definitions["Box"].evidence.scope.pop("checked")
    assert lib.get("Box").status == "callable"
    assert lib.get("Box").evidence is None


def test_world_local_evidence_without_checked_scope_is_refused():
    lib = library()
    spec = ObjectSpec("Box", "compose", tags={"box": (("value", "int"),)})
    lib.write(Definition("Box", "object", "invented", 1, (), spec, None))
    lib.check("Box")
    lib.make_callable("Box", ((1,),))
    verified = lib.verify("Box", request(1))
    evidence = replace(verified.evidence, scope={"domain": "one integer", "size": 1})
    lib._definitions["Box"] = replace(lib.get("Box"), status="callable", evidence=None)
    with pytest.raises(PipelineError, match="checked scope"):
        lib.record_evidence("Box", evidence)
    assert lib.get("Box").status == "callable"
    scope = {"domain": "one integer", "size": 1, "checked": checked_scope(((1,),))}
    recorded = lib.record_evidence("Box", replace(evidence, scope=scope))
    assert recorded.evidence.scope["checked"]["size"] == 1
    assert lib.promote("Box", Contract("world-local verifier")).status == "promoted"


def test_digest_tracks_methods_on_referenced_classes():
    class State:
        def run(self):
            return 1

    def operation():
        return State().run()

    atom = kernel.Atom("op", 0, operation)
    before = atoms_digest((atom,))
    original = State.run
    try:
        State.run = lambda self: 2
        assert atoms_digest((atom,)) != before
    finally:
        State.run = original


def test_digest_replaces_unstable_object_repr_across_processes():
    script = ("from opulse.atoms.kernel import Atom; "
              "from opulse.atoms.library import atoms_digest; "
              "print(atoms_digest((Atom('x', 0, lambda value=object(): value),)))")
    environment = {**os.environ, "PYTHONPATH": "src"}
    first = subprocess.check_output([sys.executable, "-c", script], env=environment)
    second = subprocess.check_output([sys.executable, "-c", script], env=environment)
    assert first == second


def test_class_heavy_digest_stays_fast():
    atoms = []
    for index in range(100):
        state = type(f"State{index}", (), {"run": lambda self: 1})
        atoms.append(kernel.Atom(f"op{index}", 0, lambda state=state: state().run()))
    start = time.perf_counter()
    assert len(atoms_digest(atoms)) == 64
    assert time.perf_counter() - start < 0.5
