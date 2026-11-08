"""World-parametric observation admission and verification."""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from itertools import product

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.spec import ObservationSpec, OperationSpec
from opulse.atoms.values import Bottom, Card, Ok, Unknown, outcome_equal, value_equal
from opulse.gen_v2 import fast
from opulse.gen_v2.admit import KindHook, register_hook


def _expressions(defn):
    return (defn.body, defn.spec.memory["init"], defn.spec.memory["step"]) if defn.spec.memory else (defn.body,)


def check(defn, lib):
    """Allow operations on probe-derived values, never on direct truth or acts.

    A fixed read uses Call(probe, (Var("__truth"), *literal_arguments)).
    The marker is only legal as the first argument of a granted probe; it is
    replaced by the recorded read before the body is evaluated.

    A dependency declaration arm is a top-level Case with one Always arm
    holding the original body and a never-evaluated memory.step default.
    No other unreachable code is allowed in an observation expression.
    """
    problems = []
    if not isinstance(defn.spec, ObservationSpec):
        return ["observation needs an ObservationSpec"]
    if defn.body != defn.spec.body:
        problems.append("observation body differs from spec.body")
    memory = defn.spec.memory
    declaration = (isinstance(defn.body, n.Case) and len(defn.body.arms) == 1 and
                   isinstance(defn.body.arms[0][0], n.Always) and memory and
                   isinstance(memory.get("step"), n.NODE_TYPES) and
                   defn.body.default == memory.get("step") and
                   bool(n.references(memory["step"]) - n.references(defn.body.arms[0][1])))
    for expr in _expressions(defn):
        if not isinstance(expr, n.NODE_TYPES):
            continue
        for part in n.walk(expr):
            if not isinstance(part, n.Case):
                continue
            for index, (condition, _) in enumerate(part.arms):
                if isinstance(condition, n.Always) and (index != len(part.arms) - 1 or
                        part.default is not None and not (part is defn.body and declaration)):
                    problems.append("unrecognized unreachable observation code")
    granted = {item if isinstance(item, str) else item["name"]
               for item in lib.world.observation.get("probes", ())}
    granted &= set(getattr(lib, "granted_probes", granted))
    truth_sort = lib.world.observation.get("truth")
    probe_outputs = {op.output.sort for op in lib.world.operations if op.name in granted}
    probe_outputs.update(item["sort"] for item in lib.world.observation.get("probes", ())
                         if isinstance(item, dict) and item["name"] in granted)
    seen = set()
    operation_checked = {}

    def safe_object(name, active=frozenset()):
        if name in active or name == truth_sort:
            return False
        target = lib.resolve(name)
        if target is None or getattr(target, "kind", None) != "object":
            return False
        spec = target.spec
        if spec.sealed or spec.base == truth_sort:
            return False
        if spec.base and lib.resolve(spec.base) is not None and not safe_object(spec.base, active | {name}):
            return False
        fields = (field for members in (spec.tags or {}).values() for field in
                  (members.values() if isinstance(members, dict) else (sort for _, sort in members)))
        if not all(field != truth_sort and
                   (lib.resolve(field) is None or getattr(lib.resolve(field), "kind", None) != "object"
                    or safe_object(field, active | {name})) for field in fields):
            return False
        for expr in (spec.valid, spec.canon, spec.body if spec.form == "constant" else None):
            if isinstance(expr, n.NODE_TYPES) and (
                    any(not safe_dependency(ref) for ref in sorted(n.references(expr))) or
                    any(not safe_dependency(part.value.name) for part in n.walk(expr)
                        if isinstance(part, n.Lit) and isinstance(part.value, kernel.FnRef))):
                return False
        return True

    def safe_operation(name):
        if name in operation_checked:
            return operation_checked[name]
        operation_checked[name] = False
        target = lib.resolve(name)
        declaration = next((op for op in lib.world.operations if op.name == name), None)
        spec = getattr(target, "spec", None) or declaration
        if spec is None and "." in name:
            owner = name.split(".")[0]
            obj = lib.resolve(owner)
            if obj is not None and safe_object(owner):
                operation_checked[name] = True
                return True
        if _unsafe(spec, truth_sort, probe_outputs):
            return False
        if hasattr(target, "body") and isinstance(target.body, n.NODE_TYPES):
            operation_checked[name] = (all(safe_dependency(dep) for dep in sorted(n.references(target.body))) and
                                       all(safe_dependency(part.value.name) for part in n.walk(target.body)
                                           if isinstance(part, n.Lit) and isinstance(part.value, kernel.FnRef)))
        else:
            operation_checked[name] = True
        return operation_checked[name]

    def safe_dependency(name):
        target = lib.resolve(name)
        if target is None:
            return False
        if isinstance(target, kernel.Defn):
            return "." in name and safe_operation(name)
        if getattr(target, "kind", None) == "combinator":
            return all(safe_dependency(dep) for dep in sorted(n.references(target.body))
                       if dep not in target.spec.op_params)
        if getattr(target, "kind", None) == "object" and not isinstance(target, kernel.Atom):
            return safe_object(target.name)
        return safe_operation(name)

    def inspect(current):
        if current.name in seen:
            return
        seen.add(current.name)
        reads = set(current.spec.reads)
        for probe in sorted(reads - granted):
            problems.append(f"probe {probe} is not granted")
        memory = current.spec.memory
        if memory:
            if not isinstance(memory.get("init"), n.Lit):
                problems.append("memory.init must be a closed literal")
            elif _is_truth(memory["init"].value, truth_sort):
                problems.append("memory.init cannot contain truth")
            if not isinstance(memory.get("step"), n.NODE_TYPES):
                problems.append("memory.step must be a kernel expression")
            elif n.references(memory["step"]) - n.references(current.body):
                problems.append("memory.step dependencies must occur in the body")
            if isinstance(memory.get("init"), n.NODE_TYPES) and n.references(memory["init"]) - n.references(current.body):
                problems.append("memory.init dependencies must occur in the body")
        for expr in _expressions(current):
            if not isinstance(expr, n.NODE_TYPES):
                continue
            allowed_truth = Counter(id(part.args[0]) for part in n.walk(expr) if isinstance(part, n.Call)
                                    and part.fn in granted and part.args and
                                    isinstance(part.args[0], n.Var) and part.args[0].name == "__truth")
            truth_uses = Counter(id(part) for part in n.walk(expr)
                                 if isinstance(part, n.Var) and part.name == "__truth")
            locals_ = {part.name for part in n.walk(expr) if isinstance(part, n.Let)}
            locals_ |= {param for part in n.walk(expr) if isinstance(part, n.Rec) for param in part.params}
            rec_names = {part.fn for part in n.walk(expr) if isinstance(part, n.Rec)}
            for part in n.walk(expr):
                if (isinstance(part, n.Var) and part.name not in reads | locals_ |
                        ({"memory"} if memory else set()) and
                        (part.name != "__truth" or truth_uses[id(part)] != allowed_truth[id(part)])):
                    problems.append(f"undeclared observation input {part.name}")
                if isinstance(part, n.Lit) and _is_truth(part.value, truth_sort):
                    problems.append("literal truth is forbidden")
                if isinstance(part, n.Lit) and isinstance(part.value, kernel.FnRef) and not safe_dependency(part.value.name):
                    problems.append(f"unsafe operation reference {part.value.name}")
                if not isinstance(part, n.Call) or part.fn in rec_names:
                    continue
                name = part.fn
                if name in reads and name not in granted:
                    problems.append(f"probe {name} is not granted")
                if name in granted:
                    declaration = next((op for op in lib.world.operations if op.name == name), None)
                    arity = len((declaration or lib.resolve(name).spec).inputs) - 1
                    if (name not in reads or part.args and
                            (len(part.args) != arity + 1 or
                             not isinstance(part.args[0], n.Var) or part.args[0].name != "__truth" or
                             not all(isinstance(arg, n.Lit) and not _is_truth(arg.value, truth_sort)
                                     for arg in part.args[1:]))):
                        problems.append(f"probe {name} must occur in reads with fixed literal arguments")
                    continue
                target = lib.resolve(name)
                if target is None:
                    problems.append(f"unknown observation dependency {name}")
                elif isinstance(target, kernel.Atom):
                    if target.kind == "observation":
                        problems.append(f"probe {name} is not granted")
                    else:
                        if not safe_dependency(name):
                            problems.append(f"operation {name} may read or change truth")
                elif isinstance(target, kernel.Defn):
                    if not safe_dependency(name):
                        problems.append(f"unverified dependency {name}")
                elif target.kind == "observation":
                    if not set(target.spec.reads) <= reads:
                        problems.append(f"observation {name} reads outside {current.name}.reads")
                    if target.spec.memory and not memory:
                        problems.append(f"memory observation {name} needs a history")
                    inspect(target)
                elif target.kind in ("operation", "combinator", "object") and safe_dependency(name):
                    if target.kind == "combinator":
                        for arg in part.args[:len(target.spec.op_params)]:
                            referenced = arg.value if isinstance(arg, n.Lit) else None
                            if not isinstance(referenced, kernel.FnRef) or not safe_dependency(referenced.name):
                                problems.append(f"combinator {name} has an unsafe operation slot")
                else:
                    problems.append(f"dependency {name} may read or change truth")

    inspect(defn)
    return list(dict.fromkeys(problems))


