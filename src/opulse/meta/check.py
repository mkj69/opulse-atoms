"""Check meta declarations, site exports and index (atoms-meta section 8).

An ASCII story declaration uses a core obj/op/comb/obs/law/bridge/template
head, with lowercase meta sorts and qualified bridge sorts accepted by the
matching meta declaration parser. An example has one top-level `` = ``:
its left side is the story's constructor, call, sigil call or template
instantiation, and its right side is a value, fail(reason), or Unknown<str>.
Core expressions may contain fully parsed Code<...>, VN<...>, World<...>,
and lowercase meta-card literals; strings are never interpreted as syntax.
Both fields reject non-ASCII and any expression the corresponding parser
cannot consume completely. Strict mode checks recorded inputs and outcomes.
"""

import argparse
import importlib
import json
import re
import subprocess
import sys
from dataclasses import replace
from functools import lru_cache
from pathlib import Path

from opulse.atoms import kernel, nodes, notation
from opulse.atoms.bridges import bridge_defn
from opulse.atoms.library import atoms_digest
from opulse.atoms.spec import Cost, Edge, OperationSpec, content_hash
from opulse.atoms.values import Bottom, Card, Ok, Unknown, boolean, decode, value_equal
from opulse.atoms.world import WorldDecl
from opulse.meta.export_util import (
    parse_meta_definition,
    parse_meta_expr,
    parse_meta_object_call,
    parse_meta_value,
)
from opulse.meta.worlds.index import DECLARATIONS, EXPORTS, ROOT, build_index

_SYMBOLS = {
    "object": r"[A-Z][A-Za-z_0-9]*",
    "operation": r"[a-z][a-z_0-9]*",
    "combinator": r"@[a-z][a-z_0-9]*",
    "observation": r"\?[a-z][a-z_0-9]*",
    "law": r"#[a-z][a-z_0-9]*",
    "bridge": r"~[a-z][a-z_0-9]*",
}


def _valid_symbol(kind, symbol, produces=None):
    if kind == "template":
        return produces in _SYMBOLS and isinstance(symbol, str) and re.fullmatch(
            _SYMBOLS[produces] + r"(?:\[[A-Za-z_][A-Za-z_0-9]*(?:,\s*[A-Za-z_][A-Za-z_0-9]*)*\])?",
            symbol, re.ASCII) is not None
    return isinstance(symbol, str) and kind in _SYMBOLS and re.fullmatch(
        _SYMBOLS[kind], symbol, re.ASCII) is not None


def _read(path, problems):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError, RecursionError) as exc:
        problems.append(f"{path}: {exc}")
        return None


def _split_example(source):
    stack = []
    quoted = False
    escaped = False
    closes = {"(": ")", "[": "]", "{": "}", "<": ">"}
    for position, char in enumerate(source):
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif not stack and source.startswith(" = ", position):
            return source[:position], source[position + 3:]
        elif char in closes:
            stack.append(closes[char])
        elif stack and char == stack[-1] and not (char == ">" and source[position - 1] == "-"):
            stack.pop()
    raise ValueError("expected top-level ' = ' between call and outcome")


def _same_outcome(left, right):
    if isinstance(left, Ok) and isinstance(right, Ok):
        first = boolean(left.value) if type(left.value) is bool else left.value
        second = boolean(right.value) if type(right.value) is bool else right.value
        return value_equal(first, second)
    return type(left) is type(right) and left == right


@lru_cache(maxsize=4)
def _declared_world_hash(name):
    if name not in ("code", "compiler", "builder", "vonneumann"):
        return None
    module = importlib.import_module(f"opulse.meta.worlds.{name}.world")
    return module.declaration().world_hash()


@lru_cache(maxsize=1)
def _compiler_world_hashes():
    """Resolve the base, learner and bridge declarations (atoms-meta section 5)."""
    from opulse.meta.compiler.learner import world_and_atoms

    learner_world = world_and_atoms()[0]
    extras = []
    for left in range(4):
        for right in range(4):
            if (left, right) in ((0, 0), (1, 3)):
                continue
            for name, sort in ((f"source_at_{left}{right}", "code"),
                               (f"prog_at_{left}{right}", "prog")):
                extras.append(OperationSpec(name, "transform", (Edge(sort),), Edge("int"),
                                            "Read the result channel at fixed byte inputs",
                                            ("unsupported", "overflow"), cost=0))
    bridge_world = replace(learner_world, world="compiler",
                           operations=learner_world.operations + tuple(extras))
    return {_declared_world_hash("compiler"), learner_world.world_hash(), bridge_world.world_hash()}


@lru_cache(maxsize=4)
def _given_atoms(world_name):
    if world_name == "builder":
        from opulse.meta.worlds.builder.hosts import atoms

        return {atom.name: atom for atom in atoms()}
    if world_name == "compiler":
        from opulse.meta.compiler.learner import world_and_atoms
        from opulse.meta.worlds.compiler.world import make_library

        return {**make_library().scope().atoms,
                **{atom.name: atom for atom in world_and_atoms()[1]}}
    if world_name == "vonneumann":
        from opulse.meta.vn.machine import atoms
        from opulse.meta.worlds.vonneumann.world import decrement, equal, positive

        return {atom.name: atom for atom in (*atoms(32), kernel.Atom("eq", 2, equal, cost=0),
                                              kernel.Atom("comb_positive", 1, positive),
                                              kernel.Atom("comb_dec", 1, decrement))}
    from opulse.meta.worlds.code.world import library

    return {atom.name: atom for atom in library().atoms}


