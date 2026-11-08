"""Small, deterministic probe domains for generator world adapters."""

from dataclasses import replace
from importlib import import_module
from itertools import islice

from opulse.atoms import LAYER0_KINDS
from opulse.atoms.spec import CombinatorSpec
from opulse.atoms.values import FALSE, TRUE, Card
from opulse.gen_v2.base import GenWorld, Signature, Sort

WORLD_TAGS = {
    "successor": ("math", ("compute", "counting")),
    "integer": ("math", ("compute", "counting", "equivalence")),
    "clock": ("time", ("compute", "counting")),
    "bits": ("logic", ("compute", "counting")),
    "strings": ("language", ("parsing", "compute")),
    "lists": ("program", ("compute", "counting")),
    "logic": ("logic", ("inference", "equivalence")),
    "perm": ("math", ("search", "equivalence")),
    "rel": ("math", ("inference", "search")),
    "grid": ("perception", ("geometry", "search")),
    "pitch": ("music", ("compute", "counting")),
    "action": ("agent", ("planning", "search")),
    "circuits": ("logic", ("compute", "equivalence")),
    "versions": ("program", ("planning", "equivalence")),
    "dice": ("probability", ("probability", "counting")),
    "rhythm": ("music", ("counting", "compute")),
    "hidden": ("social", ("inference", "strategy")),
    "grammar": ("language", ("parsing", "search")),
    "automata": ("program", ("compute", "search")),
    "calendar": ("time", ("counting", "compute")),
    "geometry": ("math", ("geometry", "compute")),
    "kitchen": ("resource", ("planning", "counting")),
    "melody": ("music", ("compute", "counting")),
    "molecules": ("math", ("search", "equivalence")),
    "permutation": ("math", ("search", "equivalence")),
    "pixels": ("perception", ("geometry", "search")),
    "roads": ("agent", ("planning", "search", "counting")),
    "shadows": ("perception", ("inference", "search")),
    "text": ("language", ("parsing", "compute")),
    "op_only": ("math", ("compute", "search")),
    "obs_only": ("perception", ("inference", "probability")),
    "obj_only": ("math", ("compute", "equivalence")),
    "comb_only": ("program", ("search", "compute")),
    "comb_obs": ("agent", ("planning", "inference")),
    "obj_op": ("time", ("compute", "counting")),
}

STAR_KINDS = {"dice": "observation", "hidden": "observation", "grammar": "combinator",
              "automata": "combinator", "lists": "object", "rhythm": "object",
              "action": "observation", "versions": "object"}


def world_tags(name, decl=None):
    """Describe a world for catalogue filtering, honoring declaration metadata."""
    domain, reasoning = WORLD_TAGS[name]
    open_kinds = (decl.extra.get("open_kinds") or getattr(decl, "open_kinds", LAYER0_KINDS)) if decl else LAYER0_KINDS
    tags = {"domain": domain, "modalities": ["text", "audio"] if domain == "music" else
            ["text", "image"] if domain == "perception" else ["text"],
            "open_kinds": list(open_kinds), "star_kind": STAR_KINDS.get(name, "operation"),
            "reasoning": list(reasoning), "state": "stateful" if name in
            ("action", "hidden", "versions", "automata") else "stateless",
            "outcomes": "probabilistic" if name == "dice" else "deterministic",
            "visibility": "partial" if name == "hidden" else "full",
            "agents": "2+" if name == "hidden" else 1,
            "scale": "up to 32 probe values per sort; target 300-1000 definitions",
            "difficulty": "introductory to advanced",
            "uses": ["teaching", "evaluation", "experiment"]}
    if decl:
        tags.update(decl.extra.get("world_tags") or decl.extra.get("tags") or {})
    tags["open_kinds"] = sorted(tags["open_kinds"])
    if tags["open_kinds"] and tags["star_kind"] not in tags["open_kinds"]:
        tags["star_kind"] = tags["open_kinds"][0]
    return tags