def _unsafe(spec, truth_sort, probe_outputs=()):
    return (not isinstance(spec, OperationSpec) or spec.role == "act" or
            (truth_sort not in probe_outputs and
             (spec.output.sort == truth_sort or any(edge.sort == truth_sort for edge in spec.inputs))))


def _is_truth(value, truth_sort):
    if truth_sort is None:
        return False
    if getattr(value, "sort", None) == truth_sort:
        return True
    if isinstance(value, (tuple, list)):
        return any(_is_truth(item, truth_sort) for item in value)
    if isinstance(value, dict):
        return any(_is_truth(item, truth_sort) for item in value.values())
    return any(_is_truth(item, truth_sort) for item in getattr(value, "fields", ()))


def _holds_truth_state(value, truth_states):
    """True when a literal card equals, or contains, one of the enumerated truth states (needed
    when the truth sort is Any and the states are cards of several sorts)."""
    if isinstance(value, Card):
        if any(isinstance(state, Card) and value_equal(value, state) for state in truth_states):
            return True
        return any(_holds_truth_state(item, truth_states) for item in value.fields)
    if isinstance(value, (tuple, list)):
        return any(_holds_truth_state(item, truth_states) for item in value)
    if isinstance(value, dict):
        return any(_holds_truth_state(item, truth_states) for item in value.values())
    return False


