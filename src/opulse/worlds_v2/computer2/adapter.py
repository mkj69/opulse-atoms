"""Local observation hook for immutable byte-machine truth (spec section 9)."""

from dataclasses import replace

from opulse.atoms import kernel, nodes
from opulse.atoms.check import check_definition
from opulse.atoms.library import Library, PipelineError, atoms_digest
from opulse.atoms.observations import check_observation
from opulse.atoms.spec import Edge, Evidence, OperationSpec, content_hash
from opulse.atoms.values import Bottom, Ok, Unknown, outcome_equal

from . import hosts


# ADAPTER: delete when core provides a world-neutral parameterized observation hook.
class ComputerLibrary(Library):
    def _memory_ranges(self):
        capabilities = self.world.observation["capabilities"].get(
            getattr(self, "agent", "learner"), {})
        return capabilities.get("memory_ranges", ())

    def scope(self):
        scope = super().scope()
        sequence = nodes.Call("g", (nodes.Call("f", (nodes.Var("s"),)),))
        scope.defns["@seq"] = kernel.Defn("@seq", ("f", "g", "s"), sequence,
                                           "combinator", 0)
        ranges = self._memory_ranges()
        if "?mem" in scope.atoms:
            probe = scope.atoms["?mem"]

            def granted_memory(machine, addr):
                if type(addr) is not int or not any(start <= addr <= end for start, end in ranges):
                    return Bottom("permission")
                return hosts.mem(machine, addr)

            scope.atoms["?mem"] = replace(probe, fn=granted_memory)
        return scope

    def run(self, name, args, fuel=None, trace=False):
        capabilities = self.world.observation["capabilities"].get(
            getattr(self, "agent", "learner"), {})
        granted = capabilities.get("probes", ())
        probes = {probe["name"] for probe in self.world.observation["probes"]}
        if name in probes and granted != "all" and name not in granted:
            return kernel.Run(Bottom("permission"), 0, 0, None)
        if (name in ("?at", "?mem") and
                (len(args) != 2 or type(args[1]) is not int or
                 not any(start <= args[1] <= end for start, end in self._memory_ranges()))):
            return kernel.Run(Bottom("permission"), 0, 0, None)
        return super().run(name, args, fuel=fuel, trace=trace)

    def account(self, name):
        definition = super().account(name)
        if definition.kind == "object" and definition.spec.valid is not None:
            length = nodes.length(definition.spec.valid)
            if definition.spec.canon is not None:
                length += nodes.length(definition.spec.canon)
            self._definitions[name] = replace(definition, cost=replace(definition.cost, length=length))
            return self.get(name)
        return definition

    def _deps_hash(self, name):
        seen = set()

        def collect(current):
            if current in seen or current not in self.definitions:
                return
            seen.add(current)
            definition = self.get(current)
            for dependency in definition.depends_on:
                collect(dependency)
            if isinstance(definition.body, nodes.NODE_TYPES):
                for item in nodes.walk(definition.body):
                    if isinstance(item, nodes.Lit) and isinstance(item.value, kernel.FnRef):
                        collect(item.value.name)

        collect(name)
        return content_hash({"declared": super()._deps_hash(name),
                             "fixed_slots": {item: self.get(item).to_dict() for item in sorted(seen - {name})}})

    def _params(self, definition):
        if definition.kind == "observation":
            from .story import OBS_PARAMS

            return OBS_PARAMS.get(definition.name, ())
        return super()._params(definition)

    def check(self, name):
        definition = self.get(name)
        if definition.status != "written":
            raise PipelineError("check requires written status")
        if definition.kind == "observation":
            if definition.body != definition.spec.body:
                raise PipelineError("observation body differs from spec")
            authorized = {probe["name"] for probe in self.world.observation["probes"]}
            if not set(definition.spec.reads) <= authorized:
                raise PipelineError("observation reads ungranted probe")
        generated = []
        for atom in self.scope().atoms.values():
            if atom.name not in self._definitions:
                generated.append(OperationSpec(atom.name, "transform",
                                               tuple(Edge("any") for _ in range(atom.arity)),
                                               Edge("any"), "Generated object interface."))
        for item in self.scope().defns.values():
            if item.name not in self._definitions:
                generated.append(OperationSpec(item.name, "transform",
                                               tuple(Edge("any") for _ in item.params),
                                               Edge("any"), "Generated object interface."))
        world = replace(self.world, operations=self.world.operations + tuple(generated))
        problems = [problem for problem in check_definition(definition, world, self._definitions.get)
                    if not any(narrowing in problem for narrowing in
                               ("expected Reg, got str", "expected Byte, got int",
                                "expected Addr, got int", "expected int, got bool",
                                "expected Byte, got bool", "expected unknown, got",
                                "expected any, got", "expected int, got unknown",
                                "expected Byte, got unknown", "expected Byte, got any",
                                "expected int, got Byte", "recursion measure must be int, got unknown",
                                "recursion measure must be int, got Byte",
                                "expected int, got any", "expected Addr, got any",
                                "expected int, got Addr"))]
        problems = [problem for problem in problems if not
                    (problem.startswith("layer must be ") and
                     any(dependency.startswith(("Vec.", "Wide.")) for dependency in definition.depends_on))]
        if definition.kind == "combinator":
            from opulse.atoms.combinators import check_combinator

            problems += check_combinator(definition, self)
        if definition.kind == "object":
            from opulse.atoms.objects import check_object

            problems += [problem for problem in check_object(definition, self)
                         if not any(narrowing in problem for narrowing in
                                    ("expected int, got Addr", "expected int, got Byte"))]
        if problems:
            raise PipelineError([f"{name}: {problem}" for problem in problems])
        return self._advance(name, "checked")

    def make_callable(self, name, sample):
        if self.get(name).kind != "observation":
            return super().make_callable(name, sample)
        definition = self.get(name)
        if definition.status != "checked" or not sample:
            raise PipelineError("observation requires checked status and sample")
        scope = self.scope().extend([kernel.Defn(name, self._params(definition), definition.body,
                                                  "observation", definition.layer)])
        for args in sample:
            if isinstance(kernel.call(name, args, scope).outcome, Unknown):
                raise PipelineError("observation sample exhausted resources")
        return self._advance(name, "callable")

    def verify(self, name, request):
        definition = self.get(name)
        if definition.kind != "observation":
            return super().verify(name, request)
        if definition.status != "callable" or not request.domain or request.scope.get("size") != len(request.domain):
            raise PipelineError("observation verification requires exact nonempty scope")
        if name == "?at" and any(addr not in hosts.MEMORY_GRANTS for _, addr in request.domain):
            raise PipelineError("observation scope exceeds granted memory")
        dependency_problems = check_observation(definition, self)
        if dependency_problems:
            raise PipelineError([f"{name}: {problem}" for problem in dependency_problems])
        steps = []
        for args in request.domain:
            before = tuple(args)
            actual = self.run(name, args)
            expected = request.reference(*args)
            expected = expected if isinstance(expected, Ok) else Ok(expected)
            if not outcome_equal(actual.outcome, expected) or tuple(args) != before:
                raise PipelineError("observation changed truth or disagreed with reference")
            if name == "?at":
                machine, addr = args
                memory = list(hosts.fields(machine)[1])
                memory[0] = (memory[0] + 1) % 256
                registers = hosts.fields(machine)[0]
                changed = (*registers[:3], (registers[3] + 1) % 256)
                equivalent = hosts.replace_state(machine, mem=memory, regs=changed)
                if (self.run("?mem", (machine, addr)).outcome !=
                        self.run("?mem", (equivalent, addr)).outcome or
                        not outcome_equal(actual.outcome, self.run(name, (equivalent, addr)).outcome)):
                    raise PipelineError("non-interference failed for probe-equivalent machines")
            if name == "?dot_wrap":
                machine, left, right = args
                memory = list(hosts.fields(machine)[1])
                memory[0] = (memory[0] + 1) % 256
                registers = hosts.fields(machine)[0]
                changed = (*registers[:3], (registers[3] + 1) % 256)
                equivalent = hosts.replace_state(machine, mem=memory, regs=changed)
                if not outcome_equal(actual.outcome, self.run(name, (equivalent, left, right)).outcome):
                    raise PipelineError("non-interference failed for probe-equivalent machines")
            inline = kernel.evaluate(kernel.inline(nodes.Call(name, tuple(nodes.Lit(arg) for arg in args)),
                                                    self.scope()), scope=self.scope())
            if not outcome_equal(actual.outcome, inline.outcome) or actual.steps != inline.steps:
                raise PipelineError("observation unfold mismatch")
            steps.append(actual.steps)
        checks = ("dependency", "facts_unchanged", "non_interference", "reference", "unfold_equivalence")
        from opulse.atoms.library import checked_scope

        evidence = Evidence(request.method, {**request.scope, "checked": checked_scope(request.domain)},
                            request.seed, checks,
                            self.world.world_hash(), self._deps_hash(name),
                            self.content_hash(name), atoms_digest(self.atoms))
        self._steps[name] = steps
        self._definitions[name] = replace(definition, evidence=evidence)
        return self._advance(name, "verified")
