"""Content-addressed identity and evidence (docs/spec/atoms-meta.md, sections 3 and 8.I4)."""

from __future__ import annotations

import hashlib
from copy import deepcopy
from dataclasses import dataclass, replace

from opulse.atoms.spec import Contract, Definition, Evidence, Status
from opulse.atoms.values import Card, encode
from opulse.atoms.values import decode as decode_value
from opulse.meta.code import (
    CodeError,
    canonicalize,
    code_hash,
    decode_pattern,
    encode_pattern,
    instantiate_code,
    items,
    quote_from_library,
)


class LedgerError(ValueError):
    """Invalid ledger update or missing content-addressed record."""


def dependency_hash(code: Card) -> str:
    """SHA256 of dependency code hashes, excluding origin provenance (spec 3.3)."""
    return hashlib.sha256("".join(sorted(code_hash(dep) for dep in items(code.fields[4])
                                         if dep.sort == "code")).encode()).hexdigest()


def _has_promotion_scope(scope: dict) -> bool:
    """Promotion evidence covers at least one input: positive size and a nonempty domain."""
    if not isinstance(scope, dict) or type(scope.get("size")) is not int or scope["size"] <= 0:
        return False
    return bool(scope.get("domain"))


@dataclass(frozen=True)
class ProvenanceRecord:
    definition: Definition
    origin: Card
    world_hash: str
    produced_by: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {"definition": self.definition.to_dict(), "origin": encode(self.origin),
                "world_hash": self.world_hash, "produced_by": list(self.produced_by)}


@dataclass(frozen=True)
class Record:
    code: Card
    world_hash: str
    status: str = "callable"
    deps_hash: str = ""
    evidence: tuple[Evidence, ...] = ()
    contract: Contract | None = None
    produced_by: tuple[str, ...] = ()  # generator hash, then input code hashes (spec 7)

    def to_dict(self) -> dict:
        return {"hash": code_hash(self.code), "code": encode(self.code), "world_hash": self.world_hash,
                "deps_hash": self.deps_hash,
                "status": self.status, "evidence": [item.to_dict() for item in self.evidence],
                "contract": self.contract.to_dict() if self.contract else None,
                "produced_by": list(self.produced_by)}


def edit(code: Card, path: tuple[int, ...], new_subtree: object) -> Card:
    """Replace a card field by index, then re-canonicalize (spec 3.3)."""
    if not isinstance(path, tuple) or not path:
        raise LedgerError("edit needs a nonempty tuple of field indices")

    def replace_at(value, indices):
        if not isinstance(value, Card):
            raise LedgerError("edit path does not select a card")
        index = indices[0]
        if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(value.fields):
            raise LedgerError("edit field index out of range")
        fields = list(value.fields)
        fields[index] = replace_at(fields[index], indices[1:]) if len(indices) > 1 else new_subtree
        return Card(value.sort, value.tag, tuple(fields))

    return canonicalize(replace_at(code, path))