def _scope(state, defn):
    scope = state.library.scope()
    if defn.name not in scope.defns:
        scope = scope.extend([kernel.Defn(defn.name, (), defn.body, "observation", defn.layer)])
    return scope


def _probe_args(state, probe, scope):
    cache = getattr(state, "_observation_arguments", None)
    if cache is None:
        cache = {}
        state._observation_arguments = cache
    if probe not in cache:
        signature = state.signature(probe)
        extras = signature.inputs[1:]
        if not extras:
            cache[probe] = ()
        else:
            originals = tuple(state.world.truth_states)
            snapshots = deepcopy(originals)
            options = product(*(state.sorts[sort].values[:6] for sort in extras))
            best = ((), -1)
            try:
                for args in options:
                    outcomes = []
                    for truth in originals[:12]:
                        result = fast.call(probe, (truth, *args), scope, state.world.fuel, state.world.dialect)
                        if isinstance(result.outcome, Ok):
                            outcomes.append(repr(result.outcome.value))
                        if not _same_truth_states(originals, snapshots):
                            raise ValueError("facts_unchanged: truth mutated during probe argument selection")
                    score = len(set(outcomes)) if len(outcomes) >= 2 else 0
                    if score > best[1]:
                        best = (args, score)
            finally:
                _restore_truth_states(originals, snapshots)
            cache[probe] = best[0]
    return cache[probe]


def _cacheable_truth(value):
    if isinstance(value, Card):
        return all(_cacheable_truth(field) for field in value.fields)
    if isinstance(value, tuple):
        return all(_cacheable_truth(item) for item in value)
    return type(value) in (int, str, bool)


def _read_arguments(state, defn, scope):
    arguments = {probe: [(_probe_args(state, probe, scope), probe)] for probe in defn.spec.reads}
    visited = set()

    def visit(current):
        if current.name in visited:
            return
        visited.add(current.name)
        for expr in _expressions(current):
            for part in n.walk(expr):
                if not isinstance(part, n.Call):
                    continue
                if part.fn in arguments and part.args:
                    args = tuple(arg.value for arg in part.args[1:])
                    if not any(repr(existing) == repr(args) for existing, _ in arguments[part.fn]):
                        alias = f"__probe_{sum(map(len, arguments.values()))}"
                        arguments[part.fn].append((args, alias))
                elif part.fn in state.entries and state.entries[part.fn].kind == "observation":
                    visit(state.library.get(part.fn))

    visit(defn)
    return arguments


