"""Deterministic site export for the stored-program world (atoms-meta 7)."""

import json
from dataclasses import replace
from functools import lru_cache
from pathlib import Path

from opulse.atoms import kernel, nodes, notation
from opulse.atoms.kernel import FnRef
from opulse.atoms.laws import replay_rewrite, rewrite
from opulse.atoms.spec import content_hash
from opulse.meta.export_util import (
    ascii_definition,
    ascii_example,
    input_hash,
    outcome_json,
    outside_scope,
    parse_meta_definition,
    value_json,
)
from opulse.meta.vn import machine
from opulse.meta.worlds.vonneumann.showcase import tasks
from opulse.meta.worlds.vonneumann.story import (
    RELOCATED,
    RESTORE,
    RESTORE_SOURCE,
    SMALL,
    SMALL_SOURCE,
    SUM,
    SUM_SOURCE,
    creation_story,
    evidence,
    initial,
    relocation_start,
)
from opulse.meta.worlds.vonneumann.world import LADDER, TAGS, declaration

ROOT = Path(__file__).resolve().parents[5]
DECL_PATH = ROOT / "worlds/decl/meta/vonneumann@1.json"
EXPORT_PATH = ROOT / "docs/assets/data/meta/vonneumann.json"

DEFINITIONS = {
    "SampleProgram": "This object stores the complete 32-byte sample program image.",
    "run_routine": "This operation executes a machine state until HALT within 100 instructions.",
    "sum_routine": "This operation calls the invented runner to compute a three-cell sum.",
    "next_op": "This observation reads the opcode at the current program counter without changing state.",
    "patch_operand": "This operation writes one selected memory byte, including instruction operands.",
    "twice_run": "This combinator applies its plugged operation twice to a machine state.",
    "reset_operand": "This operation restores the ADD operand at address 7.",
    "rerun_restored": "This operation repairs the operand and then invokes the named sum operation.",
    "copy_six": "This operation copies the six source instruction bytes into addresses 12 through 17.",
    "relocate_add": "This operation copies the source program and retargets both absolute operands.",
    "relocate_variant": "This operation retargets the copied ADD to source cell 29 instead.",
    "run_variant": "This operation executes the retargeted copy from program counter 12.",
    "variant_result": "This operation extracts the retargeted copy's final accumulator.",
    "restore_idempotent": "This scoped law says resetting the same operand twice has the same full-state effect as resetting it once.",
    "fix": "This bounded fixpoint reapplies operand repair until the complete code image stops changing.",
    "source_result": "This operation returns the accumulator after running the original routine at base 0.",
    "target_result": "This operation returns the accumulator after running the copied routine at base 12.",
    "relocate_12": "This partial bridge copies the routine to base 12 and retargets its absolute operands, preserving the executed accumulator on its stated scope.",
    "retarget_operand": "This template creates one separately verified operand-patching operation for each byte 29, 30, and 31.",
    "retarget_29": "This template instance sets the operand at address 7 to byte 29.",
    "retarget_30": "This template instance sets the operand at address 7 to byte 30.",
    "retarget_31": "This template instance sets the operand at address 7 to byte 31.",
}


def _ascii_story_definition(definition, lib):
    """Render a compact declaration view of a promoted definition (meta 8)."""
    if definition.kind == "template":
        source = notation.parse_definition(
            f"template op {definition.name}[operand: int] = patch_operand(s, 7, operand) L1")
    elif definition.kind == "observation":
        source = replace(definition, spec=replace(definition.spec, reads=()))
    elif definition.kind == "bridge":
        source = replace(definition, body=definition.spec.map)
    elif definition.kind == "law":
        source = replace(definition, spec=replace(definition.spec, vars=tuple(
            (name, "VN" if sort == "vn" else sort) for name, sort in definition.spec.vars)))
    elif definition.kind == "operation":
        spec = definition.spec
        inputs = tuple(replace(edge, sort="VN" if edge.sort == "vn" else
                               "int" if edge.sort == "byte" else edge.sort) for edge in spec.inputs)
        output = replace(spec.output, sort="VN" if spec.output.sort == "vn" else
                         "int" if spec.output.sort == "byte" else spec.output.sort)
        source = replace(definition, spec=replace(spec, rule="ASCII definition", extra={},
                                                  inputs=inputs, output=output),
                         depends_on=tuple(sorted(nodes.references(definition.body))))
    else:
        source = definition
    if definition.kind not in ("template", "operation"):
        excluded = set(source.spec.op_params) if definition.kind == "combinator" else set()
        source = replace(source, depends_on=tuple(sorted(nodes.references(source.body) - excluded)))
    text, reason = ascii_definition(source, None if definition.kind == "observation" else lib)
    if reason is not None:
        raise ValueError(f"{definition.name}: {reason}")
    return text


