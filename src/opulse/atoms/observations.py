"""Declarable observations and sealed truth (spec sections 7 and 11.I3)."""

from __future__ import annotations

from collections.abc import Sequence
from copy import deepcopy

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.check import all_dependencies
from opulse.atoms.library import VerifyResult
from opulse.atoms.spec import BridgeSpec, CombinatorSpec, ObservationSpec, OperationSpec
from opulse.atoms.values import Bottom, Ok, Unknown, outcome_equal, value_equal
from opulse.core.semantics import NAN


def robot_probe_atoms() -> list[kernel.Atom]:
    """Expose the robot's given observations and actions at their legacy costs."""
    from opulse.worlds import action

    return [kernel.Atom(name, 1, lambda state, probe=name: action.apply_atom(probe, state),
                        kind="observation" if name in action.OBS_RULES else "operation")
            for name in (*action.OBS_RULES, *action.ACTION_RULES)]


def _probes(lib):
    scope = lib.scope()
    return {item["name"] for item in lib.world.observation.get("probes", ())
            if item["name"] in scope.atoms and scope.atoms[item["name"]].kind == "observation"}


def _granted(lib):
    capabilities = lib.world.observation.get("capabilities", {}).get(getattr(lib, "agent", "learner"), {})
    if isinstance(capabilities, dict):
        capabilities = capabilities.get("probes", "all")
    return _probes(lib) if capabilities == "all" else set(capabilities)


def _strip_subject(node, subject: str, names) -> object:
    """``?p{s}`` is ``Call(p, (Var(s),))``; probe values are computed once per state, so the run
    calls probes and observations without the subject (spec 18.3)."""
    def strip(expr):
        if isinstance(expr, n.Call) and expr.fn in names and expr.args == (n.Var(subject),):
            return n.Call(expr.fn, ())
        return expr

    return n.map_nodes(node, strip, stop_at=(n.Blocks,))


def _observation_names(lib) -> set[str]:
    stored = getattr(lib, "records", lambda: getattr(lib, "definitions", {}))()
    return _probes(lib) | {name for name, defn in stored.items() if defn.kind == "observation"}


def _inputs(defn):
    return tuple(defn.spec.extra.get("inputs", ()))


def _public(defn):
    return "inputs" in defn.spec.extra


def _records(lib):
    return getattr(lib, "records", lambda: getattr(lib, "definitions", {}))()


