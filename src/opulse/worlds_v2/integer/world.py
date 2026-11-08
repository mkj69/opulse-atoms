"""Locked declaration and layer-zero host registration."""
import importlib
import json
from dataclasses import replace
from pathlib import Path

from opulse.atoms import kernel, nodes
from opulse.atoms.library import Library, PipelineError
from opulse.atoms.spec import Evidence
from opulse.atoms.world import WorldDecl
from opulse.worlds_v2.export_util import bound_evidence

DECL_PATH = Path(__file__).resolve().parents[4] / "worlds/decl/v2/integer@2.json"


def decl() -> WorldDecl:
    return WorldDecl.from_dict(json.loads(DECL_PATH.read_text(encoding="utf-8")))


def atoms() -> list[kernel.Atom]:
    source = decl()
    result = []
    for operation in source.operations:
        module_name, attribute = operation.impl["host"].split(":")
        implementation = getattr(importlib.import_module(module_name), attribute)
        result.append(kernel.Atom(operation.name, len(operation.inputs), implementation, operation.cost,
                                  strict=operation.strict))
    for probe in source.observation["probes"]:
        module_name, attribute = probe["impl"]["host"].split(":")
        result.append(kernel.Atom(probe["name"], 1, getattr(importlib.import_module(module_name), attribute),
                                  kind="observation"))
    return result


def new_library() -> Library:
    source = decl()
    primitives = atoms()
    return IntegerLibrary(source, primitives)


class IntegerLibrary(Library):
    def write(self, definition):
        if definition.kind == "object" and definition.spec.extra.get("template"):
            references = set(definition.depends_on)
            for expression in (definition.spec.valid, definition.spec.canon):
                if isinstance(expression, nodes.NODE_TYPES):
                    references.update(nodes.references(expression))
                    references.update(nodes.operation_literals(expression))
            definition = replace(definition, depends_on=tuple(sorted(references)))
        return super().write(definition)

    def verify(self, name, request):
        definition = self.get(name)
        if definition.kind != "observation":
            return super().verify(name, request)
        if definition.status != "callable" or request.scope.get("size") != len(request.domain):
            raise PipelineError("local verifier requires callable status and an exact finite scope")
        from opulse.worlds_v2.integer.story import verify_generic

        result = verify_generic(definition, self, request)
        if not result.ok:
            raise PipelineError(result.problems)
        self._steps[name] = result.steps
        evidence = Evidence(request.method, dict(request.scope), request.seed, result.checks,
                            self.world.world_hash(), self._deps_hash(name))
        self._definitions[name] = replace(definition, evidence=bound_evidence(self, name, evidence, request.domain))
        return self._advance(name, "verified")

    def _params(self, definition):
        if definition.kind == "observation" and definition.origin == "invented":
            return definition.spec.reads
        return super()._params(definition)