def _routine_body(routine, runner):
    """Bind the exact installed image before running it (meta 4.3, 8)."""
    return nodes.Let("routine_base", nodes.Lit(routine.base),
                     nodes.Let("routine_bytes", nodes.Lit(bytes(routine.code).hex()), runner))


@lru_cache(maxsize=1)
def build_export():
    world = declaration()
    lib, definitions = creation_story()
    ledger = evidence()
    story = []
    for routine, source, description in (
            (SUM, SUM_SOURCE, "This routine walks three array cells by rewriting the ADD operand."),
            (RESTORE, RESTORE_SOURCE, "This routine restores the operand before a repeated three-cell sum."),
            (SMALL, SMALL_SOURCE, "This routine adds two input cells from the original address."),
            (RELOCATED, "LD 30 ; Retarget first absolute load.\nADD 31 ; Retarget second absolute load.\nHALT ; Stop.\n",
             "This routine is reverified at address 12 after copying and rewriting both operands.")):
        recorded_evidence, changed, contract = ledger.record(routine)
        state = (initial(routine, (1, 3, 2) if routine == SUM else (1, 2, 3))
                 if routine in (SUM, RESTORE) else
                 relocation_start(1, 2))
        if routine == RELOCATED:
            memory = list(state.mem)
            memory[12:18] = routine.code
            state = type(state)(12, 0, tuple(memory))
        run = machine.run(machine.to_card(state), 100)
        name = {SUM: "sum3_loop", RESTORE: "sum3_restored", SMALL: "source_add",
                RELOCATED: "relocated_add"}[routine]
        displayed = replace(lib.get("run_routine"), name=name,
                            layer=1 if routine in (SUM, SMALL) else 2,
                            spec=replace(lib.get("run_routine").spec, name=name),
                            body=_routine_body(routine, lib.get("run_routine").body))
        ascii_source = _ascii_story_definition(displayed, lib)
        parsed = parse_meta_definition(ascii_source)
        if parsed.body != displayed.body:
            raise ValueError(f"routine {name} did not round-trip")
        story.append({"layer": 1 if routine in (SUM, SMALL) else 2, "kind": "operation",
                      "name": name,
                      "symbol": name,
                      "definition": description, "depends_on": sorted(nodes.references(parsed.body)),
                      "body": source,
                      "routine_id": ledger.identity(routine), "status": "promoted",
                      "evidence": recorded_evidence.to_dict(), "contract": contract.to_dict(),
                      "ascii": ascii_source, "spec": parsed.spec.to_dict(),
                      "cost": {"length": len(routine.code), "steps": run.steps,
                               "changed_addresses": sorted(changed)},
                      "examples": [{"text": description,
                                    "inputs": [value_json(machine.to_card(state))],
                                    "outcome": outcome_json(run.outcome), "steps": run.steps,
                                    "ascii": ascii_example(name, "operation", (machine.to_card(state),),
                                                           run.outcome)}]})
    base_state = machine.to_card(initial(SUM, (1, 2, 3)))
    relocated_state = machine.to_card(relocation_start(1, 2))
    restore_state = machine.poke(machine.to_card(initial(RESTORE, (1, 2, 3))), 7, 32)
    examples = {"patch_operand": (base_state, 3, 32),
                "sum_routine": (machine.to_card(initial(SUM, (0, 0, 0))),),
                "reset_operand": (restore_state,), "rerun_restored": (restore_state,),
                "copy_six": (machine.to_card(relocation_start(3, 1)),),
                "relocate_add": (relocated_state,),
                "relocate_variant": (machine.to_card(relocation_start(3, 1)),),
                "run_variant": (machine.to_card(relocation_start(3, 1)),),
                "variant_result": (machine.to_card(relocation_start(3, 1)),)}
    examples.update({"restore_idempotent": (restore_state,),
                     "fix": (restore_state, 2),
                     "source_result": (relocated_state,),
                     "target_result": (lib.run("relocate_add", (relocated_state,)).outcome.value,),
                     "relocate_12": (relocated_state,),
                     "retarget_operand": (29,),
                     **{f"retarget_{byte}": (restore_state,) for byte in (29, 30, 31)}})
    examples["retarget_29"] = (machine.to_card(initial(RESTORE, (1, 2, 3))),)

    def scope_violations(frame):
        if frame is None:
            return []
        definitions = lib.definitions
        violations = []
        seen = set()

        def visit(call):
            definition = definitions.get(call.name)
            if definition is not None and definition.origin == "invented" and \
                    definition.status == "promoted" and outside_scope(replace(call, children=[]), lib,
                                                                       {call.name: definition}):
                key = (call.name, input_hash(call.inputs))
                if key not in seen:
                    seen.add(key)
                    violations.append({"name": call.name, "outside_scope": True,
                                       "input_hash": key[1]})
            for child in call.children:
                visit(child)

        visit(frame)
        return violations

    for definition in definitions:
        if definition.kind == "combinator":
            operation = "reset_operand" if definition.name == "fix" else "step"
            args = examples.get(definition.name, (base_state,))
            run = lib.run(definition.name, (FnRef(operation), *args), fuel=100, trace=True)
            example = {"text": ("Repair until the image stabilizes within two iterations." if definition.name == "fix"
                                else "Two applications of step; the operation is plugged into f."),
                       "inputs": [value_json(FnRef(operation)), *(value_json(arg) for arg in args)],
                       "outcome": outcome_json(run.outcome),
                       "steps": run.steps}
        elif definition.kind == "law":
            args = examples[definition.name]
            run = kernel.evaluate(definition.body, {"s": args[0]}, lib.scope(),
                                  kernel.Limits(fuel=100), trace=True)
            example = {"text": "Both repaired code images are equal on this checked input.",
                       "inputs": [value_json(arg) for arg in args],
                       "outcome": outcome_json(run.outcome), "steps": run.steps}
        else:
            args = () if definition.kind == "object" else examples.get(definition.name, (base_state,))
            run = lib.run(definition.name, args, fuel=100, trace=True)
            example = {"text": {
                "SampleProgram": "Read the 32-byte constant program image.",
                "run_routine": "Execute the three-cell sum to HALT.",
                "sum_routine": "Run the three-cell sum through the named operation.",
                "next_op": "Inspect the first opcode without changing memory.",
                "patch_operand": "Rewrite the ADD operand at address 3 to 32.",
                "reset_operand": "Repair a patched ADD operand at address 7.",
                "rerun_restored": "Repair the operand before summing three cells.",
                "copy_six": "Copy six instruction bytes to address 12.",
                "relocate_add": "Copy six bytes and retarget both absolute operands.",
                "relocate_variant": "Retarget the relocated ADD to the source input.",
                "run_variant": "Execute the variant from address 12.",
                "variant_result": "Read the variant's final accumulator.",
                "source_result": "Run the source and read its final accumulator.",
                "target_result": "Run the copied program and read its final accumulator.",
                "relocate_12": "Copy and retarget a routine in the partial bridge domain.",
                "retarget_operand": "Instantiate the family for byte 29.",
                "retarget_29": "Apply the verified member to an already repaired image, preserving its operand.",
                "retarget_30": "Retarget the ADD operand to cell 30.",
                "retarget_31": "Retarget the ADD operand to cell 31.",
            }[definition.name],
                       "inputs": [value_json(arg) for arg in args],
                       "outcome": outcome_json(run.outcome), "steps": run.steps}
        violations = scope_violations(run.trace)
        example["ascii"] = ascii_example(definition.name, definition.kind,
                                           (FnRef(operation), *args) if definition.kind == "combinator"
                                           else args, run.outcome)
        if violations:
            example["outside_scope"] = True
            callees = [item for item in violations if item["name"] != definition.name]
            if callees:
                example["callee_scope"] = callees[0]
                example["callee_scopes"] = callees
        entry = {"layer": definition.layer, "kind": definition.kind,
                      "name": definition.name,
                      "symbol": (f"@{definition.name}"
                                 if definition.kind == "combinator" else
                                 "#restore_idempotent" if definition.kind == "law" else
                                 "~relocate_12" if definition.kind == "bridge" else
                                 definition.name if definition.kind in ("template", "object") else
                                 f"?{definition.name}" if definition.kind == "observation" else
                                 definition.name),
                      "definition": DEFINITIONS[definition.name],
                      "depends_on": list(definition.depends_on), "body": (
                          parse_meta_definition(_ascii_story_definition(definition, lib)).body
                          if definition.kind == "template" else nodes.to_json(definition.body)),
                      "status": definition.status, "evidence": definition.evidence.to_dict(),
                      "contract": definition.contract.to_dict(), "cost": definition.cost.to_dict(),
                      "examples": [example], "ascii": _ascii_story_definition(definition, lib)}
        entry["spec"] = parse_meta_definition(entry["ascii"]).spec.to_dict()
        if definition.kind == "bridge":
            entry["interface"] = [list(pair) for pair in definition.spec.interface]
        if definition.kind == "template":
            entry["produces"] = definition.spec.produces
            entry["family_scope"] = definition.evidence.scope
            entry["runtime_spec"] = definition.spec.to_dict()
            entry["spec"] = parse_meta_definition(entry["ascii"]).spec.to_dict()
            entry["source_spec_hash"] = content_hash(entry["spec"])
        story.append(entry)
    original = nodes.Call("get_a", (nodes.Call("reset_operand", (
        nodes.Call("reset_operand", (nodes.Var("s"),)),)),))
    rewritten = rewrite(original, "restore_idempotent", lib, at=(0,))
    derivation = replay_rewrite(original, rewritten, "restore_idempotent", lib,
                                {"s": restore_state}, fuel=100)
    next(item for item in story if item["name"] == "restore_idempotent")["derivation"] = {
        "before": nodes.to_json(original), "after": nodes.to_json(rewritten),
        "law": "#restore_idempotent", "path": list(derivation.steps[0].path),
        "rewrite_steps": len(derivation.steps), "charged_steps": derivation.charged_steps,
        "outcome": outcome_json(kernel.evaluate(rewritten, {"s": restore_state}, lib.scope(),
                                                kernel.Limits(fuel=100)).outcome)}
    story = json.loads(json.dumps(story))
    counterexample = lib.run("reset_operand", (restore_state,), fuel=100)
    false_statement = kernel.evaluate(lib.get("reset_is_identity").body,
                                      {"s": restore_state}, lib.scope(), kernel.Limits(fuel=100))
    return {"schema": "opulse.world_v2_export/1", "world": "vonneumann", "version": 1,
            "title": "The Program That Rewrites Its Own Address",
            "pitch": "One 32-byte memory holds both instructions and data. A stored-program loop learns to walk an array by editing its own next fetch.",
            "decl": world.to_dict(), "layer0": {"objects": [item.to_dict() for item in world.objects],
                                               "operations": [item.to_dict() for item in world.operations],
                                               "observations": world.observation["probes"],
                                               "combinators": world.combinators},
            "story": story, "tags": TAGS, "ladder": LADDER, "showcase": tasks(),
            "near_misses": [{"symbol": "#reset_is_identity",
                             "scope": "the single image with operand 7 = 32",
                             "input": value_json(restore_state),
                             "changed_operand": machine.from_card(counterexample.outcome.value).mem[7],
                             "outcome": outcome_json(false_statement.outcome),
                             "steps": false_statement.steps,
                             "status": lib.get("reset_is_identity").status}]}


def write():
    """Regenerate both committed artifacts from current source (atoms-meta 8)."""
    DECL_PATH.write_text(json.dumps(declaration().to_dict(), indent=2, ensure_ascii=True) + "\n",
                         encoding="utf-8")
    EXPORT_PATH.write_text(json.dumps(build_export(), indent=2, ensure_ascii=True) + "\n",
                           encoding="utf-8")


def write_export(path):
    Path(path).write_text(json.dumps(build_export(), indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    write()
