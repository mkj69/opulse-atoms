"""Reproducible builder@1 JSON publication (atoms-meta section 7)."""

import json
from dataclasses import replace
from pathlib import Path

from opulse.atoms import kernel, nodes, notation
from opulse.atoms.spec import content_hash
from opulse.atoms.values import Card, Ok
from opulse.meta import code as C
from opulse.meta import notation as meta_notation
from opulse.meta.builder import world_value as V
from opulse.meta.builder.instantiate import instantiate
from opulse.meta.export_util import (
    ascii_definition,
    ascii_example,
    compact_enumerations,
    outcome_json,
    outside_scope,
    parse_meta_definition,
    value_json,
)
from opulse.meta.worlds.builder import family, showcase, story, world

ROOT = Path(__file__).resolve().parents[5]
DECL = ROOT / "worlds/decl/meta/builder@1.json"
DATA = ROOT / "docs/assets/data/meta/builder.json"


DEFINITIONS = {
    "base_z5": "Construct the five-element z5 world with arithmetic tables and an identity probe.",
    "add5_assoc": "Verify associativity of the built Z5 addition table on all 125 triples.",
    "mul5_distributes": "Verify distributivity of the built Z5 tables on all 125 triples.",
    "embed_z5": "Embed each Z5 residue as a zero-bit pair and check addition across two worlds.",
    "hide": "Remove selected learner probes while retaining the full-state verdict.",
    "repair": "Complete a unary table by recording the missing input as an explicit error.",
    "product": "Construct a product world by pairing component values and operations.",
    "count_row": "Advance a row counter by one when a table row is visited.",
    "for_each_tuple": "Fold a supplied function across every row in a selected table.",
    "table_total": "Count table rows using the reusable tuple-fold combinator.",
    "product_table_total": "Count the first operation's rows in a newly constructed product world.",
    "audit_product": "Compare a product table's row count with the counts of its two component tables.",
    "same_verdict": "Check whether hiding selected probes preserves the well-formedness verdict.",
    "audit_hidden_product": "Combine product cardinality auditing with a hidden-probe verdict check.",
}


def _ascii_example(name, kind, inputs, outcome):
    try:
        return ascii_example(name, kind, inputs, outcome)
    except (ValueError, TypeError):
        replacements = {}

        def prepare(value):
            if isinstance(value, Card) and value.sort not in ("code", "vn", "world"):
                source = (f"bool.{value.tag}()" if value.sort == "bool" and not value.fields
                          else meta_notation._value(value))
            elif isinstance(value, kernel.FnRef) and kind != "combinator":
                source = "&" + value.name
            else:
                return value
            marker = f"__builder_value_{len(replacements)}__"
            replacements[notation.print_value(marker)] = source
            return marker

        rendered = ascii_example(name, kind, tuple(prepare(arg) for arg in inputs),
                                 Ok(prepare(outcome.value)) if isinstance(outcome, Ok) else outcome)
        for marker, source in replacements.items():
            rendered = rendered.replace(marker, source)
        return rendered


