"""Deterministic site export for code@1 (atoms-meta section 7)."""

import json
import re
from dataclasses import replace
from pathlib import Path

from opulse.atoms import kernel, nodes, notation
from opulse.atoms.spec import content_hash
from opulse.atoms.templates import instantiate
from opulse.atoms.values import Card, Ok
from opulse.meta import code
from opulse.meta import notation as meta_notation
from opulse.meta.export_util import (
    _ascii_value,
    ascii_definition,
    ascii_example,
    compact_enumerations,
    outcome_json,
    outside_scope,
    parse_meta_definition,
    value_json,
)
from opulse.meta.notation import show_code

from .showcase import LADDER, showcase
from .story import build_story
from .world import DECL, declaration

DEST = Path(__file__).resolve().parents[5] / "docs/assets/data/meta/code.json"

DESCRIPTIONS = {
    "poly": "A constant holding the quoted polynomial add(mul(x0,x0),3).",
    "expr_size": "Count nodes in the expression field of a program value.",
    "has_div": "Search calls and lets for division; conservatively guard case expressions.",
    "const_fold": "Recursively evaluate add/sub/mul when both children are integer literals.",
    "simplify_unsafe": "Cancel equal subtraction terms even when evaluating them fails; never promoted.",
    "simplify_safe": "Cancel identical subtractions only when their subtrees contain no division.",
    "stable_simplify": "Fold first, then apply verified guarded simplification.",
    "specialize": "Fix x0 to k, rename x1 to x0, and fold the resulting unary program.",
    "specialize_zero": "Generate a unary program by fixing the first input to zero.",
    "pipeline": "A public combinator: unfold to stable_simplify(t2(t1(c))).",
    "fold_idempotent": "Folding twice gives the same code as folding once on all 224 recorded programs.",
    "unsafe_equivalence": "An unverified claim that unsafe simplification preserves evaluation at a recorded input.",
    "fold_bridge": "Translate by constant folding; the interface commutes on all 224 recorded programs.",
    "Specialize": "A bounded family of code transformers that fix the first input to a constant.",
}


def _display_definition(definition):
    """Project recorded metadata to the compact declaration subset (meta 8)."""
    name = ("Poly" if definition.name == "poly" else "specialize_fixed"
            if definition.name == "Specialize" else definition.name.lower()
            if definition.name.startswith("Specialize_member_") else definition.name)
    if definition.kind == "template":
        return notation.parse_definition(
            "template op specialize_fixed[k: int] = specialize(arg0, k) L1")
    if definition.kind == "object":
        return replace(definition, name=name, spec=replace(definition.spec, name=name, base=None))
    if definition.kind == "operation":
        names = definition.spec.extra.get("input_names", [f"arg{index}" for index in range(len(definition.spec.inputs))])
        spec = replace(definition.spec, name=name, rule="ASCII definition", extra={},
                       inputs=tuple(replace(edge, name=param)
                                    for edge, param in zip(definition.spec.inputs, names)),
                       output=definition.spec.output)
        return replace(definition, name=name, spec=spec)
    return definition


def _ascii_source(definition, library):
    display = _display_definition(definition)
    source, reason = ascii_definition(display, None if definition.name.startswith("generated_") else library)
    if source is not None:
        try:
            if parse_meta_definition(source).body == (display.body if display.kind == "template"
                                                       else definition.body):
                return display.name, source
        except (ValueError, notation.NotationError):
            pass
    if display.kind not in ("object", "operation"):
        raise ValueError(f"{definition.name}: {reason}")
    literals = {}

    def prepare(part):
        if isinstance(part, nodes.Lit) and isinstance(part.value, Card):
            marker = f"__code_literal_{len(literals)}__"
            value = part.value
            literals[notation.print_value(marker)] = (
                f"literal<bool_card: {value.tag}>" if value.sort == "bool"
                else _ascii_value(value))
            return nodes.Lit(marker)
        return part

    try:
        rendered = notation.print_expr(nodes.map_nodes(definition.body, prepare), library)
        for marker, literal in literals.items():
            rendered = rendered.replace(marker, literal)
        if display.kind == "operation":
            names = [edge.name for edge in display.spec.inputs]
            inputs = ", ".join(f"{name}: {edge.sort}" for name, edge in zip(names, display.spec.inputs))
            source = (f"op {display.name}({inputs}) -> {display.spec.output.sort} = "
                      f"{rendered} L{display.layer}")
        else:
            source = f"obj {display.name} = ({rendered}) L{display.layer}"
        parsed = parse_meta_definition(source)
    except (ValueError, TypeError, notation.NotationError):
        parsed = None
    if parsed is None or parsed.body != definition.body:
        if display.kind == "operation":
            names = [edge.name for edge in display.spec.inputs]
            inputs = ", ".join(f"{name}: {edge.sort}" for name, edge in zip(names, display.spec.inputs))
        rendered = meta_notation._expr(code.encode_node(definition.body), exact=True)
        memo_names = {part.fn for part in nodes.walk(definition.body)
                      if isinstance(part, nodes.Rec) and part.memo}
        for name in memo_names:
            rendered = re.sub(rf"\brec {re.escape(name)}\(", f"rec memo {name}(", rendered)
        source = (f"op {display.name}({inputs}) -> {display.spec.output.sort} = {rendered} L{display.layer}"
                  if display.kind == "operation" else
                  f"obj {display.name} = ({rendered}) L{display.layer}")
        if parse_meta_definition(source).body != definition.body:
            raise ValueError(f"{definition.name}: declaration does not round-trip: {reason}")
    return display.name, source