@lru_cache(maxsize=4)
def _evidence_libraries(world_name):
    """Rebuild the checked libraries rather than trusting exported commitments (meta 8)."""
    if world_name == "code":
        from opulse.meta.worlds.code.story import build_story

        return (build_story()[0],)
    if world_name == "compiler":
        from opulse.meta.worlds.compiler.story import build_story

        story = build_story()
        return story.library, story.compiler, story.bridge
    if world_name == "vonneumann":
        from opulse.meta.worlds.vonneumann.story import creation_story

        return (creation_story()[0],)
    if world_name == "builder":
        from opulse.meta.worlds.builder.family import creation as family_creation
        from opulse.meta.worlds.builder.story import creation

        return creation()[0], family_creation()[0]
    return ()


def _checked_deps_hash(lib, name, world_name):
    """Replay member dependency state at verification, before template accounting (meta 8)."""
    template = ("Zn" if world_name == "builder" and name.startswith("Zn_member_") else
                "Compiled" if world_name == "compiler" and name == "Compiled_member_0" else None)
    if template is None:
        return lib.deps_hash(name)
    seen = set()

    def collect(current):
        for dependency in lib._dependency_names(lib.get(current)):
            if dependency == name or dependency in seen:
                continue
            seen.add(dependency)
            owner = dependency if dependency in lib.definitions else dependency.split(".", 1)[0]
            if owner in lib.definitions:
                seen.add(owner)
                collect(owner)

    collect(name)
    records = {}
    for dependency in sorted(seen):
        if dependency in lib.definitions:
            definition = lib.get(dependency)
            if dependency == template:
                definition = replace(definition, status="verified", contract=None, cost=Cost())
            records[dependency] = definition.to_dict()
    return content_hash(records)


def _template_body_matches(origin, body):
    """Check a member's no-op origin marker against its template source (meta 8)."""
    source = parse_meta_definition(origin)
    if source.kind != "template" or not isinstance(body, nodes.Let) or not isinstance(body.value, nodes.Call):
        return False
    params = source.spec.params
    arguments = body.value.args
    if len(params) != len(arguments) or any(not isinstance(arg, nodes.Lit) for arg in arguments):
        return False
    expression = source.body
    if expression.startswith("op "):
        expression = parse_meta_definition(expression + " L1").body
    else:
        expression = parse_meta_expr(expression)
    replacements = {param: nodes.Call(arg.value, ()) if kind == "operation" else arg
                    for (param, kind), arg in zip(params, arguments)}
    expected = nodes.map_nodes(expression, lambda part: replacements.get(part.name, part)
                               if isinstance(part, nodes.Var) else part)
    return expected == body.body


TEMPLATE_REF = "_template_ref_"
DEFINITION_SORTS = ("op", "operation", "combinator", "observation", "law", "bridge")


def _template_refs(body):
    """Split core's unused template reference bindings from the executable body (meta 8)."""
    refs = {}
    while (isinstance(body, nodes.Let) and body.name.startswith(TEMPLATE_REF) and
           isinstance(body.value, nodes.Lit) and isinstance(body.value.value, kernel.FnRef)):
        index = body.name[len(TEMPLATE_REF):]
        if not index.isdigit() or int(index) in refs:
            return None, body
        refs[int(index)] = body.value.value.name
        body = body.body
    return refs, body


def _template_reference_matches(origin, body, family=None):
    """Rebuild core's template reference bindings from the source pattern and compare (meta 8)."""
    source = parse_meta_definition(origin)
    refs, actual = _template_refs(body)
    if source.kind != "template" or not refs or 0 not in refs:
        return False
    expression = parse_meta_expr(source.body)
    params = dict(source.spec.params)
    bound = {}

    def matches(pattern, value):
        if isinstance(pattern, nodes.Var) and pattern.name in params:
            allowed = (isinstance(value, nodes.Lit) if params[pattern.name] not in (
                "operation", "op") else isinstance(value, nodes.Call) and not value.args)
            if not allowed or pattern.name in bound and bound[pattern.name] != value:
                return False
            bound[pattern.name] = value
            return True
        if type(pattern) is not type(value):
            return False
        if isinstance(pattern, nodes.Call):
            return (pattern.fn == value.fn and len(pattern.args) == len(value.args) and
                    all(matches(left, right) for left, right in zip(pattern.args, value.args)))
        return pattern == value

    if not matches(expression, actual):
        return False
    definition_params = [name for name, sort in source.spec.params if sort in DEFINITION_SORTS]
    for position, name in enumerate(definition_params, 1):
        if name not in bound and position in refs:
            bound[name] = nodes.Call(refs[position], ())
    if params.keys() != bound.keys():
        return False
    used = nodes.references(actual) | nodes.operation_literals(actual)
    expected = actual
    for index, dependency in enumerate((refs[0], *(bound[name].fn for name in definition_params))):
        if dependency not in used:
            expected = nodes.Let(f"{TEMPLATE_REF}{index}", nodes.Lit(kernel.FnRef(dependency)), expected)
    if expected != body:
        return False
    if family is None:
        return True
    arguments = {name: value.value if isinstance(value, nodes.Lit) else value.fn
                 for name, value in bound.items()}
    return arguments in family


