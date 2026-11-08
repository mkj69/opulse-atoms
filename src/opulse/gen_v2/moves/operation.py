"""Typed operation proposals over the given and invented sorts of a world."""

from __future__ import annotations

import random
from dataclasses import dataclass
from itertools import product

from opulse.atoms import kernel, nodes
from opulse.atoms.library import VerifyRequest
from opulse.atoms.spec import Edge, OperationSpec
from opulse.atoms.values import Card, Ok, truth
from opulse.gen_v2 import vocab
from opulse.gen_v2.base import Candidate, GenState, Signature
from opulse.gen_v2.kinds.combinators import definition as make_definition


def _starts_at_measure(state, sort, measure) -> bool:
    """An int counter may start at measure(x) when the measure maps int to non-negative ints
    (an absolute value): the loop then counts down from there."""
    return bool(measure) and sort == "int" and measure in vocab.int_measures(state, "int") and \
        state.signature(measure) == Signature(("int",), "int")


def _start_value(state, sort, measure, value):
    if not _starts_at_measure(state, sort, measure):
        return value
    outcome = kernel.call(measure, (value,), state.library.scope()).outcome
    return outcome.value if isinstance(outcome, Ok) else value


def _usable(state: GenState, name: str) -> bool:
    signature = state.signature(name)
    return (signature is not None and not signature.op_inputs
            and signature.output in state.sorts
            and all(sort in state.sorts for sort in signature.inputs))


def _callables(state: GenState, output: str | None = None) -> list[str]:
    return [name for name in state.callables("operation", output=output) if _usable(state, name)]


def _cheap(state: GenState, name: str) -> bool:
    entry = state.entries.get(name)
    return entry is None or ((entry.move != "op.recurse" or entry.steps_mean < 6)
                             and (entry.steps_mean < 16 and entry.steps_max < 55
                                  or state.world.dialect == "legacy-v1" and entry.layer < 10
                                  and entry.steps_mean < 40
                                  and entry.steps_max < 90)
                             and entry.layer < 24)


def _choose(rng: random.Random, names: list[str]) -> str:
    return rng.choice(names) if rng.random() < 0.35 else rng.choice(names[-min(16, len(names)):])


def _literal_ok(state: GenState, sort: str, value) -> bool:
    actual = (value.sort if isinstance(value, Card) else
              "bool" if type(value) is bool else
              "int" if type(value) is int else
              "str" if type(value) is str else None)
    return actual is not None and actual in (sort, state.sorts[sort].base)


def _leaf(state: GenState, rng: random.Random, sort: str, env: dict[str, str]):
    variables = [nodes.Var(name) for name, value_sort in env.items() if value_sort == sort]
    values = [value for value in state.sorts[sort].values
              if _literal_ok(state, sort, value)]
    if variables and (not values or rng.random() < 0.75):
        return rng.choice(variables)
    if values:
        return nodes.Lit(rng.choice(values))
    return rng.choice(variables) if variables else None


def term(state: GenState, rng: random.Random, sort: str, env: dict[str, str], depth: int):
    """Build a typed, small term, or return None if the sort has no inhabitant."""
    leaf = _leaf(state, rng, sort, env) if sort in state.sorts else None
    if depth <= 0 or (leaf is not None and rng.random() < 0.35):
        return leaf
    options = [name for name in _callables(state, sort)
               if _cheap(state, name) and len(state.signature(name).inputs) <= 2]
    for _ in range(min(8, len(options))):
        name = _choose(rng, options)
        options.remove(name)
        signature = state.signature(name)
        args = [term(state, rng, input_sort, env, depth - 1) for input_sort in signature.inputs]
        if all(arg is not None for arg in args):
            return nodes.Call(name, tuple(args))
    return leaf


