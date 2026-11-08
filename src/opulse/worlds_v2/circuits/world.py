"""Locked layer-zero world and its host atoms."""

import json
from dataclasses import replace
from functools import lru_cache
from pathlib import Path

from opulse.atoms import kernel, nodes, values
from opulse.atoms.check import check_definition
from opulse.atoms.kernel import Atom
from opulse.atoms.library import Library, PipelineError
from opulse.atoms.objects import check_object, object_atoms
from opulse.atoms.world import WorldDecl
from opulse.worlds_v2.circuits import hosts

DECL_PATH = Path(__file__).resolve().parents[4] / "worlds/decl/v2/circuits@1.json"
JUDGE_ONLY = frozenset(("dag_gates", "dag_outputs", "eval_bits", "xor_value",
                        "adder_value", "mult_value"))


def decl() -> WorldDecl:
    return WorldDecl.from_dict(json.loads(DECL_PATH.read_text(encoding="utf-8")))


def atoms() -> list[Atom]:
    return [Atom(op.name, len(op.inputs), getattr(hosts, op.impl["host"].split(":")[1]),
                 cost=op.cost, kind="observation" if op.name == "out_pin" else "operation",
                 strict=op.strict) for op in decl().operations]


def new_library() -> Library:
    class CircuitLibrary(Library):
        def __init__(self, world, given_atoms):
            super().__init__(world, given_atoms)
            self._verification_definitions = None
            self._stable_world = None
            self._inside_run = False
            self._valid_bases = lru_cache(maxsize=4096)(self._check_refinement)

        def _check_refinement(self, name, base):
            try:
                outcome = kernel.evaluate(self.get(name).spec.valid, {"x": base}, super().scope(),
                                          dialect=self.dialect).outcome
                return isinstance(outcome, values.Ok) and values.truth(outcome.value)
            except (TypeError, ValueError, RecursionError):
                return False

        def scope(self):
            scope = super().scope()
            definitions = self.definitions
            refinements = {name for name in ("Xor", "Adder8")
                           if name in definitions and definitions[name].status in
                           ("callable", "verified", "promoted")}

            def valid(value):
                if isinstance(value, values.Card):
                    if value.sort in ("Xor", "Adder8"):
                        if (value.sort not in refinements or value.tag != "val"
                                or len(value.fields) != 1):
                            return False
                        return valid_base(value.sort, value.fields[0])
                    return all(valid(field) for field in value.fields)
                if isinstance(value, (tuple, list)):
                    return all(valid(item) for item in value)
                return True

            def valid_base(name, base):
                if hosts.deep_inspect(base) is not None:
                    return False
                try:
                    return self._valid_bases(name, base)
                except (TypeError, RecursionError):
                    return False

            def guard(atom):
                def guarded(*args):
                    if atom.name.endswith(".base") and not all(valid(arg) for arg in args):
                        return values.Bottom("invalid")
                    for name in refinements:
                        if atom.name == f"{name}._pack" and not valid_base(name, args[0]):
                            return values.Bottom("invalid")
                    return atom.fn(*args)

                return replace(atom, fn=guarded)

            guarded_names = {
                f"{sort}.{suffix}" for sort in refinements for suffix in ("base", "_pack")}
            scope = kernel.DictScope({name: guard(atom) if name in guarded_names
                else atom for name, atom in scope.atoms.items()},
                                     scope.defns, scope.fast_paths)
            if getattr(self, "agent", "learner") == "judge" or self._inside_run:
                return scope

            def checked_base(sort):
                def unwrap(value):
                    if (not isinstance(value, values.Card) or value.sort != sort or
                            value.tag != "val" or len(value.fields) != 1 or
                            not valid_base(sort, value.fields[0])):
                        return values.Bottom("invalid")
                    return value.fields[0]

                return kernel.Atom(f"{sort}.base", 1, unwrap, kind="object")

            atoms = {name: atom for name, atom in scope.atoms.items() if name not in JUDGE_ONLY}
            atoms.update((f"{sort}.base", checked_base(sort)) for sort in refinements)
            return kernel.DictScope(atoms,
                                    {name: definition for name, definition in scope.defns.items()
                                     if name not in JUDGE_ONLY and name not in atoms}, scope.fast_paths)

        @property
        def definitions(self):
            if self._verification_definitions is not None:
                return self._verification_definitions
            return super().definitions

        def _sync_world(self):
            if self._world is not self._stable_world:
                super()._sync_world()

        def verify(self, name, request):
            self._verification_definitions = self._definitions
            inside_run = self._inside_run
            self._inside_run = True
            try:
                verified = super().verify(name, request)
                if verified.kind == "combinator" and "fixed_ops" not in request.scope:
                    evidence = replace(verified.evidence,
                                       scope={**verified.evidence.scope, "fixed_ops": []})
                    self._definitions[name] = replace(verified, evidence=evidence)
                    return self.get(name)
                return verified
            finally:
                self._verification_definitions = None
                self._inside_run = inside_run

        def run(self, name, args, fuel=None, trace=False):
            if getattr(self, "agent", "learner") != "judge" and name in JUDGE_ONLY:
                raise PipelineError(f"judge-only circuit operation: {name}")
            def invented_invalid(value):
                if isinstance(value, values.Card):
                    return (value.sort in ("Xor", "Adder8") and
                            (value.tag != "val" or len(value.fields) != 1 or
                             hosts.deep_inspect(value.fields[0]) is not None or
                             not self._valid_bases(value.sort, value.fields[0]))) or any(
                                 invented_invalid(item) for item in value.fields)
                if isinstance(value, (tuple, list)):
                    return any(invented_invalid(item) for item in value)
                return False

            if any(invented_invalid(arg) for arg in args):
                return kernel.call(name, args, kernel.DictScope(
                    (kernel.Atom(name, len(args), lambda *ignored: values.Bottom("invalid")),)),
                    trace=trace)
            definitions = self._verification_definitions
            inside_run = self._inside_run
            self._verification_definitions = self._definitions
            self._inside_run = True
            try:
                return super().run(name, args, fuel=fuel, trace=trace)
            finally:
                self._verification_definitions = definitions
                self._inside_run = inside_run

        def make_callable(self, name, sample):
            inside_run = self._inside_run
            self._inside_run = True
            try:
                return super().make_callable(name, sample)
            finally:
                self._inside_run = inside_run

        def _params(self, definition):
            if definition.kind == "law" and definition.origin == "invented":
                return tuple(name for name, _ in definition.spec.vars)
            if definition.kind == "observation" and definition.origin == "invented":
                return {"truth_table": ("circuit",), "first_diff": ("left", "right")}.get(
                    definition.name, ())
            return super()._params(definition)

        def check(self, name):
            inside_run = self._inside_run
            self._inside_run = True
            try:
                return self._check_circuit(name)
            finally:
                self._inside_run = inside_run

        def _check_circuit(self, name):
            definition = self.get(name)
            generated = {item.name: item for candidate in self.definitions.values()
                         if candidate.kind == "object" and candidate.origin == "invented"
                         for item in object_atoms(candidate.spec, self)}
            if definition.kind != "object" and (definition.body is None or not any(
                    reference in generated for reference in nodes.references(definition.body))):
                return super().check(name)
            problems = check_definition(definition, self.world,
                                        lambda reference: self.definitions.get(reference) or generated.get(reference))
            if definition.kind == "object":
                problems += [problem for problem in check_object(definition, self)
                             if not problem.startswith("layer must be ")]
            if problems:
                raise PipelineError(problems)
            return self._advance(name, "checked")

    return CircuitLibrary(decl(), atoms())
