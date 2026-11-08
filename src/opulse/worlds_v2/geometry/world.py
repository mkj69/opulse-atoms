"""Locked geometry declaration and its layer-zero atoms."""

import json
from dataclasses import replace
from pathlib import Path

from opulse.atoms import kernel, nodes
from opulse.atoms.check import check_definition
from opulse.atoms.combinators import check_combinator
from opulse.atoms.kernel import Atom
from opulse.atoms.library import Library, PipelineError
from opulse.atoms.objects import check_object
from opulse.atoms.values import Bottom, Card, Ok
from opulse.atoms.world import WorldDecl

from . import hosts

DECL_PATH = Path(__file__).resolve().parents[4] / "worlds/decl/v2/geometry@1.json"


def decl() -> WorldDecl:
    return WorldDecl.from_dict(json.loads(DECL_PATH.read_text(encoding="utf-8")))


def atoms() -> list[Atom]:
    world = decl()
    return ([Atom(op.name, len(op.inputs), getattr(hosts, op.name), op.cost, strict=op.strict)
             for op in world.operations]
            + [Atom(probe["name"], 1, getattr(hosts, probe["name"]), 1, kind="observation")
               for probe in world.observation["probes"]])


class GeometryLibrary(Library):
    def _valid_card(self, value, scope):
        if isinstance(value, tuple):
            return all(self._valid_card(item, scope) for item in value)
        if not isinstance(value, Card):
            return True
        if value.sort == "Point":
            return hosts.valid_point(value)
        if value.sort == "Path":
            return (value.tag == "points" and len(value.fields) <= 24 and
                    all(hosts.valid_point(vertex) for vertex in value.fields))
        if value.sort == "List":
            return value.tag == "items" and all(self._valid_card(item, scope) for item in value.fields)
        if value.sort == "bool":
            return value.tag in ("true", "false") and not value.fields
        if value.sort == "RegionPair":
            try:
                if value in self._validated_cards:
                    return True
            except TypeError:
                return False
            if value.tag != "shape" or len(value.fields) != 2:
                return False
            outer, holes = value.fields
            if (not isinstance(holes, tuple) or len(holes) > self.world.params["max_holes"] or
                    not isinstance(outer, Card) or outer.sort != "Ring" or
                    not self._valid_card(outer, scope) or
                    not all(isinstance(hole, Card) and hole.sort == "Ring" and
                            self._valid_card(hole, scope) for hole in holes)):
                return False
            self._validated_cards.add(value)
            return True
        if value.sort in ("Ring", "Region", "Signature", "TranslationCanon", "DihedralCanon"):
            try:
                if value in self._validated_cards:
                    return True
            except TypeError:
                return False
            if value.tag != "val" or len(value.fields) != 1 or not self._valid_card(value.fields[0], scope):
                return False
            if value.sort not in self._definitions or self.get(value.sort).status not in (
                    "callable", "verified", "promoted"):
                return False
            result = kernel.call(value.sort + ".make", value.fields, scope, dialect=self.dialect).outcome
            if not isinstance(result, Ok) or result.value != value:
                return False
            self._validated_cards.add(value)
            return True
        return False

    def scope(self):
        scope = super().scope()
        world_hash = self.world.world_hash()
        if getattr(self, "_validation_world", None) != world_hash:
            self._validated_cards = set()
            self._validation_world = world_hash
        original_points = scope.atoms.get("points")
        stored_ring = scope.atoms.get("Ring._stored")
        if stored_ring is not None:
            def ring_stored(value):
                if (not isinstance(value, Card) or value.sort != "Ring" or value.tag != "val" or
                        len(value.fields) != 1 or not isinstance(value.fields[0], tuple) or
                        len(value.fields[0]) > self.world.params["max_vertices"] or
                        not all(hosts.valid_point(vertex) for vertex in value.fields[0])):
                    return Bottom("invalid")
                return value.fields[0]

            scope.atoms["Ring._stored"] = kernel.Atom("Ring._stored", 1, ring_stored,
                                                      stored_ring.cost, kind="object")
        if original_points is not None:
            def safe_points(value):
                is_region_input = (isinstance(value, Card) and value.sort in ("Ring", "Region") or
                                   isinstance(value, tuple) and len(value) == 2 and
                                   isinstance(value[0], Card) and value[0].sort == "Region")
                if is_region_input:
                    return value if self._valid_card(value, scope) else Bottom("invalid")
                return original_points.fn(value)

            scope.atoms["points"] = kernel.Atom("points", 1, safe_points, original_points.cost,
                                                 kind="observation")
        shape = scope.atoms.get("RegionPair.shape")
        if shape is not None:
            def safe_shape(outer, holes):
                if (not isinstance(holes, tuple) or len(holes) > self.world.params["max_holes"] or
                        not isinstance(outer, Card) or outer.sort != "Ring" or
                        any(not isinstance(hole, Card) or hole.sort != "Ring" for hole in holes) or
                        not all(self._valid_card(item, scope) for item in (outer, *holes))):
                    return Bottom("invalid")
                return shape.fn(outer, holes)

            scope.atoms["RegionPair.shape"] = kernel.Atom("RegionPair.shape", 2, safe_shape,
                                                           shape.cost, kind="object")
        for definition in self._definitions.values():
            if definition.kind != "operation" or definition.origin != "invented":
                continue
            for position, edge in self._operation_edges(definition.spec):
                if edge.enter != "bottom" or edge.sort not in ("Ring", "Region", "Signature"):
                    continue
                name = self._edge_name(definition.name, position)
                original = scope.atoms.get(name)
                if original is None:
                    continue

                def cached_entry(context, value, *, original=original, sort=edge.sort):
                    if isinstance(value, Card) and value.sort == sort:
                        return value if self._valid_card(value, scope) else Bottom("invalid")
                    return original.fn(context, value)

                scope.atoms[name] = kernel.Atom(name, 1, cached_entry, original.cost,
                                                kind="object", metered=True)
        for sort in ("Ring", "Region", "Signature", "TranslationCanon", "DihedralCanon"):
            name = sort + ".base"
            if name not in scope.defns:
                continue

            def checked_base(value, *, expected=sort):
                if not isinstance(value, Card) or value.sort != expected or not self._valid_card(value, scope):
                    return Bottom("invalid")
                return value.fields[0]

            scope.defns.pop(name)
            scope.atoms[name] = kernel.Atom(name, 1, checked_base, kind="object")
        for definition in self._definitions.values():
            if definition.origin == "invented" and definition.kind == "observation" and definition.status in (
                    "callable", "verified", "promoted"):
                scope.defns[definition.name] = kernel.Defn(definition.name, ("r",), definition.body,
                                                            "observation", definition.layer)
        return scope

    def run(self, name, args, fuel=None, trace=False):
        if name.endswith(("._pack", "._canon_free")):
            return kernel.Run(Bottom("invalid"), 0, 0, None)
        scope = self.scope()
        if not all(self._valid_card(arg, scope) for arg in args):
            return kernel.Run(Bottom("invalid"), 0, 0, None)
        return super().run(name, args, fuel=fuel, trace=trace)

    def replace(self, name, definition, force_new_version=False):
        result = super().replace(name, definition, force_new_version=force_new_version)
        self._validated_cards.clear()
        return result

    def get(self, name):
        if name.startswith(("Ring.", "Region.", "RegionPair.", "Signature.")) and name not in self._definitions:
            return super().get(name.split(".", 1)[0])
        return super().get(name)

    def check(self, name):
        if self.get(name).kind == "template":
            return super().check(name)
        generated = {}
        for object_name in ("Ring", "Region", "RegionPair", "Signature"):
            obj = self._definitions.get(object_name)
            if obj is None:
                continue
            for generated_name in (f"{object_name}.make", f"{object_name}.base", f"{object_name}.shape",
                                   f"{object_name}.outer", f"{object_name}.holes"):
                if generated_name not in self._definitions:
                    generated[generated_name] = replace(obj, name=generated_name)
        self._definitions.update(generated)
        try:
            definition = self._definitions[name]
            problems = check_definition(definition, self.world, self._definitions.get)
            generic = ("eq argument", "cons argument", "singleton argument")
            indexed = ("cross argument", "at argument", "head argument", "twice_area argument",
                       "x argument", "y argument", "segments_meet argument", "boundary_lattice argument",
                       "_locate argument", "_boundaries_meet argument", "le argument", "sub argument",
                       "move argument", "maximum argument", "minimum argument")
            problems = [problem for problem in problems
                        if not (problem.startswith(generic) or problem.startswith(indexed) and
                                problem.endswith(("got List", "got unknown")) or
                                problem.startswith(tuple(f"d4_{index} argument" for index in range(8))) and
                                problem.endswith("got List"))]
            if definition.kind == "object":
                object_problems = check_object(definition, self)
                problems += [problem for problem in object_problems
                             if not (problem.startswith(generic) or
                                     problem.startswith(indexed) and
                                     problem.endswith(("got List", "got unknown")) or
                                     problem.startswith(tuple(f"d4_{index} argument" for index in range(8))) and
                                     problem.endswith("got List"))]
            if definition.kind == "combinator":
                problems += check_combinator(definition, self)
            if (definition.kind == "observation" and
                    (definition.spec.reads != ("points",) or "points" not in nodes.references(definition.body))):
                problems.append("geometry observations must read the granted points probe")
            if problems:
                raise PipelineError(problems)
            return self._advance(name, "checked")
        finally:
            for generated_name in generated:
                self._definitions.pop(generated_name, None)

    def make_callable(self, name, sample):
        if self.get(name).kind == "observation":
            from . import adapter
            return adapter.make_callable(self, name, sample)
        return super().make_callable(name, sample)

    def verify(self, name, request):
        if name == "RegionPair":
            from . import adapter
            return adapter.verify_region_pair(self, name, request)
        if self.get(name).kind == "observation":
            from . import adapter
            return adapter.verify(self, name, request)
        if name == "congruent":
            from . import adapter
            return adapter.verify_heavy_operation(self, name, request)
        return super().verify(name, request)


def new_library() -> Library:
    return GeometryLibrary(decl(), atoms())