def _example_semantics(definition, inputs, outcome, location, problems, entries, world_name,
                       recorded_spec=None, specs=None, families=None):
    """Unfold operations, laws and bridges to published definitions and atoms (meta 8)."""
    if definition.kind not in ("operation", "law", "bridge"):
        return
    atoms = _given_atoms(world_name)
    names = (tuple(edge.name for edge in definition.spec.inputs) if definition.kind == "operation" else
             tuple(name for name, _sort in definition.spec.vars) if definition.kind == "law" else ("x",))
    if len(names) != len(inputs) or not all(names):
        problems.append(f"{location}: semantic verification unavailable: invalid parameters")
        return
    if definition.kind == "operation" and isinstance(recorded_spec, dict) and "input_names" in recorded_spec:
        original = recorded_spec["input_names"]
        if (not isinstance(original, list) or len(original) != len(names) or
                len(set(original)) != len(names) or any(
                    name != displayed and (notation.is_valid_name("operation", name) or
                                           displayed != f"arg{index}")
                    for index, (name, displayed) in enumerate(zip(original, names)))):
            problems.append(f"{location}: semantic verification unavailable: input names differ")
            return
        names = tuple(original)
    resolved = {}
    bodies = {}
    pending = [definition]
    while pending:
        current = pending.pop()
        if current.name in resolved:
            continue
        body = current.body
        if (isinstance(body, nodes.Let) and body.name.startswith("_template_origin_") and
                isinstance(body.value, nodes.Call) and
                not any(isinstance(part, nodes.Var) and part.name == body.name
                        for part in nodes.walk(body.body))):
            origin = entries.get(body.value.fn)
            if origin is not None and not _template_body_matches(origin, body):
                problems.append(f"{location}: semantic verification unavailable: template origin differs")
                return
            if origin is not None:
                body = body.body
        refs, inner = _template_refs(body)
        if refs is None or refs:
            template = (refs or {}).get(0)
            origin = entries.get(template)
            family = (families or {}).get(template)
            if origin is None or not _template_reference_matches(origin, body, family):
                problems.append(f"{location}: semantic verification unavailable: template reference differs")
                return
            body = inner
        if current.kind == "bridge":
            body = bridge_defn(current.spec).body
        if current.kind == "operation":
            params = tuple(edge.name for edge in current.spec.inputs)
        elif current.kind == "combinator":
            params = current.spec.params
        elif current.kind == "object" and current.spec.form == "constant":
            params = ()
        elif current.kind == "law":
            params = tuple(name for name, _sort in current.spec.vars)
        elif current.kind == "bridge":
            params = ("x",)
        else:
            problems.append(f"{location}: semantic verification unavailable: non-operation {current.name}")
            return
        if current is definition:
            params = names
        elif specs and isinstance(specs.get(current.name), dict):
            original = specs[current.name].get("input_names")
            if (isinstance(original, list) and len(original) == len(params) and
                    all(displayed == name or (displayed == f"arg{index}" and
                        not notation.is_valid_name("operation", name))
                        for index, (name, displayed) in enumerate(zip(original, params)))):
                params = tuple(original)
        resolved[current.name] = kernel.Defn(current.name, params, body, kind=current.kind)
        bodies[current.name] = body
        local_operations = set(current.spec.op_params) if current.kind == "combinator" else set()
        references = (nodes.references(body) | nodes.operation_literals(body) |
                      {value.name for value in inputs if isinstance(value, kernel.FnRef)})
        for reference in sorted(references - local_operations):
            if reference in atoms or reference in resolved:
                continue
            source = entries.get(reference)
            if source is None:
                problems.append(f"{location}: semantic verification unavailable: unresolved {reference}")
                return
            try:
                child = parse_meta_definition(source)
            except (ValueError, notation.NotationError) as exc:
                problems.append(f"{location}: semantic verification unavailable: {exc}")
                return
            pending.append(child)
    scope = kernel.DictScope(atoms, tuple(resolved.values()))
    try:
        result = kernel.evaluate(bodies[definition.name], dict(zip(names, inputs)), scope).outcome
    except (ValueError, TypeError, KeyError, IndexError, AttributeError) as exc:
        problems.append(f"{location}: semantic verification unavailable: {exc}")
        return
    if not _same_outcome(result, outcome):
        problems.append(f"{location}: ascii outcome differs from declaration evaluation")


def _valid_outcome(stored):
    if not isinstance(stored, dict) or stored.get("kind") not in ("Ok", "Bottom", "Unknown"):
        raise ValueError("invalid outcome kind")
    kind = stored["kind"]
    if kind == "Ok":
        if "code_hash" in stored and (not isinstance(stored["code_hash"], str) or
                                      re.fullmatch(r"[0-9a-f]{64}", stored["code_hash"]) is None):
            raise ValueError("invalid code_hash")
        if "value" not in stored and "code_hash" not in stored:
            raise ValueError("missing Ok value")
        if "value" in stored:
            decode(stored["value"])
    elif not isinstance(stored.get("reason" if kind == "Bottom" else "resource"), str):
        raise ValueError("invalid outcome reason")


