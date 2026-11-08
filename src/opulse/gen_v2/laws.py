"""Conjecture scoped laws over the admitted operation catalogue.

Local records are proposals; admitted laws use core LawSpec and verification.
"""

from __future__ import annotations

import itertools
import json
from dataclasses import dataclass, field, replace

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.values import Ok, truth, value_equal
from opulse.gen_v2 import fast, vocab
from opulse.gen_v2.codec import encode_value
from opulse.gen_v2.notation import print_node


@dataclass(frozen=True)
class LawRecord:
    name: str
    statement: n.Node
    vars: tuple[tuple[str, str], ...]
    depends_on: tuple[str, ...]
    layer: int
    evidence: dict = field(default_factory=dict)
    shortens: dict = field(default_factory=lambda: {"sites": 0, "steps_saved_per_use": 0,
                                                    "total_over_scope": 0})
    kind: str = "law"

    def text(self, state=None) -> str:
        variables = ", ".join(f"{name}: {sort}" for name, sort in self.vars)
        try:
            statement = print_node(self.statement, state)
        except TypeError:
            statement = json.dumps(n.to_json(self.statement), ensure_ascii=True, sort_keys=True)
        return f"law #{self.name}: {statement} for {variables}  L{self.layer}"


def _node_key(node, rename):
    if isinstance(node, n.Var):
        return ("var", rename[node.name])
    if isinstance(node, n.Lit):
        return ("lit", repr(node.value))
    if isinstance(node, n.Call):
        return ("call", node.fn, tuple(_node_key(arg, rename) for arg in node.args))
    if isinstance(node, n.Case):
        return ("case", tuple((_node_key(cond, rename), _node_key(body, rename))
                               for cond, body in node.arms), _node_key(node.default, rename))
    if isinstance(node, n.Test):
        return ("test", _node_key(node.expr, rename))
    if node is None:
        return ("none",)
    return (type(node).__name__, repr(node))


def _prune(node, state=None):
    if isinstance(node, n.Case):
        arms = []
        for condition, body in node.arms:
            condition = _prune_condition(condition, state)
            if isinstance(condition, n.Always) or (isinstance(condition, n.Test) and
                    isinstance(condition.expr, n.Lit) and condition.expr.value is True):
                return n.Case(tuple(arms), _prune(body, state)) if arms else _prune(body, state)
            if isinstance(condition, n.Test) and isinstance(condition.expr, n.Lit) and condition.expr.value is False:
                continue
            arms.append((condition, _prune(body, state)))
        return n.Case(tuple(arms), _prune(node.default, state)) if arms else _prune(node.default, state)
    if isinstance(node, n.Call):
        args = tuple(_prune(arg, state) for arg in node.args)
        if state is not None and len(args) == 2 and args[0] == args[1]:
            signature = state.signature(node.fn)
            if signature and signature.inputs and node.fn in vocab.equal(state, signature.inputs[0]):
                return n.Lit(True)
        return n.Call(node.fn, args)
    if isinstance(node, n.Let):
        return n.Let(node.name, _prune(node.value, state), _prune(node.body, state))
    return node


def _prune_condition(condition, state):
    if isinstance(condition, n.Test):
        return n.Test(_prune(condition.expr, state))
    if isinstance(condition, n.Not):
        return n.Not(_prune_condition(condition.operand, state))
    if isinstance(condition, (n.And, n.Or)):
        return type(condition)(_prune_condition(condition.left, state),
                               _prune_condition(condition.right, state))
    return condition


def _obvious_constant(node):
    if isinstance(node, n.Lit) and type(node.value) is bool:
        return node.value
    if isinstance(node, n.Case):
        results = [_obvious_constant(body) for _, body in node.arms]
        results.append(_obvious_constant(node.default))
        if results and results[0] is not None and all(item is results[0] for item in results):
            return results[0]
    return None


