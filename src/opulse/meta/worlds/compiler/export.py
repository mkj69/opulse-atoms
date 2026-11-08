"""Deterministic site export (atoms-meta section 7)."""

import json
import re
from dataclasses import replace
from pathlib import Path

from opulse.atoms import kernel, nodes, notation
from opulse.atoms.bridges import bridge_defn
from opulse.atoms.spec import Definition, ObjectSpec, content_hash
from opulse.atoms.values import Card, Ok
from opulse.meta import notation as meta_notation
from opulse.meta.code import code_hash, encode_node, lst
from opulse.meta.compiler.validate import routine_id
from opulse.meta.export_util import (
    ascii_definition,
    ascii_example,
    compact_enumerations,
    input_hash,
    outcome_json,
    outside_scope,
    parse_meta_definition,
    value_json,
)
from opulse.meta.vn import reference
from opulse.meta.worlds.compiler.showcase import LADDER, tasks
from opulse.meta.worlds.compiler.story import build_story
from opulse.meta.worlds.compiler.world import TAGS, declaration

ROOT = Path(__file__).resolve().parents[5]
DECL_PATH = ROOT / "worlds/decl/meta/compiler@1.json"
EXPORT_PATH = ROOT / "docs/assets/data/meta/compiler.json"


def _example(library, definition, arguments, display_name=None):
    result = library.run(definition.name, arguments, trace=True)
    example = {"text": f"{definition.name} unfolds its own checked input tuple.",
            "inputs": [value_json(arg) for arg in arguments],
            "outcome": outcome_json(result.outcome), "steps": result.steps,
            "ascii": ascii_example(display_name or definition.name, definition.kind,
                                   arguments, result.outcome)}
    if result.outcome == Ok(lst(())):
        example["ascii"] = example["ascii"].rsplit(" = ", 1)[0] + " = list.items<>"
    if outside_scope(result.trace, library, check=_outside_scope):
        example["outside_scope"] = True
    return example


def _declaration(definition, library, display_name=None):
    """Print and check the kernel source and bridge domain (atoms-meta section 8)."""
    printable = (replace(definition, name=display_name, spec=replace(definition.spec, name=display_name))
                 if display_name and display_name != definition.name and definition.kind == "operation"
                 else definition)
    text, reason = ascii_definition(printable, library)
    if text is None:
        if definition.kind == "operation":
            spec = definition.spec
            params = getattr(spec, "extra", {}).get("input_names", ())
            name = display_name or definition.name
            arguments = [edge.name or (params[index] if index < len(params) else f"arg{index}")
                         for index, edge in enumerate(spec.inputs)]
            arguments = [arg if notation.is_valid_name("operation", arg) else f"arg{index}"
                         for index, arg in enumerate(arguments)]
            head = (f"op {name}(" + ", ".join(f"{arg}: {edge.sort}"
                    for arg, edge in zip(arguments, spec.inputs)) + f") -> {spec.output.sort} = ")
            try:
                body = notation.print_expr(definition.body, library)
                text = head + body + f" L{definition.layer}"
                if parse_meta_definition(text).body != definition.body:
                    text = None
            except (ValueError, TypeError):
                text = None
            if text is None:
                body = meta_notation._expr(encode_node(definition.body), True)
                body = re.sub(r"([a-z][a-z_0-9]*)<", r"\1 <", body)
                text = head + body + f" L{definition.layer}"
        elif definition.kind == "bridge":
            spec = definition.spec
            text = (f"bridge ~{definition.name}: {spec.source} -> {spec.target}"
                    f" = {notation.print_expr(spec.map, library)}")
            if spec.domain is not None:
                text += " where " + notation.print_expr(spec.domain, library)
            if spec.interface:
                text += " commutes (" + ", ".join(f"{source} -> {target}"
                                                    for source, target in spec.interface) + ")"
            text += f" L{definition.layer}"
        elif definition.kind == "template":
            name = display_name or definition.name
            text = f"template op {name}[src: op] = pack_prog(lcompile(src)) L{definition.layer}"
        elif definition.kind == "object" and isinstance(definition.body, nodes.Lit):
            value = definition.body.value
            literal = (meta_notation.show_code(value, signature=True, deps=True, exact=True)
                       if isinstance(value, Card) and value.sort == "code"
                       else meta_notation._value(value))
            text = f"obj {definition.name} = ({literal}) L{definition.layer}"
    if text is None:
        raise ValueError(f"cannot print {definition.name}: {reason}")
    parsed = parse_meta_definition(text)
    body = bridge_defn(parsed.spec).body if definition.kind == "bridge" else parsed.body
    if (parsed.kind != definition.kind or parsed.name != (display_name or definition.name)
            or (definition.kind != "template" and body != definition.body) or
            (definition.kind == "bridge" and (parsed.spec.domain != definition.spec.domain or
                                              parsed.spec.source != definition.spec.source or
                                              parsed.spec.target != definition.spec.target or
                                              parsed.spec.interface != definition.spec.interface))):
        raise ValueError(f"ASCII declaration differs from {definition.name}")
    return text


