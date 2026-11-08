"""Shared records of the kind-generic generator (atoms-v2, docs/spec/atoms-v2.md).

The generator grows a library of invented definitions of the four kinds in one world. Every
part of ``opulse.gen_v2`` talks through the records in this module:

* ``GenWorld``   what a world offers the generator: its declaration, layer-0 atoms, typed
                 signatures, a finite probe domain per sort, the truth states and probes for
                 observations, and the kinds it opens (``open_kinds``).
* ``Sort``       one sort known to the generator (given or invented) with its probe values.
* ``Signature``  typed inputs and output of an operation (or observation, or combinator use).
* ``Candidate``  one proposed definition plus everything the pipeline needs to admit it.
* ``Entry``      one admitted (promoted) definition in the generator's catalogue.
* ``GenState``   the growing catalogue: library, sorts, entries, names, rejections.
* ``Move``       a proposal function ``(state, rng) -> Candidate | None`` for one kind.

Names follow the ASCII notation (common.md): objects ``A7``, operations ``f6``, combinators
``k3`` (written ``@k3``), observations ``q4`` (written ``?q4``). Internal names carry no sigil;
the notation printer adds ``@`` and ``?``.
"""

from __future__ import annotations

import random
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import ClassVar, Protocol

from opulse.atoms import kernel
from opulse.atoms.library import VerifyRequest
from opulse.atoms.spec import Definition
from opulse.atoms.world import WorldDecl

KINDS = ("object", "operation", "combinator", "observation", "law", "bridge")


@dataclass(frozen=True)
class Signature:
    """Typed interface. ``inputs`` are sort names; ``op_inputs`` are operation-slot signatures
    (only combinators have them; each slot is itself a ``Signature``)."""

    inputs: tuple[str, ...]
    output: str
    op_inputs: tuple[Signature, ...] = ()

    @property
    def arity(self) -> int:
        return len(self.inputs) + len(self.op_inputs)


@dataclass
class Sort:
    """A sort the generator can build terms of.

    ``values`` is the finite probe domain used for verification scopes, fingerprints and
    examples (canonical values only, at most a few dozen). ``origin`` is ``given`` or
    ``invented``; ``defined_by`` names the object definition that introduced an invented sort.
    ``constructors`` / ``accessors`` / ``testers`` name the operations that build, read and test
    cards of the sort (for compose sorts: ``S.tag``, ``S.field``, ``S.is_tag``; for refine sorts:
    ``S.make`` and ``S.base``). ``interface`` lists the only operations allowed to touch the
    inside when the sort is sealed. ``finite`` certifies that ``values`` covers the entire
    declared universe, not merely a bounded sample.
    """

    name: str
    values: tuple
    origin: str = "given"
    defined_by: str | None = None
    constructors: tuple[str, ...] = ()
    accessors: tuple[str, ...] = ()
    testers: tuple[str, ...] = ()
    sealed: bool = False
    interface: tuple[str, ...] = ()
    base: str | None = None
    doc: str = ""
    finite: bool = False


def signature_data(signature: Signature | None):
    if signature is None:
        return None
    return {"inputs": list(signature.inputs), "output": signature.output,
            "op_inputs": [signature_data(slot) for slot in signature.op_inputs]}


def signature_from_data(data):
    if data is None:
        return None
    return Signature(tuple(data["inputs"]), data["output"],
                     tuple(signature_from_data(slot) for slot in data.get("op_inputs", ())))


def kind_counts(entries):
    return Counter(entry.kind for entry in entries)


def count_summary(entries):
    entries = tuple(entries)
    kinds = kind_counts(entries)
    layers = Counter(entry.layer for entry in entries)
    pairs = {kind: Counter(entry.layer for entry in entries if entry.kind == kind) for kind in KINDS}
    return {"per_kind": {kind: kinds[kind] for kind in KINDS},
            "per_layer": {str(layer): count for layer, count in sorted(layers.items())},
            "per_kind_layer": {kind: {str(layer): count for layer, count in sorted(pairs[kind].items())}
                               for kind in KINDS}}