def _key(law, state=None):
    def normalized(variables):
        rename = {name: f"v{index}:{sort}" for index, (name, sort) in enumerate(variables)}
        statement = _prune(law.statement, state)
        signature = state.signature(statement.fn) if state is not None and isinstance(statement, n.Call) else None
        if (signature and len(statement.args) == 2 and signature.inputs and
                statement.fn in vocab.equal(state, signature.inputs[0])):
            left, right = (_node_key(arg, rename) for arg in statement.args)
            first, second = sorted((left, right), key=repr)
            return (tuple(sort for _, sort in variables), statement.fn, first, second)
        return (tuple(sort for _, sort in variables), _node_key(statement, rename))

    groups = {}
    for index, (_, sort) in enumerate(law.vars):
        groups.setdefault(sort, []).append(index)
    permutations = [tuple(itertools.permutations(positions)) for positions in groups.values()]
    keys = []
    for choices in itertools.product(*permutations):
        reordered = list(law.vars)
        for positions, replacement in zip(groups.values(), choices):
            for position, chosen in zip(positions, replacement):
                reordered[position] = law.vars[chosen]
        keys.append(normalized(reordered))
    return min(keys, key=repr)


def _law(state, statement, variables):
    refs = tuple(sorted(n.references(statement)))
    return LawRecord("", statement, tuple(variables), refs,
                     1 + max((state.layer(name) for name in refs), default=0))


def _eq(state, sort, left, right):
    equals = vocab.equal(state, sort)
    return n.Call(equals[0], (left, right)) if equals else None


def _probe(state, statement, variables):
    """Early falsification only; full checking is always done by check()."""
    domains = [state.sorts[sort].values[:4] for _, sort in variables]
    if not all(domains):
        return False
    scope = state.library.scope()
    for args in itertools.product(*domains):
        env = dict(zip((name for name, _ in variables), args))
        try:
            outcome = fast.evaluate(statement, env, scope, state.world.fuel, state.world.dialect).outcome
        except (TypeError, ValueError, KeyError, IndexError, AttributeError):  # host rejects the values
            return False
        if not isinstance(outcome, Ok):
            return False
        try:
            if not truth(outcome.value):
                return False
        except TypeError:
            return False
    return True


