"""Generator programs and bounded template families (atoms-meta, section 7)."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from opulse.atoms import nodes
from opulse.atoms.library import PipelineError, VerifyRequest
from opulse.atoms.spec import (
    BridgeSpec,
    CombinatorSpec,
    Definition,
    Edge,
    LawSpec,
    ObjectSpec,
    ObservationSpec,
    OperationSpec,
    TemplateSpec,
    content_hash,
)
from opulse.atoms.templates import _encode_nodes, instantiate
from opulse.atoms.templates import cite_template_evidence as core_cite_template_evidence
from opulse.atoms.values import Card, Ok, encode
from opulse.meta.code import (
    CodeError,
    Resolved,
    atom_digest,
    canonicalize,
    code_hash,
    decode,
    decode_node,
    decode_pattern,
    instantiate_code,
    items,
    quote,
    quote_from_library,
)
from opulse.meta.identity import Ledger, ProvenanceRecord, Record


def cite_template_evidence(definition: Definition, library) -> bool:
    """Cite only a member reconstructed from its claimed arguments (section 7)."""
    metadata = definition.spec.extra.get("template", {})
    template = library.definitions.get(metadata.get("name"))
    if template is None or not isinstance(metadata.get("args"), dict):
        return False
    try:
        expected = instantiate(template, metadata["args"], definition.name, lib=library)
    except (ValueError, KeyError, TypeError, AttributeError):
        return False
    return (definition.kind == expected.kind and definition.body == expected.body
            and definition.spec == expected.spec and definition.depends_on == expected.depends_on
            and core_cite_template_evidence(definition, library))


def _fresh_name(library, prefix: str) -> str:
    name = prefix
    index = 1
    while name in library.definitions:
        name = f"{prefix}_{index}"
        index += 1
    return name


def _from_code(library, code: Card, name: str) -> Definition:
    decoded = decode(code)
    if decoded.kind not in ("operation", "combinator", "object", "observation", "template", "law", "bridge"):
        raise ValueError("generator output has no supported definition kind")
    signature = decoded.sig
    body = decoded.main.body
    if decoded.kind == "template":
        pattern, fallback = (decode_pattern(field) for field in code.fields[2].fields)
        params = tuple(tuple(pair.fields) for pair in items(signature.fields[0]))
        return Definition(name, "template", "invented", 1, (),
                          TemplateSpec(name, params, signature.fields[1], _encode_nodes(pattern)), fallback)
    if decoded.kind == "operation":
        inputs = tuple(Edge(*edge.fields) for edge in items(signature.fields[0]))
        output = Edge(*signature.fields[1].fields)
        spec = OperationSpec(name, "transform", inputs, output, f"generated {name}",
                             extra={"input_names": list(decoded.main.params)})
    elif decoded.kind == "combinator":
        params = decoded.main.params
        operation_params = tuple(params[position] for position in items(signature.fields[1]))
        spec = CombinatorSpec(name, params, operation_params, body)
    elif decoded.kind == "observation":
        spec = ObservationSpec(name, tuple(items(signature.fields[0])), body)
    elif decoded.kind == "law":
        spec = LawSpec(name, tuple(tuple(pair.fields) for pair in items(signature.fields[0])), body)
    elif decoded.kind == "bridge":
        domain = signature.fields[3]
        spec = BridgeSpec(name, signature.fields[0], signature.fields[1],
                          decode_node(code.fields[2]),
                          decode_node(domain.fields[0]) if domain.tag == "some" else None,
                          tuple(tuple(pair.fields) for pair in items(signature.fields[2])))
    else:
        spec = ObjectSpec(name, "constant", body=body)

    resolved = {}
    for dependency in decoded.deps:
        digest = dependency.name[1:]
        match = None
        for candidate in library.definitions.values():
            if candidate.origin != "invented" or candidate.kind not in (
                    "operation", "combinator", "object", "observation", "law", "bridge"):
                continue
            try:
                if code_hash(quote_from_library(library, candidate.name)) == digest:
                    match = candidate.name
                    break
            except CodeError:
                continue
        if match is None:
            raise ValueError(f"missing generator output dependency: {digest}")
        resolved[dependency.name] = match
    body = nodes.map_nodes(body, lambda node: nodes.Call(resolved[node.fn], node.args)
                           if isinstance(node, nodes.Call) and node.fn in resolved else node) if resolved else body
    if decoded.kind == "combinator":
        spec = CombinatorSpec(name, spec.params, spec.op_params, body)
    if decoded.kind == "object":
        spec = ObjectSpec(name, "constant", body=body)
    if decoded.kind == "observation":
        spec = ObservationSpec(name, spec.reads, body)
    if decoded.kind == "law":
        spec = LawSpec(name, spec.vars, body)
    if decoded.kind == "bridge":
        def restore_bridge(node):
            if isinstance(node, nodes.Var) and node.name == "x0":
                return nodes.Var("x")
            if isinstance(node, nodes.Call) and node.fn in resolved:
                return nodes.Call(resolved[node.fn], node.args)
            return node

        spec = BridgeSpec(name, spec.source, spec.target, nodes.map_nodes(spec.map, restore_bridge),
                          nodes.map_nodes(spec.domain, restore_bridge) if spec.domain is not None else None,
                          spec.interface)
        body = nodes.map_nodes(body, restore_bridge)
    dependencies = tuple(sorted(nodes.references(body) | nodes.operation_literals(body)))
    layer = 1 + max((library.get(dep).layer for dep in dependencies if dep in library.definitions), default=0)
    return Definition(name, decoded.kind, "invented", layer, dependencies, spec, body)


def _with_template_origin(library, code: Card, name: str) -> Definition:
    """Reconstruct a direct output from its embedded template before storing it (section 7)."""
    origin = next((dep for dep in items(code.fields[4]) if dep.sort == "origin"), None)
    if origin is None:
        return _from_code(library, code, name)
    template_code, arguments = origin.fields
    for template in library.definitions.values():
        if template.kind == "template" and quote_from_library(library, template.name) == template_code:
            params = tuple(pair[0] for pair in template.spec.params)
            values = tuple(decode_pattern(arg) for arg in items(arguments))
            if len(params) != len(values):
                break
            definition = instantiate(template, dict(zip(params, values)), name, lib=library)
            world_ops = {operation.name: operation for operation in library.world.operations}
            digests = {atom.name: atom_digest(world_ops[atom.name]) for atom in library.atoms
                       if atom.name in world_ops}
            def resolve(dependency):
                candidate = library.definitions.get(dependency)
                return candidate if candidate is not None and candidate.origin == "invented" else None

            if quote(definition, resolve, digests) != code:
                raise ValueError("template origin does not describe generator output")
            return definition
    raise ValueError("generator output template origin is not stored in the library")


def _template_output(library, request: Card, name: str) -> tuple[Definition, Card | tuple[Definition, Card]]:
    if request.tag != "instantiate" or len(request.fields) != 2:
        raise ValueError("invalid template instantiation request")
    template_name, arguments = request.fields
    template = library.get(template_name)
    if template.kind != "template":
        raise ValueError("generator template requests require a template")
    values = items(arguments)
    if len(values) != len(template.spec.params):
        raise ValueError("template argument count differs")
    args = {param: value for (param, _), value in zip(template.spec.params, values)}
    definition = instantiate(template, args, name, lib=library)
    world_ops = {operation.name: operation for operation in library.world.operations}
    digests = {atom.name: atom_digest(world_ops[atom.name]) for atom in library.atoms if atom.name in world_ops}
    def resolve(dependency: str) -> Resolved | None:
        candidate = library.definitions.get(dependency)
        if candidate is not None and candidate.origin == "invented":
            return Resolved(code=quote_from_library(library, dependency))
        if dependency in digests:
            return Resolved(digest=digests[dependency])
        return None

    code = instantiate_code(quote_from_library(library, template_name), values, resolve, name=name)
    return definition, code


def run_generator(library, ledger: Ledger, generator_name: str,
                  inputs: Sequence[object]) -> tuple[Record | ProvenanceRecord, ...]:
    """Run an invented code transformer; check outputs without borrowing its evidence (section 7)."""
    generator = library.get(generator_name)
    if generator.origin != "invented" or generator.kind != "operation" or generator.status not in (
            "callable", "verified", "promoted"):
        raise ValueError("generator must be an invented callable operation")
    producer = quote_from_library(library, generator_name)
    produced_by = (code_hash(producer), *(code_hash(value) if isinstance(value, Card) and value.sort == "code"
                                               else content_hash(encode(value)) for value in inputs))
    outcome = library.run(generator_name, tuple(inputs)).outcome
    if not isinstance(outcome, Ok):
        raise PipelineError(f"generator did not return a value: {outcome!r}")
    value = outcome.value
    outputs = items(value) if isinstance(value, Card) and value.sort == "list" else (value,)
    records = []
    for output in outputs:
        if not isinstance(output, Card) or output.sort not in ("code", "generator"):
            raise ValueError("generator output must be code or a template request")
        if output.sort == "generator":
            name = _fresh_name(library, f"generated_{template_name(output)}")
            definition, code = _template_output(library, output, name)
        else:
            code = canonicalize(output)
            world_ops = {operation.name: operation for operation in library.world.operations}
            expected = {atom.name: atom_digest(world_ops[atom.name]) for atom in library.atoms
                        if atom.name in world_ops}
            if any(expected.get(atom.fields[0]) != atom.fields[1] for atom in items(code.fields[3])):
                raise ValueError("generator output uses foreign given atoms")
            digest = code_hash(code)
            name = _fresh_name(library, f"generated_{digest[:12]}")
            definition = _with_template_origin(library, code, name)
        library.write(definition)
        library.check(name)
        sample = tuple(0 for _ in definition.spec.inputs) if definition.kind == "operation" else (
            tuple(0 for _ in definition.spec.vars) if definition.kind == "law" else (
                (0,) if definition.kind in ("bridge", "observation") else ()))
        library.make_callable(name, (sample,))
        world_hash = library.world.world_hash()
        if isinstance(code, tuple):
            produced_definition, provenance = code
            source_spec = produced_definition.spec.to_dict()
            stored_spec = definition.spec.to_dict()
            source_spec.pop("template", None)
            stored_spec.pop("template", None)
            if (source_spec != stored_spec or produced_definition.kind != definition.kind
                    or produced_definition.body != definition.body):
                raise PipelineError("template provenance does not describe the stored definition")
            records.append(ledger.add_provenance(library.get(name), provenance, world_hash, produced_by))
        else:
            if quote_from_library(library, name) != code:
                raise PipelineError("generator output code does not identify the stored definition")
            digest = ledger.add(code, world_hash, name, produced_by)
            records.append(ledger.record(digest, world_hash))
    return tuple(records)


def template_name(request: Card) -> str:
    """Stable display prefix for a template request (section 7)."""
    return content_hash(encode(request))[:12]


def instantiate_family(library, template_name: str, family: Sequence[dict[str, object]],
                       request_builder: Callable[[int, dict[str, object], Definition], VerifyRequest],
                       *, method: str = "bounded") -> tuple[Definition, ...]:
    """Verify a finite family and each member in its own core pipeline (section 19.3)."""
    template = library.get(template_name)
    if template.kind != "template" or not isinstance(template.spec, TemplateSpec):
        raise ValueError("family requires a template")
    family = list(family)
    if not family or method not in ("bounded", "sampled"):
        raise ValueError("family requires members and bounded or sampled evidence")
    requests = [request_builder(index, args, instantiate(template, args, f"{template_name}_member_{index}", lib=library))
                for index, args in enumerate(family)]
    if method == "bounded" and any(request.method not in ("bounded", "exhaustive") for request in requests):
        method = "sampled"
    if template.status == "written":
        library.check(template_name)
    if library.get(template_name).status == "checked":
        library.make_callable(template_name, ((),))
    if library.get(template_name).status != "callable":
        raise PipelineError("template must be callable before family verification")
    family_members = [{"args": args, "size": len(member_request.domain),
                       "domain_hash": content_hash([[encode(value) for value in inputs]
                                                    for inputs in member_request.domain])}
                      for args, member_request in zip(family, requests)]
    request = VerifyRequest(method, tuple(tuple(args[param] for param, _ in template.spec.params)
                                          for args in family),
                            {"domain": f"bounded family of {len(family)}", "size": len(family),
                             "family": family, "family_count": len(family),
                             "family_members": family_members, "family_hash": content_hash(family_members)},
                            seed=0 if method == "sampled" else None,
                            extra={"family": family, "member_requests": requests})
    library.verify(template_name, request)
    members = []
    for index, (args, member_request) in enumerate(zip(family, requests)):
        member = instantiate(library.get(template_name), args,
                             _fresh_name(library, f"{template_name}_member_{index}"), lib=library)
        library.write(member)
        library.check(member.name)
        library.make_callable(member.name, member_request.domain)
        library.verify(member.name, member_request)
        members.append(library.get(member.name))
    return tuple(members)