def _ascii_definition(definition, lib):
    source, reason = ascii_definition(definition, lib)
    if source is not None:
        return source
    if definition.kind == "template":
        source = f"template obj {definition.name}[n: int] = refine world canon(make_zn) L{definition.layer}"
        if parse_meta_definition(source).kind != "template":
            raise ValueError(f"cannot print builder template {definition.name}")
        return source
    elif definition.kind == "object" and definition.name.startswith("Zn_member_"):
        printable = replace(definition, spec=replace(definition.spec, body=definition.body, extra={}))
        source, reason = ascii_definition(printable, lib)
    if source is not None:
        return source
    if definition.kind == "object" and definition.name.startswith("Zn_member_"):
        body = meta_notation._expr(C.encode_node(definition.body), exact=True)
        source = f"obj {definition.name} = ({body}) L{definition.layer}"
        if parse_meta_definition(source).body != definition.body:
            raise ValueError(f"cannot print builder object {definition.name}")
        return source
    literals = {}

    def prepare(node):
        if isinstance(node, nodes.Lit) and isinstance(node.value, Card):
            marker = f"__builder_literal_{len(literals)}__"
            literals[marker] = (meta_notation.show_world(node.value) if node.value.sort == "world"
                                else meta_notation._value(node.value))
            return nodes.Lit(marker)
        return node

    body = nodes.map_nodes(definition.body, prepare)
    if definition.kind == "object":
        printable = replace(definition, name="BaseZ5",
                            spec=replace(definition.spec, name="BaseZ5", body=body), body=body)
    elif definition.kind == "bridge":
        spec = definition.spec
        printable = replace(definition, spec=replace(spec, source="Z", target="Pair", map=body),
                            body=body)
    elif definition.kind == "operation":
        spec = definition.spec
        inputs = tuple(replace(edge, sort=edge.sort.title(), name=f"arg{index}")
                       for index, edge in enumerate(spec.inputs))
        output = replace(spec.output, sort=spec.output.sort.title())
        printable = replace(definition, spec=replace(spec, role="transform", rule="ASCII definition",
                            inputs=inputs, output=output, errors=(), impl=None, cost=1,
                            reads_params=(), extra={}), body=body)
    else:
        raise ValueError(f"cannot print builder definition {definition.name}: {reason}")
    source, reason = ascii_definition(printable, lib)
    if source is None:
        raise ValueError(f"cannot print builder definition {definition.name}: {reason}")
    for marker, value in literals.items():
        source = source.replace(notation.print_value(marker), value)
    if definition.kind == "object":
        source = source.replace("obj BaseZ5 =", "obj base_z5 =", 1)
    if definition.kind == "bridge":
        spec = definition.spec
        source = source.replace("bridge ~embed_z5: Z -> Pair", f"bridge ~embed_z5: {spec.source} -> {spec.target}", 1)
    if definition.kind == "operation":
        spec = definition.spec
        for edge in (*spec.inputs, spec.output):
            source = source.replace(": " + edge.sort.title(), ": " + edge.sort)
        source = source.replace(" -> " + spec.output.sort.title() + " =", " -> " + spec.output.sort + " =", 1)
        if spec.role != "transform":
            source = source.replace(" = ", f" role {spec.role} = ", 1)
    parsed = parse_meta_definition(source)
    if (parsed.kind != definition.kind or parsed.name != definition.name or
            (definition.kind == "operation" and parsed.spec.role != definition.spec.role) or
            parsed.body != nodes.from_json(nodes.to_json(definition.body))):
        raise ValueError(f"builder declaration does not round-trip: {definition.name}")
    return source