def conjecture(state, entry_or_names):
    """Propose behaviourally plausible laws for invented operations and their peers.

    Conjectures are only hypotheses; callers must pass each through check().
    """
    if isinstance(entry_or_names, str):
        names = (entry_or_names,)
    elif hasattr(entry_or_names, "name"):
        names = (entry_or_names.name,)
    else:
        names = tuple(item.name if hasattr(item, "name") else item for item in entry_or_names)
    seen = set()
    for name in names:
        entry = state.entries.get(name)
        if entry is None or entry.kind != "operation" or entry.signature is None:
            continue
        sig = entry.signature
        if sig.op_inputs or sig.output not in state.sorts or len(sig.inputs) not in (1, 2):
            continue
        sort = sig.output
        variables = (("a", sig.inputs[0]),) if len(sig.inputs) == 1 else (("a", sig.inputs[0]), ("b", sig.inputs[1]))
        left_args = tuple(n.Var(var) for var, _ in variables)
        term = n.Call(name, left_args)
        proposals = []
        if len(sig.inputs) == 1 and sig.inputs[0] == sort:
            x = left_args[0]
            proposals.extend(((_eq(state, sort, n.Call(name, (term,)), term), variables),
                              (_eq(state, sort, n.Call(name, (term,)), x), variables)))
            for peer in state.callables("operation", inputs=(sort,), output=sort)[:48]:
                if peer != name:
                    proposals.append((_eq(state, sort, n.Call(peer, (term,)),
                                                 n.Call(name, (n.Call(peer, (x,)),))), variables))
        if len(sig.inputs) == 2 and sig.inputs == (sort, sort):
            x, y = left_args
            triple = variables + (("c", sort),)
            z = n.Var("c")
            proposals.extend(((_eq(state, sort, term, n.Call(name, (y, x))), variables),
                              (_eq(state, sort, n.Call(name, (n.Call(name, (x, y)), z)),
                                   n.Call(name, (x, n.Call(name, (y, z))))), triple)))
            for constant in state.sorts[sort].values[:8]:
                value = n.Lit(constant)
                proposals.extend(((_eq(state, sort, n.Call(name, (x, value)), x), variables[:1]),
                                  (_eq(state, sort, n.Call(name, (value, x)), x), variables[:1]),
                                  (_eq(state, sort, n.Call(name, (x, value)), value), variables[:1]),
                                  (_eq(state, sort, n.Call(name, (value, x)), value), variables[:1])))
            for peer in state.callables("operation", inputs=(sort, sort), output=sort)[:24]:
                if peer != name:
                    proposals.append((_eq(state, sort, term, n.Call(peer, (x, y))), variables))
                    proposals.append((_eq(state, sort,
                                          n.Call(name, (x, n.Call(peer, (y, z)))),
                                          n.Call(peer, (n.Call(name, (x, y)), n.Call(name, (x, z))))), triple))
            for unary in state.callables("operation", inputs=(sort,), output=sort)[:16]:
                proposals.append((_eq(state, sort, n.Call(unary, (term,)),
                                        n.Call(name, (n.Call(unary, (x,)), n.Call(unary, (y,))))),
                                  variables))
        for peer in state.callables("operation", inputs=sig.inputs, output=sort)[:48]:
            if peer != name and len(sig.inputs) == 1:
                proposals.append((_eq(state, sort, term, n.Call(peer, left_args)), variables))
        if len(sig.inputs) == 1 and sig.inputs[0] == sort:
            x, y = n.Var("a"), n.Var("b")
            for measure in vocab.int_measures(state, sort)[:8]:
                proposals.append((_eq(state, "int", n.Call(measure, (term,)),
                                               n.Call(measure, (x,))), variables))
            for order in vocab.less(state, sort)[:2]:
                predicate = n.Call(order, (x, y))
                first = n.Call(name, (x,))
                second = n.Call(name, (y,))
                equal = vocab.equal(state, sort)
                consequent = n.Call(order, (first, second))
                if equal:
                    consequent = n.Case(((n.Test(consequent), n.Lit(True)),
                                         (n.Test(n.Call(equal[0], (first, second))), n.Lit(True))),
                                        n.Lit(False))
                proposals.append((n.Case(((n.Test(predicate), consequent),), n.Lit(True)),
                                  (("a", sort), ("b", sort))))
            for tester in (list(state.sorts[sort].testers) + vocab.deciders(state, sort))[:8]:
                if state.signature(tester) is not None and state.signature(tester).inputs == (sort,):
                    test = n.Call(tester, (x,))
                    preserved = n.Call(tester, (term,))
                    proposals.append((n.Case(((n.Test(test), preserved),), n.Lit(True)), variables))
        for statement, params in proposals:
            if statement is None or any(sort_name not in state.sorts for _, sort_name in params):
                continue
            law = _law(state, statement, params)
            key = _key(law, state)
            if key not in seen and _probe(state, statement, params):
                seen.add(key)
                yield law


def _domains(state, law):
    """Never claim a larger scope than the probes or an invented dependency's request."""
    domains = {}
    for _, sort in law.vars:
        if sort not in state.sorts:
            return None
        allowed = list(state.sorts[sort].values)
        for ref in law.depends_on:
            request = state.requests.get(ref)
            sig = state.signature(ref)
            if request is None or sig is None or not request.domain or len(sig.inputs) != len(request.domain[0]):
                continue
            for index, input_sort in enumerate(sig.inputs):
                if input_sort == sort:
                    values = [row[index] for row in request.domain]
                    allowed = [value for value in allowed if any(value_equal(value, item) for item in values)]
        unique = []
        for value in allowed:
            if not any(value_equal(value, earlier) for earlier in unique):
                unique.append(value)
        domains[sort] = tuple(sorted(unique, key=_probe_size))
    return domains if all(domains.values()) else None