def _probe_values(state, reads, truth, scope, arguments=None):
    values = {}
    steps = 0
    for probe in reads:
        for fixed, alias in (arguments[probe] if arguments is not None else
                             [(_probe_args(state, probe, scope), probe)]):
            cache = getattr(state, "_observation_values", None)
            if cache is None:
                cache = {}
                state._observation_values = cache
            key = (probe, truth, repr(fixed)) if isinstance(truth, Card) and _cacheable_truth(truth) else None
            if key is not None and key in cache:
                value, cost, error = cache[key]
            else:
                result = fast.call(probe, (truth, *fixed), scope, state.world.fuel, state.world.dialect)
                value = result.outcome.value if isinstance(result.outcome, Ok) else None
                cost, error = result.steps, None if isinstance(result.outcome, Ok) else result.outcome
                if key is not None:
                    cache[key] = (value, cost, error)
            steps += cost
            if error is not None:
                return values, steps, error
            values[alias] = value
    return values, steps, None


def _expand(expr, state, scope, history, cache, arguments=None):
    """Inline observation dependencies, leaving their probe variables lexically bound."""
    if isinstance(expr, n.Call) and arguments is not None and expr.fn in arguments:
        fixed = tuple(arg.value for arg in expr.args[1:]) if expr.args else arguments[expr.fn][0][0]
        return n.Var(next(alias for values, alias in arguments[expr.fn] if repr(values) == repr(fixed)))
    if isinstance(expr, n.Call) and expr.fn in state.entries and state.entries[expr.fn].kind == "observation":
        dep = state.library.get(expr.fn)
        if dep.spec.memory:
            if expr.fn not in cache:
                cache[expr.fn] = _evaluate(state, dep, history, scope)
            outcome, _ = cache[expr.fn]
            if not isinstance(outcome, Ok):
                raise ValueError(f"memory dependency {expr.fn} failed")
            return n.Lit(outcome.value)
        return _expand(dep.body, state, scope, history, cache, arguments)
    if isinstance(expr, n.Call):
        return n.Call(expr.fn, tuple(_expand(arg, state, scope, history, cache, arguments) for arg in expr.args))
    if isinstance(expr, n.Let):
        return n.Let(expr.name, _expand(expr.value, state, scope, history, cache, arguments),
                     _expand(expr.body, state, scope, history, cache, arguments))
    if isinstance(expr, n.Rec):
        return n.Rec(expr.fn, expr.params, _expand(expr.body, state, scope, history, cache, arguments),
                     tuple(_expand(arg, state, scope, history, cache, arguments) for arg in expr.args),
                     expr.measure if isinstance(expr.measure, str) else
                     _expand(expr.measure, state, scope, history, cache, arguments))
    if isinstance(expr, n.Case):
        def cond(item):
            if isinstance(item, n.Test):
                return n.Test(_expand(item.expr, state, scope, history, cache, arguments))
            if isinstance(item, (n.And, n.Or)):
                return type(item)(cond(item.left), cond(item.right))
            if isinstance(item, n.Not):
                return n.Not(cond(item.operand))
            return item
        declaration = (len(expr.arms) == 1 and isinstance(expr.arms[0][0], n.Always) and
                       expr.default is not None)
        return n.Case(tuple((cond(test), _expand(value, state, scope, history, cache, arguments))
                            for test, value in expr.arms),
                      expr.default if declaration else
                      _expand(expr.default, state, scope, history, cache, arguments)
                      if expr.default is not None else None)
    if isinstance(expr, n.Blocks):
        def condition(item):
            if isinstance(item, n.Test):
                return n.Test(_expand(item.expr, state, scope, history, cache, arguments))
            if isinstance(item, (n.And, n.Or)):
                return type(item)(condition(item.left), condition(item.right))
            if isinstance(item, n.Not):
                return n.Not(condition(item.operand))
            return item

        blocks = []
        for label, block in expr.blocks:
            end = block.end
            if isinstance(end, n.Halt):
                end = n.Halt(_expand(end.value, state, scope, history, cache, arguments))
            elif isinstance(end, n.CondJump):
                end = n.CondJump(condition(end.cond), end.then, end.else_)
            blocks.append((label, n.Block(tuple((name, _expand(value, state, scope, history, cache, arguments))
                                          for name, value in block.assigns), end)))
        return n.Blocks(tuple((name, _expand(value, state, scope, history, cache, arguments))
                              for name, value in expr.vars), expr.entry, tuple(blocks))
    return expr


