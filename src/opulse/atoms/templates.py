"""Definition templates (docs/spec/atoms-v2.md, section 18; common brief, templates).

The pattern is a produced spec's ``to_dict`` mapping; optional ``definition_body``
holds the produced kernel body, otherwise body-bearing specs use their own body.
Whole ``$param`` strings in ``Lit`` become values, in ``Var`` and ``Call`` names;
other strings interpolate as text. JSON nodes follow the same convention. Template
provenance lives in the produced spec's ``extra`` because Definition has no extra.
"""

from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import fields, is_dataclass, replace

from opulse.atoms import KINDS, nodes
from opulse.atoms.library import VerifyResult, atoms_digest
from opulse.atoms.spec import (
    BridgeSpec,
    CombinatorSpec,
    Definition,
    LawSpec,
    ObjectSpec,
    ObservationSpec,
    OperationSpec,
    TemplateSpec,
    content_hash,
)
from opulse.atoms.values import Card, encode

_PLACEHOLDER = re.compile(r"\$([A-Za-z_][A-Za-z_0-9]*)")
_SPECS = {"object": ObjectSpec, "operation": OperationSpec, "combinator": CombinatorSpec,
          "observation": ObservationSpec, "law": LawSpec, "bridge": BridgeSpec}


def _name(value):
    if isinstance(value, Definition):
        return value.name
    if isinstance(value, (str, int, bool)):
        return value
    raise ValueError(f"name parameter needs a definition or string, got {value!r}")


def _argument(value):
    if isinstance(value, Definition):
        return value.name
    if isinstance(value, Card):
        return encode(value)
    if isinstance(value, (str, int, bool)):
        return value
    raise ValueError(f"template argument is not serializable: {value!r}")