def _has_domain_commitment(scope):
    if not isinstance(scope, dict):
        return False

    def digest(value):
        return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None

    if any(digest(scope.get(key)) for key in ("domain_hash", "inputs_sha256", "family_hash", "fingerprint")):
        return True
    if any(isinstance(scope.get(key), list) and scope[key] and all(map(digest, scope[key]))
           for key in ("input_hashes", "source_hashes")):
        return True
    if any(isinstance(value, dict) and type(value.get("count")) is int and
           value["count"] > 0 and digest(value.get("sha256")) for value in scope.values()):
        return True
    domain = scope.get("domain")
    if not isinstance(domain, dict):
        return False
    axes = domain.get("product_axes")
    return (isinstance(axes, list) and bool(axes) and all(isinstance(axis, list) and axis for axis in axes) or
            isinstance(domain.get("programs"), list) and bool(domain["programs"]) and
            isinstance(domain.get("arguments"), list) and bool(domain["arguments"]))


def _evidence_problems(item, label, world_name):
    evidence = item.get("evidence")
    problems = []
    if not isinstance(evidence, dict):
        return [f"{label}: verified/promoted requires evidence"]
    routine = world_name == "vonneumann" and item.get("name") in (
        "sum3_loop", "sum3_restored", "source_add", "relocated_add") and "routine_id" in item
    ledger_constant = world_name == "compiler" and item.get("name") in (
        "SourceCode", "CompiledProgram", "LearnerSource", "LearnerProgram")
    if evidence.get("method") not in ("exhaustive", "bounded"):
        problems.append(f"{label}: verified/promoted requires exhaustive or bounded evidence")
    scope = evidence.get("scope")
    if not isinstance(scope, dict) or type(scope.get("size")) is not int or scope["size"] <= 0:
        problems.append(f"{label}: verified/promoted requires scope.size > 0")
    if not _has_domain_commitment(scope):
        problems.append(f"{label}: evidence requires domain fingerprint or enumeration")
    if isinstance(scope, dict) and isinstance(scope.get("input_hashes"), list) and scope["input_hashes"] and (
            type(scope.get("size")) is int and len(scope["input_hashes"]) != scope["size"]):
        problems.append(f"{label}: evidence input_hashes count differs from scope.size")
    try:
        expected_hash = _declared_world_hash(world_name)
        if world_name == "compiler" and item.get("world_hash"):
            expected_hash = item["world_hash"]
            if expected_hash not in _compiler_world_hashes():
                problems.append(f"{label}: unknown declaration world_hash")
    except (ImportError, AttributeError, ValueError, TypeError) as exc:
        expected_hash = None
        problems.append(f"{label}: cannot resolve declaration world hash: {exc}")
    if not isinstance(expected_hash, str) or evidence.get("world_hash") != expected_hash:
        problems.append(f"{label}: evidence world_hash differs from declaration world hash")
    if not isinstance(evidence.get("atoms_hash"), str) or not re.fullmatch(
            r"[0-9a-f]{64}", evidence["atoms_hash"]):
        problems.append(f"{label}: evidence requires atoms_hash")
    for key in ("content_hash", "deps_hash"):
        if not (routine or ledger_constant and key == "deps_hash") and (
                not isinstance(evidence.get(key), str) or
                re.fullmatch(r"[0-9a-f]{64}", evidence[key]) is None):
            problems.append(f"{label}: evidence requires {key}")
    try:
        name = item.get("record_name") or item.get("name")
        if routine:
            from opulse.meta.worlds.vonneumann.story import (
                RELOCATED,
                RESTORE,
                SMALL,
                SUM,
            )
            from opulse.meta.worlds.vonneumann.story import evidence as ledger

            source = {"sum3_loop": SUM, "sum3_restored": RESTORE,
                      "source_add": SMALL, "relocated_add": RELOCATED}[name]
            record = ledger().record(source)
            expected = record[0] if record is not None else None
            if (item.get("routine_id") != ledger().identity(source) or expected is None or
                    evidence != expected.to_dict()):
                problems.append(f"{label}: routine evidence differs from checked routine")
        elif ledger_constant:
            from opulse.meta.worlds.compiler.story import build_story

            story = build_story()
            source_name = {"SourceCode": "source_code", "CompiledProgram": "compiled_program",
                           "LearnerSource": "learner_source", "LearnerProgram": "learner_program"}[name]
            digest = story.ledger.resolve(source_name)
            record = story.ledger.record(digest, story.library.world.world_hash())
            if (record is None or record.evidence[0].to_dict() != evidence or
                    evidence.get("content_hash") != digest or
                    evidence.get("atoms_hash") != atoms_digest(story.library.atoms)):
                problems.append(f"{label}: evidence differs from checked ledger constant")
            if (isinstance(item.get("body"), dict) and
                    item["body"] != nodes.to_json(nodes.Lit(story.constants[source_name]))):
                problems.append(f"{label}: exported body differs from checked ledger constant")
        else:
            if world_name == "compiler":
                name = {"compiled": "Compiled", "compiled_member_0": "Compiled_member_0"}.get(name, name)
            libraries = _evidence_libraries(world_name)
            matches = [lib for lib in libraries if name in lib.definitions and
                       lib.world.world_hash() == evidence.get("world_hash")]
            if len(matches) != 1:
                problems.append(f"{label}: semantic verification unavailable: no matching definition")
            else:
                lib = matches[0]
                checked = lib.get(name).to_dict()
                if isinstance(item.get("body"), dict) and isinstance(checked["body"], dict) and (
                        item["body"] != checked["body"]):
                    problems.append(f"{label}: exported body differs from checked definition")
                source_spec = item.get("runtime_spec", item.get("spec") if world_name == "builder" else None)
                if source_spec is not None and source_spec != checked["spec"]:
                    problems.append(f"{label}: exported spec differs from checked definition")
                commitments = {"content_hash": lib.content_hash(name),
                               "deps_hash": _checked_deps_hash(lib, name, world_name),
                               "atoms_hash": atoms_digest(lib.atoms)}
                for key, actual in commitments.items():
                    if evidence.get(key) != actual:
                        problems.append(f"{label}: evidence {key} differs from checked definition")
    except (ImportError, AttributeError, KeyError, ValueError, TypeError, RuntimeError) as exc:
        problems.append(f"{label}: semantic verification unavailable: evidence: {exc}")
    if not isinstance(evidence.get("checks"), list) or not evidence["checks"]:
        problems.append(f"{label}: evidence requires checks")
    if item.get("status") == "promoted":
        contract = item.get("contract")
        if (not isinstance(contract, dict) or
                not isinstance(contract.get("guarantees"), str) or not contract["guarantees"] or
                any(not isinstance(contract.get(key), list) or
                    any(not isinstance(name, str) for name in contract[key])
                    for key in ("may_change", "keeps"))):
            problems.append(f"{label}: promoted requires contract")
    return problems