def _condition(state: GenState, rng: random.Random, env: dict[str, str], depth: int = 1):
    if "bool" not in state.sorts:
        return None
    decisions = [name for name in _callables(state, "bool") if _cheap(state, name)
                 if state.signature(name).inputs and len(state.signature(name).inputs) <= 2
                 and any(sort in env.values() for sort in state.signature(name).inputs)]
    if not decisions:
        if any(state.signature(name).inputs for name in _callables(state, "bool")):
            return None
        boolean_variables = [name for name, sort in env.items() if sort == "bool"]
        return nodes.Test(nodes.Var(rng.choice(boolean_variables))) if boolean_variables else None
    given = [name for name in decisions if name not in state.entries]
    if given and rng.random() < 0.8:
        decisions = given
    name = rng.choice(decisions)
    inputs = state.signature(name).inputs
    variable_slot = rng.choice([index for index, sort in enumerate(inputs) if sort in env.values()])
    args = []
    for index, sort in enumerate(inputs):
        if index == variable_slot:
            args.append(nodes.Var(rng.choice([key for key, value in env.items()
                                              if value == sort])))
        else:
            argument = term(state, rng, sort, env, 0)
            if (index > variable_slot and sort == inputs[variable_slot]
                    and argument == args[variable_slot]):
                alternatives = [nodes.Var(key) for key, value in env.items()
                                if value == sort and nodes.Var(key) != argument]
                alternatives.extend(nodes.Lit(value) for value in state.sorts[sort].values[:8]
                                    if _literal_ok(state, sort, value))
                if alternatives:
                    argument = rng.choice(alternatives)
            args.append(argument)
    args = tuple(args)
    if any(arg is None for arg in args):
        return None
    condition = nodes.Test(nodes.Call(name, args))
    if depth and rng.random() < 0.4:
        other = _condition(state, rng, env, 0)
        if other is not None:
            return rng.choice((nodes.And, nodes.Or))(condition, other)
    return nodes.Not(condition) if rng.random() < 0.25 else condition


def _candidate(state: GenState, move: str, inputs: tuple[str, ...], output: str, body, meta=None):
    if body is None or not nodes.node_kinds(body) <= state.world.decl.opened_nodes():
        return None
    name = state.names.fresh("operation")
    params = [f"x{index}" for index in range(len(inputs))]
    spec = OperationSpec(name, "decide" if output == "bool" else "transform",
                         tuple(Edge(sort) for sort in inputs), Edge(output),
                         "Apply the typed kernel expression to the declared inputs.",
                         extra={"input_names": params})
    definition = make_definition(state, "operation", name, spec, body, fold_layer=False)
    bound = 8 if len(inputs) < 2 else 6
    domains = [state.sorts[sort].values for sort in inputs]
    request = None
    if any(len(values) > bound for values in domains):
        # Spec 8: "bounded" = every input up to a size bound. Probe values are ordered by
        # size, so a prefix of each sort's values is such a bound.
        samples = tuple(product(*(values[:bound] for values in domains)))
        description = (f"bounded: every argument among the first {bound} probe values of its sort "
                       f"(values ordered by size; up to {bound} per argument; inputs {', '.join(inputs)})")
        request = VerifyRequest("bounded", samples,
                                {"domain": description, "description": description,
                                 "size": len(samples), "bound": bound})
    return Candidate(definition, Signature(inputs, output), move,
                     request=request,
                     contract="Equal to its unfolding on the recorded verification domain.",
                     meta=meta or {})


