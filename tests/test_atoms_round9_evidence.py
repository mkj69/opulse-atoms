"""Evidence and discard regressions (atoms-v2 spec sections 8 and 9)."""

import os
import subprocess
import sys
from copy import deepcopy

import pytest
from test_atoms_library import definition, fixture, ready

from opulse.atoms import nodes
from opulse.atoms.library import Library, PipelineError, VerifyRequest, checked_scope
from opulse.atoms.spec import Contract, Definition


def dependent_library():
    lib = fixture()
    lib.write(definition("source", nodes.Var("arg0"), (), 1, ("arg0",)))
    lib.write(definition("consumer", nodes.Call("source", (nodes.Var("arg0"),)),
                         ("source",), 2, ("arg0",)))
    lib.write(definition("second_consumer", nodes.Call("source", (nodes.Var("arg0"),)),
                         ("source",), 2, ("arg0",)))
    return lib


def test_discard_rejects_dependents_and_preserves_both_records():
    lib = dependent_library()
    with pytest.raises(PipelineError, match="consumer.*second_consumer"):
        lib.discard("source")
    assert set(lib.records()) >= {"source", "consumer", "second_consumer"}


def test_discard_rejects_dependents_with_python_optimized():
    result = subprocess.run(
        [sys.executable, "-O", "-c",
         ("from test_atoms_round9_evidence import dependent_library\n"
         "from opulse.atoms.library import PipelineError\n"
         "lib = dependent_library()\n"
         "try:\n"
         "    lib.discard('source')\n"
         "except PipelineError as error:\n"
         "    if 'consumer' not in str(error) or 'second_consumer' not in str(error):\n"
         "        raise RuntimeError('dependent names missing from error')\n"
         "else:\n"
         "    raise RuntimeError('discard accepted a dependent')\n"
         "if 'source' not in lib.records():\n"
         "    raise RuntimeError('discard removed the source')\n")],
        capture_output=True, text=True, check=False,
        env={**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)},
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("status", ["verified", "promoted"])
def test_reloaded_evidence_without_checked_becomes_callable(status):
    lib = fixture()
    ready(lib, definition("source", nodes.Var("arg0"), (), 1, ("arg0",)), ((1,),))
    lib.verify("source", VerifyRequest("bounded", ((1,),), {"domain": "one", "size": 1},
                                       reference=lambda value: value))
    if status == "promoted":
        lib.promote("source", Contract("identity"))
    data = deepcopy(lib.to_dict())
    data["definitions"][0]["evidence"]["scope"].pop("checked")
    # The record is a plain value; the library decides validity on reload.
    assert not Definition.from_dict(data["definitions"][0]).evidence.checked_recorded()
    restored = Library.from_dict(data, lib.world, lib.atoms).get("source")
    assert restored.status == "callable"
    assert restored.evidence is None
    assert restored.contract is None


def test_live_missing_checked_invalidates_world_local_evidence():
    lib = fixture()
    ready(lib, definition("source", nodes.Var("arg0"), (), 1, ("arg0",)), ((1,),))
    evidence = lib.verify("source", VerifyRequest("bounded", ((1,),),
                                                  {"domain": "one", "size": 1},
                                                  reference=lambda value: value)).evidence
    lib._definitions["source"].evidence.scope.pop("checked")
    evidence.scope.pop("checked")
    assert lib.get("source").status == "callable"
    assert lib.get("source").evidence is None
    with pytest.raises(PipelineError, match="checked"):
        lib.record_evidence("source", evidence)


def test_import_rejects_mismatched_checked_scope():
    lib = fixture()
    ready(lib, definition("source", nodes.Var("arg0"), (), 1, ("arg0",)), ((1,),))
    lib.verify("source", VerifyRequest("bounded", ((1,),), {"domain": "one", "size": 1},
                                       reference=lambda value: value))
    stored = deepcopy(lib.to_dict()["definitions"][0])
    stored["evidence"]["scope"]["checked"]["size"] = 2
    restored = Library.from_dict({**lib.to_dict(), "definitions": [stored]}, lib.world, lib.atoms).get("source")
    assert restored.status == "callable"
    assert restored.evidence is None


def test_world_local_evidence_requires_and_preserves_checked_inputs():
    lib = fixture()
    ready(lib, definition("source", nodes.Var("arg0"), (), 1, ("arg0",)), ((1,),))
    evidence = lib.verify("source", VerifyRequest("bounded", ((1,),),
                                                  {"domain": "one", "size": 1},
                                                  reference=lambda value: value)).evidence
    local = fixture()
    ready(local, definition("source", nodes.Var("arg0"), (), 1, ("arg0",)), ((1,),))
    evidence.scope["checked"] = checked_scope(((1,),))
    recorded = local.record_evidence("source", evidence)
    assert recorded.status == "verified"
    assert recorded.evidence.scope["checked"] == checked_scope(((1,),))