def _signature_equal(definition, spec):
    kind = definition.kind
    parsed = definition.spec
    if kind == "operation":
        inputs = spec.get("inputs", ())
        output = spec.get("output", {})
        names = spec.get("extra", {}).get("input_names", ())
        return (parsed.role == spec.get("role", "transform") and len(parsed.inputs) == len(inputs) and
                all((edge.name == (stored.get("name") or (names[index] if index < len(names) else edge.name))
                     and bool(edge.name) and (edge.sort, edge.enter) ==
                     (stored.get("sort"), stored.get("enter", "bottom")))
                    for index, (edge, stored) in enumerate(zip(parsed.inputs, inputs))) and
                (parsed.output.sort, parsed.output.enter) ==
                (output.get("sort"), output.get("enter", "bottom")))
    if kind == "combinator":
        return parsed.params == tuple(spec.get("params", ())) and parsed.op_params == tuple(spec.get("op_params", ()))
    if kind == "observation":
        return parsed.reads == tuple(spec.get("reads", ()))
    if kind == "law":
        return parsed.vars == tuple(tuple(pair) for pair in spec.get("vars", ()))
    if kind == "bridge":
        return ((parsed.source, parsed.target, parsed.interface) ==
                (spec.get("source"), spec.get("target"), tuple(tuple(pair) for pair in spec.get("interface", ()))))
    if kind == "template":
        return parsed.params == tuple(tuple(pair) for pair in spec.get("params", ())) and parsed.produces == spec.get("produces")
    if kind == "object":
        return parsed.form == spec.get("form") and parsed.tags == spec.get("tags")
    return False


