"""Shared code sort, operations, and metered library (atoms-meta sections 2.1-2.3)."""

import hashlib
import json
import re
from copy import deepcopy
from dataclasses import replace

from opulse.atoms import kernel
from opulse.atoms.library import Library
from opulse.atoms.spec import Edge, ObjectSpec, OperationSpec
from opulse.atoms.values import Bottom, encode
from opulse.meta import cards, code, engine
from opulse.meta.export_util import host_rule, input_hash


def code_object():
    return ObjectSpec("code", "compose", tags={"def": [["kind", "str"], ["sig", "sig"],
                                                     ["body", "any"], ["atoms", "list"],
                                                     ["deps", "list"]]},
                      canon=host_rule(code.canonicalize), canon_cost="free")


def signature_objects():
    """Card shapes shared by code-building worlds (atoms-meta 2.1)."""
    shapes = {
        "sig": {"op": "inputs:list output:edge", "comb": "arity:int op_params:list",
                "obs": "reads:list", "const": "", "law": "vars:list",
                "bridge": "source:str target:str interface:list domain:opt",
                "template": "params:list produces:str"},
        "var": {"var": "name:str sort:str"},
        "pair": {"pair": "source:str target:str"},
        "param": {"param": "name:str kind_or_sort:str"},
        "pattern": {"template": "pattern:pattern fallback:pattern", "node": "expr:expr",
                    "map": "entries:list", "entry": "key:str value:pattern",
                    "list": "items:list", "tuple": "items:list", "value": "value:any",
                    "bool": "value:bool", "bottom": "reason:str", "none": "",
                    "definition": "name:str kind:str content_hash:str"},
        "origin": {"template": "template_code:code args:list"},
    }
    return tuple(ObjectSpec(sort, "compose", tags={tag: [part.split(":") for part in fields.split()]
                                                    for tag, fields in variants.items()})
                 for sort, variants in shapes.items())


def code_hash(value):
    try:
        return code.code_hash(value)
    except (code.CodeError, TypeError):
        return Bottom("invalid")


def normalize_card(value):
    if isinstance(value, Bottom) or value.sort != "code":
        return value
    try:
        return code.canonicalize(value)
    except (code.CodeError, ValueError, TypeError, AttributeError, KeyError, IndexError):
        return Bottom("invalid")


def mk(sort, tag, fields):
    return normalize_card(cards.mk(sort, tag, fields))


def with_field(value, index, replacement):
    return normalize_card(cards.with_field(value, index, replacement))


_SPECS = (
    ("code_hash", "code", "str", "Content hash", "invalid", code_hash, 1),
    ("eval", "code list", "any", "Metered evaluation on the shared engine",
     "arity not_callable foreign_code ill_formed", engine.eval_atom, 0),
    ("run", "code list int", "any", "Metered evaluation with an inner step budget",
     "arity not_callable foreign_code ill_formed", engine.run_atom, 0),
)


def operations(host_rules=None):
    host_rules = host_rules or {}
    return tuple(OperationSpec(name, "transform", tuple(Edge(sort) for sort in inputs.split()),
                               Edge(output), rule, tuple(errors.split()),
                               host_rule(host_rules.get(name, fn)), cost)
                 for name, inputs, output, rule, errors, fn, cost in _SPECS)


def atoms(world_atoms, declaration):
    given = tuple(world_atoms)
    digests = {op.name: code.atom_digest(op) for op in declaration.operations}
    opened = declaration.opened_nodes()
    metered = (engine.eval_atom(given, digests, opened), engine.run_atom(given, digests, opened))
    return (kernel.Atom("code_hash", 1, code_hash), *metered)