def _target(state: GenState, rng: random.Random, output: str | None = None):
    entries = [entry.name for entry in state.entries.values()
               if entry.kind == "operation" and _usable(state, entry.name)
               and (output is None or entry.signature.output == output)
               and _cheap(state, entry.name)
               and (entry.move != "op.recurse" or entry.steps_mean < 6)
               and len(entry.signature.inputs) <= 2]
    wrappers = {sort for name in _callables(state) if _cheap(state, name)
                and len(state.signature(name).inputs) <= 2
                for sort in state.signature(name).inputs}
    entries = [name for name in entries if state.signature(name).output in wrappers]
    if entries:
        transforms = [name for name in entries if state.signature(name).output != "bool"]
        if not transforms and output is None and rng.random() < 0.95:
            given_transforms = [name for name in _callables(state)
                                if name not in state.entries and 0 < len(state.signature(name).inputs) <= 2
                                and state.signature(name).output != "bool"
                                and state.signature(name).output in wrappers]
            if given_transforms:
                return rng.choice(given_transforms)
        if transforms and rng.random() < 0.95:
            entries = transforms
        unary = [name for name in entries if len(state.signature(name).inputs) == 1]
        if unary and rng.random() < 0.7:
            entries = unary
        highest = max(state.layer(name) for name in entries)
        target_layer = rng.choices(range(1, highest + 1),
                                   weights=[1 + 3 * (layer > 2 * highest / 3)
                                            for layer in range(1, highest + 1)])[0]
        distance = min(abs(state.layer(name) - target_layer) for name in entries)
        return rng.choice([name for name in entries
                           if abs(state.layer(name) - target_layer) == distance])
    given = [name for name in _callables(state, output)
             if 0 < len(state.signature(name).inputs) <= 2
             and state.signature(name).output in wrappers]
    transforms = [name for name in given if state.signature(name).output != "bool"]
    if transforms and rng.random() < 0.95:
        given = transforms
    return rng.choice(given) if given else None


def _substitute(state: GenState, rng: random.Random):
    if "Call" not in state.world.decl.opened_nodes():
        return None
    for _ in range(64):
        target = _target(state, rng)
        if target is None:
            return None
        signature = state.signature(target)
        inputs = signature.inputs
        if not inputs:
            continue
        extra = signature.output if rng.random() < 0.65 else rng.choice(inputs)
        inputs = inputs + (extra,) if rng.random() < 0.18 else inputs
        if len(inputs) > 2:
            inputs = inputs[:2]
        env = {f"x{index}": sort for index, sort in enumerate(inputs)}
        args = []
        for index, sort in enumerate(signature.inputs):
            value = nodes.Var(f"x{index}") if index < len(inputs) and inputs[index] == sort else term(state, rng, sort, env, 0)
            if value is None:
                break
            args.append(value)
        if len(args) != len(signature.inputs):
            continue
        anchor = nodes.Call(target, tuple(args))
        wrappers = [name for name in _callables(state) if name != target and _cheap(state, name)
                    and signature.output in state.signature(name).inputs
                    and len(state.signature(name).inputs) <= 2]
        rng.shuffle(wrappers)
        for wrapper in wrappers[:12]:
            wrapped = state.signature(wrapper)
            slot = rng.choice([index for index, sort in enumerate(wrapped.inputs) if sort == signature.output])
            arguments = [anchor if index == slot else term(state, rng, sort, env, 1)
                         for index, sort in enumerate(wrapped.inputs)]
            if any(arg is None for arg in arguments):
                continue
            body = nodes.Call(wrapper, tuple(arguments))
            if all(any(isinstance(node, nodes.Var) and node.name == name for node in nodes.walk(body))
                   for name in env):
                return _candidate(state, "op.substitute", inputs, wrapped.output, body,
                                  {"target": target})
    return None