def _ascii_problems(exported, path, missing=False):
    problems = []
    if not isinstance(exported, dict):
        return problems
    entries = {notation.stored_name(item["name"]): item["ascii"]
               for item in exported.get("story", []) if isinstance(item, dict) and
               isinstance(item.get("name"), str) and isinstance(item.get("ascii"), str)}
    entries.update({item["record_name"]: item["ascii"]
                    for item in exported.get("story", []) if isinstance(item, dict) and
                    isinstance(item.get("record_name"), str) and isinstance(item.get("ascii"), str)})
    entries.update({item["spec"]["name"]: item["ascii"]
                    for item in exported.get("story", []) if isinstance(item, dict) and
                    item.get("kind") == "template" and isinstance(item.get("spec"), dict) and
                    isinstance(item["spec"].get("name"), str) and isinstance(item.get("ascii"), str)})
    specs = {notation.stored_name(item["name"]): item["spec"]
             for item in exported.get("story", []) if isinstance(item, dict) and
             isinstance(item.get("name"), str) and isinstance(item.get("spec"), dict)}
    families = {item.get("record_name") or item["spec"].get("name") or item["name"]:
                item["family_scope"].get("family")
                for item in exported.get("story", []) if isinstance(item, dict) and
                item.get("kind") == "template" and isinstance(item.get("spec"), dict) and
                isinstance(item.get("family_scope"), dict) and
                isinstance(item["family_scope"].get("family"), list)}
    for index, item in enumerate(exported.get("story", [])):
        if not isinstance(item, dict):
            continue
        kind = item.get("kind")
        label = f"{path}: story[{index}] {item.get('name')}"
        text = item.get("ascii")
        definition = None
        if text is None:
            if missing:
                problems.append(f"{label}: missing ascii")
        elif not isinstance(text, str) or not text.isascii():
            problems.append(f"{label}: ascii must be ASCII text")
        else:
            try:
                definition = parse_meta_definition(text)
                if definition.kind != kind or definition.name != notation.stored_name(item.get("name", "")):
                    problems.append(f"{label}: ascii declaration disagrees with kind or name")
                if item.get("routine_id") is not None:
                    from opulse.meta.vn.asm import assemble
                    from opulse.meta.vn.report import routine_id
                    from opulse.meta.worlds.vonneumann.story import creation_story

                    base = 12 if item["name"] == "relocated_add" else 0
                    routine_bytes = tuple(assemble(item["body"], 32))
                    runner = creation_story()[0].get("run_routine").body
                    expected = nodes.Let("routine_base", nodes.Lit(base), nodes.Let(
                        "routine_bytes", nodes.Lit(bytes(routine_bytes).hex()), runner))
                    if (item["routine_id"] != routine_id(32, base, routine_bytes)
                            or definition.body != expected
                            or item.get("depends_on") != sorted(nodes.references(definition.body))):
                        problems.append(f"{label}: ascii routine bytes/base or dependencies differ")
                expected_body = (bridge_defn(definition.spec).body if definition.kind == "bridge"
                                 else definition.body)
                recorded_body = item.get("body")
                if missing and ((isinstance(recorded_body, dict) and
                                 nodes.to_json(expected_body) != recorded_body) or
                                (kind == "template" and "body" in item and
                                 recorded_body != definition.body)):
                    problems.append(f"{label}: ascii declaration body differs from exported body")
                if (missing and isinstance(item.get("spec"), dict)
                        and not _signature_equal(definition, item["spec"])):
                    problems.append(f"{label}: ascii declaration signature differs from exported spec")
                if (missing and kind == "template" and isinstance(item.get("spec"), dict) and
                        (item.get("source_pattern", definition.spec.pattern) != definition.spec.pattern or
                         item.get("source_spec_hash") != content_hash(definition.spec.to_dict()))):
                    problems.append(f"{label}: ascii template pattern or source hash differs")
            except (notation.NotationError, ValueError, TypeError, KeyError, IndexError,
                    AttributeError, RecursionError) as exc:
                problems.append(f"{label}: invalid ascii declaration: {exc}")
        for example_index, example in enumerate(item.get("examples", [])):
            if not isinstance(example, dict):
                continue
            location = f"{label}: example[{example_index}]"
            source = example.get("ascii")
            if source is None:
                if missing:
                    problems.append(f"{location}: missing ascii")
                continue
            if not isinstance(source, str) or not source.isascii():
                problems.append(f"{location}: ascii must be ASCII text")
                continue
            try:
                call, result = _split_example(source)
                if not result:
                    raise ValueError("empty result")
                name = notation.stored_name(item.get("name", ""))
                if kind == "law":
                    if not call.startswith(f"#{name}("):
                        raise ValueError("invalid law instance")
                    parsed = parse_meta_expr(call[1:], {"kinds": {name: "operation"}})
                elif kind == "template":
                    if not call.startswith(f"{name}[") or not call.endswith("]"):
                        raise ValueError("invalid template instance")
                    parsed = parse_meta_expr(name + "(" + call[len(name) + 1:-1] + ")")
                elif kind == "object":
                    object_args = parse_meta_object_call(call, name)
                    parsed = None
                else:
                    parsed = parse_meta_expr(call, {"kinds": {name: kind}})
                if parsed is not None and getattr(parsed, "fn", None) != name:
                    raise ValueError("instance does not call its story entry")
                if result.startswith("Unknown<"):
                    if not result.endswith(">") or not isinstance(notation.parse_value(result[8:-1]), str):
                        raise ValueError("invalid unknown outcome")
                    outcome = Unknown(notation.parse_value(result[8:-1]))
                else:
                    value = parse_meta_value(result)
                    outcome = value if isinstance(value, Bottom) else Ok(value)
                actual = (object_args if kind == "object" else tuple(
                    argument.value for argument in parsed.args) if hasattr(parsed, "args") and all(
                        isinstance(argument, nodes.Lit) for argument in parsed.args) else None)
                if missing and "inputs" not in example:
                    problems.append(f"{location}: missing recorded inputs")
                if missing and "outcome" not in example:
                    problems.append(f"{location}: missing recorded outcome")
                if missing and "inputs" in example:
                    if not isinstance(example["inputs"], list):
                        raise ValueError("inputs must be an array")
                    recorded = tuple(kernel.FnRef(value["fn"]) if isinstance(value, dict) and "fn" in value
                                     else decode(value) if isinstance(value, dict) else value
                                     for value in example["inputs"])
                    if actual is None or (len(actual) != len(recorded) or
                                               any(not value_equal(left, right) for left, right in zip(actual, recorded))):
                        problems.append(f"{location}: ascii call inputs differ from recorded inputs")
                if missing and "outcome" in example:
                    stored = example["outcome"]
                    _valid_outcome(stored)
                    if stored["kind"] == "Ok" and "code_hash" in stored:
                        from opulse.meta.code import code_hash

                        matches = (isinstance(outcome, Ok) and isinstance(outcome.value, Card) and
                                   outcome.value.sort == "code" and
                                   code_hash(outcome.value) == stored["code_hash"] and
                                   ("value" not in stored or _same_outcome(outcome, Ok(decode(stored["value"])))))
                    else:
                        expected = (Ok(decode(stored["value"])) if stored["kind"] == "Ok" else
                                    Bottom(stored["reason"]) if stored["kind"] == "Bottom" else
                                    Unknown(stored["resource"]))
                        matches = _same_outcome(outcome, expected)
                    if not matches:
                        problems.append(f"{location}: ascii outcome differs from recorded outcome")
                if missing and kind in ("operation", "law", "bridge") and definition is not None:
                    if actual is None:
                        problems.append(f"{location}: semantic verification unavailable: non-literal inputs")
                        continue
                    _example_semantics(definition, actual, outcome, location, problems,
                                       entries, exported.get("world"), item.get("spec"), specs, families)
            except (ValueError, TypeError, KeyError, IndexError, AttributeError,
                    RecursionError, notation.NotationError) as exc:
                problems.append(f"{location}: invalid ascii example: {exc}")
    return problems


