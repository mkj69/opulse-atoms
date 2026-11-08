"""Locked melody declaration and counted given atoms."""

import hashlib
import json
from pathlib import Path

from opulse.atoms import kernel, nodes
from opulse.atoms.check import check_definition
from opulse.atoms.library import Library, PipelineError
from opulse.atoms.values import Bottom, Unknown
from opulse.atoms.world import WorldDecl

from . import hosts

_COMPATIBLE_ARGUMENTS = {
    "Motif": {"lt argument 1: expected int, got Nat", "lt argument 2: expected int, got Nat",
              "list_get argument 2: expected Nat, got int", "sub argument 1: expected int, got Nat"},
    "Score": {"le argument 2: expected int, got Nat", "lt argument 1: expected int, got Nat",
              "lt argument 2: expected int, got Nat", "sub argument 1: expected int, got Nat",
              "list_get argument 2: expected Nat, got int"},
    "occurs": {"lt argument 1: expected int, got Nat", "add argument 2: expected int, got Nat",
               "sub argument 1: expected int, got Nat", "list_get argument 2: expected Nat, got int"},
    "scan": {"sub argument 1: expected int, got Nat", "sub argument 2: expected int, got Nat"},
    "intervals": {"sub argument 1: expected int, got Nat", "le argument 1: expected int, got Nat",
                  "list_get argument 2: expected Nat, got int"},
    "realize": {"sub argument 1: expected int, got Nat", "list_get argument 2: expected Nat, got int"},
    "motif_at": {"sub argument 1: expected int, got Nat", "list_get argument 2: expected Nat, got int"},
    "count_covers": {"sub argument 1: expected int, got Nat", "list_get argument 2: expected Nat, got int",
                     "add argument 2: expected int, got Nat"},
    "best_cover": {"sub argument 1: expected int, got Nat", "list_get argument 2: expected Nat, got int",
                   "add argument 2: expected int, got Nat", "list_length argument 1: expected List, got str",
                   "lt argument 1: expected int, got Nat", "lt argument 2: expected int, got Nat",
                   "list_lex_lt argument 1: expected List, got str",
                   "list_lex_lt argument 2: expected List, got str"},
    "perform": {"list_get argument 2: expected Nat, got int", "sub argument 1: expected int, got Nat"},
}


def decl():
    path = Path(__file__).resolve().parents[4] / "worlds/decl/v2/melody@1.json"
    return WorldDecl.from_dict(json.loads(path.read_text(encoding="utf-8")))


def transpose_cost(source, semitones):
    return len(source.fields) if hosts.valid_melody(source) and type(semitones) is int and -12 <= semitones <= 12 else 1


def slice_events_cost(source, start, length):
    return (length if hosts.valid_melody(source) and type(start) is int and type(length) is int
            and 0 <= start <= 63 and 1 <= length <= 64 and start + length <= len(source.fields) else 1)


class EventCost:
    def __init__(self, name, calculate):
        self.name = name
        self.calculate = calculate

    def __call__(self, *args):
        return self.calculate(*args)

    def __repr__(self):
        code = self.calculate.__code__
        digest = hashlib.sha256(repr((code.co_code.hex(), code.co_consts, code.co_names)).encode()).hexdigest()
        return f"melody.cost.{self.name}:{digest}"


def atoms():
    world = decl()
    costs = {"transpose": EventCost("transpose", transpose_cost),
             "slice_events": EventCost("slice_events", slice_events_cost)}
    result = [kernel.Atom(spec.name, len(spec.inputs), getattr(hosts, spec.name),
                          costs.get(spec.name, spec.cost),
                          cost_rule=world.extra.get("atom_cost_rules", {}).get(spec.name, ""))
              for spec in world.operations]
    result += [kernel.Atom(probe["name"], 1, getattr(hosts, probe["name"]),
                           1, "observation") for probe in world.observation["probes"]]
    result += [kernel.Atom("Melody.events", 1, hosts.events, 1, "object"),
               kernel.Atom("Melody.make", 1, lambda items: hosts.melody(*items), 1, "object")]
    return result


class MelodyLibrary(Library):
    def scope(self):
        scope = super().scope()
        for name, valid in (("Motif", hosts.valid_motif), ("Score", hosts.valid_score)):
            if f"{name}._stored" in scope.atoms:
                scope.atoms[f"{name}._stored"] = kernel.Atom(
                    f"{name}._stored", 1,
                    lambda value, valid=valid: value.fields[0] if valid(value) else Bottom("invalid"),
                    kind="object")
        return scope

    def _params(self, definition):
        if definition.kind == "observation":
            return definition.spec.reads
        return super()._params(definition)

    def check(self, name):
        from opulse.atoms import library

        definition = self.get(name)

        def resolve(reference):
            found = self.definitions.get(reference)
            if found is not None:
                return found
            generated = self.scope().resolve(reference)
            if generated is not None and "." in reference:
                parent = reference.split(".")[0]
                if parent in self.definitions:
                    if isinstance(generated, kernel.Defn):
                        return kernel.Defn(generated.name, generated.params, generated.body,
                                           generated.kind, self.get(parent).layer)
                    return generated
            return None

        problems = check_definition(definition, self.world, resolve)
        if isinstance(definition.body, nodes.NODE_TYPES) and any(
                isinstance(item, nodes.Lit) and not hosts.valid_cards(item.value)
                for item in nodes.walk(definition.body)):
            problems.append("invalid card literal")
        library._ensure_kind(definition.kind)
        checker = library._CHECKERS.get(definition.kind)
        if checker:
            problems += checker(definition, self)
        if definition.kind == "observation":
            granted = set(self.world.observation["capabilities"]["learner"]["probes"])
            direct = nodes.references(definition.body)
            transitive = {f"probe {probe} is not granted in {name}.reads"
                          for probe in granted - direct - set(definition.spec.reads)}
        else:
            transitive = set()
        problems = [problem for problem in problems if problem not in _COMPATIBLE_ARGUMENTS.get(name, ())
                    and problem not in transitive
                    and not (definition.kind == "observation" and
                             ("is not an observation" in problem or "unknown dependency" in problem))]
        if problems:
            raise PipelineError(problems)
        return self._advance(name, "checked")

    def make_callable(self, name, sample):
        if self.get(name).kind == "observation":
            from .adapter import run_observation
            for (state,) in sample:
                if isinstance(run_observation(self, name, state).outcome, Unknown):
                    raise PipelineError("observation sample exhausted fuel")
            return self._advance(name, "callable")
        return super().make_callable(name, sample)

    def verify(self, name, request):
        if self.get(name).kind == "observation":
            from .adapter import verify
            return verify(self, name, request)
        return super().verify(name, request)

    def run(self, name, args, fuel=None, trace=False):
        if not all(hosts.valid_cards(arg) for arg in args):
            return kernel.Run(Bottom("invalid"), 0, 0, None)
        return super().run(name, args, fuel=fuel, trace=trace)


def new_library():
    return MelodyLibrary(decl(), atoms())
