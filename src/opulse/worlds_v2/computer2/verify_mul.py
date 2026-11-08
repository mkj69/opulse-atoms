"""Exhaustive full-machine multiplication evidence (spec section 9)."""

import argparse
import hashlib
import json
import multiprocessing
import random
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from opulse.atoms import kernel, nodes
from opulse.atoms.library import PipelineError, atoms_digest, checked_scope
from opulse.atoms.spec import Evidence, content_hash
from opulse.atoms.values import Ok

from . import hosts

ARTIFACT = Path(__file__).with_name("data") / "mul_into.evidence.json"
WHILE_ARTIFACT = ARTIFACT.with_name("while_b.evidence.json")
DESCRIPTION = ("all B,C in 0..255; A=(13*C+7*B)%256, D=C^B, "
               "PC=(C+B)%256, z=(C^B)&1, mem[i]=(37*i+11)%256; "
               "one predetermined full machine per pair")
_LIBRARY = None
_SCOPE = None
_MEMORY = tuple((index * 37 + 11) % 256 for index in range(256))


def inputs_sha256():
    root = Path(__file__).resolve().parents[4]
    paths = list((root / "src/opulse/atoms").glob("*.py"))
    paths += list(Path(__file__).parent.glob("*.py"))
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.relative_to(root).as_posix().encode("utf-8") + b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def context(counter, factor):
    return hosts.machine(((factor * 13 + counter * 7) % 256, counter, factor,
                          (factor ^ counter) % 256), _MEMORY,
                         (factor + counter) % 256, (factor ^ counter) & 1)


def expected(initial):
    regs, memory, _, flag = hosts.fields(initial)
    counter = regs[1]
    return hosts.machine(((regs[0] + counter * regs[2]) % 256, 0, regs[2], regs[3]),
                         memory, 1, 1 if counter else flag)


def formula(counter):
    return 6 + 8 * counter


def hashes(library):
    return {"definition_body_hash": content_hash(nodes.to_json(library.get("mul_into").body)),
            "world_hash": library.world.world_hash(),
            "dependencies_hash": library._deps_hash("mul_into"),
            "content_hash": library.content_hash("mul_into"),
            "atoms_hash": atoms_digest(library.atoms)}


def mul_scope():
    return {"domain": DESCRIPTION, "size": 65536,
            "checked": checked_scope(tuple((counter, factor) for factor in range(256)
                                           for counter in range(256)))}


def validate_artifact(library, artifact):
    run = artifact.get("full_run", {})
    if (artifact.get("schema") != "opulse.computer2.mul_evidence/1" or
            any(artifact.get(key) != value for key, value in hashes(library).items()) or
            artifact.get("scope") != mul_scope() or
            artifact.get("checks") != ["reference", "unfold_equivalence", "exact_steps"] or
            artifact.get("steps") != {"formula": "6 + 8*B", "min": 6, "max": 2046,
                                      "mean": 1026.0} or
            run.get("pairs_checked") != 65536 or
            type(run.get("process_count")) is not int or run["process_count"] < 1 or
            not isinstance(run.get("date_utc"), str) or not run["date_utc"].endswith("+00:00") or
            run.get("inputs_sha256") != inputs_sha256()):
        raise PipelineError("mul_into exhaustive evidence missing, stale or malformed")


def apply_artifact(library):
    artifact = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    validate_artifact(library, artifact)
    definition = library.get("mul_into")
    if definition.status != "callable":
        raise PipelineError("mul_into evidence requires callable status")
    evidence = Evidence("exhaustive", artifact["scope"], None, tuple(artifact["checks"]),
                        artifact["world_hash"], artifact["dependencies_hash"],
                        artifact["content_hash"], artifact["atoms_hash"])
    library._steps["mul_into"] = [formula(counter) for counter in range(256) for _ in range(256)]
    library._definitions["mul_into"] = replace(definition, evidence=evidence)
    library._advance("mul_into", "verified")


def save_while_artifact(library):
    definition = library.get("@while_b")
    artifact = {"schema": "opulse.computer2.while_b_evidence/1",
                "definition_body_hash": content_hash(nodes.to_json(definition.body)),
                "world_hash": library.world.world_hash(),
                "dependencies_hash": library._deps_hash("@while_b"),
                "content_hash": library.content_hash("@while_b"),
                "atoms_hash": atoms_digest(library.atoms),
                "evidence": definition.evidence.to_dict(),
                "steps": library._steps["@while_b"]}
    WHILE_ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    WHILE_ARTIFACT.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n",
                              encoding="utf-8")