def _specialize(state: GenState, rng: random.Random):
    if "Call" not in state.world.decl.opened_nodes():
        return None
    sources = [name for name in _callables(state) if _cheap(state, name)
               and len(state.signature(name).inputs) >= 3
               and len(state.signature(name).inputs) <= 4]
    if not sources:
        return None
    for _ in range(32):
        source = _choose(rng, sources)
        signature = state.signature(source)
        slots = sorted(rng.sample(range(len(signature.inputs)), 2))
        inputs = tuple(signature.inputs[index] for index in slots)
        env = {f"x{index}": sort for index, sort in enumerate(inputs)}
        args = []
        for index, sort in enumerate(signature.inputs):
            if index in slots:
                args.append(nodes.Var(f"x{slots.index(index)}"))
            else:
                args.append(term(state, rng, sort, env, rng.choice((0, 0, 1))))
        if any(arg is None for arg in args):
            continue
        body = nodes.Call(source, tuple(args))
        output = signature.output
        wrappers = [name for name in _callables(state) if name != source and _cheap(state, name)
                    and len(state.signature(name).inputs) <= 2
                    and output in state.signature(name).inputs]
        if wrappers and rng.random() < 0.7:
            rng.shuffle(wrappers)
            for wrapper in wrappers[:8]:
                wrapped = state.signature(wrapper)
                slot = rng.choice([index for index, sort in enumerate(wrapped.inputs)
                                   if sort == output])
                arguments = [body if index == slot else term(state, rng, sort, env, 0)
                             for index, sort in enumerate(wrapped.inputs)]
                if all(arg is not None for arg in arguments):
                    body = nodes.Call(wrapper, tuple(arguments))
                    output = wrapped.output
                    break
        if all(any(isinstance(node, nodes.Var) and node.name == name
                   for node in nodes.walk(body)) for name in env):
            return _candidate(state, "op.specialize", inputs, output, body,
                              {"source": source})
    return None


def _combine(state: GenState, rng: random.Random):
    if "Call" not in state.world.decl.opened_nodes():
        return None
    entries = [entry for entry in state.entries.values() if entry.kind == "operation"
               and _usable(state, entry.name) and _cheap(state, entry.name)
               and (entry.move != "op.recurse" or entry.steps_mean < 6)
               and 0 < len(entry.signature.inputs) <= 2]
    if len(entries) < 2:
        return _substitute(state, rng)
    for _ in range(24):
        first = state.entries.get(_target(state, rng))
        if first is None or first not in entries:
            first = rng.choice(entries)
        others = [entry for entry in entries if entry.name != first.name]
        same_inputs = [entry for entry in others if entry.signature.inputs == first.signature.inputs]
        if same_inputs and rng.random() < 0.8:
            others = same_inputs
        second = rng.choice(others[-min(35, len(others)):])
        combiners = [name for name in _callables(state)
                     if _cheap(state, name) and name not in (first.name, second.name)
                     and 2 <= len(state.signature(name).inputs) <= 4
                     and (first.signature.output in state.signature(name).inputs)
                     and (sum(sort == first.signature.output
                              for sort in state.signature(name).inputs) >= 2
                          if first.signature.output == second.signature.output
                          else second.signature.output in state.signature(name).inputs)]
        if not combiners:
            continue
        inputs = first.signature.inputs
        for value_sort in second.signature.inputs:
            if value_sort not in inputs or (len(inputs) == 1 and rng.random() < 0.65):
                inputs += (value_sort,)
            if len(inputs) >= 2:
                break
        inputs = inputs[:2]
        env = {f"x{index}": sort for index, sort in enumerate(inputs)}
        def call(entry, environment=env):
            args = [term(state, rng, sort, environment, 0) for sort in entry.signature.inputs]
            return nodes.Call(entry.name, tuple(args)) if all(arg is not None for arg in args) else None
        left, right = call(first), call(second)
        if left is None or right is None:
            continue
        if (len(inputs) == 2 and inputs[0] == inputs[1]
                and first.signature.inputs == second.signature.inputs == (inputs[0],)):
            left = nodes.Call(first.name, (nodes.Var("x0"),))
            right = nodes.Call(second.name, (nodes.Var("x1"),))
        combiner = rng.choice(combiners)
        signature = state.signature(combiner)
        first_slot = rng.choice([index for index, sort in enumerate(signature.inputs)
                                 if sort == first.signature.output])
        second_slot = rng.choice([index for index, sort in enumerate(signature.inputs)
                                  if index != first_slot and sort == second.signature.output])
        arguments = [left if index == first_slot else right if index == second_slot
                     else term(state, rng, sort, env, 0)
                     for index, sort in enumerate(signature.inputs)]
        if any(argument is None for argument in arguments):
            continue
        body = nodes.Call(combiner, tuple(arguments))
        if not all(any(isinstance(node, nodes.Var) and node.name == name for node in nodes.walk(body))
                   for name in env):
            continue
        return _candidate(state, "op.combine", inputs, state.signature(combiner).output, body)
    return None