class MeteredLibrary(Library):
    """Library extension that preserves the meta engine's step and trace accounting."""

    @property
    def definitions(self):
        if getattr(self, "_building_scope", False):
            return self._building_scope
        return deepcopy(super().definitions)

    def _sync_world(self):
        previous = self._world_hash
        super()._sync_world()
        if previous != self._world_hash:
            given = tuple(atom for atom in self.atoms if atom.name not in ("eval", "run"))
            self._rebind_metered(given)
            self._metered_atoms_key = tuple(id(atom) for atom in given)

    def _rebind_metered(self, given):
        metered = atoms(given, self._world)
        by_name = {atom.name: atom for atom in metered}
        self.atoms = tuple(by_name.get(atom.name, atom) if atom.name in ("eval", "run") else atom
                           for atom in self.atoms)
        self._scope_key = None

    def get(self, name):
        return deepcopy(super().get(name))

    def write(self, defn, replace=False):
        return deepcopy(super().write(deepcopy(defn), replace))

    def to_dict(self):
        return deepcopy(super().to_dict())

    def derived_world(self):
        return deepcopy(super().derived_world())

    def verify(self, name, request):
        request = deepcopy(request)
        if not request.domain:
            from opulse.atoms.library import PipelineError
            raise PipelineError("verification domain must be nonempty")
        if request.method == "bounded" and not re.search(
                r"\d|\b(?:one|two|three|four|five|six|seven|eight|nine|ten)\b",
                str(request.scope.get("domain", ""))):  # prose or an enumerated domain
            from opulse.atoms.library import PipelineError
            raise PipelineError("bounded domain needs an explicit finite bound")
        if request.reference is None and self.get(name).kind == "operation":
            # Operations are checked against a reference; combinators against their unfold rule over
            # an operation family, objects and observations by their own obligations (atoms-v2 9).
            from opulse.atoms.library import PipelineError
            raise PipelineError("reference oracle required")
        if request.reference is not None and self.get(name).kind == "operation":
            from opulse.atoms.library import PipelineError
            expected_outcomes = []
            for args in request.domain:
                expected = (self.run(request.reference, args).outcome if isinstance(request.reference, str)
                            else request.reference(*args))
                expected_outcomes.append(expected)
                if isinstance(expected, Bottom):
                    actual = self.run(name, args).outcome
                    if isinstance(actual, Bottom) and actual != expected:
                        raise PipelineError(f"reference mismatch for {args!r}")
            cached = iter(expected_outcomes)
            request = replace(request, reference=lambda *args: next(cached))
        domain = [[{"fn": arg.name} if isinstance(arg, kernel.FnRef) else encode(arg)
                   for arg in args] for args in request.domain]
        count = len(domain)
        hashes = [input_hash(args) for args in request.domain]
        if request.scope.get("enumerated_count", count) != count or request.scope.get(
                "input_hashes", hashes) != hashes:
            from opulse.atoms.library import PipelineError
            raise PipelineError("declared domain enumeration differs")
        request.scope["enumerated_count"] = count
        request.scope["input_hashes"] = hashes
        fingerprint = hashlib.sha256(json.dumps(
            domain, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if "domain_hash" in request.scope and request.scope["domain_hash"] != fingerprint:
            from opulse.atoms.library import PipelineError
            raise PipelineError("enumerated domain fingerprint differs")
        request.scope["domain_hash"] = fingerprint
        return deepcopy(super().verify(name, request))

    def check(self, name):
        from opulse.atoms import library
        from opulse.atoms.check import check_definition

        defn = self.get(name)
        if defn.status != "written":
            raise library.PipelineError("check requires written status")
        problems = [problem for problem in check_definition(defn, self.world, self._definitions.get)
                    if "expected any, got " not in problem and not problem.endswith(", got any")]
        checker = library._CHECKERS.get(defn.kind)
        if checker:
            problems.extend(checker(defn, self))
        if problems:
            raise library.PipelineError(problems)
        return self._advance(name, "checked")

    def scope(self):
        self._sync_world()
        given = tuple(atom for atom in self.atoms if atom.name not in ("eval", "run"))
        metered_key = tuple(id(atom) for atom in given)
        if not hasattr(self, "_metered_atoms_key"):
            self._metered_atoms_key = metered_key
        elif self._metered_atoms_key != metered_key:
            self._rebind_metered(given)
            self._metered_atoms_key = metered_key
        key = (self._world_hash, id(self.atoms), tuple(id(atom) for atom in self.atoms),
               tuple((name, defn.status, id(defn)) for name, defn in self._definitions.items()))
        if getattr(self, "_scope_key", None) != key:
            self._building_scope = deepcopy(super().definitions)
            try:
                self._scope_key, self._scope_value = key, super().scope()
            finally:
                self._building_scope = False
        return kernel.DictScope(self._scope_value.atoms, self._scope_value.defns)

    def run(self, name, args, fuel=None, trace=False):
        return engine.call(name, args, self.scope(), kernel.Limits(fuel=fuel), trace, self.dialect)