def export(built=None):
    lib, family, counterexample = built if built is not None else build_story()
    story = []
    for definition in lib.definitions.values():
        if definition.origin != "invented":
            continue
        if definition.name == "pipeline":
            arguments = (kernel.FnRef("const_fold"), kernel.FnRef("simplify_safe"), family[11])
            shown = ["@const_fold", "@simplify_safe", show_code(family[11])]
        elif definition.name == "poly":
            arguments, shown = (), []
        elif definition.kind == "law":
            arguments = (counterexample, code.lst((0,))) if definition.name == "unsafe_equivalence" else (family[12],)
            shown = [show_code(arguments[0])] + (["[0]"] if len(arguments) == 2 else [])
        elif definition.kind == "bridge":
            arguments, shown = (family[13],), [show_code(family[13])]
        elif definition.kind == "template":
            arguments, shown = (3,), ["3"]
        elif definition.name.startswith("Specialize_member_"):
            index = int(definition.name.rsplit("_", 1)[1])
            from .story import specialization_family
            value = specialization_family(lib, family)[index]
            arguments, shown = (value,), [show_code(value)]
        elif definition.name.startswith("generated_"):
            arguments, shown = (4,), ["4"]
        elif definition.name == "has_div":
            arguments, shown = (counterexample.fields[2],), ["sub(div(x0, 0), div(x0, 0))"]
        elif definition.name == "simplify_unsafe":
            from .showcase import decide_family
            value = decide_family(lib)[0]
            arguments, shown = (value,), [show_code(value)]
        elif definition.name in ("specialize", "specialize_zero"):
            from .story import specialize_source
            arguments = (specialize_source(lib), 3) if definition.name == "specialize" else (specialize_source(lib),)
            shown = [show_code(specialize_source(lib))] + (["3"] if definition.name == "specialize" else [])
        else:
            example = family[{"expr_size": 11, "const_fold": 32, "simplify_safe": 33,
                              "stable_simplify": 34}[definition.name]]
            arguments, shown = (example,), [show_code(example)]
        result = lib.run(definition.name, arguments, trace=True) if definition.kind not in ("law", "template") else None
        if definition.kind == "law":
            result = kernel.evaluate(definition.body,
                                     dict(zip((name for name, _ in definition.spec.vars), arguments)), lib.scope())
        if definition.kind == "template":
            from .story import specialization_family

            member = lib.get("Specialize_member_1")
            instance = instantiate(definition, {"k": 3}, member.name, lib=lib)
            if (instance.body, instance.spec, instance.depends_on) != (
                    member.body, member.spec, member.depends_on):
                raise ValueError("displayed template member differs from instantiation")
            program = specialization_family(lib, family)[1]
            produced = lib.run(member.name, (program,), trace=True)
            if not isinstance(produced.outcome, Ok):
                raise ValueError(f"template member failed: {produced.outcome!r}")
            result = kernel.Run(Ok(code.quote_from_library(lib, member.name)), 0, 0, None)
        display_name, source = _ascii_source(definition, lib)
        ascii_arguments = arguments
        outcome = result.outcome
        example = {"text": definition.name + "(" + ", ".join(shown) + ")",
                   "inputs": [value_json(arg) for arg in arguments],
                   "outcome": outcome_json(result.outcome), "steps": result.steps,
                   "ascii": ascii_example(display_name, definition.kind, ascii_arguments, outcome)}
        if definition.kind == "template":
            example["text"] = "Specialize[3] -> " + member.name
            example["member"] = {"name": member.name, "result": outcome_json(produced.outcome),
                                 "program": value_json(program), "steps": produced.steps}
            quoted = result.outcome.value
            example["ascii"] = ascii_example(display_name, definition.kind, ascii_arguments, Ok(quoted))
            example["outcome"] = {"kind": "Ok", "code_hash": code.code_hash(quoted),
                                  "value": value_json(quoted)}
        if definition.kind not in ("law", "template") and outside_scope(result.trace, lib):
            example["outside_scope"] = True
        try:
            parsed_source = parse_meta_definition(source)
        except (ValueError, notation.NotationError) as exc:
            raise ValueError(f"{definition.name}: invalid published declaration: {source[:200]}") from exc
        entry = {
            "layer": definition.layer, "kind": definition.kind, "name": display_name,
            "symbol": ("Poly" if definition.name == "poly" else "@pipeline" if definition.name == "pipeline"
                       else "#" + definition.name if definition.kind == "law"
                       else "~" + definition.name if definition.kind == "bridge"
                       else "specialize_fixed[k]" if definition.kind == "template"
                       else definition.name.lower() if definition.name.startswith("Specialize_member_")
                       else definition.name),
            "definition": DESCRIPTIONS.get(definition.name, "Generate a unary result from the recorded specialization program." if definition.name.startswith("generated_") else "Fix the first input to a recorded constant and return a unary program."),
            "depends_on": list(definition.depends_on),
            "body": parsed_source.body if definition.kind == "template"
            else nodes.to_json(definition.body),
            "status": definition.status,
            "evidence": compact_enumerations(definition.evidence.to_dict()) if definition.evidence else None,
            "contract": definition.contract.to_dict() if definition.contract else None,
            "cost": compact_enumerations(definition.cost.to_dict()), "examples": [example], "ascii": source,
            "spec": parsed_source.spec.to_dict(),
        }
        if display_name != definition.name:
            entry["record_name"] = definition.name
        if definition.kind == "bridge":
            entry["interface"] = [list(pair) for pair in definition.spec.interface]
        if definition.name == "unsafe_equivalence":
            changed = lib.run("simplify_unsafe", (counterexample,)).outcome
            if not isinstance(changed, Ok):
                raise ValueError(f"unsafe counterexample did not transform: {changed!r}")
            entry["counterexample"] = {
                "program": show_code(counterexample), "input": 0,
                "before": outcome_json(lib.run("eval", (counterexample, code.lst((0,)))).outcome),
                "after": outcome_json(lib.run("eval", (changed.value, code.lst((0,)))).outcome),
            }
        if definition.kind == "template":
            entry["produces"] = definition.spec.produces
            entry["family_scope"] = compact_enumerations(definition.evidence.scope)
            entry["runtime_spec"] = definition.spec.to_dict()
            entry["spec"] = parsed_source.spec.to_dict()
            entry["source_spec_hash"] = content_hash(entry["spec"])
        story.append(json.loads(json.dumps(entry)))
    return {"schema": "opulse.world_v2_export/1", "world": "code", "version": 1,
            "title": "Programs as Objects", "pitch": "Transform canonical programs; test meaning and cost independently.",
            "decl": lib.world.to_dict(), "layer0": [item.to_dict() for item in lib.world.operations],
            "story": story, "tags": lib.world.extra["tags"], "ladder": LADDER,
            "generated": [lib.generated_ledger.record(digest, lib.world.world_hash()).to_dict()
                          for digest in lib.generated_hashes] + [record.to_dict() for record in lib.generator_records],
            "showcase": showcase(lib, family, counterexample)}


def build_export():
    """Build the current site export (atoms-meta 8)."""
    return export()


def serialized():
    return json.dumps(build_export(), sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"


def write():
    DECL.write_text(json.dumps(declaration().to_dict(), indent=2, sort_keys=True,
                               ensure_ascii=True) + "\n", encoding="utf-8")
    DEST.write_text(serialized(), encoding="utf-8")


if __name__ == "__main__":
    write()