def _branch(state: GenState, rng: random.Random):
    if not {"Case", "Call"} <= state.world.decl.opened_nodes():
        return None
    for _ in range(12):
        target = _target(state, rng)
        if target is None:
            return None
        signature = state.signature(target)
        if not signature.inputs or len(signature.inputs) > 2:
            continue
        inputs = signature.inputs
        arguments = tuple(nodes.Var(f"x{index}") for index in range(len(inputs)))
        guard_sorts = [sort for sort in state.sorts if sort not in inputs
                       and (sort == "bool" and not any(
                           state.signature(name).inputs for name in _callables(state, "bool"))
                            or any(state.signature(name).inputs == (sort,)
                                   or state.signature(name).inputs == (sort, sort)
                                   for name in _callables(state, "bool")))]
        if len(inputs) == 1 and rng.random() < 0.7:
            if guard_sorts:
                inputs += (rng.choice(guard_sorts),)
        elif len(inputs) == 2 and guard_sorts and rng.random() < 0.7:
            slot = rng.randrange(2)
            retained = signature.inputs[slot]
            fixed_sort = signature.inputs[1 - slot]
            fixed = term(state, rng, fixed_sort, {"x0": retained}, 0)
            if fixed is None:
                continue
            inputs = (retained, rng.choice(guard_sorts))
            arguments = (nodes.Var("x0"), fixed) if slot == 0 else (fixed, nodes.Var("x0"))
        env = {f"x{index}": sort for index, sort in enumerate(inputs)}
        guard = _condition(state, rng, env)
        if guard is None:
            continue
        anchor = nodes.Call(target, arguments)
        default = term(state, rng, signature.output, env, 1)
        alternatives = [name for name in _callables(state, signature.output)
                        if name != target and name in state.entries and _cheap(state, name)
                        and state.entries[name].move != "op.recurse"
                        and state.signature(name).inputs == signature.inputs]
        if alternatives and rng.random() < 0.75:
            default = nodes.Call(_choose(rng, alternatives), arguments)
        if default is None or default == anchor:
            continue
        arms = [(guard, anchor)]
        if rng.random() < 0.3:
            other = _condition(state, rng, env)
            value = term(state, rng, signature.output, env, 1)
            if other is not None and value is not None and value != anchor:
                arms.append((other, value))
        return _candidate(state, "op.branch", inputs, signature.output,
                          nodes.Case(tuple(arms), default), {"target": target})
    return None


