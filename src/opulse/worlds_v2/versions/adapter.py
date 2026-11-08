"""Version-specific object validation and public observation verification."""

from copy import deepcopy
from dataclasses import replace

from opulse.atoms import kernel, nodes
from opulse.atoms.check import check_definition
from opulse.atoms.library import Library, PipelineError
from opulse.atoms.spec import Evidence
from opulse.atoms.values import Bottom, Card, Ok, Unknown, outcome_equal
from opulse.worlds_v2.export_util import bound_evidence


class VersionsLibrary(Library):
    def _build_scope(self):
        from opulse.worlds_v2.versions import hosts

        scope = super()._build_scope()

        def valid_clash(value):
            return (isinstance(value, Card) and value.sort == "Clash" and value.tag == "clash"
                    and len(value.fields) == 4 and value.fields[0] in hosts.PATHS
                    and all(hosts.valid_text(item) for item in value.fields[1:])
                    and len(set(value.fields[1:])) == 3)

        def patch(path, old, new):
            if path not in hosts.PATHS or not hosts.valid_text(old) or not hosts.valid_text(new):
                return Bottom("invalid")
            return Card("Patch", "patch", (path, old, new))

        def merge(document, conflicts):
            if not hosts.valid_doc(document) or not isinstance(conflicts, tuple) or not all(
                    valid_clash(item) for item in conflicts) or tuple(sorted(
                        item.fields[0] for item in conflicts)) != tuple(item.fields[0] for item in conflicts) or len({
                            item.fields[0] for item in conflicts}) != len(conflicts) or any(
                                hosts.at(document, item.fields[0]) != item.fields[1] for item in conflicts):
                return Bottom("invalid")
            return Card("Merge", "merge", (document, conflicts))

        def replay(document, applied, blocked, conflicts):
            if (not hosts.valid_doc(document) or type(applied) is not int or applied < 0
                    or type(blocked) is not int or blocked not in (0, applied + 1)
                    or not isinstance(conflicts, tuple) or not all(valid_clash(item) for item in conflicts)
                    or bool(blocked) != bool(conflicts) or any(
                        hosts.at(document, item.fields[0]) != item.fields[1] for item in conflicts)
                    or tuple(sorted(item.fields[0] for item in conflicts)) != tuple(
                        item.fields[0] for item in conflicts) or len({
                            item.fields[0] for item in conflicts}) != len(conflicts)):
                return Bottom("invalid")
            return Card("Replay", "replay", (document, applied, blocked, conflicts))

        for sort, name, constructor in (("Patch", "patch", patch), ("Merge", "merge", merge),
                                        ("Replay", "replay", replay)):
            target = f"{sort}.{name}"
            if target in scope.atoms:
                scope.atoms[target] = kernel.Atom(target, scope.atoms[target].arity,
                                                  constructor, kind="object")
        return scope

    def _params(self, definition):
        if definition.kind == "observation":
            from opulse.worlds_v2.versions.story import SPECS
            return next(params for name, _, params, *_ in SPECS if name == definition.name)
        return super()._params(definition)

    def check(self, name):
        definition = self.get(name)
        problems = [problem for problem in check_definition(
                    definition, self.world,
                    lambda target: self._definitions.get(target) or self.scope().resolve(target))
                    if "expected Any" not in problem and "got Any" not in problem
                    and "expected unknown" not in problem and "got unknown" not in problem]
        if definition.kind == "object":
            from opulse.atoms.objects import check_object
            problems.extend(check_object(definition, self))
        if definition.kind == "combinator":
            from opulse.atoms.combinators import check_combinator
            problems.extend(check_combinator(definition, self))
        if definition.kind == "law":
            from opulse.atoms.laws import check_law
            problems.extend(check_law(definition, self))
        if definition.kind == "observation" and definition.body != definition.spec.body:
            problems.append("observation body differs from public rule")
        if problems:
            raise PipelineError(problems)
        return self._advance(name, "checked")

    def make_callable(self, name, sample):
        definition = self.get(name)
        if definition.kind != "observation":
            return super().make_callable(name, sample)
        if definition.status != "checked" or not sample:
            raise PipelineError("checked definition needs samples")
        scope = self.scope().extend([kernel.Defn(name, tuple(self._params(definition)), definition.body,
                                                 definition.kind, definition.layer)])
        self._steps[name] = [kernel.call(name, args, scope).steps for args in sample]
        return self._advance(name, "callable")

    def verify(self, name, request):
        definition = self.get(name)
        if definition.kind in ("object", "observation") and (
                request.method not in ("exhaustive", "bounded", "sampled") or
                request.method == "sampled" and request.seed is None or
                not request.domain or request.scope.get("size") != len(request.domain) or
                not request.scope.get("domain")):
            raise PipelineError("finite verification needs a method and exact domain scope")
        if definition.kind == "object":
            if request.reference is None:
                raise PipelineError("object construction needs an independent reference")
            if definition.status != "callable":
                raise PipelineError("object construction needs callable status")
            steps = []
            for args in request.domain:
                actual = self.run(f"{definition.spec.name}.{name}", args)
                expected = request.reference(*args)
                if not isinstance(expected, (Ok, Bottom, Unknown)):
                    expected = Ok(expected)
                if not outcome_equal(actual.outcome, expected):
                    raise PipelineError(f"{name}: generated constructor differs from reference at {args!r}")
                steps.append(actual.steps)
            self._steps[name] = steps
            evidence = Evidence(request.method, dict(request.scope), request.seed,
                                ("construction", "reference"), self.world.world_hash(), self._deps_hash(name))
            self._definitions[name] = replace(definition, evidence=bound_evidence(
                self, name, evidence, request.domain))
            return self._advance(name, "verified")
        if definition.kind != "observation":
            return super().verify(name, request)
        if definition.status != "callable" or request.reference is None:
            raise PipelineError("finite verification requires a callable reference")
        steps = []
        observed = []
        for args in request.domain:
            before = deepcopy(args)
            result = self.run(name, args)
            expected = request.reference(*args)
            if not isinstance(expected, (Ok, Bottom, Unknown)):
                expected = Ok(expected)
            inline = kernel.evaluate(kernel.inline(nodes.Call(name, tuple(nodes.Lit(arg) for arg in args)),
                                                   self.scope()), scope=self.scope())
            if isinstance(result.outcome, Unknown) or not outcome_equal(result.outcome, expected) or not outcome_equal(result.outcome, inline.outcome) or result.steps != inline.steps or args != before:
                raise PipelineError(f"{name}: reference, immutability or unfolding failed for {args!r}: {result.outcome!r} != {expected!r}")
            if definition.kind == "observation":
                from opulse.worlds_v2.versions.hosts import read, valid_doc
                public = tuple(read(arg) if valid_doc(arg) else arg for arg in args)
                if any(view == public and not outcome_equal(outcome, result.outcome)
                       for view, outcome in observed):
                    raise PipelineError(f"{name}: non_interference failed")
                observed.append((public, result.outcome))
            steps.append(result.steps)
        checks = (("dependency", "facts_unchanged", "non_interference", "reference", "unfold_equivalence")
                  if definition.kind == "observation" else ("unfold_equivalence", "reference"))
        evidence = Evidence(request.method, dict(request.scope), request.seed, checks,
                            self.world.world_hash(), self._deps_hash(name))
        self._steps[name] = steps
        self._definitions[name] = replace(definition, evidence=bound_evidence(self, name, evidence, request.domain))
        return self._advance(name, "verified")