def _evaluate(state, defn, history, scope, unfolded=False, prepared=None, arguments=None):
    if arguments is None:
        arguments = _read_arguments(state, defn, scope)
    memory = None
    total = 0
    if defn.spec.memory:
        initial = fast.evaluate(defn.spec.memory["init"], {}, scope, None, state.world.dialect)
        if not isinstance(initial.outcome, Ok):
            return initial.outcome, initial.steps
        memory = initial.outcome.value
        total += initial.steps
    last_values = {}
    for index, truth in enumerate(history):
        values, steps, error = _probe_values(state, defn.spec.reads, truth, scope, arguments)
        total += steps
        if error:
            return error, total
        last_values = values
        if defn.spec.memory:
            cache = {}
            step = (prepared[1] if prepared is not None else
                    _expand(defn.spec.memory["step"], state, scope, history[:index + 1], cache, arguments))
            if unfolded and prepared is None:
                step = kernel.inline(step, scope)
            total += sum(cost for _, cost in cache.values())
            updated = fast.evaluate(step, {**values, "memory": memory}, scope, state.world.fuel,
                                    state.world.dialect)
            total += updated.steps
            if not isinstance(updated.outcome, Ok):
                return updated.outcome, total
            if _oversized(updated.outcome.value):
                return Unknown("observation-value"), total
            memory = updated.outcome.value
    cache = {}
    body = prepared[0] if prepared is not None else _expand(defn.body, state, scope, history, cache, arguments)
    if unfolded and prepared is None:
        body = kernel.inline(body, scope)
    total += sum(cost for _, cost in cache.values())
    evaluated = fast.evaluate(body, {**last_values, "memory": memory}, scope, state.world.fuel,
                              state.world.dialect)
    if isinstance(evaluated.outcome, Ok) and _oversized(evaluated.outcome.value):
        return Unknown("observation-value"), total + evaluated.steps
    return evaluated.outcome, total + evaluated.steps


def _oversized(value):
    if type(value) is int:
        return value.bit_length() > 128
    if isinstance(value, Card):
        return any(_oversized(field) for field in value.fields)
    if isinstance(value, (tuple, list)):
        return any(_oversized(item) for item in value)
    return False


def _history(args, memory):
    if memory:
        if len(args) == 1 and isinstance(args[0], (list, tuple)):
            return tuple(args[0])
        return tuple(args) if isinstance(args, tuple) else tuple(args[0])
    return (args[0],)


def _partition(keys):
    labels = {}
    return tuple(labels.setdefault(key, len(labels)) for key in keys)


def _same_truth(left, right):
    if type(left) is not type(right):
        return False
    if isinstance(left, Card):
        return (left.sort == right.sort and left.tag == right.tag and
                _same_truth(left.fields, right.fields))
    if isinstance(left, (tuple, list)):
        return len(left) == len(right) and all(_same_truth(a, b) for a, b in zip(left, right))
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(_same_truth(value, right[key]) for key, value in left.items())
    if callable(getattr(left, "to_dict", None)):
        return _same_truth(left.to_dict(), right.to_dict())
    if hasattr(left, "__dict__"):
        return _same_truth(vars(left), vars(right))
    return value_equal(left, right)


def _same_domain(before, after, memory):
    return len(before) == len(after) and all(
        len(_history(old, memory)) == len(_history(new, memory)) and
        all(_same_truth(left, right) for left, right in zip(_history(old, memory), _history(new, memory)))
        for old, new in zip(before, after))


def _same_truth_states(originals, snapshots):
    return all(_same_truth(original, snapshot) for original, snapshot in zip(originals, snapshots))