def _probe_size(value):
    if type(value) is int:
        return abs(value)
    if isinstance(value, str):
        return len(value)
    if isinstance(value, (tuple, list)):
        return 1 + sum(_probe_size(item) for item in value)
    if hasattr(value, "fields"):
        return 1 + sum(_probe_size(item) for item in value.fields)
    return 0


def _sort(state, node, variables):
    if isinstance(node, n.Var):
        return variables.get(node.name)
    if isinstance(node, n.Lit):
        if isinstance(node.value, bool):
            return "bool"
        if type(node.value) is int:
            return "int"
        if isinstance(node.value, str):
            return "str"
        if hasattr(node.value, "sort"):
            return node.value.sort
        matches = [name for name, sort in state.sorts.items()
                   if any(value_equal(node.value, value) for value in sort.values)]
        return matches[0] if len(matches) == 1 else None
    if isinstance(node, n.Call):
        sig = state.signature(node.fn)
        if (sig is None or sig.op_inputs or len(sig.inputs) != len(node.args) or
                any(_sort(state, arg, variables) != sort for arg, sort in zip(node.args, sig.inputs))):
            return None
        return sig.output
    if isinstance(node, n.Case):
        outputs = [_sort(state, body, variables) for _, body in node.arms]
        outputs.append(_sort(state, node.default, variables))
        if any(_sort(state, cond.expr, variables) != "bool" for cond, _ in node.arms
               if isinstance(cond, n.Test)):
            return None
        return outputs[0] if outputs[0] is not None and all(item == outputs[0] for item in outputs) else None
    return None


def _evaluated_calls(state, statement, env, scope):
    engine = kernel._Engine(scope, kernel.Limits(fuel=state.world.fuel), True, state.world.dialect)
    root = kernel.CallNode(None, "root", 0, False, (), (), kernel.Unknown("pending"), 0)
    engine.frames.append(root)
    engine.nodes = 1
    outcome = engine.eval(statement, env, {}, 1)
    pending = [root]
    while pending:
        frame = pending.pop()
        if frame.name in state.entries:
            request = state.requests.get(frame.name)
            if request is None or not request.domain or not any(
                    len(row) == len(frame.inputs) and all(value_equal(item, value)
                                                           for item, value in zip(frame.inputs, row))
                    for row in request.domain):
                return outcome, None
        pending.extend(frame.children)
    return outcome, root


def _exhaustive_dependency(state, name):
    request = state.requests.get(name)
    signature = state.signature(name)
    if request is None or signature is None or request.method != "exhaustive":
        return False
    if any(sort not in state.sorts or not state.sorts[sort].finite for sort in signature.inputs):
        return False
    if size_of(len(state.sorts[sort].values) for sort in signature.inputs) != len(request.domain):
        return False
    product = itertools.product(*(state.sorts[sort].values for sort in signature.inputs))
    return all(
        len(actual) == len(row) and all(value_equal(item, value)
                                        for item, value in zip(actual, row))
        for actual, row in zip(request.domain, product))