def _json_lists(value):
    if isinstance(value, dict):
        return {key: _json_lists(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_lists(item) for item in value]
    return value


def generator_decl(decl):
    """Represent fixed-field compose tags as pairs for the current core object builder."""

    objects = tuple(replace(obj, tags={tag: fields if isinstance(fields, dict) and
                                set(fields) == {"items"} else
                                list(fields.items()) if isinstance(fields, dict) else fields
                                for tag, fields in obj.tags.items()})
                    if obj.form == "compose" else obj for obj in decl.objects)
    return replace(decl, objects=objects,
                   open_kinds=tuple(decl.extra.get("open_kinds") or decl.open_kinds))


def signatures(decl):
    result = {op.name: Signature(tuple(edge.sort for edge in op.inputs), op.output.sort)
              for op in decl.operations}
    truth = decl.observation.get("truth")
    for probe in decl.observation.get("probes", ()):
        result.setdefault(probe["name"], Signature((probe.get("reads", truth),), probe["sort"]))
    return result


def ordered(values, limit=32):
    """Keep short, structurally simple values first without requiring hashable hosts."""
    unique = []
    for value in values:
        if not any(type(value) is type(other) and value == other for other in unique):
            unique.append(value)
    return tuple(sorted(unique, key=lambda value: (len(repr(value)), repr(value)))[:limit])


def truth_samples(values, count=24):
    return tuple(islice(values, count))


def build(name, decl, atoms, values, *, measures=None, bases=None, extra_scope=(),
          truth_states=None, probe_inputs=None, granted_probes=None, excluded_probes=(),
          finite_sorts=(), max_steps=400, max_scope=200):
    from opulse.atoms.kernel import Defn

    tags = world_tags(name, decl)
    declared_combinators = tuple(CombinatorSpec.from_dict({**entry, "body": _json_lists(entry["body"])})
                                 for entry in decl.combinators.get("library", ())
                                 if isinstance(entry, dict) and "body" in entry)
    resolved_combinators = {spec.name: spec.to_dict() for spec in declared_combinators}
    given = list(extra_scope)
    given.extend(Defn(spec.name, spec.params, spec.body, "combinator", 0)
                 for spec in declared_combinators if spec.name not in {item.name for item in given})
    named_combinators = [entry for entry in decl.combinators.get("library", ())
                         if isinstance(entry, str)]
    if named_combinators and decl.dialect == "atoms-v2":
        world_module = import_module(f"opulse.worlds_v2.{name}.world")
        library = world_module.new_library()
        for combinator in named_combinators:
            definition = library.definitions.get(combinator.removeprefix("@"))
            if definition and definition.kind == "combinator":
                if combinator not in {item.name for item in given}:
                    given.append(Defn(combinator, definition.spec.params, definition.body,
                                      "combinator", 0))
                resolved_combinators[combinator] = replace(definition.spec, name=combinator).to_dict()
            else:
                source = (decl.combinators.get("given_rules") or {}).get(combinator)
                if source is None:
                    source = next((item for item in decl.combinators.get("given", ())
                                   if isinstance(item, dict) and item["name"] == combinator), None)
                if source is None:
                    raise ValueError(f"{name}: missing given combinator {combinator}")
                spec = CombinatorSpec.from_dict({**source, "body": _json_lists(source["body"])})
                if combinator not in {item.name for item in given}:
                    given.append(Defn(combinator, spec.params, spec.body, "combinator", 0))
                resolved_combinators[combinator] = replace(spec, name=combinator).to_dict()
    extra_scope = tuple(given)
    decl = generator_decl(decl)
    if resolved_combinators:
        combinators = dict(decl.combinators)
        combinators["library"] = [resolved_combinators.get(
            entry["name"] if isinstance(entry, dict) else entry, entry)
            for entry in combinators.get("library", ())]
        decl = replace(decl, combinators=combinators)
    sigs = signatures(decl)
    excluded = set(excluded_probes)
    if excluded - {probe["name"] for probe in decl.observation.get("probes", ())}:
        raise ValueError(f"{name}: unknown excluded probe")
    for probe in sorted(excluded):
        sigs.pop(probe, None)
    atoms = tuple(atom for atom in atoms if atom.name not in excluded)
    for probe, inputs in (probe_inputs or {}).items():
        sigs[probe] = Signature((decl.observation["truth"], *inputs), sigs[probe].output)
    missing = set(sigs) - {atom.name for atom in atoms} - {defn.name for defn in extra_scope}
    if missing:
        raise ValueError(f"missing layer-zero atoms: {sorted(missing)}")
    used = {sort for sig in sigs.values() for sort in (*sig.inputs, sig.output)}
    values = dict(values)
    for obj in decl.objects:
        if obj.name in used and not values.get(obj.name):
            if obj.name in ("any", "Any", "unknown", "public", "value"):
                values[obj.name] = (0, 1, "a", "b")
            elif obj.name in ("str", "Text"):
                values[obj.name] = ("", "a", "b")
            elif obj.name in ("int", "Int", "Nat"):
                values[obj.name] = tuple(range(8))
            elif obj.name in ("bool", "Bool"):
                values[obj.name] = (FALSE, TRUE)
            else:
                values[obj.name] = (Card(obj.name, "sample", (0,)), Card(obj.name, "sample", (1,)))
    sorts = {obj.name: Sort(obj.name, ordered(values.get(obj.name, ())), sealed=obj.sealed,
                            interface=obj.interface, base=obj.base, doc=obj.extra.get("doc", ""),
                            finite=(obj.name in finite_sorts)
                            or (obj.name == "bool" and len(ordered(values.get(obj.name, ()))) == 2)
                            or (bool(obj.tags) and all(not fields for fields in obj.tags.values())
                                and {Card(obj.name, tag) for tag in obj.tags} ==
                                set(ordered(values.get(obj.name, ())))))
             for obj in decl.objects if obj.name in used or obj.name in values}
    for sort in sorted(used):
        if sort not in sorts or len(sorts[sort].values) < 2:
            raise ValueError(f"{name}: insufficient probe values for {sort}")
    truth = decl.observation.get("truth")
    probes = (tuple(granted_probes) if granted_probes is not None else
              tuple(probe["name"] for probe in decl.observation.get("probes", ())))
    atom_map = {atom.name: atom for atom in atoms}
    if any(atom_map[probe].kind != "observation" for probe in probes):
        raise ValueError(f"{name}: probes must be observation atoms")
    result = GenWorld(name, decl, atoms, sigs, sorts,
                    frozenset(decl.extra.get("open_kinds") or decl.open_kinds), truth,
                    tuple(truth_states) if truth_states is not None else
                    truth_samples(sorts[truth].values) if truth else (), probes,
                    measures or {}, bases or {}, decl.dialect, extra_scope=extra_scope,
                    max_steps=max_steps, max_scope=max_scope,
                    title=decl.extra.get("title", name))
    result.tags = tags
    return result


BOOL = (FALSE, TRUE)