def _restore_truth(original, snapshot):
    if isinstance(original, dict):
        original.clear()
        original.update(deepcopy(snapshot))
    elif isinstance(original, list):
        original[:] = deepcopy(snapshot)
    elif isinstance(original, Card) and isinstance(snapshot, Card):
        for field, saved in zip(original.fields, snapshot.fields):
            _restore_truth(field, saved)
        object.__setattr__(original, "sort", snapshot.sort)
        object.__setattr__(original, "tag", snapshot.tag)
        object.__setattr__(original, "fields", deepcopy(snapshot.fields))
    elif isinstance(original, tuple) and isinstance(snapshot, tuple):
        for field, saved in zip(original, snapshot):
            _restore_truth(field, saved)
    elif hasattr(original, "__dict__") and hasattr(snapshot, "__dict__"):
        vars(original).clear()
        vars(original).update(deepcopy(vars(snapshot)))


def _restore_truth_states(originals, snapshots):
    for original, snapshot in zip(originals, snapshots):
        if not _same_truth(original, snapshot):
            _restore_truth(original, snapshot)


def _check_memory_domain(state, request):
    if request.method == "sampled":
        if request.seed is None:
            raise ValueError("sampled memory histories require a seed")
        return
    indices = request.scope.get("history_state_indices")
    length = request.scope.get("history_length")
    if request.method != "bounded" or not isinstance(indices, (tuple, list)) or not indices or (
            not isinstance(length, int) or not 1 <= length <= 3 or
            any(type(index) is not int or not 0 <= index < len(state.world.truth_states) for index in indices) or
            len(set(indices)) != len(indices)):
        raise ValueError("memory histories require a bounded enumerated scope or seeded sampled evidence")
    states = tuple(state.world.truth_states[index] for index in indices)
    expected = tuple(history for size in range(1, length + 1)
                     for history in product(states, repeat=size))
    if (len(request.domain) != len(expected) or
            any(not _same_domain((actual,), (history,), True)
                for actual, history in zip(request.domain, expected)) or
            request.scope.get("size") != len(expected)):
        raise ValueError("bounded memory histories must cover every enumerated state history up to the length bound")


def run(state, candidate, request):
    if not set(candidate.defn.spec.reads) <= set(state.world.probes):
        raise ValueError("observation reads a probe not granted by the world adapter")
    if candidate.defn.spec.memory:
        _check_memory_domain(state, request)
    if state.world.truth_sort is not None and state.world.truth_states:
        sample = state.world.truth_states[0]
        expressions = list(_expressions(candidate.defn))
        if candidate.defn.spec.memory:
            expressions.append(candidate.defn.spec.memory["init"])
        for expression in expressions:
            if any(isinstance(node, n.Lit) and
                   (_is_truth(node.value, state.world.truth_sort) or
                    isinstance(sample, (tuple, list, dict)) and
                    isinstance(node.value, type(sample)) and
                    any(value_equal(node.value, state_value) for state_value in state.world.truth_states) or
                    _holds_truth_state(node.value, state.world.truth_states))
                   for node in n.walk(expression)):
                raise ValueError("literal sealed truth is forbidden")
    scope = _scope(state, candidate.defn)
    originals = tuple(state.world.truth_states)
    snapshots = deepcopy(originals)
    before_domain = deepcopy(request.domain)
    try:
        arguments = _read_arguments(state, candidate.defn, scope)
        if not _same_truth_states(originals, snapshots) or not _same_domain(before_domain, request.domain,
                                                                            candidate.defn.spec.memory):
            raise ValueError("facts_unchanged: truth mutated during probe argument selection")
        if candidate.defn.spec.reads:
            request.scope["probe_arguments"] = {
                probe: [repr(fixed) for fixed, _ in arguments[probe]] for probe in candidate.defn.spec.reads
                if len(state.signature(probe).inputs) > 1}
        request.scope["reference"] = "independent" if request.reference is not None else "none"
        results = [(args, *_evaluate(state, candidate.defn, _history(args, candidate.defn.spec.memory), scope,
                                    arguments=arguments)) for args in request.domain]
        if not _same_truth_states(originals, snapshots) or not _same_domain(before_domain, request.domain,
                                                                            candidate.defn.spec.memory):
            raise ValueError("facts_unchanged: truth mutated during observation evaluation")
        candidate.meta["_truth_before"] = before_domain
        return results
    finally:
        _restore_truth_states(originals, snapshots)
        for original, snapshot in zip(request.domain, before_domain):
            if not _same_domain((original,), (snapshot,), candidate.defn.spec.memory):
                for current, saved in zip(_history(original, candidate.defn.spec.memory),
                                          _history(snapshot, candidate.defn.spec.memory)):
                    _restore_truth(current, saved)