def _check(state, law, seed, bound, sampled=False):
    if not isinstance(law.statement, n.NODE_TYPES) or law.kind != "law" or not law.vars:
        return None
    if len({name for name, _ in law.vars}) != len(law.vars):
        return None
    if len(law.vars) > 3:
        return None
    refs = tuple(sorted(n.references(law.statement)))
    if refs != law.depends_on or law.layer != 1 + max((state.layer(name) for name in refs), default=0):
        return None
    if not any(ref in state.entries for ref in refs):
        return None
    if any(state.signature(ref) is None for ref in refs):
        return None
    statement = _prune(law.statement, state)
    active_refs = set(n.references(statement))
    invented = {ref for ref in refs if ref in state.entries}
    if not invented or not invented <= active_refs or _obvious_constant(statement) is not None:
        return None
    free = {node.name for node in n.walk(statement) if isinstance(node, n.Var)}
    if free != {name for name, _ in law.vars}:
        return None
    if _sort(state, statement, dict(law.vars)) != "bool":
        return None
    domains = _domains(state, law)
    if domains is None:
        return None
    ordered = [domains[sort] for _, sort in law.vars]
    size = 1
    for domain in ordered:
        size *= len(domain)
    prefixes = {sort: len(domains[sort]) if size <= bound else 1 for _, sort in law.vars}
    if size > bound:
        while True:
            options = []
            for sort, length in prefixes.items():
                if length < len(domains[sort]):
                    trial = {**prefixes, sort: length + 1}
                    if size_of(trial[item_sort] for _, item_sort in law.vars) <= bound:
                        options.append((length, sort))
            if not options:
                break
            prefixes[min(options)[1]] += 1
        ordered = [domains[sort][:prefixes[sort]] for _, sort in law.vars]
    if sampled and size > bound:
        import random

        rng = random.Random(seed)
        original = [domains[sort] for _, sort in law.vars]
        assignments = list(itertools.islice(itertools.product(*original), min(bound // 2, size)))
        assignments.extend(tuple(rng.choice(domain) for domain in original)
                           for _ in range(bound - len(assignments)))
        unique = []
        for args in assignments:
            if not any(all(value_equal(left, right) for left, right in zip(args, previous))
                       for previous in unique):
                unique.append(args)
        assignments = unique
        ordered = original
    else:
        assignments = list(itertools.product(*ordered))
    scope = state.library.scope()
    witnessed = set()
    for args in assignments:
        env = dict(zip((name for name, _ in law.vars), args))
        try:
            outcome, trace = _evaluated_calls(state, statement, env, scope)
            if trace is None:
                return None
            pending = [trace]
            while pending:
                frame = pending.pop()
                if frame.name in invented:
                    witnessed.add(frame.name)
                pending.extend(frame.children)
            if not isinstance(outcome, Ok) or not truth(outcome.value):
                return None
        except (TypeError, ValueError, KeyError, RecursionError, AttributeError):
            return None
    if witnessed != invented:
        return None
    exhaustive = (size <= bound and
                  all(state.sorts[sort].finite and len(domains[sort]) == len(state.sorts[sort].values)
                      for _, sort in law.vars) and
                  all(_exhaustive_dependency(state, ref) for ref in invented))
    scope_data = {"domain": {sort: [encode_value(item) for item in domains[sort][:prefixes[sort]]]
                             for sort in prefixes} if not sampled else {
                                 sort: [encode_value(item) for item in domains[sort]] for sort in prefixes},
                  "size": len(assignments), "distinct_inputs": len(assignments),
                  "bound": bound, "product_size": size}
    if not exhaustive:
        scope_data["checked_inputs"] = [[encode_value(item) for item in args] for args in assignments]
    return {"method": "exhaustive" if exhaustive else "sampled" if sampled else "bounded",
            "scope": scope_data, "seed": seed}


def size_of(lengths):
    product = 1
    for length in lengths:
        product *= length
    return product


def check(state, law, seed=0, bound=256, sampled=False):
    """Return evidence for an unrefuted law, or None on false, invalid or unknown."""
    if bound < 1:
        raise ValueError("bound must be positive")
    return fast.deep(_check, state, law, seed, bound, sampled)


def _match(pattern, node, bindings):
    if isinstance(pattern, n.Var):
        existing = bindings.get(pattern.name)
        if existing is not None and existing != node:
            return False
        bindings[pattern.name] = node
        return True
    if type(pattern) is not type(node):
        return False
    if isinstance(pattern, n.Call):
        return pattern.fn == node.fn and len(pattern.args) == len(node.args) and all(
            _match(arg, actual, bindings) for arg, actual in zip(pattern.args, node.args))
    return pattern == node


def _steps(state, term, env):
    try:
        result = fast.evaluate(term, env, state.library.scope(), state.world.fuel, state.world.dialect)
    except (TypeError, ValueError, KeyError, IndexError, AttributeError):
        return None
    return result.steps if isinstance(result.outcome, Ok) else None


def _value(state, law):
    statement = law.statement
    if not isinstance(statement, n.Call) or len(statement.args) != 2:
        return {"sites": 0, "steps_saved_per_use": 0, "total_over_scope": 0}
    signature = state.signature(statement.fn)
    if signature is None or not signature.inputs or statement.fn not in vocab.equal(state, signature.inputs[0]):
        return {"sites": 0, "steps_saved_per_use": 0, "total_over_scope": 0}
    left, right = statement.args
    difference = n.length(left) - n.length(right)
    count = 0
    for entry in state.entries.values():
        body = state.library.get(entry.name).body
        if not isinstance(body, n.NODE_TYPES):
            continue
        for node in n.walk(body):
            if isinstance(node, n.NODE_TYPES) and _match(left, node, {}):
                count += 1
    if not count:
        return {"sites": 0, "steps_saved_per_use": 0, "total_over_scope": 0}
    domains = _domains(state, law)
    if domains is None:
        return {"sites": 0, "steps_saved_per_use": 0, "total_over_scope": 0}
    assignments = itertools.islice(itertools.product(*(domains[sort] for _, sort in law.vars)), 256)
    saved = 0
    trials = 0
    for args in assignments:
        env = dict(zip((name for name, _ in law.vars), args))
        left_steps, right_steps = _steps(state, left, env), _steps(state, right, env)
        if left_steps is None or right_steps is None:
            return {"sites": 0, "steps_saved_per_use": 0, "total_over_scope": 0}
        saved += left_steps - right_steps
        trials += 1
    if difference <= 0 and saved <= 0 or not trials:
        return {"sites": 0, "steps_saved_per_use": 0, "total_over_scope": 0}
    mean = max(0, saved / trials)
    return {"sites": count, "steps_saved_per_use": mean, "total_over_scope": count * mean}


def value(state, law):
    """Count matching catalogue call sites and measured layer-0 steps saved."""
    return fast.deep(_value, state, law)


def discover(state, max_laws=200, seed=0):
    """Return verified, deduplicated laws ordered by shortening value."""
    if max_laws < 0:
        raise ValueError("max_laws must be non-negative")
    if max_laws == 0:
        return []

    def run():
        found = {}
        for law in conjecture(state, tuple(state.entries)):
            key = _key(law, state)
            if key in found:
                continue
            try:
                evidence = _check(state, law, seed, 256)
            except (TypeError, ValueError, KeyError, IndexError, AttributeError):
                evidence = None  # a host rejects the values: no law on this scope
            if evidence is not None:
                found[key] = replace(law, evidence=evidence)
        ranked = sorted(((law, _value(state, law)) for law in found.values()),
                        key=lambda item: (-item[1]["total_over_scope"], -item[1]["sites"],
                                          repr(_key(item[0], state))))
        return [replace(law, name=f"l{index + 1}", shortens=score)
                for index, (law, score) in enumerate(ranked[:max_laws])]

    return fast.deep(run)


def admit_discovered(state, max_laws=200, seed=0):
    """Admit discovered conjectures as promoted core LawSpec definitions."""
    from opulse.gen_v2.admit import admit
    from opulse.gen_v2.base import Entry
    from opulse.gen_v2.moves.law import candidate

    if "law" not in state.world.open_kinds:
        return []
    entries = []
    for law in discover(state, max_laws, seed):
        proposal = candidate(state, law)
        if proposal is not None:
            result = admit(state, proposal)
            if isinstance(result, Entry):
                entries.append(result)
    return entries


def export_json(laws, state=None):
    """JSON-ready law catalogue, with the kernel expression and ASCII notation."""
    return {"schema": "opulse.gen_v2.law/1", "laws": [
        {"name": law.name, "kind": law.kind, "statement": n.to_json(law.statement),
         "text": law.text(state), "vars": [list(item) for item in law.vars],
         "depends_on": list(law.depends_on), "layer": law.layer,
         "evidence": law.evidence, "shortens": law.shortens} for law in laws]}


def write_json(laws, path, state=None):
    """Write an ASCII-only law catalogue to path."""
    from pathlib import Path

    Path(path).write_text(json.dumps(export_json(laws, state), ensure_ascii=True, indent=2) + "\n",
                          encoding="utf-8")