def build_export():
    declaration = world.declaration()
    lib, families = story.creation()
    members = []
    for name, inputs in families.items():
        definition = lib.get(name)
        record = json.loads(json.dumps(definition.to_dict()))
        examples = []
        example_inputs = inputs
        if name == "mul5_distributes":
            witness = (story.z(1), story.z(2), story.z(3))
            example_inputs = [witness, *(args for args in inputs if args != witness)]
        if len(example_inputs) > 32:
            example_inputs = example_inputs[:3]
        for args in example_inputs:
            if definition.kind == "law":
                run = kernel.evaluate(definition.spec.statement,
                                      dict(zip((variable for variable, _ in definition.spec.vars), args)),
                                      lib.scope(), trace=True)
            else:
                run = lib.run(name, args, trace=True)
            example = {"inputs": [value_json(arg) for arg in args],
                       "outcome": outcome_json(run.outcome), "steps": run.steps,
                       "ascii": _ascii_example(name, definition.kind, args, run.outcome)}

            if definition.kind != "law" and outside_scope(run.trace, lib):
                example["outside_scope"] = True
            examples.append(example)
        entry = {"layer": definition.layer, "kind": definition.kind, "name": name,
                        "symbol": f"@{name}" if definition.kind == "combinator"
                        else "BaseZ5" if name == "base_z5"
                        else f"#{name}" if definition.kind == "law"
                        else f"~{name}" if definition.kind == "bridge" else name,
                        "definition": DEFINITIONS[name], "ascii": _ascii_definition(definition, lib),
                        "spec": record["spec"],
                        "depends_on": list(definition.depends_on),
                        "body": record["body"], "status": definition.status,
                        "evidence": compact_enumerations(record["evidence"]), "contract": record["contract"],
                        "cost": compact_enumerations(record["cost"]), "examples": examples,
                        **({"interface": record["spec"]["interface"]}
                           if definition.kind == "bridge" else {})}
        members.append(entry)
    near_miss, witness, failed = story.cancellation_near_miss(lib)
    rejection = {"symbol": "#mul5_cancels", "status": near_miss.status,
                 "evidence": None, "counterexample": {
                     "inputs": [value_json(arg) for arg in witness],
                     "outcome": outcome_json(kernel.evaluate(
                         near_miss.spec.statement,
                         dict(zip((name for name, _ in near_miss.spec.vars), witness)),
                         lib.scope()).outcome),
                     "steps": failed.steps[0]}, "problems": failed.problems}
    template_lib, instances = family.creation()
    template = template_lib.get("Zn")
    template_record = template.to_dict()
    template_source = _ascii_definition(template, template_lib)
    parsed_template = parse_meta_definition(template_source)
    members.append({"layer": template.layer, "kind": "template", "name": "Zn",
                    "symbol": "Zn[n]", "produces": "object",
                    "definition": "Generate a modular world for each size from three through seven.",
                    "ascii": template_source,
                    "source_pattern": parsed_template.spec.pattern,
                    "source_spec_hash": content_hash(parsed_template.spec.to_dict()),
                    "spec": template_record["spec"],
                    "body": parsed_template.body,
                    "depends_on": list(template.depends_on), "status": template.status,
                    "evidence": template_record["evidence"], "contract": template_record["contract"],
                    "cost": template_record["cost"],
                    "family_scope": template.evidence.scope,
                    "examples": [{"inputs": [value_json(3)],
                                  "outcome": outcome_json(template_lib.run(instances[0].name, ()).outcome),
                                  "steps": template_lib.run(instances[0].name, ()).steps,
                                  "ascii": _ascii_example("Zn", "template", (3,),
                                      template_lib.run(instances[0].name, ()).outcome)}]})
    for index, instance in enumerate(instances):
        definition = template_lib.get(instance.name)
        record = definition.to_dict()
        run = template_lib.run(instance.name, (), trace=True)
        members.append({"layer": definition.layer, "kind": "object", "name": instance.name,
                        "symbol": f"Zn{index + 3}", "definition":
                        f"Build modular arithmetic with {index + 3} residues from the checked template.",
                        "ascii": _ascii_definition(definition, template_lib),
                        "spec": record["spec"], "body": record["body"],
                        "depends_on": list(definition.depends_on), "status": definition.status,
                        "evidence": record["evidence"], "contract": record["contract"],
                        "cost": record["cost"], "examples": [{"inputs": [],
                            "outcome": outcome_json(run.outcome), "steps": run.steps,
                            "ascii": _ascii_example(instance.name, "object", (), run.outcome)}]})
    value, generated, ledger, derived = story.promoted_mul5()
    _, entries = instantiate(value)
    scope = kernel.DictScope([entry for entry in entries if isinstance(entry, kernel.Atom)])
    table = kernel.call("mul5", (story.z(3), story.z(2)), scope)
    decoded = C.decode(generated)
    extended = scope.extend((decoded.main,))
    repeated = kernel.call(decoded.main.name, (story.z(3), story.z(2)), extended)
    tower, power_code, power_ledger, powered, power_steps = story.promoted_power5()
    return {"schema": "opulse.world_v2_export/1", "world": "builder", "version": 1,
            "title": "Builder: Worlds That Build Worlds",
            "pitch": "Construct finite worlds as values, audit their tables, and promote code only for the world it was checked against.",
            "decl": declaration.to_dict(),
            "layer0": [{"name": op.name, "rule": op.rule, "cost": op.cost,
                        "impl": op.impl} for op in declaration.operations],
            "story": members, "tags": world.TAGS, "ladder": showcase.LADDER,
            "near_miss": rejection,
            "showcase": showcase.tasks(),
            "derived": {"base_hash": V.world_hash(value), "code_hash": C.code_hash(generated),
                        "scope": derived.scopes(), "table_steps": table.steps,
                        "repeated_add_steps": repeated.steps,
                        "result": outcome_json(repeated.outcome),
                        "evidence_status": ledger.status(C.code_hash(generated), V.world_hash(value)),
                        "power_base_hash": V.world_hash(tower),
                        "power_code_hash": C.code_hash(power_code),
                        "power_scope": powered.scopes(), "power_steps_z3_z2": power_steps[3, 2],
                        "power_evidence_status": power_ledger.status(C.code_hash(power_code),
                                                                       V.world_hash(tower))}}


def write():
    """Write both canonical UTF-8 artifacts; the test compares them byte for byte."""
    DECL.parent.mkdir(parents=True, exist_ok=True)
    DATA.parent.mkdir(parents=True, exist_ok=True)
    DECL.write_text(json.dumps(world.declaration().to_dict(), sort_keys=True, indent=2) + "\n")
    DATA.write_text(json.dumps(build_export(), sort_keys=True, separators=(",", ":")) + "\n")


build = build_export


if __name__ == "__main__":
    write()