def export_problems(exported, path, strict=False):
    """Validate text and promotable evidence without trusting generated index counts."""
    problems = []

    def visit(value, location):
        pending = [(value, location)]
        while pending:
            current, position = pending.pop()
            if isinstance(current, str):
                for offset, char in enumerate(current):
                    if ord(char) > 0x7e:
                        problems.append(f"{path}: {position}[{offset}]: non-ASCII U+{ord(char):04X}")
            elif isinstance(current, dict):
                for key, child in reversed(tuple(current.items())):
                    pending.append((child, f"{position}.{key}"))
                    pending.append((key, f"{position}.key"))
            elif isinstance(current, list):
                pending.extend((child, f"{position}[{index}]")
                               for index, child in reversed(tuple(enumerate(current))))

    visit(exported, "$")
    if not isinstance(exported, dict):
        return problems + [f"{path}: export must be an object"]
    if "world" in exported and not isinstance(exported["world"], str):
        problems.append(f"{path}: world must be a string")
        return problems
    for field in ("story", "showcase"):
        if not isinstance(exported.get(field, []), list):
            problems.append(f"{path}: {field} must be an array")
    if problems and any("must be an array" in problem for problem in problems):
        return problems
    for index, item in enumerate(exported.get("story", [])):
        if not isinstance(item, dict):
            problems.append(f"{path}: story[{index}]: entry must be an object")
            continue
        if not isinstance(item.get("name"), str) or not isinstance(item.get("kind"), str):
            problems.append(f"{path}: story[{index}]: name and kind must be strings")
        if item.get("status") not in ("callable", "verified", "promoted"):
            problems.append(f"{path}: story[{index}]: invalid status")
        if item.get("kind") == "template" and not isinstance(item.get("produces"), str):
            problems.append(f"{path}: story[{index}]: produces must be a string")
        if "spec" in item and not isinstance(item["spec"], dict):
            problems.append(f"{path}: story[{index}]: spec must be an object")
        if not isinstance(item.get("examples", []), list):
            problems.append(f"{path}: story[{index}]: examples must be an array")
        elif any(not isinstance(example, dict) for example in item["examples"]):
            problems.append(f"{path}: story[{index}]: example must be an object")
    if problems and any(message in problem for problem in problems for message in (
            "entry must be an object", "name and kind must be strings", "invalid status",
            "produces must be a string",
            "spec must be an object",
            "examples must be an array", "example must be an object")):
        return problems
    problems.extend(_ascii_problems(exported, path, missing=strict))
    examples_seen = {}
    for index, item in enumerate(exported.get("story", [])):
        if not isinstance(item, dict):
            problems.append(f"{path}: story[{index}]: entry must be an object")
            continue
        definition = item.get("definition")
        kind = item.get("kind")
        label = f"{path}: story[{index}] {item.get('name')}"
        if not _valid_symbol(kind, item.get("symbol"), item.get("produces")):
            problems.append(f"{label}: invalid {kind} symbol {item.get('symbol')!r}")
        if kind == "bridge":
            interface = item.get("interface")
            if (not isinstance(interface, list) or not interface or
                    any(not isinstance(pair, (list, tuple)) or len(pair) != 2 or
                        any(not isinstance(name, str) or not name for name in pair)
                        for pair in interface)):
                problems.append(f"{label}: bridge requires nonempty interface pairs")
            evidence = item.get("evidence")
            checks = evidence.get("checks") if isinstance(evidence, dict) else None
            if not isinstance(checks, (list, tuple)) or "commutes" not in checks:
                problems.append(f"{label}: bridge evidence requires commutes check")
        if kind == "template":
            if item.get("produces") not in _SYMBOLS:
                problems.append(f"{label}: template requires produces kind")
            scope = item.get("family_scope")
            if not isinstance(scope, dict) or not scope:
                problems.append(f"{label}: template requires family_scope")
            evidence = item.get("evidence")
            if isinstance(evidence, dict) and evidence.get("method") == "exhaustive":
                problems.append(f"{label}: template must not claim exhaustive evidence")
        if (not isinstance(definition, str) or not definition.strip()
                or any(marker in definition for marker in ("{", "}", "\n", "Code<", "Call(", "Lit("))):
            problems.append(f"{path}: story[{index}] {item.get('name')}: definition must be plain English")
        examples = item.get("examples")
        if not isinstance(examples, list) or not examples:
            problems.append(f"{path}: story[{index}] {item.get('name')}: examples must be nonempty")
        else:
            for example_index, example in enumerate(examples):
                if not isinstance(example, dict):
                    problems.append(f"{path}: story[{index}] example[{example_index}]: example must be an object")
                    continue
                try:
                    fingerprint = json.dumps({key: value for key, value in example.items() if key != "text"},
                                             sort_keys=True, ensure_ascii=True)
                except (ValueError, TypeError, RecursionError) as exc:
                    problems.append(f"{label}: example[{example_index}]: invalid example: {exc}")
                    continue
                if fingerprint in examples_seen:
                    problems.append(f"{path}: story[{index}] example[{example_index}]: duplicate example of story[{examples_seen[fingerprint]}]")
                examples_seen[fingerprint] = index
        if item.get("status") != "promoted":
            continue
        evidence = item.get("evidence") or {}
        if not isinstance(evidence, dict):
            evidence = {}
        if evidence.get("method") not in ("exhaustive", "bounded"):
            problems.append(f"{path}: story[{index}] {item.get('name')}: promoted requires exhaustive or bounded evidence")
        scope = evidence.get("scope") or {}
        size = scope.get("size") if isinstance(scope, dict) else None
        if type(size) is not int or size <= 0:
            problems.append(f"{path}: story[{index}] {item.get('name')}: promoted requires scope.size > 0")
        if strict:
            problems.extend(_evidence_problems(item, label, exported.get("world")))
    if strict:
        for index, item in enumerate(exported.get("story", [])):
            if isinstance(item, dict) and item.get("status") == "verified":
                problems.extend(_evidence_problems(
                    item, f"{path}: story[{index}] {item.get('name')}", exported.get("world")))
    for index, item in enumerate(exported.get("showcase", [])):
        if (not isinstance(item, dict) or item.get("angle") not in
                ("Compute", "Invert", "Decide", "Describe", "Induce", "Create") or
                not isinstance(item.get("kinds_involved"), list) or not item["kinds_involved"]):
            problems.append(f"{path}: showcase[{index}]: requires angle and kinds_involved")
    return problems