def check_observation(defn, lib) -> list[str]:
    problems = []
    if defn.body != defn.spec.body:
        problems.append("observation body differs from its declared body")
    truth_sort = lib.world.observation.get("truth")
    inputs = _inputs(defn)
    if any(not isinstance(pair, (tuple, list)) or len(pair) != 2 or
           not isinstance(pair[0], str) or not pair[0] or
           not isinstance(pair[1], str) or not pair[1] or pair[1] == truth_sort for pair in inputs):
        problems.append("observation inputs must be named public sorts")
        return problems
    elif len({name for name, _ in inputs}) != len(inputs):
        problems.append("observation input names must be unique")
    if _public(defn) and (defn.spec.reads or defn.spec.memory):
        problems.append("public observation cannot read probes or memory")
    probes = _probes(lib)
    granted = _granted(lib)
    seen = set()

    world_ops = {op.name: op for op in lib.world.operations}
    if hasattr(lib.world, "world") and hasattr(lib.world, "version"):
        source_id = f"{lib.world.world}@{lib.world.version}"
        world_ops.update({f"{source_id}:{op.name}": op for op in lib.world.operations})
    for attached_id, attached in getattr(lib, "_attached_worlds", {}).items():
        for operation in attached.world.operations:
            world_ops.setdefault(operation.name, operation)
            world_ops[f"{attached_id}:{operation.name}"] = operation
    records = _records(lib)

    def inspect_dependency(name):
        if name in probes:
            if name not in defn.spec.reads or name not in granted:
                problems.append(f"probe {name} is not granted in {defn.name}.reads")
            return
        operation = world_ops.get(name)
        if operation is not None and (operation.role == "act" or
                                      truth_sort and any(edge.sort == truth_sort for edge in operation.inputs)):
            problems.append(f"operation {name} may read or change truth")
        dependency = records.get(name)
        if dependency is None:
            target = lib.scope().resolve(name)
            if operation is None and target is None:
                problems.append(f"unknown dependency {name}")
            if isinstance(target, kernel.Defn) and name not in seen:
                seen.add(name)
                for child in n.all_dependencies(target.body) - {name}:
                    inspect_dependency(child)
            return
        if dependency.kind == "observation" and isinstance(dependency.spec, ObservationSpec):
            if not set(dependency.spec.reads) <= set(defn.spec.reads):
                problems.append(f"observation {name} reads probes outside {defn.name}.reads")
            inspect(dependency)
            return
        if name in seen:
            return
        seen.add(name)
        if (isinstance(dependency.spec, OperationSpec) and
                (dependency.spec.role == "act" or
                 truth_sort and any(edge.sort == truth_sort for edge in dependency.spec.inputs))):
            problems.append(f"operation {name} may read or change truth")
        if (isinstance(dependency.spec, BridgeSpec) and truth_sort and
                dependency.spec.source.rsplit(":", 1)[-1] == truth_sort):
            problems.append(f"bridge {name} may read truth")
        if getattr(dependency.spec, "extra", {}).get("role") == "act":
            problems.append(f"dependency {name} has act role")
        excluded = set(dependency.spec.op_params) if isinstance(dependency.spec, CombinatorSpec) else set()
        for child in (set(dependency.depends_on) | all_dependencies(dependency)) - excluded - {name}:
            if child not in probes:
                inspect_dependency(child)

    def inspect(definition):
        if definition.name in seen:
            return
        seen.add(definition.name)
        reads = set(definition.spec.reads)
        for probe in reads:
            if probe not in probes or probe not in granted:
                problems.append(f"probe {probe} is not granted")
        expressions = [definition.body]
        if definition.spec.memory:
            expressions.extend((definition.spec.memory["init"], definition.spec.memory["step"]))
            if any((isinstance(item, n.Var) or isinstance(item, n.Call) and
                    item.fn in _observation_names(lib)) for item in n.walk(definition.spec.memory["init"])):
                problems.append("memory.init must not read truth or probes")
        subject = getattr(definition.spec, "subject", "s")
        public_inputs = _inputs(definition)
        allowed_vars = reads | ({"memory"} if definition.spec.memory else set()) | (
            {name for name, _ in public_inputs} if _public(definition) else {subject})
        observed = _observation_names(lib)
        public_observations = {name for name, item in records.items()
                               if item.kind == "observation" and _public(item)}
        for expr in expressions:
            if expr is None:
                continue
            # The subject (the observed truth) may only be handed to probes and private observations.
            handed = {id(item.args[0]) for item in n.walk(expr) if isinstance(item, n.Call)
                      and item.fn in observed - public_observations and len(item.args) == 1
                      and item.args[0] == n.Var(subject)}
            if not _public(definition) and any(isinstance(item, n.Var) and item.name == subject and id(item) not in handed
                   for item in n.walk(expr)):
                problems.append(f"the subject {subject} may only be passed to probes and observations")
            recursive_names = {part.fn for part in n.walk(expr) if isinstance(part, n.Rec)}
            for item in n.walk(expr):
                # A literal can only forge the truth when the truth is a structured value (a card or a
                # host state object); a plain int/str/bool literal is data even if the truth sort is int.
                if isinstance(item, n.Lit) and truth_sort and not isinstance(item.value, (bool, int, str)) and (
                        getattr(item.value, "sort", None) == truth_sort or
                        type(item.value).__name__.lower() == truth_sort.lower()):
                    problems.append("observation cannot receive literal truth state")
                if (isinstance(item, n.Var) and item.name not in allowed_vars and
                    item.name not in {part.name for part in n.walk(expr) if isinstance(part, n.Let)} and
                    item.name not in {param for part in n.walk(expr) if isinstance(part, n.Rec)
                                      for param in part.params}):
                    problems.append(f"observation reads undeclared value {item.name}")
                if not isinstance(item, n.Call):
                    continue
                name = item.fn
                if not _public(definition) and name in public_observations and n.Var(subject) in item.args:
                    problems.append(f"subject {subject} may not be passed to public observation {name}")
                if name in recursive_names:
                    continue
                if name in probes:
                    if _public(definition):
                        problems.append(f"public observation cannot call probe {name}")
                    if name not in reads:
                        problems.append(f"probe {name} is not in reads")
                    if item.args and item.args != (n.Var(subject),):
                        problems.append(f"probe {name} receives only the subject {subject}")
                    continue
                inspect_dependency(name)

        for name in set(definition.depends_on) | all_dependencies(definition):
            if name not in probes and name not in {definition.name}:
                inspect_dependency(name)

    inspect(defn)
    return list(dict.fromkeys(problems))