def verify(state, candidate, request, results):
    originals = tuple(state.world.truth_states)
    snapshots = deepcopy(originals)
    before_domain = deepcopy(request.domain)
    try:
        checks, problems = _verify_results(state, candidate, request, results)
        if not _same_truth_states(originals, snapshots) or not _same_domain(before_domain, request.domain,
                                                                            candidate.defn.spec.memory):
            problems.append("facts_unchanged: truth mutated during verification")
        return checks, problems
    finally:
        _restore_truth_states(originals, snapshots)
        for original, snapshot in zip(request.domain, before_domain):
            for current, saved in zip(_history(original, candidate.defn.spec.memory),
                                      _history(snapshot, candidate.defn.spec.memory)):
                if not _same_truth(current, saved):
                    _restore_truth(current, saved)


def _verify_results(state, candidate, request, results):
    checks = ("dependency", "facts_unchanged", "non_interference", "unfold_equivalence")
    if request.reference is not None:
        checks += ("reference",)
    problems = []
    scope = _scope(state, candidate.defn)
    defn = candidate.defn
    arguments = _read_arguments(state, defn, scope)
    memory_dependencies = any(ref in state.entries and state.entries[ref].kind == "observation"
                              and state.library.get(ref).spec.memory
                              for expression in _expressions(defn) if isinstance(expression, n.NODE_TYPES)
                              for ref in n.references(expression))
    prepared = None
    if not memory_dependencies:
        prepared = (kernel.inline(_expand(defn.body, state, scope, (), {}, arguments), scope),
                    kernel.inline(_expand(defn.spec.memory["step"], state, scope, (), {}, arguments), scope)
                    if defn.spec.memory else None)
    before_run = candidate.meta.pop("_truth_before", None)
    if before_run is not None and not _same_domain(before_run, request.domain, defn.spec.memory):
        problems.append("facts_unchanged: truth mutated during first evaluation")
    partitions = {}
    for args, outcome, steps in results:
        history = _history(args, candidate.defn.spec.memory)
        original = deepcopy(history)
        repeated, repeated_steps = _evaluate(state, candidate.defn, history, scope,
                                              unfolded=True, prepared=prepared, arguments=arguments)
        if len(history) != len(original) or any(not _same_truth(a, b) for a, b in zip(history, original)):
            problems.append("facts_unchanged: truth mutated")
        if not outcome_equal(outcome, repeated):
            problems.append("unfold_equivalence: outcomes differ")
        if steps != repeated_steps:
            problems.append("unfold_equivalence: steps differ")
        probe_key = []
        for truth in history:
            values, _, error = _probe_values(state, candidate.defn.spec.reads, truth, scope, arguments)
            probe_key.append(tuple(repr(values.get(alias, error)) for probe in candidate.defn.spec.reads
                                   for _, alias in arguments[probe]))
        key = tuple(probe_key)
        if key in partitions and (not outcome_equal(outcome, partitions[key][0]) or
                                  steps != partitions[key][1]):
            problems.append("non_interference: identical probes produce different observations")
        partitions[key] = (outcome, steps)
        if request.reference is not None:
            expected = request.reference(*args) if callable(request.reference) else request.reference[args]
            if not outcome_equal(outcome, expected if isinstance(expected, (Ok, Bottom, Unknown)) else Ok(expected)):
                problems.append("reference: behaviour mismatch")
    from opulse.gen_v2.interest import _key

    partition = _partition(_key(outcome) for _, outcome, _ in results)
    for entry in state.entries.values():
        if (entry.kind == "observation" and bool(entry.meta.get("memory")) == bool(candidate.defn.spec.memory)
                and entry.signature.inputs == candidate.signature.inputs and entry.fingerprint[2] == partition):
            problems.append(f"duplicate: same truth partition as {entry.name}")
            break
    return checks, list(dict.fromkeys(problems))


register_hook("observation", KindHook(check, run, verify))