def _outside_scope(definition, arguments):
    """Compare one example against its recorded evidence (atoms-meta section 8)."""
    evidence = definition.evidence
    if evidence is None:
        return False
    scope = evidence.scope
    if definition.kind == "combinator" and scope.get("op_family"):
        if any(not isinstance(arguments[index], kernel.FnRef) or
               arguments[index].name not in scope["op_family"]
               for index in range(len(definition.spec.op_params))):
            return True
        arguments = arguments[len(definition.spec.op_params):]
    if "input_hashes" in scope:
        return input_hash(arguments) not in scope["input_hashes"]
    if "inputs" in scope:
        return list(arguments) not in scope["inputs"]
    if "accepted_hashes" in scope:
        return code_hash(arguments[0]) not in scope["accepted_hashes"]
    return False


def build_export(story=None):
    """Export only checked claims with their exact domains, contracts and costs."""
    story = story or build_story()
    world = story.library.world
    descriptions = {
        "fetch": "Read the instruction at the machine program counter.",
        "exec_one": "Execute one vn/1 instruction and return the next machine state.",
        "vn_interp": "Interpret a vn/1 memory image through kernel-node instructions until halt or fuel exhaustion.",
        "source_fib": "Compute exact integer Fibonacci using a tail-recursive triple of remaining count and two accumulators.",
        "agrees": "Return the matching result or signal a mismatch between two computations.",
        "target_fib": "Load an input byte into the compiled Fibonacci memory and read the invented interpreter's result channel.",
        "validated": "Compare the results of two selected operations on one shared input; its recorded family contains source_fib and target_fib.",
        "fib_crosscheck": "Compute Fibonacci through both exact-integer source and invented byte-machine interpreter, rejecting unequal results.",
        "fib_recurrence": "Check that three independently computed neighboring Fibonacci terms satisfy the recurrence.",
        "source_code": "Store the canonical tiny/1 Fibonacci source as an immutable named code value.",
        "compiled_program": "Store the reference compiler's vn/1 bytes with source provenance, without granting compiler-wide correctness.",
        "learner_source": "Store a case-based tiny/1 source accepted by the invented compiler.",
        "learner_program": "Store the invented compiler's translated case program with its compiler and source hashes.",
        "lcompile": "Translate the accepted subset of a 4618-program family to vn/1 bytes through kernel nodes; the fixed n=64 interface packages those bytes as a program.",
        "emit": "Construct a two-byte instruction from its opcode and operand.",
        "tail": "Return all instruction bytes after the first byte.",
        "lookup": "Find an input variable's assigned byte-memory address.",
        "branch": "Join condition, body, and fallback bytecode with patched jump addresses.",
        "compile_expr": "Recursively compile a supported tiny/1 expression into vn/1 bytes.",
        "interp_agrees": "Exact integer Fibonacci agrees with the compiled program read through the invented interpreter on inputs 0..13.",
        "fib_commutes": "Compare exact integer Fibonacci against its byte-machine target on the proposed input range.",
    }
    definitions = []
    for definition in story.library.definitions.values():
        if definition.origin != "invented":
            continue
        item = definition.to_dict()
        definitions.append({"layer": item["layer"], "kind": item["kind"], "name": item["name"],
                            "symbol": {"combinator": "@", "law": "#"}.get(definition.kind, "") + item["name"],
                            "definition": descriptions[definition.name], "spec": definition.spec.to_dict(),
                            "ascii": _declaration(definition, story.library),
                            "depends_on": item["depends_on"],
                            "body": item["body"], "status": item["status"],
                            "evidence": item["evidence"], "contract": item["contract"],
                            "cost": item["cost"], "examples": []})
    samples = {"fetch": (lst((0,) * 16), 0),
               "exec_one": (lst((1, 7) + (0,) * 14), 0, 0, 1),
               "vn_interp": (lst(reference.load(story.program.code, 256,
                                                  {story.program.args[0]: 2}).mem), 0, 0, 500),
               "source_fib": (3,), "agrees": (1, 2), "target_fib": (4,),
               "validated": (kernel.FnRef("source_fib"), kernel.FnRef("target_fib"), 10),
               "fib_crosscheck": (5,), "fib_recurrence": (8,),
               "interp_agrees": (0,), "fib_commutes": (0,)}
    for entry in definitions:
        if entry["kind"] == "law":
            value = samples[entry["name"]][0]
            statement = story.library.get(entry["name"]).spec.statement
            run = kernel.evaluate(statement, {"value": value}, story.library.scope())
            entry["examples"] = [{"text": f"{entry['name']} checks the integer input {value}.",
                                   "inputs": [value_json(value)], "outcome": outcome_json(run.outcome),
                                   "steps": run.steps,
                                   "ascii": ascii_example(entry["name"], "law", (value,),
                                       run.outcome)}]
        else:
            entry["examples"] = [_example(story.library, story.library.get(entry["name"]),
                                           samples[entry["name"]])]
        if _outside_scope(story.library.get(entry["name"]), samples[entry["name"]]):
            entry["examples"][0]["outside_scope"] = True
    learner_samples = {
        "emit": (1, 0), "tail": (lst((1, 2)),),
        "lookup": ("x0", lst(("x0",)), lst((60,))),
        "branch": (lst((1, 0)), lst((1, 1)), lst((1, 2)), 0),
        "compile_expr": (encode_node(nodes.Lit(0)), lst(("x0",)), lst((60,)), 0, 0, 0),
        "lcompile": (story.constants["learner_source"],),
    }
    for name, arguments in learner_samples.items():
        if name != "lcompile":
            arguments = story.helper_calls[name]["sample"]
        definition = story.compiler.get(name)
        item = definition.to_dict()
        example = _example(story.compiler, definition, arguments)
        example["text"] = (f"{name} contributes its checked kernel-node compilation stage."
                           if name != "lcompile" else
                           "lcompile translates a case instead of invoking the reference compiler.")
        if _outside_scope(definition, arguments):
            example["outside_scope"] = True
        definitions.append({"layer": definition.layer, "kind": "operation", "name": name,
                            "symbol": name,
                            "ascii": _declaration(definition, story.compiler),
                            "definition": descriptions[name], "spec": item["spec"],
                            "depends_on": item["depends_on"], "body": item["body"],
                            "status": item["status"], "evidence": item["evidence"],
                            "contract": item["contract"], "cost": item["cost"],
                            "world_hash": story.compiler.world.world_hash(),
                            "examples": [example]})
    for name, value in story.constants.items():
        digest = story.ledger.resolve(name)
        record = story.ledger.record(digest, world.world_hash())
        display_name = {"source_code": "SourceCode", "compiled_program": "CompiledProgram",
                        "learner_source": "LearnerSource", "learner_program": "LearnerProgram"}[name]
        display_definition = Definition(display_name, "object", "invented", 1, (),
            ObjectSpec(display_name, "constant", body=nodes.Lit(value)), nodes.Lit(value))
        definitions.append({"layer": 1, "kind": "object", "name": display_name,
                            "symbol": display_name,
                            "ascii": _declaration(display_definition, story.library),
                            "definition": descriptions[name],
                            "spec": ObjectSpec(display_name, "constant", body=nodes.Lit(value)).to_dict(),
                            "depends_on": [], "body": nodes.to_json(nodes.Lit(value)),
                            "status": record.status, "evidence": record.evidence[0].to_dict(),
                            "contract": record.contract.to_dict(),
                            "cost": {"length": 1, "steps": {"min": 0, "max": 0, "mean": 0}},
                            "examples": [{"text": f"{name} is a closed, zero-step immutable literal.",
                                          "inputs": [],
                                          "value": value_json(value), "code_hash": digest,
                                          "outcome": outcome_json(Ok(value)), "steps": 0,
                                          "ascii": ascii_example(display_name, "object", (), Ok(value))}],
                            "produced_by": list(record.produced_by)})
    bridge = story.bridge.get("compile")
    bridge_example = _example(story.bridge, bridge, (story.bridge_family[0],))
    bridge_example["text"] = "compile translates one checked member of its 16-code domain."
    definitions.append({"layer": bridge.layer, "kind": "bridge", "name": bridge.name,
                        "symbol": "~compile", "definition":
                        "Translate 16 accepted tiny source codes into byte programs on all 16 input pairs in 0..3.",
                        "ascii": _declaration(bridge, story.bridge),
                        "spec": bridge.spec.to_dict(), "interface": [list(pair) for pair in bridge.spec.interface],
                        "depends_on": list(bridge.depends_on), "body": nodes.to_json(bridge.body),
                        "status": bridge.status, "evidence": bridge.evidence.to_dict(),
                        "contract": bridge.contract.to_dict(), "cost": bridge.cost.to_dict(),
                        "world_hash": story.bridge.world.world_hash(), "examples": [bridge_example]})
    for name in ("recorded_source", "Compiled", "Compiled_member_0"):
        definition = story.bridge.get(name)
        display_name = {"Compiled": "compiled", "Compiled_member_0": "compiled_member_0"}.get(name, name)
        arguments = ("recorded_source",) if name == "Compiled" else ()
        example = _example(story.bridge, definition, arguments, display_name)
        example["text"] = f"{name} records one source in the verified compiler template family."
        definitions.append({"layer": definition.layer, "kind": definition.kind,
                            "name": display_name, "symbol": {"Compiled": "compiled[src]",
                                                    "Compiled_member_0": "compiled_member_0"}.get(name, name),
                            "ascii": _declaration(definition, story.bridge, display_name),
                            **({"source_pattern": parse_meta_definition(_declaration(
                                definition, story.bridge, display_name)).spec.pattern,
                                "source_spec_hash": content_hash(parse_meta_definition(_declaration(
                                    definition, story.bridge, display_name)).spec.to_dict())}
                               if name == "Compiled" else {}),
                            **({"produces": "operation", "family_scope": definition.evidence.scope}
                               if name == "Compiled" else {}),
                            "definition": "Instantiate a compiled operation on the recorded source family." if name == "Compiled" else
                            "Return the recorded source or its compiled byte program.",
                            "spec": definition.spec.to_dict(), "depends_on": list(definition.depends_on),
                            "body": (parse_meta_definition(_declaration(definition, story.bridge, display_name)).body
                                     if name == "Compiled" else nodes.to_json(definition.body)),
                            "status": definition.status,
                            "evidence": definition.evidence.to_dict() if definition.evidence else None,
                            "contract": definition.contract.to_dict() if definition.contract else None,
                            "cost": definition.cost.to_dict(), "world_hash": story.bridge.world.world_hash(),
                            "examples": [example]})
    payload = {"schema": "opulse.world_v2_export/1", "world": world.world,
            "version": world.version, "title": "A Fibonacci Compiler Bridge", "pitch":
            "An invented kernel compiler bridges tiny/1 cases to byte programs; a separate reference compiler handles Fibonacci. Pair evidence never grants compiler-wide correctness.",
            "decl": world.to_dict(), "layer0": [op.to_dict() for op in world.operations],
            "story": definitions, "tags": TAGS, "ladder": LADDER, "showcase": tasks(story),
            "learner_translation": {"pair": list(story.learner_validation.pair),
                                    "evidence": story.ledger.pair_evidence(
                                        *story.learner_validation.pair, world.world_hash())[0].to_dict(),
                                    "compiler_hash": story.compiler_hash,
                                    "routine_id": story.learner_validation.routine_id},
            "translation": {"pair": list(story.validation.pair),
                            "source_hash": code_hash(story.constants["source_code"]),
                            "routine_id": routine_id(story.program),
                            "method": story.validation.method,
                            "scope": {"domain": [list(row) for row in story.validation.scope["domain"]],
                                      "size": story.validation.scope["size"], "fuel": 500},
                            "accepted": story.validation.accepted,
                            "evidence": story.ledger.pair_evidence(
                                *story.validation.pair, world.world_hash())[0].to_dict(),
                            "bridge": "~compile: Code -> Prog",
                            "contract": "Result channel only; x0=0..13, fuel=500; no compiler-wide claim."},
            "law_near_miss": {"symbol": "#fib_commutes", "status": "callable",
                              "scope": "integer inputs 0..15, fuel 500; inputs 14 and 15 disagree",
                              "counterexamples": [{"input": value,
                                                   "source": outcome_json(story.library.run("source_fib", (value,)).outcome),
                                                   "target": outcome_json(story.library.run("target_fib", (value,)).outcome)}
                                                  for value in (14, 15)]},
            "rejection": {"pair": list(story.rejection.pair),
                          "counterexample": {"input": list(story.rejection.counterexample.inputs),
                                             "source": value_json(story.rejection.counterexample.source.value),
                                             "compiled": value_json(story.rejection.counterexample.compiled.value),
                                             "reason": story.rejection.counterexample.reason},
                          "status": "unpromoted"}}
    for item in payload["story"]:
        for key in ("evidence", "cost", "family_scope"):
            if key in item and item[key] is not None:
                item[key] = compact_enumerations(item[key])
    return json.loads(json.dumps(payload))


def export(story=None):
    """Compatibility wrapper for existing callers."""
    return build_export(story)


def write():
    """Regenerate the declaration and the committed static payload."""
    story = build_story()
    DECL_PATH.parent.mkdir(parents=True, exist_ok=True)
    EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    DECL_PATH.write_text(json.dumps(declaration().to_dict(), indent=2, sort_keys=True) + "\n")
    EXPORT_PATH.write_text(json.dumps(build_export(story), indent=2, sort_keys=True) + "\n")


write_export = write


if __name__ == "__main__":
    write()