def _replace(value, args):
    if isinstance(value, nodes.Lit) and isinstance(value.value, str):
        match = _PLACEHOLDER.fullmatch(value.value)
        if match:
            argument = args[match.group(1)]
            return nodes.Lit(argument.name if isinstance(argument, Definition) else argument)
    if isinstance(value, (nodes.Var, nodes.Call)) and _PLACEHOLDER.search(value.name if isinstance(value, nodes.Var) else value.fn):
        referenced = _PLACEHOLDER.findall(value.name if isinstance(value, nodes.Var) else value.fn)
        if any(not isinstance(args[param], (str, Definition)) for param in referenced):
            raise ValueError("Var and Call placeholders require definition names")
    if is_dataclass(value) and type(value).__module__ == nodes.__name__:
        return type(value)(**{field.name: _replace(getattr(value, field.name), args) for field in fields(value)})
    if isinstance(value, str):
        return _PLACEHOLDER.sub(lambda match: str(_name(args[match.group(1)])), value)
    if isinstance(value, dict):
        if "node" in value:
            return _replace(nodes.from_json(value), args)
        return {key: _replace(item, args) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return type(value)(_replace(item, args) for item in value)
    return value


def instantiate(template_defn: Definition, args: dict[str, object], name: str,
                *, lib=None) -> Definition:
    """Produce a written definition; pass ``lib`` to resolve string-valued definitions."""
    if template_defn.kind != "template" or not isinstance(template_defn.spec, TemplateSpec):
        raise ValueError("instantiate requires a template definition")
    params = {param for param, _ in template_defn.spec.params}
    if set(args) != params:
        raise ValueError(f"template arguments must be exactly {sorted(params)}")
    if not name:
        raise ValueError("instantiation needs a name")
    normalized = {param: _argument(args[param]) for param, _ in template_defn.spec.params}
    definition_args = []
    layers = [template_defn.layer]
    for param, kind in template_defn.spec.params:
        value = args[param]
        primitive = {"int": int, "str": str, "bool": bool}.get(kind)
        if primitive is not None and type(value) is not primitive:
            raise ValueError(f"{param} expects {kind}")
        sort_argument = kind == "sort" or kind not in set(KINDS) | {"int", "str", "bool"}
        target = (value if isinstance(value, Definition) else
                  lib.records().get(value) if lib is not None and isinstance(value, str) else None
                  ) if kind in KINDS else None
        if isinstance(value, Definition) and value.kind != kind and kind != "sort":
            raise ValueError(f"{param} expects {kind}, got {value.kind}")
        if sort_argument and not isinstance(value, str):
            raise ValueError(f"{param} expects a sort name")
        if target is not None:
            if kind in KINDS and target.kind != kind or kind == "sort" and target.kind != "object":
                raise ValueError(f"{param} expects {kind}, got {target.kind}")
            definition_args.append(target.name)
            layers.append(target.layer)
        elif kind in KINDS and not isinstance(value, str):
            raise ValueError(f"{param} expects a definition name")
        elif kind in KINDS and lib is not None and not (
            kind == "object" and any(obj.name == value for obj in lib.world.objects)
        ):
            raise ValueError(f"{param}: unknown {kind} definition {value}")
    produced = template_defn.spec.produces
    pattern = deepcopy(template_defn.spec.pattern)
    body_source = {"combinator": "body", "observation": "body", "law": "statement",
                   "bridge": "map"}.get(produced)
    body_pattern = pattern.pop("definition_body", pattern.get(body_source, template_defn.body))
    pattern = _replace(pattern, args)
    if not isinstance(pattern, dict):
        raise TypeError("template pattern must describe a spec")
    pattern["name"] = name
    template_hash = (lib.content_hash(template_defn.name) if lib is not None
                     and template_defn.name in lib.records() else template_defn.content_hash())
    pattern["template"] = {"name": template_defn.name, "args": normalized, "hash": template_hash}
    pattern = _encode_nodes(pattern)
    spec = _SPECS[produced].from_dict(pattern)
    body = _replace(body_pattern, args) if "definition_body" in template_defn.spec.pattern else (
        None if produced == "object" and spec.form in ("refine", "compose") else _replace(body_pattern, args))
    if produced == "bridge" and "definition_body" not in template_defn.spec.pattern:
        from opulse.atoms.bridges import bridge_defn

        body = bridge_defn(spec).body
    if isinstance(body, nodes.NODE_TYPES):
        from opulse.atoms.kernel import FnRef

        if produced not in ("law", "bridge"):
            for index, dependency in enumerate((template_defn.name, *definition_args)):
                if dependency not in nodes.references(body) | nodes.operation_literals(body):
                    body = nodes.Let(f"_template_ref_{index}", nodes.Lit(FnRef(dependency)), body)
        if produced in ("combinator", "observation"):
            spec = replace(spec, body=body)
    dependencies = tuple(dict.fromkeys((template_defn.name, *definition_args,
                                        *(sorted(nodes.references(body)) if isinstance(body, nodes.NODE_TYPES) else ()))))
    if lib is not None:
        layers.extend(lib.records()[dependency].layer for dependency in dependencies
                      if dependency in lib.records())
    return Definition(name, produced, "invented", 1 + max(layers), dependencies, spec, body)


def _encode_nodes(value):
    if isinstance(value, nodes.NODE_TYPES):
        return nodes.to_json(value)
    if isinstance(value, dict):
        return {key: _encode_nodes(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return type(value)(_encode_nodes(item) for item in value)
    return value


def _placeholders(value):
    if isinstance(value, str):
        return set(_PLACEHOLDER.findall(value))
    if isinstance(value, dict):
        return set().union(*(_placeholders(item) for item in value.values())) if value else set()
    if isinstance(value, (tuple, list)):
        return set().union(*(_placeholders(item) for item in value)) if value else set()
    if isinstance(value, nodes.NODE_TYPES):
        return _placeholders(nodes.to_json(value))
    return set()


def check_template(defn: Definition, lib) -> list[str]:
    """Check parameters, references, and one representative instantiation."""
    if defn.kind != "template" or not isinstance(defn.spec, TemplateSpec):
        return ["not a template definition"]
    spec = defn.spec
    params = [param for param, _ in spec.params]
    problems = []
    if len(params) != len(set(params)):
        problems.append("duplicate template parameters")
    undeclared = (_placeholders(spec.pattern) | _placeholders(defn.body)) - set(params)
    if undeclared:
        problems.append(f"undeclared template placeholders: {sorted(undeclared)}")
    sorts = {"int", "str", "bool"} | {obj.name for obj in lib.world.objects}
    sorts.update(item.spec.name for item in lib.records().values() if item.kind == "object")
    for param, kind in spec.params:
        if kind not in set(KINDS) | sorts | {"sort"}:
            problems.append(f"{param}: unknown parameter kind or sort {kind}")
    if problems:
        return problems
    family = spec.extra.get("family", ())
    if family:
        trial = family[0]
    else:
        candidates = {item.kind: item.name for item in lib.records().values()}
        defaults = {"int": 0, "str": "", "bool": False, "sort": "int"}
        trial = {param: defaults.get(kind, candidates.get(kind, kind))
                 for param, kind in spec.params}
    try:
        scratch = deepcopy(lib)
        scratch._definitions.setdefault(defn.name, defn)
        member = instantiate(defn, trial, f"{defn.name}_trial", lib=scratch)
        scratch.write(member)
        scratch.check(member.name)
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        problems.append(f"trial instantiation: {error}")
    return problems


def verify_template(defn: Definition, lib, request) -> VerifyResult:
    """Verify every listed member through an independent scratch library pipeline."""
    family = request.extra.get("family")
    if request.method not in ("bounded", "sampled"):
        return VerifyResult(False, (), ["template evidence must be bounded or sampled"], [])
    if not isinstance(family, list) or not family or request.scope.get("family") != family:
        return VerifyResult(False, (), ["scope must list the exact nonempty family"], [])
    member_requests = request.extra.get("member_requests", ())
    builder = request.extra.get("member_request_builder")
    if len(member_requests) != len(family) and not callable(builder):
        return VerifyResult(False, (), ["each family member needs a verification request"], [])
    problems = check_template(defn, lib)
    steps = []
    for index, args in enumerate(family) if not problems else ():
        try:
            scratch = deepcopy(lib)
            member_name = f"{defn.name}_member_{index}"
            while member_name in scratch.records():
                member_name += "_"
            member = instantiate(defn, args, member_name, lib=scratch)
            scratch.write(member)
            scratch.check(member.name)
            member_request = (member_requests[index] if index < len(member_requests)
                              else builder(index, args, member))
            if member_request.method != request.method:
                raise ValueError("member verification method must match the template method")
            scratch.make_callable(member.name, member_request.domain)
            scratch.verify(member.name, member_request)
            steps.extend(scratch._steps.get(member.name, ()))
        except (ValueError, TypeError, KeyError, AttributeError) as error:
            problems.append(f"family member {index}: {error}")
    return VerifyResult(not problems, ("family",) if not problems else (), problems, steps)


def cite_template_evidence(inst_defn: Definition, lib) -> bool:
    """Permit a citation only for an exact member of a currently evidenced family."""
    metadata = inst_defn.spec.extra.get("template", {})
    template = lib.records().get(metadata.get("name"))
    if (template is None or template.kind != "template" or template.evidence is None
            or template.name not in inst_defn.depends_on):
        return False
    evidence = template.evidence
    if template.status not in ("verified", "promoted") or evidence.method not in ("bounded", "sampled"):
        return False
    if (metadata.get("hash") != lib.content_hash(template.name)
            or evidence.content_hash != lib.content_hash(template.name)
            or evidence.world_hash != lib.world.world_hash()
            or evidence.atoms_hash != atoms_digest(lib.atoms)
            or evidence.deps_hash != lib._deps_hash(template.name)):
        return False
    for args in evidence.scope.get("family", ()):
        if content_hash(args) != content_hash(metadata.get("args")):
            continue
        try:
            expected = instantiate(template, args, inst_defn.name, lib=lib)
        except (ValueError, TypeError, KeyError, AttributeError):
            return False
        return (inst_defn.spec == expected.spec and inst_defn.body == expected.body
                and inst_defn.depends_on == expected.depends_on)
    return False
