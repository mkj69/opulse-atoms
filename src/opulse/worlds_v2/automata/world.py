"""Locked declaration and the layer-zero kernel scope."""

import json
from pathlib import Path
from weakref import WeakValueDictionary

from opulse.atoms.kernel import Atom
from opulse.atoms.library import Library
from opulse.atoms.spec import Definition
from opulse.atoms.values import Bottom, Card
from opulse.atoms.world import WorldDecl

from . import hosts

DECL_PATH = Path(__file__).resolve().parents[4] / "worlds/decl/v2/automata@1.json"


class AutomataLibrary(Library):
    """Support parameterized DFA observations and validate generated Pair interfaces."""

    def __init__(self, world, given_atoms):
        super().__init__(world, given_atoms)
        self._minted_pairs = WeakValueDictionary()
        self._minted_trims = WeakValueDictionary()
        from opulse.atoms.spec import Edge, OperationSpec

        for name, arity, layer in (("Pair.pair", 4, 1), ("Pair.left", 1, 1),
                                   ("Pair.right", 1, 1), ("Trim.make", 1, 2),
                                   ("Trim.base", 1, 2)):
            spec = OperationSpec(name, "transform", tuple(Edge("any") for _ in range(arity)),
                                 Edge("any"), "Generated object interface.")
            self._definitions[name] = Definition(name, "operation", "given", layer, (), spec,
                                                  {"generated_object": name}, status="promoted")

    def _params(self, definition):
        if definition.name in ("empty_language", "equivalent", "included"):
            if definition.name != "empty_language":
                return ("left", "right")
            return ("machine",)
        return super()._params(definition)

    def run(self, name, args, fuel=None, trace=False):
        if name in ("Trim._pack", "Trim._invalid"):
            from opulse.atoms.library import PipelineError

            raise PipelineError(f"private object constructor: {name}")
        return super().run(name, args, fuel=fuel, trace=trace)

    def _build_scope(self):
        scope = super()._build_scope()
        if "Pair.pair" not in scope.atoms:
            return scope

        def pair_valid(pair):
            if not isinstance(pair, Card) or (pair.sort, pair.tag) != ("Pair", "pair") or len(pair.fields) != 4:
                return False
            left, right, initial, capacity = pair.fields
            return (hosts.machine_valid(left) and hosts.machine_valid(right)
                    and initial == hosts.make_row(hosts.start(left), hosts.start(right))
                    and type(capacity) is int and capacity == hosts.count(left) * hosts.count(right))

        def pair_make(left, right, initial, capacity):
            pair = original_constructor.fn(left, right, initial, capacity)
            if not pair_valid(pair):
                return Bottom("invalid")
            self._minted_pairs[id(pair)] = pair
            return pair

        original_constructor = scope.atoms["Pair.pair"]
        scope.atoms["Pair.pair"] = Atom("Pair.pair", 4, pair_make, kind="object")
        def minted_pair(pair):
            return isinstance(pair, Card) and self._minted_pairs.get(id(pair)) is pair

        for name, index in (("left", 0), ("right", 1), ("initial", 2), ("capacity", 3)):
            def field(pair, index=index):
                return pair.fields[index] if minted_pair(pair) else Bottom("invalid")

            scope.atoms[f"Pair.{name}"] = Atom(f"Pair.{name}", 1, field, kind="object")
        original_size = scope.atoms["Pair.size"]
        scope.atoms["Pair.size"] = Atom("Pair.size", 1,
                                         lambda pair: original_size.fn(pair) if minted_pair(pair) else Bottom("invalid"),
                                         kind="object")
        scope.atoms["Pair.is_pair"] = Atom("Pair.is_pair", 1, minted_pair, kind="object")
        if "Trim._pack" in scope.atoms:
            original_pack = scope.atoms["Trim._pack"]

            def trim_pack(machine):
                if not hosts.machine_valid(machine):
                    return Bottom("invalid")
                trimmed = original_pack.fn(machine)
                self._minted_trims[id(trimmed)] = trimmed
                return trimmed

            def trim_stored(trimmed):
                if (not isinstance(trimmed, Card) or (trimmed.sort, trimmed.tag) != ("Trim", "val")
                        or len(trimmed.fields) != 1 or self._minted_trims.get(id(trimmed)) is not trimmed):
                    return Bottom("invalid")
                return original_stored.fn(trimmed)

            original_stored = scope.atoms["Trim._stored"]
            scope.atoms["Trim._pack"] = Atom("Trim._pack", 1, trim_pack, kind="object")
            scope.atoms["Trim._stored"] = Atom("Trim._stored", 1, trim_stored, kind="object")
        return scope

    def check(self, name):
        from opulse.atoms.check import check_definition
        from opulse.atoms.combinators import check_combinator
        from opulse.atoms.library import PipelineError
        from opulse.atoms.objects import check_object
        definition = self.get(name)
        problems = [problem for problem in check_definition(definition, self.world, self.definitions.get)
                    if "expected any" not in problem and "got any" not in problem
                    and not problem.startswith("equal argument")]
        if definition.kind == "object":
            problems.extend(check_object(definition, self))
        if definition.kind == "combinator":
            problems.extend(check_combinator(definition, self))
        if definition.kind == "observation":
            from opulse.atoms import nodes
            probes = {probe["name"] for probe in self.world.observation["probes"]}
            granted = set(definition.spec.reads)
            if not granted <= probes:
                problems.append("observation requests ungranted probes")
            pending = [definition.body]
            visited = set()
            while pending:
                body = pending.pop()
                for reference in nodes.references(body):
                    if reference in probes and reference not in granted:
                        problems.append(f"observation reads ungranted {reference}")
                    if reference in visited:
                        continue
                    visited.add(reference)
                    dependent = self._definitions.get(reference)
                    if dependent is not None and isinstance(dependent.body, nodes.NODE_TYPES):
                        pending.append(dependent.body)
        if problems:
            raise PipelineError(problems)
        return self._advance(name, "checked")

    def make_callable(self, name, sample):
        if name not in ("empty_language", "equivalent", "included"):
            return super().make_callable(name, sample)
        from opulse.atoms.kernel import Defn, call
        from opulse.atoms.library import PipelineError
        from opulse.atoms.values import Unknown
        definition = self.get(name)
        scope = self.scope().extend((Defn(name, self._params(definition), definition.body,
                                         "observation", definition.layer),))
        if any(isinstance(call(name, args, scope).outcome,
                          Unknown) for args in sample):
            raise PipelineError("observation sample exceeded resource limit")
        return self._advance(name, "callable")

    def verify(self, name, request):
        if name == "sync":
            from opulse.atoms.combinators import verify_combinator
            from opulse.atoms.library import PipelineError

            from .adapter import record

            if self.get(name).status != "callable" or request.scope.get("size") != len(request.domain):
                raise PipelineError("invalid paired DFA combinator domain")
            result = verify_combinator(self.get(name), self, request)
            if not result.ok:
                raise PipelineError(result.problems)
            return record(self, name, request, result.checks, result.steps)
        if name == "Pair":
            from opulse.atoms.library import PipelineError
            from opulse.atoms.values import Ok

            from .adapter import record

            if self.get(name).status != "callable" or request.scope.get("size") != len(request.domain):
                raise PipelineError("invalid paired DFA domain")
            steps = []
            for left, right in request.domain:
                initial = hosts.make_row(hosts.start(left), hosts.start(right))
                capacity = hosts.count(left) * hosts.count(right)
                run = self.run("Pair.pair", (left, right, initial, capacity))
                expected = Card("Pair", "pair", (left, right, initial, capacity))
                if run.outcome != Ok(expected):
                    raise PipelineError("Pair constructor disagrees with reference")
                if self.run("Pair.left", (run.outcome.value,)).outcome != Ok(left) or self.run(
                        "Pair.right", (run.outcome.value,)).outcome != Ok(right):
                    raise PipelineError("Pair accessor disagrees with reference")
                steps.append(run.steps)
            return record(self, name, request, ("reference", "object_constructor"), steps)
        if name not in ("empty_language", "equivalent", "included"):
            return super().verify(name, request)
        from opulse.atoms import kernel, nodes
        from opulse.atoms.library import PipelineError
        from opulse.atoms.values import Ok, outcome_equal

        from .adapter import record

        if self.get(name).status != "callable" or request.scope.get("size") != len(request.domain):
            raise PipelineError("invalid public DFA observation domain")
        steps = []
        observations = {}
        for index, arguments in enumerate(request.domain):
            original = tuple(arguments)
            run = self.run(name, arguments)
            expected = request.reference(*arguments)
            if not outcome_equal(run.outcome, expected if isinstance(expected, (Ok,)) else Ok(expected)):
                raise PipelineError(f"{name}: reference counterexample {arguments!r}")
            unfolded = kernel.evaluate(kernel.inline(nodes.Call(name, tuple(nodes.Lit(arg) for arg in arguments)),
                                                      self.scope()), scope=self.scope())
            if not outcome_equal(run.outcome, unfolded.outcome) or run.steps != unfolded.steps or original != tuple(arguments):
                raise PipelineError(f"{name}: unfolding or read-only counterexample")
            view = tuple(hosts.from_card(machine) for machine in arguments)
            if view in observations and not outcome_equal(observations[view], run.outcome):
                raise PipelineError(f"{name}: public-probe non-interference counterexample")
            observations[view] = run.outcome
            if index in (0, len(request.domain) - 1):
                clone = tuple(hosts.to_card(*hosts.from_card(machine)) for machine in arguments)
                if not outcome_equal(run.outcome, self.run(name, clone).outcome):
                    raise PipelineError(f"{name}: identical public probes changed the result")
            steps.append(run.steps)
        return record(self, name, request,
                      ("dependency", "facts_unchanged", "non_interference", "reference", "unfold_equivalence"),
                      steps)

def decl() -> WorldDecl:
    return WorldDecl.from_dict(json.loads(DECL_PATH.read_text(encoding="utf-8")))


def atoms() -> list[Atom]:
    world = decl()
    operations = [Atom(op.name, len(op.inputs), getattr(hosts, op.name), op.cost, strict=op.strict)
                  for op in world.operations]
    arities = {op.name: len(op.inputs) for op in world.operations}
    operations.extend(Atom(probe["name"], arities.get(probe["name"], 2 if probe["name"] == "accept" else 1),
                           hosts.count if probe["name"] == "size" else getattr(hosts, probe["name"]),
                           1, "observation")
                      for probe in world.observation["probes"])
    return operations


def new_library() -> Library:
    return AutomataLibrary(decl(), atoms())