def _recurse(state: GenState, rng: random.Random):
    if not {"Rec", "Case", "Call"} <= state.world.decl.opened_nodes():
        return None
    if len(state.entries) > 8 and any(entry.move == "op.recurse" for entry in
                                      list(state.entries.values())[-100:]):
        return None
    mode = state.world.decl.combinators.get("recursion")
    if mode not in ("measure", "legacy", "fuel"):
        return None
    measures = {sort: list(pairs) for sort, pairs in state.world.measures.items()}
    bases = {sort: list(names) for sort, names in state.world.bases.items()}
    for sort in state.sorts.values():
        if sort.origin != "invented":
            continue
        steps = [name for name in sort.accessors if state.signature(name) == Signature((sort.name,), sort.name)]
        measures_for_sort = [name for name in _callables(state, "int")
                             if state.signature(name).inputs == (sort.name,)]
        if sort.defined_by and sort.defined_by in state.library.definitions:
            specification = state.library.get(sort.defined_by).spec
            for tag, fields in (specification.tags or {}).items():
                sorts = fields.values() if isinstance(fields, dict) else (pair[1] for pair in fields)
                if sort.name not in sorts:
                    tester = f"{sort.name}.is_{tag}"
                    if state.signature(tester) == Signature((sort.name,), "bool"):
                        bases.setdefault(sort.name, []).append(tester)
        if not bases.get(sort.name):
            bases[sort.name] = [name for name in sort.testers
                                if state.signature(name) == Signature((sort.name,), "bool")]
        measures.setdefault(sort.name, []).extend((step, measure)
                                                    for step in steps for measure in measures_for_sort)
    for sort, pairs in list(measures.items()):
        for step in [name for name in _callables(state, sort) if name in state.entries
                     and _cheap(state, name) and state.signature(name).inputs == (sort,)][-8:]:
            measures[sort].extend((step, measure) for _, measure in pairs[:1])
    if (mode == "measure" and not measures.get("int") and "int" in state.sorts
            and state.sorts["int"].values
            and all(type(value) is int and value >= 0 for value in state.sorts["int"].values)):
        scope = state.library.scope()
        for step in _callables(state, "int"):
            if state.signature(step) != Signature(("int",), "int") or not _cheap(state, step):
                continue
            outcomes = [kernel.call(step, (value,), scope).outcome
                        for value in state.sorts["int"].values]
            if all(value == 0 or (isinstance(outcome, Ok) and type(outcome.value) is int
                                  and 0 <= outcome.value < value)
                   for value, outcome in zip(state.sorts["int"].values, outcomes)):
                for base in vocab.zero_test(state, "int")[:2]:
                    measures.setdefault("int", []).append((step, None))
                    bases.setdefault("int", []).append(base)
                break
    options = [(sort, step, measure, None, None) for sort, pairs in measures.items()
               for step, measure in pairs if sort in state.sorts and _usable(state, step)
               and (measure is None or _usable(state, measure))
               and state.signature(step) == Signature((sort,), sort)
               and (measure is None or state.signature(measure) == Signature((sort,), "int"))
               and bases.get(sort)]
    options.extend((sort, step, None, literal, base or next(
                       (name for name in vocab.zero_test(state, sort)
                        if state.signature(name) == Signature((sort,), "bool")), None))
                   for sort, triples in state.world.counters.items() for step, literal, base in triples
                   if sort in state.sorts and _usable(state, step)
                   and (base is None or _usable(state, base))
                   and state.signature(step) == Signature((sort, sort), sort)
                   and (base is None or state.signature(base) == Signature((sort,), "bool"))
                   and (mode != "measure" or sort == "int"))
    rng.shuffle(options)
    for sort, step, measure, literal, counter_base in options:
        base_names = ([counter_base] if counter_base is not None else
                      [name for name in bases.get(sort, ()) if _usable(state, name)
                       and state.signature(name) == Signature((sort,), "bool")])
        if not base_names:
            continue
        zero = [name for name in base_names if name in vocab.zero_test(state, sort)]
        if zero:
            base_names = zero[:1]
        if measure and step in state.entries:
            scope = state.library.scope()
            probes = state.sorts[sort].values
            def valid(value, base_name=base_names[0], current_scope=scope,
                      measure_name=measure, step_name=step):
                base = kernel.call(base_name, (value,), current_scope).outcome
                if not isinstance(base, Ok):
                    return False
                try:
                    if truth(base.value):
                        return True
                except TypeError:
                    return False
                previous = kernel.call(measure_name, (value,), current_scope).outcome
                following = kernel.call(step_name, (value,), current_scope).outcome
                if not isinstance(previous, Ok) or not isinstance(following, Ok):
                    return False
                next_measure = kernel.call(measure_name, (following.value,), current_scope).outcome
                return (isinstance(next_measure, Ok) and type(previous.value) is int
                        and type(next_measure.value) is int
                        and 0 <= next_measure.value < previous.value)
            if not all(valid(_start_value(state, sort, measure, value)) for value in probes):
                continue
        counter = nodes.Var("counter")
        next_counter = nodes.Call(step, (counter,) if literal is None else
                                  (counter, nodes.Lit(literal)))
        condition = nodes.Test(nodes.Call(base_names[0], (counter,)))
        for name in base_names[1:]:
            condition = nodes.Or(condition, nodes.Test(nodes.Call(name, (counter,))))
        start = nodes.Var("x0")
        if _starts_at_measure(state, sort, measure):
            start = nodes.Call(measure, (start,))
        if (mode == "measure" and measure is None
                and any(type(value) is not int or value < 0 for value in state.sorts[sort].values)):
            continue
        recursion_measure = (nodes.Call(measure, (counter,)) if measure else counter) if mode == "measure" else mode
        if sort != "int" and measure and rng.random() < 0.4:
            constructors = [name for name in state.sorts[sort].constructors
                            if _usable(state, name)]
            nil = [name for name in constructors if state.signature(name).inputs == ()]
            cons = [name for name in constructors if state.signature(name).inputs
                    and state.signature(name).inputs[-1] == sort
                    and len(state.signature(name).inputs) == 2]
            head = [name for name in state.sorts[sort].accessors if _usable(state, name)
                    and state.signature(name).inputs == (sort,)
                    and cons and state.signature(name).output == state.signature(cons[0]).inputs[0]]
            if nil and cons and head:
                head_sort = state.signature(head[0]).output
                transformations = [name for name in _callables(state, head_sort) if _cheap(state, name)
                                   and state.signature(name).inputs == (head_sort,)]
                recursive = nodes.Call("loop", (next_counter,))
                item = nodes.Call(head[0], (counter,))
                if transformations:
                    item = nodes.Call(rng.choice(transformations), (item,))
                rebuilt = nodes.Call(cons[0], (item, recursive))
                rec = nodes.Rec("loop", ("counter",),
                                nodes.Case(((condition, nodes.Call(nil[0], ())),), rebuilt),
                                (start,), recursion_measure)
                return _candidate(state, "op.recurse", (sort,), sort, rec,
                                  {"measure": measure, "step": step})
        if sort == "int" and measure is None and mode == "measure" and rng.random() < 0.7:
            value_sorts = [value_sort for value_sort in state.sorts if value_sort != "int"
                           and any(state.signature(name) == Signature((value_sort,), value_sort)
                                   and _cheap(state, name)
                                   for name in _callables(state, value_sort))]
            rng.shuffle(value_sorts)
            for value_sort in value_sorts:
                workers = [name for name in vocab.steps(state, value_sort)
                           if _cheap(state, name)]
                if not workers:
                    continue
                worker = _choose(rng, workers)
                accumulator = nodes.Var("acc")
                body = nodes.Case(((condition, accumulator),),
                                  nodes.Call("loop", (next_counter,
                                                      nodes.Call(worker, (accumulator,)))))
                rec = nodes.Rec("loop", ("counter", "acc"), body,
                                (start, nodes.Var("x1")), recursion_measure)
                return _candidate(state, "op.recurse", (sort, value_sort), value_sort, rec,
                                  {"measure": measure, "step": step, "worker": worker})
        output = "int" if "int" in state.sorts else sort
        workers = [name for name in _callables(state, output) if _cheap(state, name)
                   and state.signature(name).inputs == (output, output)]
        unary_workers = [name for name in _callables(state, output) if _cheap(state, name)
                         and state.signature(name).inputs == (output,)]
        if not (workers or (sort == "int" and unary_workers)) or not state.sorts[output].values:
            continue
        useful_workers = [name for name in workers if name != "mul"] or workers or unary_workers
        worker = rng.choice(useful_workers)
        accumulator = nodes.Var("acc")
        initial = nodes.Lit(0 if output == "int" and 0 in state.sorts[output].values
                            else rng.choice(state.sorts[output].values))
        heads = [name for name in state.sorts[sort].accessors if _usable(state, name)
                 and state.signature(name) == Signature((sort,), output)
                 and name != step] if state.sorts[sort].origin == "invented" else []
        if heads:
            value = nodes.Call(rng.choice(heads), (counter,))
        elif measure is None and output == "int":
            value = counter
        else:
            value = nodes.Call(measure, (counter,)) if output == "int" else counter
        next_accumulator = nodes.Call(worker, (accumulator, value) if worker in workers
                                      else (accumulator,))
        body = nodes.Case(((condition, accumulator),), nodes.Call("loop", (next_counter, next_accumulator)))
        rec = nodes.Rec("loop", ("counter", "acc"), body, (start, initial), recursion_measure)
        return _candidate(state, "op.recurse", (sort,), output, rec,
                          {"measure": measure, "step": step})
    return None