def _coverage_problems(exported, path):
    if not isinstance(exported, dict):
        return []
    story = exported.get("story", [])
    kinds = {item["kind"] for item in story if isinstance(item, dict) and
             isinstance(item.get("kind"), str)} if isinstance(story, list) else set()
    return [f"{path}: story requires at least one {kind}" for kind in ("law", "bridge")
            if kind not in kinds]


def check(root=ROOT, fresh_exports=True, strict=False):
    """Return precise inconsistencies; a clean tree returns an empty list."""
    root = Path(root)
    problems = []
    decl_dir = root / DECLARATIONS
    for path in sorted(decl_dir.glob("*.json")):
        name = path.name.split("@", 1)[0]
        if not (root / EXPORTS / f"{name}.json").is_file():
            problems.append(f"{path}: missing export {name}.json")
        raw = _read(path, problems)
        if raw is None:
            continue
        try:
            parsed = WorldDecl.from_dict(raw)
            if parsed.to_dict() != raw:
                problems.append(f"{path}: declaration round trip differs")
        except (ValueError, KeyError, TypeError, AttributeError, IndexError) as exc:
            problems.append(f"{path}: invalid WorldDecl: {exc}")
            continue
        try:
            module = importlib.import_module(f"opulse.meta.worlds.{name}.world")
            if raw != module.declaration().to_dict():
                problems.append(f"{path}: declaration differs from fresh {name}.world.declaration()")
        except (ImportError, AttributeError, ValueError, TypeError, AssertionError, RuntimeError) as exc:
            problems.append(f"{path}: cannot build declaration: {exc}")

    for path in sorted((root / EXPORTS).glob("*.json")):
        if path.name == "index.json":
            continue
        if not (decl_dir / f"{path.stem}@1.json").is_file():
            problems.append(f"{path}: missing declaration {path.stem}@1.json")
        exported = _read(path, problems)
        if exported is None:
            continue
        problems.extend(export_problems(exported, path, strict=strict))
        if strict:
            problems.extend(_coverage_problems(exported, path))
        if fresh_exports:
            try:
                module = importlib.import_module(f"opulse.meta.worlds.{path.stem}.export")
                if exported != module.build_export():
                    problems.append(f"{path}: export differs from fresh {path.stem}.export.build_export()")
                if path.stem == "builder":
                    command = (sys.executable, "-c", ("import json; "
                               "from opulse.meta.worlds.builder.export import build_export; "
                               "print(json.dumps(build_export(), sort_keys=True))"))
                    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
                                            check=True)
                    if exported != json.loads(result.stdout):
                        problems.append(f"{path}: export differs from fresh subprocess builder build")
            except (ImportError, AttributeError, ValueError, TypeError, AssertionError, RuntimeError,
                    OSError, subprocess.CalledProcessError) as exc:
                problems.append(f"{path}: cannot build export: {exc}")

    index_path = root / EXPORTS / "index.json"
    stored_index = _read(index_path, problems)
    if stored_index is not None:
        try:
            if stored_index != build_index(root):
                problems.append(f"{index_path}: index differs from build_index()")
        except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError) as exc:
            problems.append(f"{index_path}: cannot build index: {exc}")
    return problems


def main():
    parser = argparse.ArgumentParser(description="Check meta declarations, exports and index")
    parser.add_argument("--strict", action="store_true", help="require a law and bridge in each world")
    args = parser.parse_args()
    problems = check(root=ROOT, strict=args.strict)
    if not args.strict:
        for path in sorted((ROOT / EXPORTS).glob("*.json")):
            if path.name == "index.json":
                continue
            exported = _read(path, [])
            for warning in _coverage_problems(exported, path):
                print(f"warning: {warning}")
            for warning in _ascii_problems(exported, path, missing=True):
                if "missing ascii" in warning:
                    print(f"warning: {warning}")
    for problem in problems:
        print(problem)
    if problems:
        raise SystemExit(1)
    print("Meta declarations, exports and index are current.")


if __name__ == "__main__":
    main()
