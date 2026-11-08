"""Export reproducible kernel runs for the Learn grammar lesson."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from opulse.atoms import kernel
from opulse.atoms.notation import print_value
from opulse.atoms.values import Bottom, Card, Ok, Unknown
from opulse.worlds_v2.grammar import hosts, story
from tools.atoms2_core_source import printed_declaration, printed_label

OUTPUT = ROOT / "docs/assets/data/atoms2/grammar_core.json"
DESIGN = ROOT / "docs/assets/data/atoms2/grammar.json"


def input_digest():
    paths = sorted((ROOT / "src/opulse/atoms").glob("*.py"))
    paths += sorted((ROOT / "src/opulse/worlds_v2/grammar").glob("*.py"))
    paths += [DESIGN, Path(__file__), ROOT / "tools/atoms2_core_source.py", ROOT / "tools/atoms2_parse_status.py",
              ROOT / "worlds/decl/v2/grammar@1.json"]
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(str(path.relative_to(ROOT)).encode("ascii") + b"\0" + path.read_bytes())
    return digest.hexdigest()


def outcome_text(outcome):
    if isinstance(outcome, Ok):
        if isinstance(outcome.value, Card) and outcome.value.sort == "bool" and not outcome.value.fields:
            return "Ok(" + outcome.value.tag + ")"
        return "Ok(" + print_value(outcome.value) + ")"
    if isinstance(outcome, Bottom):
        return "Bottom(" + outcome.reason + ")"
    if isinstance(outcome, Unknown):
        return "Unknown(" + outcome.resource + ")"
    raise TypeError("unexpected kernel outcome")


def compact_trace(node, limit=12):
    if node is None:
        return []
    rows = []
    pending = [(node, 0)]
    while pending and len(rows) < limit:
        current, depth = pending.pop(0)
        rows.append({"call": current.name or "root", "depth": depth, "layer": current.layer,
                     "steps": current.steps, "outcome": outcome_text(current.outcome)})
        pending.extend((child, depth + 1) for child in current.children)
    return rows


def declaration(definition, library):
    if definition.kind == "observation":
        definition = replace(definition, spec=replace(
            definition.spec, extra={**definition.spec.extra, "subject": "w"}))
    printed = printed_declaration(definition, library)
    if printed["text"] is not None:
        printed["label"] = printed_label(printed)
    else:
        printed["label"] = f"Design summary (printer unavailable: {printed['reason']})"
    return printed


def run_record(library, name, args, expression, scope=None):
    run = library.run(name, args, trace=True)
    if type(run.outcome) is Unknown:
        raise RuntimeError(f"{name} exhausted resources: {run.outcome.resource}")
    outside = False
    if scope is not None:
        words, tiny = story._domains(None, None)
        outside = args != (hosts.HOLE,) if name == "ExprTree.make" else args[-1] not in (tiny if name == "chart" else words)
    return {"input": expression, "outcome": outcome_text(run.outcome), "layer0_steps": run.steps,
            **({"outside_checked_scope": True} if outside else {}),
            "trace": compact_trace(run.trace)}


def export():
    try:
        library = story.build_library(stop_after="parse_count")
    except Exception as error:
        raise RuntimeError("grammar world code failed in build_library() (not stale UI data)") from error
    design = json.loads(DESIGN.read_text(encoding="utf-8"))
    tokens = tuple(2 if index % 2 == 0 else "+" if index % 4 == 1 else "*"
                   for index in range(15))
    word = story.word_from(tokens)
    word_ascii = print_value(word)
    if tuple(tokens) != tuple(json.loads('[' + design["input"][5:-1] + ']')):
        raise ValueError("Learn Word tokens differ from grammar world input")
    slots = tuple(kernel.FnRef(name) for name in
                  ("one", "multiply", "identity", "combine_count", "zero"))
    cases = {
        "object": ("ExprTree", "ExprTree.make", (hosts.to_card(("num", 7)),),
                   "ExprTree.make(Draft.num<7>)"),
        "operation": ("split", "split", (word,), "split(" + word_ascii + ")"),
        "combinator": ("chart", "chart", (*slots, word),
                       "@chart[one,multiply,identity,combine_count,zero](" + word_ascii + ")"),
        "observation": ("parse_count", "parse_count", (word,), "?parse_count{" + word_ascii + "}"),
    }
    rows = {}
    for kind, (name, callable_name, args, expression) in cases.items():
        definition = library.get(name)
        evidence = definition.evidence
        rows[kind] = {"name": name, "layer": definition.layer,
                      "depends_on": list(definition.depends_on),
                      "declaration": declaration(definition, library),
                      "status": evidence.method, "scope": evidence.scope["domain"],
                      "evidence": {"method": evidence.method, "scope": evidence.scope,
                                   "checks": list(evidence.checks), "content_hash": evidence.content_hash},
                      "content_hash": library.content_hash(name),
                      "example": run_record(library, callable_name, args, expression, evidence.scope)}
    rows["object"]["failure"] = run_record(library, "ExprTree.make", (hosts.HOLE,),
                                             "ExprTree.make(Draft.E<>)", rows["object"]["scope"])
    if rows["observation"]["example"]["outcome"] != "Ok(429)":
        raise ValueError("the Learn Word did not produce 429 through ?parse_count")
    if not rows["object"]["failure"]["outcome"].startswith("Bottom("):
        raise ValueError("unfinished tree did not fail")
    payload = {"schema": "opulse.atoms2_grammar_core/1",
               "inputs_sha256": input_digest(),
               "input": word_ascii, "rows": rows}
    payload["digest"] = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"),
                                                ensure_ascii=True).encode("ascii")).hexdigest()
    return payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check and OUTPUT.is_file():
        try:
            existing = json.loads(OUTPUT.read_text(encoding="utf-8"))
            payload = {key: value for key, value in existing.items() if key != "digest"}
            checksum = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"),
                                                ensure_ascii=True).encode("ascii")).hexdigest()
            if (existing["schema"] == "opulse.atoms2_grammar_core/1" and
                    set(existing["rows"]) == {"object", "operation", "combinator", "observation"} and
                    existing["inputs_sha256"] == input_digest() and existing["digest"] == checksum):
                return
        except (ValueError, KeyError, TypeError):
            pass
    from opulse.notation3.export import add_notation3

    rendered = json.dumps(add_notation3(export(), 'atoms2', source='atoms2/grammar_core.json'),
                          indent=2, ensure_ascii=True) + "\n"
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != rendered:
            parser.exit(1, f"stale generated data: {OUTPUT}\n")
    else:
        OUTPUT.write_text(rendered, encoding="utf-8")


if __name__ == "__main__":
    main()