@dataclass
class GenWorld:
    """Everything a world gives the generator.

    * ``decl``: the world declaration (``opulse.world/2``).
    * ``atoms``: layer-0 kernel atoms (given operations and probes), as the world module builds
      them; observation probes have ``kind="observation"``.
    * ``signatures``: typed signature of every given operation and probe, by name.
    * ``sorts``: every given sort with its probe values.
    * ``open_kinds``: the kinds the generator may invent in this world (common.md, Open kinds).
      Classic worlds use ``{"operation"}``.
    * ``truth_sort`` / ``truth_states`` / ``probes``: the sealed truth sort, a finite set of truth
      states for observation scopes, and the probe names granted to the learner (empty when the
      world has no truth).
    * ``measures``: per sort, how a recursion can shrink a value of that sort: a list of
      ``(step_op, measure_op)`` pairs (``step_op`` moves the value one step towards the base;
      ``measure_op`` maps it to a non-negative int that ``step_op`` decreases). ``bases`` maps a
      sort to the decide operations that recognise its base case.
    * ``counters``: per sort, binary count-down steps of classic worlds: ``(op, literal, base_op)``
      means the counter steps by ``op(counter, literal)`` (``sub(n, 1)``, ``shift_right(n, 1)``)
      and stops when ``base_op(counter)`` is true (legacy recursion needs no measure node).
    * ``tags``: the world's tags (common.md 'World tags'), carried into exports.
    * ``dialect``: ``atoms-v2`` or ``legacy-v1``.
    * ``fuel``: layer-0 step budget per verified input.
    * ``extra_scope``: kernel ``Defn``s the world needs in every scope (given combinators).
    * ``max_steps``: candidates whose mean layer-0 steps on the scope exceed this are rejected.
    """

    name: str
    decl: WorldDecl
    atoms: Sequence[kernel.Atom]
    signatures: dict[str, Signature]
    sorts: dict[str, Sort]
    open_kinds: frozenset[str] = frozenset(KINDS)
    truth_sort: str | None = None
    truth_states: tuple = ()
    probes: tuple[str, ...] = ()
    measures: dict[str, list[tuple[str, str]]] = field(default_factory=dict)
    bases: dict[str, list[str]] = field(default_factory=dict)
    dialect: str = "atoms-v2"
    fuel: int = 20_000
    extra_scope: Sequence[kernel.Defn] = ()
    max_steps: int = 400
    max_scope: int = 400
    title: str = ""
    counters: dict[str, list[tuple[str, object, str]]] = field(default_factory=dict)
    tags: dict = field(default_factory=dict)  # common.md 'World tags' (English values)

    @property
    def version(self) -> int:
        return self.decl.version


@dataclass
class Candidate:
    """A proposed definition and what its admission needs.

    * ``defn``: a ``Definition`` with status ``written``, origin ``invented`` and the right layer.
    * ``signature``: its typed interface (``None`` for objects; objects give ``new_sorts``).
    * ``move``: the move that produced it (``op.substitute``, ``obj.refine``, ...), for stats.
    * ``request``: the verification request (method, domain, scope, reference). The admit step
      fills a default when ``None``.
    * ``extra_atoms``: kernel atoms or Defns the definition brings into scope (constructors and
      accessors of a new object; ``Sort.constructors`` names them).
    * ``new_sorts``: sorts an object definition introduces, with probe values.
    * ``contract``: guarantees text for promotion.
    * ``extra_signatures``: signatures of ``extra_atoms`` (added to ``GenState.extra_signatures``
      when the candidate is admitted, removed when it is refused).
    * ``meta``: free-form data for interest and export (template, slots, measure, ...).
    """

    defn: Definition
    signature: Signature | None
    move: str
    request: VerifyRequest | None = None
    extra_atoms: Sequence[kernel.Atom | kernel.Defn] = ()
    new_sorts: Sequence[Sort] = ()
    contract: str = ""
    extra_signatures: dict = field(default_factory=dict)
    meta: dict = field(default_factory=dict)


@dataclass
class Entry:
    """An admitted definition: promoted in the library, catalogued for later moves."""

    name: str
    kind: str
    layer: int
    signature: Signature | None
    move: str
    depends_on: tuple[str, ...]
    fingerprint: tuple = ()          # behaviour on the probe domain (kind-specific, hashable)
    steps_mean: float = 0.0
    steps_max: int = 0
    length: int = 0
    reuse: int = 0                   # call sites in later admitted definitions
    interest: dict = field(default_factory=dict)
    examples: list = field(default_factory=list)  # [(inputs, outcome, steps)] on probe values
    meta: dict = field(default_factory=dict)


@dataclass
class Rejection:
    move: str
    kind: str
    stage: str          # check | callable | verify | degenerate | duplicate | cost | closed_kind
    reason: str


