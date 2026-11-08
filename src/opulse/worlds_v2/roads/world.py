"""Locked public twelve-junction road world and its counted primitives."""

import json
import weakref
from dataclasses import replace
from pathlib import Path

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.check import check_definition
from opulse.atoms.combinators import check_combinator
from opulse.atoms.library import Library, PipelineError
from opulse.atoms.objects import check_object
from opulse.atoms.spec import Definition, Edge, Evidence, OperationSpec
from opulse.atoms.values import Bottom, Ok, outcome_equal
from opulse.atoms.world import WorldDecl
from opulse.worlds_v2.export_util import bound_evidence

from . import depth_hosts


def decl():
    path = Path(__file__).resolve().parents[4] / "worlds/decl/v2/roads@1.json"
    return WorldDecl.from_dict(json.loads(path.read_text(encoding="utf-8")))


class RoadsLibrary(Library):
    def __init__(self, world, atoms):
        super().__init__(world, atoms)
        self._minted_routes = weakref.WeakValueDictionary()
        self._minted_closures = weakref.WeakValueDictionary()

    def _build_scope(self):
        scope = super()._build_scope()
        for name, minted in (("Route", self._minted_routes), ("Closure", self._minted_closures)):
            pack = scope.atoms.get(f"{name}._pack")
            stored = scope.atoms.get(f"{name}._stored")
            if pack is None or stored is None:
                continue

            def record(raw, pack=pack, minted=minted):
                made = pack.fn(raw)
                minted[id(made)] = made
                return made

            def checked_stored(value, stored=stored, minted=minted):
                if not getattr(self, "_verifying", False) and minted.get(id(value)) is not value:
                    return Bottom("invalid")
                return stored.fn(value)

            scope.atoms[pack.name] = replace(pack, fn=record)
            scope.atoms[stored.name] = replace(stored, fn=checked_stored)
        return scope

    def visible(self, context, graph):
        if not isinstance(graph, depth_hosts.Card) or graph.sort != "Closure":
            if not depth_hosts.valid_graph(graph):
                return Bottom("invalid_graph")
            return context.call("roads_from_parts", graph.fields)
        if not getattr(self, "_verifying", False) and self._minted_closures.get(id(graph)) is not graph:
            return Bottom("invalid_closure")
        base = context.call("Closure.base", (graph,))
        if not isinstance(base, Ok):
            return base
        closed = context.call("Closure.closed_edges", (graph,))
        if not isinstance(closed, Ok):
            return closed
        raw_graph = context.call("ClosureRaw.base", (base.value,))
        if not isinstance(raw_graph, Ok):
            return raw_graph
        return context.call("filter_closed", (raw_graph.value, closed.value), (kernel.Defn(
            "filter_closed", ("graph", "blocked"), n.Call("roads_from_parts", (
                n.Call("graph_nodes", (n.Var("graph"),)),
                n.Rec("keep", ("remaining", "result"),
                      n.Case(((n.Test(n.Call("empty", (n.Var("remaining"),))),
                               n.Call("reverse", (n.Var("result"),))),),
                             n.Call("keep", (n.Call("tail", (n.Var("remaining"),)),
                                             n.Case(((n.Test(n.Call("contains", (
                                                 n.Call("edge_id", (n.Call("head", (n.Var("remaining"),)),)),
                                                 n.Call("Edges.edge_ids", (n.Var("blocked"),))))),
                                                      n.Var("result")),),
                                                    n.Call("cons", (n.Call("head", (n.Var("remaining"),)),
                                                                    n.Var("result"))))))),
                      (n.Call("graph_edges", (n.Var("graph"),)), n.Lit(depth_hosts.items())),
                      n.Call("size", (n.Var("remaining"),))))), "operation", 1),))

    def road_nodes(self, context, graph):
        if isinstance(graph, depth_hosts.Card) and graph.sort == "Closure":
            view = context.call("map_view", (graph,))
            if not isinstance(view, Ok):
                return view
            graph = view.value
        return context.call("road_nodes", (graph,))

    def road_edge(self, context, graph, start, end):
        if isinstance(graph, depth_hosts.Card) and graph.sort == "Closure":
            view = context.call("map_view", (graph,))
            if not isinstance(view, Ok):
                return view
            graph = view.value
        return context.call("road_edge", (graph, start, end))

    def get(self, name):
        try:
            return super().get(name)
        except KeyError:
            parent = name.split(".")[0]
            if parent not in self._definitions or self._definitions[parent].kind != "object":
                raise
            generated = self.scope().resolve(name)
            if generated is None:
                raise
            arity = generated.arity if isinstance(generated, kernel.Atom) else len(generated.params)
            spec = OperationSpec(name, "transform", tuple(Edge("unknown") for _ in range(arity)),
                                 Edge("unknown"), "Core-generated object operation.")
            return Definition(name, "operation", "given", 0, (parent,), spec,
                              {"generated": name}, status="promoted")

    def check(self, name):
        definition = self.get(name)
        problems = check_definition(definition, self.world,
                                    lambda reference: self.definitions.get(reference) or self.scope().resolve(reference))
        problems = [problem for problem in problems if "got unknown" not in problem
                    and "expected unknown" not in problem
                    and not ("expected Roads, got Closure" in problem and definition.name == "cut_certificate")
                    and not (problem.startswith("layer must be") and any("." in dep for dep in definition.depends_on))]
        if definition.kind == "object":
            problems.extend(check_object(definition, self))
        if definition.kind == "combinator":
            problems.extend(check_combinator(definition, self))
        if (definition.kind == "observation"
                and ("map_view" not in definition.spec.reads or definition.body != definition.spec.body)):
            problems.append("observation must use the declared public map probe")
        if problems:
            raise PipelineError(problems)
        return self._advance(name, "checked")

    def _params(self, definition):
        if definition.kind == "observation":
            return {"optimal": ("r",), "survives": ("g", "s", "target", "b"),
                    "cut_certificate": ("g", "s", "target")}[definition.name]
        return super()._params(definition)

    def make_callable(self, name, sample):
        if self.get(name).kind != "observation":
            return super().make_callable(name, sample)
        definition = self.get(name)
        if definition.status != "checked":
            raise PipelineError("observation must be checked first")
        scope = self.scope().extend([kernel.Defn(name, self._params(definition), definition.body,
                                                  "observation", definition.layer)])
        for args in sample:
            run = kernel.call(name, args, scope, kernel.Limits(fuel=500_000))
            if not isinstance(run.outcome, (Ok, Bottom)):
                raise PipelineError(f"observation sample failed: {run.outcome!r}")
        return self._advance(name, "callable")

    def verify(self, name, request):
        if self.get(name).kind != "observation":
            self._verifying = True
            try:
                return super().verify(name, request)
            finally:
                self._verifying = False
        if request.scope.get("size") != len(request.domain) or request.reference is None:
            raise PipelineError("observation needs exact bounded public-state reference")
        steps = []
        for args in request.domain:
            before = repr(args)
            actual = self.run(name, args, fuel=1_000_000)
            expected = request.reference(*args)
            if not outcome_equal(actual.outcome, expected if isinstance(expected, (Ok, Bottom)) else Ok(expected)):
                raise PipelineError(f"observation reference mismatch: {name} {args!r}")
            if repr(args) != before:
                raise PipelineError("observation mutated public facts")
            copied = tuple(depth_hosts.to_card(depth_hosts.from_card(arg)) if isinstance(arg, depth_hosts.Card)
                           and arg.sort == "Roads" else arg for arg in args)
            if not outcome_equal(actual.outcome, self.run(name, copied, fuel=1_000_000).outcome):
                raise PipelineError("identical public maps gave different observations")
            steps.append(actual.steps)
        definition = self.get(name)
        self._steps[name] = steps
        self._definitions[name] = replace(definition, evidence=bound_evidence(self, name, Evidence(
            request.method, dict(request.scope), request.seed,
            ("dependency", "facts_unchanged", "non_interference", "reference"),
            self.world.world_hash(), self._deps_hash(name)), request.domain))
        return self._advance(name, "verified")


def atoms():
    world = decl()
    given = [kernel.Atom(op.name, len(op.inputs),
                          getattr(depth_hosts, op.impl["host"].split(":")[1]),
                          op.cost, kind="observation" if op.name in ("map_view", "size") else "operation",
                          strict=op.strict, metered=op.name == "map_view")
             for op in world.operations]
    return given


def new_library():
    library = RoadsLibrary(decl(), atoms())
    library_ref = weakref.ref(library)

    def visible(context, graph):
        return library_ref().visible(context, graph)

    def road_nodes(context, graph):
        return library_ref().road_nodes(context, graph)

    def road_edge(context, graph, start, end):
        return library_ref().road_edge(context, graph, start, end)

    wrapped = {"map_view": visible, "graph_nodes": road_nodes, "edge": road_edge}
    library.atoms = tuple(replace(atom, fn=wrapped[atom.name], metered=True)
                          if atom.name in wrapped else atom
                          for atom in library.atoms)
    return library