def _run(defn, lib, states, *, inline=False):
    inputs = _inputs(defn)
    if _public(defn):
        scope = lib.scope()
        if scope.resolve(defn.name) is None:
            scope = scope.extend([kernel.Defn(defn.name, tuple(name for name, _ in inputs),
                                              defn.body, defn.kind, defn.layer)])
        outputs, steps = [], []
        for args in states:
            if len(args) != len(inputs):
                raise ValueError(f"observation requires {len(inputs)} public inputs")
            body = n.Call(defn.name, tuple(n.Lit(value) for value in args))
            if inline:
                body = kernel.inline(body, scope)
            run = kernel.evaluate(body, scope=scope, dialect=lib.dialect)
            outputs.append(run.outcome)
            steps.append(run.steps)
        return outputs, steps
    probe_scope = lib.scope()
    allowed = set(defn.spec.reads)
    truth_sort = lib.world.observation.get("truth")
    forbidden = {op.name for op in lib.world.operations
                 if op.name not in allowed and (op.role == "act" or
                                                any(edge.sort == truth_sort for edge in op.inputs))}
    scope = kernel.DictScope(atoms={name: atom for name, atom in probe_scope.atoms.items()
                                    if name not in forbidden and name not in allowed},
                             defns=probe_scope.defns)
    names = _observation_names(lib) - {name for name, item in _records(lib).items()
                                       if item.kind == "observation" and _public(item)}
    subject = defn.spec.subject
    defns = {name: (kernel.Defn(item.name, (),
                                _strip_subject(item.body, lib.get(name).spec.subject, names), item.kind, item.layer)
                    if _records(lib).get(name) is not None and lib.get(name).kind == "observation"
                    and not _public(lib.get(name))
                    else item)
             for name, item in scope.defns.items()}
    dependencies = {name: lib.get(name) for name in defns
                    if name != defn.name and name in _records(lib)
                    and lib.get(name).kind == "observation" and not _public(lib.get(name))}
    dependent_runs = {name: _run(dependency, lib, states, inline=inline)
                      for name, dependency in dependencies.items()
                      if any(isinstance(part, n.Call) and part.fn == name
                             and part.args in ((), (n.Var(subject),))
                             for expression in (defn.spec.body, defn.spec.memory["step"] if defn.spec.memory else None)
                             if expression is not None for part in n.walk(expression))}
    body = _strip_subject(defn.spec.body, subject, names)
    step = _strip_subject(defn.spec.memory["step"], subject, names) if defn.spec.memory else None
    memory = None
    if defn.spec.memory:
        initial = kernel.evaluate(defn.spec.memory["init"], scope=scope, dialect=lib.dialect)
        memory = initial.outcome
    outputs = []
    steps = []
    for index, state in enumerate(states):
        probe_runs = {name: kernel.call(name, (state,), probe_scope, dialect=lib.dialect)
                      for name in defn.spec.reads}
        values = {name: run.outcome for name, run in probe_runs.items()}
        probe_steps = sum(run.steps for run in probe_runs.values())
        env = {name: Bottom("undefined") if isinstance(value, Ok) and value.value is NAN else
               value.value if isinstance(value, Ok) else value for name, value in values.items()}
        probe_atoms = [kernel.Atom(name, 0, lambda value=env[name]: value,
                                   cost=0, kind="observation")
                       for name in defn.spec.reads]
        probe_atoms.extend(kernel.Atom(name, 0, lambda value=outputs[index]: value, cost=0,
                                       kind="observation")
                           for name, (outputs, _) in dependent_runs.items())
        current = kernel.DictScope(atoms={**scope.atoms, **{atom.name: atom for atom in probe_atoms}},
                                   defns={name: item for name, item in defns.items() if name not in dependent_runs})
        if inline:
            values_to_inline = {**env, **{name: outputs[index] for name, (outputs, _) in dependent_runs.items()}}

            def inline_call(node, values_to_inline=values_to_inline):
                if isinstance(node, n.Call) and not node.args and node.fn in values_to_inline:
                    return n.Lit(values_to_inline[node.fn])
                return node

            current_body = n.map_nodes(body, inline_call)
            current_step = n.map_nodes(step, inline_call) if step is not None else None
        else:
            current_body, current_step = body, step
        if defn.spec.memory:
            if not isinstance(memory, Ok):
                outputs.append(memory)
                steps.append(probe_steps)
                continue
            updated = kernel.evaluate(current_step, {**env, "memory": memory.value},
                                      current, dialect=lib.dialect)
            memory = updated.outcome
            if not isinstance(memory, Ok):
                outputs.append(memory)
                steps.append(probe_steps + updated.steps)
                continue
        result = kernel.evaluate(current_body, {**env, "memory": memory.value if memory else None},
                                 current, dialect=lib.dialect)
        outputs.append(result.outcome)
        steps.append(probe_steps + result.steps +
                     (updated.steps if defn.spec.memory else 0) +
                     sum(costs[index] for _, costs in dependent_runs.values()))
    return outputs, steps