class Move(Protocol):
    """A proposal function for one kind. Must be deterministic given ``rng``."""

    kind: str
    name: str

    def __call__(self, state: GenState, rng: random.Random) -> Candidate | None: ...


class Names:
    """Generated names per kind: A7 / f6 / k3 / q4 (a letter cycle plus a running number)."""

    LETTERS: ClassVar[dict[str, str]] = {"object": "ABCDEFGHJKLMNPRSTUVWXYZ", "operation": "fghpqrstuvw",
               "combinator": "k", "observation": "q", "law": "l", "bridge": "b"}

    def __init__(self, taken: Sequence[str] = ()):
        self.counter = 0
        self.taken = set(taken)

    def fresh(self, kind: str) -> str:
        letters = self.LETTERS[kind]
        while True:
            self.counter += 1
            name = f"{letters[self.counter % len(letters)]}{self.counter}"
            if name not in self.taken:
                self.taken.add(name)
                return name

    def release(self, name: str) -> None:
        """Give back a name whose candidate was refused (the counter steps back when it was the
        last name issued), so refusals leave no gaps."""
        if name not in self.taken:
            return
        self.taken.discard(name)
        suffix = str(self.counter)
        if name.endswith(suffix) and name[:-len(suffix)] and name[:-len(suffix)] in "".join(self.LETTERS.values()):
            self.counter -= 1


@dataclass
class GenState:
    """The growing catalogue of one generator run.

    ``library`` is a ``opulse.gen_v2.library.GenLibrary`` (a ``Library`` with a cached scope);
    ``entries`` keeps admitted definitions in admission order; ``sorts`` holds every given and
    invented sort; ``fingerprints`` maps a behaviour fingerprint to the entry that owns it (for
    duplicate rejection); ``rejections`` records every refused candidate.
    """

    world: GenWorld
    library: object
    sorts: dict[str, Sort]
    entries: dict[str, Entry] = field(default_factory=dict)
    names: Names = field(default_factory=Names)
    fingerprints: dict[tuple, str] = field(default_factory=dict)
    rejections: list[Rejection] = field(default_factory=list)
    seed: int = 0
    # Signatures of extra atoms brought in by admitted objects (constructors ``S.tag``,
    # accessors ``S.field``, testers ``S.is_tag``, ``S.make``, ``S.base``), by name.
    extra_signatures: dict[str, Signature] = field(default_factory=dict)
    # The exact verification request of every admitted entry (domain tuples, scope, method), so
    # audits re-check the evidence domain itself. Not exported.
    requests: dict[str, VerifyRequest] = field(default_factory=dict)

    # ---- typed lookups used by every move ------------------------------------------------

    def signature(self, name: str) -> Signature | None:
        entry = self.entries.get(name)
        if entry is not None and entry.signature is not None:
            return entry.signature
        return self.world.signatures.get(name) or self.extra_signatures.get(name)

    def layer(self, name: str) -> int:
        entry = self.entries.get(name)
        if entry is not None:
            return entry.layer
        owner, separator, _ = name.partition(".")
        parent = self.entries.get(owner) if separator else None
        return parent.layer if parent is not None and parent.kind == "object" else 0

    def callables(self, kind: str = "operation", output: str | None = None,
                  inputs: tuple[str, ...] | None = None) -> list[str]:
        """Names of given atoms and admitted entries of ``kind`` with the given output sort and
        input sorts (``None`` matches anything). Deterministic order: given first, then
        admission order. Probes count as kind ``observation``."""
        result = []
        for name, sig in self.world.signatures.items():
            atom_kind = "observation" if name in self.world.probes else "operation"
            if atom_kind == kind and _match(sig, output, inputs):
                result.append(name)
        if kind == "operation":
            result.extend(name for name, sig in self.extra_signatures.items() if _match(sig, output, inputs))
        for name, entry in self.entries.items():
            if entry.kind == kind and entry.signature is not None and _match(entry.signature, output, inputs):
                result.append(name)
        return result

    def max_layer(self, kind: str | None = None) -> int:
        return max((entry.layer for entry in self.entries.values() if kind is None or entry.kind == kind),
                   default=0)


def _match(sig: Signature, output, inputs) -> bool:
    return (output is None or sig.output == output) and (inputs is None or sig.inputs == inputs)


Reference = Callable[..., object]