class Ledger:
    """Records keyed by (content hash, world hash), with independent name bindings (spec 3.3)."""

    def __init__(self):
        self._records: dict[tuple[str, str], Record] = {}
        self._names: dict[str, str] = {}
        self.history: list[tuple[str, str, str]] = []
        self._pairs: dict[tuple[str, str, str], list[Evidence]] = {}
        self._provenance: dict[str, ProvenanceRecord] = {}

    def add_provenance(self, definition: Definition, origin: Card, world_hash: str,
                       produced_by: tuple[str, ...] = ()) -> ProvenanceRecord:
        """Record a core-only definition and its template card without inventing code (section 7)."""
        if origin.sort != "origin" or origin.tag != "template" or definition.kind != "object" or (
                definition.spec.form not in ("refine", "compose")):
            raise LedgerError("provenance needs a core-only template output")
        try:
            template_code, arguments = origin.fields
            if canonicalize(template_code) != template_code or template_code.fields[0] != "template":
                raise LedgerError("noncanonical provenance template")
            params = tuple(pair.fields[0] for pair in items(template_code.fields[1].fields[0]))
            values = tuple(decode_pattern(arg) for arg in items(arguments))
            if (len(values) != len(params) or
                    tuple(encode_pattern(value) for value in values) != tuple(items(arguments))):
                raise LedgerError("noncanonical provenance arguments")
            reconstructed, canonical_origin = instantiate_code(template_code, values, name=definition.name)
            metadata = definition.spec.extra.get("template", {})
            if (canonical_origin != origin or not isinstance(metadata, dict)
                    or not isinstance(metadata.get("name"), str)
                    or not isinstance(metadata.get("args"), dict)
                    or tuple(metadata["args"].values()) != values):
                raise LedgerError("provenance arguments differ from stored definition")
            def without_template(spec):
                return {key: value for key, value in spec.to_dict().items() if key != "template"}

            expected_dependencies = tuple(metadata["name"] if dep == "template_source" else dep
                                          for dep in reconstructed.depends_on)
            if (definition.kind != reconstructed.kind or definition.body != reconstructed.body
                    or without_template(definition.spec) != without_template(reconstructed.spec)
                    or definition.depends_on != expected_dependencies):
                raise LedgerError("provenance differs from stored definition")
        except (CodeError, ValueError, TypeError, KeyError, AttributeError, IndexError) as error:
            raise LedgerError("invalid template provenance") from error
        record = ProvenanceRecord(deepcopy(definition), origin, world_hash, tuple(produced_by))
        self._provenance[definition.name] = record
        return deepcopy(record)

    def provenance(self, name: str) -> ProvenanceRecord:
        return deepcopy(self._provenance[name])

    def add(self, code: Card, world_hash: str, name: str | None = None,
            produced_by: tuple[str, ...] = ()) -> str:
        """Record ``code``; ``produced_by`` names the generator program and its input hashes (spec 7)."""
        code = canonicalize(code)
        digest = code_hash(code)
        key = (digest, world_hash)
        if key not in self._records:
            self._records[key] = Record(code, world_hash, deps_hash=dependency_hash(code),
                                        produced_by=tuple(produced_by))
        elif self._records[key].code != code:
            raise LedgerError("content hash collision")
        elif produced_by and tuple(produced_by) != self._records[key].produced_by:
            record = self._records[key]
            if record.status == "promoted":
                raise LedgerError("promoted record is immutable")
            self._records[key] = replace(record, produced_by=tuple(produced_by))
        if name is not None:
            self.bind(name, digest)
        return digest

    def bind(self, name: str, code_or_hash: Card | str) -> None:
        digest = code_hash(canonicalize(code_or_hash)) if isinstance(code_or_hash, Card) else code_or_hash
        if not isinstance(name, str) or not name or not isinstance(digest, str) or not any(
                key[0] == digest for key in self._records):
            raise LedgerError("binding requires a name and an existing code hash")
        previous = self._names.get(name)
        if previous is not None and previous != digest:
            self.history.append((name, previous, digest))
        self._names[name] = digest

    def resolve(self, name: str) -> str:
        try:
            return self._names[name]
        except KeyError as error:
            raise LedgerError(f"unbound name: {name}") from error

    def record(self, digest: str, world_hash: str) -> Record:
        try:
            return deepcopy(self._records[digest, world_hash])
        except KeyError as error:
            raise LedgerError(f"no record for {digest} in {world_hash}") from error

    def status(self, digest: str, world_hash: str) -> str:
        return self.record(digest, world_hash).status

    def attach_evidence(self, digest: str, world_hash: str, evidence: Evidence) -> None:
        record = self.record(digest, world_hash)
        if not isinstance(evidence, Evidence) or evidence.world_hash != world_hash:
            raise LedgerError("evidence must match the record's world hash")
        if not evidence.deps_hash:  # evidence written for this record: bind it to the record's commitment
            evidence = replace(evidence, deps_hash=record.deps_hash)
        if record.deps_hash != dependency_hash(record.code) or evidence.deps_hash != record.deps_hash:
            raise LedgerError("evidence dependency hash does not match the record")
        if record.status == "promoted":
            raise LedgerError("promoted record is immutable")
        if evidence.method in ("exhaustive", "bounded") and not _has_promotion_scope(evidence.scope):
            raise LedgerError("promotion evidence requires scope.size > 0 and a nonempty domain")
        self._records[digest, world_hash] = replace(record, evidence=record.evidence + (deepcopy(evidence),),
                                                   status="verified")

    def promote(self, digest: str, world_hash: str, contract: Contract) -> None:
        record = self.record(digest, world_hash)
        if record.deps_hash != dependency_hash(record.code) or any(
                item.deps_hash != record.deps_hash or item.world_hash != world_hash for item in record.evidence):
            raise LedgerError("promotion dependency hash does not match the record")
        if record.status == "promoted":
            raise LedgerError("promoted record is immutable")
        if not isinstance(contract, Contract):
            raise LedgerError("promotion needs a Contract")
        if not any(item.method in ("exhaustive", "bounded") and _has_promotion_scope(item.scope)
                   for item in record.evidence):
            raise LedgerError("promotion needs exhaustive or bounded evidence")
        self._records[digest, world_hash] = replace(record, status="promoted", contract=deepcopy(contract))

    def promoted(self, digest: str, world_hash: str) -> tuple[Evidence, Contract] | None:
        """The promotion of (hash, world hash): its strongest evidence and contract, else None (spec 6.3)."""
        record = self._records.get((digest, world_hash))
        if record is None or record.status != "promoted":
            return None
        evidence = [item for item in record.evidence if item.method in ("exhaustive", "bounded")]
        return deepcopy(evidence[-1]), deepcopy(record.contract)

    def claim_equivalent(self, hash_a: str, hash_b: str, world_hash: str, evidence: Evidence) -> None:
        self.record(hash_a, world_hash)
        self.record(hash_b, world_hash)
        if not isinstance(evidence, Evidence) or evidence.world_hash != world_hash:
            raise LedgerError("pair evidence must match the world hash")
        key = (min(hash_a, hash_b), max(hash_a, hash_b), world_hash)
        self._pairs.setdefault(key, []).append(deepcopy(evidence))

    def pair_evidence(self, hash_a: str, hash_b: str, world_hash: str) -> tuple[Evidence, ...]:
        return tuple(deepcopy(self._pairs.get((min(hash_a, hash_b), max(hash_a, hash_b), world_hash), ())))

    @classmethod
    def from_library(cls, library) -> Ledger:
        """Snapshot stored invented definitions, preserving their library pipeline state (spec 3.3)."""
        ledger = cls()
        world_hash = library.world.world_hash()
        for name, definition in library.definitions.items():
            if definition.origin != "invented":
                continue
            try:
                code = quote_from_library(library, name)
            except CodeError:
                metadata = definition.spec.extra.get("template", {})
                template = library.definitions.get(metadata.get("name"))
                if template is None or not isinstance(metadata.get("args"), dict):
                    raise
                from opulse.meta.code import instantiate_code

                result = instantiate_code(quote_from_library(library, template.name),
                                          tuple(metadata["args"][param] for param, _ in template.spec.params),
                                          name=name)
                if not isinstance(result, tuple):
                    raise
                from opulse.atoms.templates import instantiate

                expected = instantiate(template, metadata["args"], name, lib=library)
                if (expected.body != definition.body or expected.spec != definition.spec
                        or expected.depends_on != definition.depends_on):
                    raise LedgerError("provenance differs from stored definition")
                ledger.add_provenance(definition, result[1], world_hash)
                continue
            existing = (code_hash(code), world_hash) in ledger._records
            digest = ledger.add(code, world_hash, name)
            evidence = (deepcopy(definition.evidence),) if definition.evidence else ()
            if evidence and evidence[0].world_hash != world_hash:
                raise LedgerError("library evidence does not match the world hash")
            if evidence:
                if evidence[0].deps_hash != library.deps_hash(name):
                    raise LedgerError("library evidence dependency hash changed")
                evidence = (replace(evidence[0], deps_hash=dependency_hash(code)),)
            current = ledger._records[digest, world_hash]
            imported = Record(code, world_hash, definition.status, dependency_hash(code),
                              deepcopy(evidence), deepcopy(definition.contract))
            if imported.status == "promoted" and not any(
                    item.method in ("exhaustive", "bounded") and _has_promotion_scope(item.scope)
                    for item in imported.evidence):
                raise LedgerError("promoted record requires a nonempty evidence scope")
            if not existing or Status(definition.status) == Status.PROMOTED:
                if existing and current.status == "promoted" and imported != current:
                    raise LedgerError("promoted record is immutable")
                ledger._records[digest, world_hash] = imported
            elif current.status != "promoted":
                combined = current.evidence + tuple(item for item in evidence if item not in current.evidence)
                order = tuple(Status)
                status = max((current.status, definition.status), key=lambda item: order.index(Status(item)))
                ledger._records[digest, world_hash] = replace(current, status=status, evidence=combined)
        return ledger

    def to_dict(self) -> dict:
        return deepcopy({"schema": "opulse.ledger/1",
                "records": [record.to_dict() for _, record in sorted(self._records.items())],
                "names": dict(self._names), "history": [list(entry) for entry in self.history],
                "provenance": [record.to_dict() for _, record in sorted(self._provenance.items())],
                "pairs": [{"hash_a": left, "hash_b": right, "world_hash": world,
                           "evidence": [item.to_dict() for item in evidence]}
                          for (left, right, world), evidence in sorted(self._pairs.items())]})

    @classmethod
    def from_dict(cls, data: dict) -> Ledger:
        if not isinstance(data, dict) or data.get("schema") != "opulse.ledger/1":
            raise LedgerError("invalid ledger schema")
        ledger = cls()
        for entry in data.get("provenance", ()):
            ledger.add_provenance(Definition.from_dict(entry["definition"]),
                                  decode_value(entry["origin"]), entry["world_hash"],
                                  tuple(entry.get("produced_by", ())))
        for entry in data["records"]:
            code = decode_value(entry["code"])
            digest = ledger.add(code, entry["world_hash"])
            if digest != entry["hash"]:
                raise LedgerError("record hash does not match its code")
            evidence = tuple(Evidence.from_dict(item) for item in entry["evidence"])
            if entry.get("deps_hash") != dependency_hash(code) or any(
                    item.deps_hash != entry["deps_hash"] for item in evidence):
                raise LedgerError("record evidence dependency hash does not match the code")
            if any(item.world_hash != entry["world_hash"] for item in evidence):
                raise LedgerError("record evidence does not match its world hash")
            status = entry["status"]
            contract = Contract.from_dict(entry["contract"]) if entry["contract"] is not None else None
            if status not in Status._value2member_map_ or (status == "promoted" and (
                    contract is None or not any(item.method in ("exhaustive", "bounded") and
                                                _has_promotion_scope(item.scope) for item in evidence))):
                raise LedgerError("invalid record status or promotion")
            key = (digest, entry["world_hash"])
            imported = Record(code, entry["world_hash"], status, entry["deps_hash"], deepcopy(evidence),
                              deepcopy(contract),
                              tuple(entry.get("produced_by", ())))
            if ledger._records[key].status == "promoted" and imported != ledger._records[key]:
                raise LedgerError("promoted record is immutable")
            ledger._records[key] = imported
        for name, digest in data["names"].items():
            ledger.bind(name, digest)
        ledger.history = [tuple(entry) for entry in data["history"]]
        for entry in data["pairs"]:
            for item in entry["evidence"]:
                ledger.claim_equivalent(entry["hash_a"], entry["hash_b"], entry["world_hash"],
                                        Evidence.from_dict(item))
        return ledger