def observe(defn, lib, states: Sequence[object]) -> list:
    problems = check_observation(defn, lib)
    if problems:
        raise ValueError("; ".join(problems))
    return _run(defn, lib, states)[0]


def verify_observation(defn, lib, request):
    problems = check_observation(defn, lib)
    if _public(defn):
        inputs = _inputs(defn)
        domain = tuple(getattr(request, "domain", ()))
        if not domain:
            problems.append("observation verification needs a nonempty domain")
        if any(len(args) != len(inputs) for args in domain):
            problems.append("observation domain input arity mismatch")
        if hasattr(request, "scope"):
            request.scope["non_interference"] = "n/a"
            if request.reference is None:
                request.scope["reference"] = "none"
        checks, steps = [], []
        if not problems:
            checks.append("dependency")
            for args in domain:
                before = deepcopy(args)
                try:
                    outputs, costs = _run(defn, lib, [args])
                    steps.extend(costs)
                    if isinstance(outputs[0], Unknown):
                        problems.append(f"observation unknown for {args!r}: {outputs[0]!r}")
                    if request.reference is None:
                        unfolded, unfolded_costs = _run(defn, lib, [deepcopy(args)], inline=True)
                        if costs != unfolded_costs or not outcome_equal(outputs[0], unfolded[0]):
                            problems.append(f"unfold_equivalence: public observation differs on {args!r}")
                    else:
                        expected = (request.reference(*deepcopy(args)) if callable(request.reference)
                                    else lib.run(request.reference, deepcopy(args)).outcome)
                        if not outcome_equal(outputs[0], expected if isinstance(expected, (Ok, Bottom, Unknown))
                                             else Ok(expected)):
                            problems.append(f"reference mismatch for {args!r}")
                except (ValueError, TypeError, KeyError, RecursionError) as error:
                    problems.append(f"observation counterexample {args!r}: {error}")
                if not value_equal(before, args):
                    problems.append("facts_unchanged: observation changed public inputs")
            if not any(problem.startswith("facts_unchanged") for problem in problems):
                checks.append("facts_unchanged")
            comparison = "reference" if request.reference is not None else "unfold_equivalence"
            if not any(problem.startswith(comparison) for problem in problems):
                checks.append(comparison)
        return VerifyResult(not problems, tuple(checks), problems, steps)
    histories = request.extra.get("states", ())
    if histories and not isinstance(histories[0], (list, tuple)):
        histories = (histories,)
    remaining = list(getattr(request, "domain", ((state,) for history in histories for state in history)))
    covered = []
    for history in histories:
        checked = []
        for state in history:
            match = next((index for index, args in enumerate(remaining)
                          if len(args) == 1 and value_equal(args[0], state)), None)
            if match is not None:
                checked.append(remaining.pop(match)[0])
        if checked:
            covered.append(checked)
    covered.extend([args[0]] for args in remaining if len(args) == 1)
    if any(len(args) != 1 for args in remaining):
        problems.append("observation domain requires one state per input")
    histories = covered
    if request.reference is None and hasattr(request, "scope"):
        request.scope["reference"] = "none"
    checks = ["dependency"] if not problems else []
    steps = []
    if not problems:
        for history in histories:
            before = deepcopy(history)
            before_values = [state.to_dict() if hasattr(state, "to_dict") else state for state in before]
            before_repr = [repr(value) for value in before_values]
            inline_history = deepcopy(history) if request.reference is None else None
            outputs, costs = _run(defn, lib, history)
            steps.extend(costs)
            if request.reference is None:
                unfolded, unfolded_costs = _run(defn, lib, inline_history, inline=True)
                if costs != unfolded_costs or len(outputs) != len(unfolded) or any(
                    not outcome_equal(actual, expected)
                    for actual, expected in zip(outputs, unfolded)
                ):
                    problems.append("unfold_equivalence: observation differs from inlined body")
            if request.reference is not None:
                for state, output in zip(history, outputs):
                    expected = request.reference(state) if callable(request.reference) else lib.run(request.reference, (state,)).outcome
                    if not outcome_equal(output, expected if isinstance(expected, (Ok, Bottom, Unknown)) else Ok(expected)):
                        problems.append(f"reference mismatch for {state!r}")
                        break
            for first in range(len(history)):
                for second in range(first + 1, len(history)):
                    if all(outcome_equal(kernel.call(probe, (history[first],), lib.scope(),
                                                     dialect=lib.dialect).outcome,
                                         kernel.call(probe, (history[second],), lib.scope(),
                                                     dialect=lib.dialect).outcome)
                           for probe in _granted(lib)) and not outcome_equal(
                               _run(defn, lib, [history[first]])[0][0],
                               _run(defn, lib, [history[second]])[0][0]):
                        problems.append("non_interference: indistinguishable states differ")
                        break
            after_values = [state.to_dict() if hasattr(state, "to_dict") else state for state in history]
            try:
                unchanged = after_values == before_values
                if not isinstance(unchanged, bool):
                    unchanged = repr(after_values) == repr(before_values)
            except (TypeError, ValueError):
                unchanged = [repr(value) for value in after_values] == before_repr
            if not unchanged:
                problems.append("facts_unchanged: observation changed truth state")
        if not any(problem.startswith("facts_unchanged") for problem in problems):
            checks.append("facts_unchanged")
        if request.reference is not None and not any(problem.startswith("reference") for problem in problems):
            checks.append("reference")
        if request.reference is None and not any(problem.startswith("unfold_equivalence") for problem in problems):
            checks.append("unfold_equivalence")
        if not any(problem.startswith("non_interference") for problem in problems):
            checks.append("non_interference")
    return VerifyResult(not problems, tuple(checks), problems, steps)


def judge(task_judge_view, truth_state, answer_state):
    """Grade full truth, never a learner's rendered observation."""
    if task_judge_view is None or task_judge_view == "full_state":
        return value_equal(truth_state, answer_state)
    if callable(task_judge_view):
        return value_equal(task_judge_view(truth_state), task_judge_view(answer_state))
    fields = task_judge_view.get("fields") if isinstance(task_judge_view, dict) else None
    if fields is None and isinstance(task_judge_view, str) and task_judge_view.startswith("contract_projection(") and task_judge_view.endswith(")"):
        fields = [field.strip() for field in task_judge_view[20:-1].split(",")]
    if fields is None:
        raise ValueError("unknown judge_view")
    return all(value_equal(getattr(truth_state, field), getattr(answer_state, field)) for field in fields)