def apply_while_artifact(library):
    from .story import request_for

    artifact = json.loads(WHILE_ARTIFACT.read_text(encoding="utf-8"))
    definition = library.get("@while_b")
    request = request_for("@while_b", library)
    scope = artifact.get("evidence", {}).get("scope")
    if (artifact.get("schema") != "opulse.computer2.while_b_evidence/1" or
            artifact.get("definition_body_hash") != content_hash(nodes.to_json(definition.body)) or
            artifact.get("world_hash") != library.world.world_hash() or
            artifact.get("dependencies_hash") != library._deps_hash("@while_b") or
            artifact.get("content_hash") != library.content_hash("@while_b") or
            artifact.get("atoms_hash") != atoms_digest(library.atoms) or
            artifact["evidence"].get("method") != "bounded" or
            artifact["evidence"].get("content_hash") != artifact["content_hash"] or
            artifact["evidence"].get("atoms_hash") != artifact["atoms_hash"] or
            scope != {**request.scope, "checked": {**checked_scope(request.domain),
                                                   "by": "library"}} or
            len(artifact.get("steps", [])) != 1024 or
            set(artifact["evidence"].get("checks", ())) != {"reference", "unfold_equivalence"}):
        raise PipelineError("@while_b bounded evidence missing, stale or malformed")
    evidence = Evidence("bounded", scope, None, tuple(artifact["evidence"]["checks"]),
                        artifact["world_hash"], artifact["dependencies_hash"],
                        artifact["content_hash"], artifact["atoms_hash"])
    library._steps["@while_b"] = artifact["steps"]
    library._definitions["@while_b"] = replace(definition, evidence=evidence)
    library._advance("@while_b", "verified")


def check_pair(library, counter, factor, scope=None):
    initial = context(counter, factor)
    result = (kernel.call("mul_into", (initial,), scope, dialect=library.dialect)
              if scope is not None else library.run("mul_into", (initial,)))
    if result.outcome != Ok(expected(initial)) or result.steps != formula(counter):
        raise AssertionError(f"mul_into counterexample B={counter}, C={factor}: "
                             f"steps={result.steps}, outcome={result.outcome!r}")
    return result.steps


def _check_chunk(chunk):
    return [check_pair(_LIBRARY, counter, factor, _SCOPE)
            for factor in range(*chunk) for counter in range(256)]


def _check_pairs(pairs):
    return [check_pair(_LIBRARY, pair % 256, pair // 256, _SCOPE) for pair in pairs]


def _init_worker():
    global _LIBRARY, _SCOPE

    from .story import definitions
    from .world import new_library

    _LIBRARY = new_library()
    entries = {name: (kind, body) for name, kind, _, body in definitions()}
    _SCOPE = _LIBRARY.scope().extend([
        kernel.Defn(name, params, entries[name][1], entries[name][0])
        for name, params in (("mul_tick", ("s",)), ("@while_b", ("body", "s")),
                             ("mul_into", ("s",)))])


def check_all(processes=32, library=None):
    from .story import build_library

    if library is None:
        library = build_library(use_mul_artifact=False)
    for name in ("mul_tick", "@while_b", "mul_into"):
        if library.get(name).status != "promoted":
            raise PipelineError(f"{name} must pass the pipeline before exhaustive checking")
    chunks = [(factor, factor + 1) for factor in range(256)]
    context = multiprocessing.get_context("spawn")
    with context.Pool(processes=min(processes, 32, len(chunks)), initializer=_init_worker) as pool:
        counts = [0, 0, 0]
        for steps in pool.imap_unordered(_check_chunk, chunks):
            counts[0] += len(steps)
            counts[1] += sum(steps)
            counts[2] = max(counts[2], max(steps))
            print(f"verified {counts[0]}/65536 pairs", flush=True)
    if counts != [65536, 65536 * 1026, 2046]:
        raise AssertionError(f"unexpected exhaustive statistics: {counts}")
    return counts[0]


def check_subset(library, size=2000, seed=0, processes=16):
    pairs = random.Random(seed).sample(range(65536), size)
    if library.get("mul_into").status != "promoted":
        raise PipelineError("subset requires promoted multiplication")
    with multiprocessing.get_context("spawn").Pool(processes=min(processes, 32),
                                                    initializer=_init_worker) as pool:
        for checked in pool.imap_unordered(_check_pairs, (pairs[index:index + 32]
                                                      for index in range(0, size, 32))):
            if len(checked) == 0:
                raise AssertionError("empty verification chunk")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--while", dest="only_while", action="store_true",
                        help="only regenerate the loop evidence")
    parser.add_argument("--processes", type=int, default=32)
    args = parser.parse_args()
    if args.only_while:
        from .story import build_library

        library = build_library(use_mul_artifact=False, use_while_artifact=False)
        save_while_artifact(library)
        print("@while_b bounded evidence recorded: all 256 counters, two contexts and two slots")
        return
    if not args.write:
        parser.error("pass --write to run and record the exhaustive proof")
    from .story import build_library

    library = build_library(use_mul_artifact=False, use_while_artifact=False)
    save_while_artifact(library)
    pairs_checked = check_all(args.processes, library)
    if pairs_checked != 65536:
        raise AssertionError("full verification did not cover all pairs")
    artifact = {"schema": "opulse.computer2.mul_evidence/1", **hashes(library),
                "full_run": {"date_utc": datetime.now(timezone.utc).isoformat(),
                             "inputs_sha256": inputs_sha256(), "process_count": min(args.processes, 32),
                             "pairs_checked": pairs_checked},
                "scope": mul_scope(),
                "checks": ["reference", "unfold_equivalence", "exact_steps"],
                "steps": {"formula": "6 + 8*B", "min": 6, "max": 2046, "mean": 1026.0}}
    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("65536 pairs passed: full final machine and exact layer-0 steps")


if __name__ == "__main__":
    main()