def _over_object(state: GenState, rng: random.Random):
    invented = [sort for sort in state.sorts.values() if sort.origin == "invented" and sort.values]
    rng.shuffle(invented)
    for sort in invented:
        operations = [name for name in (*sort.constructors, *sort.accessors, *sort.testers)
                      if _usable(state, name)]
        rng.shuffle(operations)
        for name in operations:
            signature = state.signature(name)
            if not signature.inputs or len(signature.inputs) > 2:
                continue
            inputs = signature.inputs
            if len(inputs) == 1 and rng.random() < 0.6:
                inputs += ("int" if "int" in state.sorts else inputs[0],)
            env = {f"x{index}": value for index, value in enumerate(inputs)}
            args = tuple(term(state, rng, value, env, 1) if rng.random() < 0.35
                         else nodes.Var(f"x{index}") for index, value in enumerate(signature.inputs))
            if any(arg is None for arg in args):
                continue
            inner = nodes.Call(name, args)
            if sort.name not in (*inputs, signature.output):
                continue
            wrappers = [other for other in _callables(state) if _cheap(state, other)
                        and other != name and signature.output in state.signature(other).inputs
                        and len(state.signature(other).inputs) <= 2]
            if wrappers:
                wrapper = rng.choice(wrappers)
                wrapped = state.signature(wrapper)
                slot = rng.choice([index for index, value in enumerate(wrapped.inputs)
                                   if value == signature.output])
                arguments = [inner if index == slot else term(state, rng, value, env, 1)
                             for index, value in enumerate(wrapped.inputs)]
                if any(arg is None for arg in arguments):
                    continue
                body = nodes.Call(wrapper, tuple(arguments))
                output = wrapped.output
            elif "Case" in state.world.decl.opened_nodes() and "bool" in state.sorts:
                guard = _condition(state, rng, env)
                alternate = term(state, rng, signature.output, env, 1)
                if guard is None or alternate is None or alternate == inner:
                    continue
                body = nodes.Case(((guard, inner),), alternate)
                output = signature.output
            else:
                continue
            if sort.name not in (*inputs, output):
                continue
            if not all(any(isinstance(node, nodes.Var) and node.name == key
                           for node in nodes.walk(body)) for key in env):
                continue
            candidate = _candidate(state, "op.over_object", inputs, output, body,
                                   {"object": sort.name})
            if candidate is not None:
                return candidate
    return None


@dataclass(frozen=True)
class _OperationMove:
    name: str
    build: object
    kind: str = "operation"

    def __call__(self, state: GenState, rng: random.Random):
        if "operation" not in state.world.open_kinds:
            return None
        return self.build(state, rng)


MOVES = [
    _OperationMove("op.substitute", _substitute),
    _OperationMove("op.branch", _branch),
    _OperationMove("op.recurse", _recurse),
    _OperationMove("op.over_object", _over_object),
    _OperationMove("op.combine", _combine),
    _OperationMove("op.specialize", _specialize),
]
