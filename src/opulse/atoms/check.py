"""Definition checks (docs/spec/atoms-v2.md, sections 8 and 9)."""

from __future__ import annotations

from opulse.atoms import kernel, nodes
from opulse.atoms.spec import CombinatorSpec, Definition, OperationSpec, compute_layer
from opulse.atoms.values import Card

WILDCARD_SORTS = frozenset({"any", "unknown", None})  # unknown or declared-any sorts never mismatch


def all_dependencies(defn: Definition) -> set[str]:
    """References in a body and observation memory, including literal operation handles."""
    expressions = [defn.body]
    memory = getattr(defn.spec, "memory", None)
    if memory:
        expressions.extend((memory["init"], memory["step"]))
    return set().union(*(nodes.references(expr) | nodes.operation_literals(expr)
                         for expr in expressions if isinstance(expr, nodes.NODE_TYPES)))


def validation_problems(defn: Definition) -> list[str]:
    return defn.validate()


def check_definition(defn: Definition, world, resolve_kind) -> list[str]:
    problems = validation_problems(defn)
    if not isinstance(defn.body, nodes.NODE_TYPES):
        # A compose/refine object has no body: its nodes are valid/canon, checked by the object rules.
        bodiless = defn.kind == "object" and getattr(defn.spec, "form", None) in ("compose", "refine")
        return problems + (["invented definition needs a kernel body"]
                           if defn.origin == "invented" and not bodiless else [])

    op_params = set(defn.spec.op_params) if isinstance(defn.spec, CombinatorSpec) else set()
    references = all_dependencies(defn) - op_params
    expressions = [defn.body]
    if getattr(defn.spec, "memory", None):
        expressions.extend((defn.spec.memory["init"], defn.spec.memory["step"]))
    for node_kind in sorted(set().union(*(nodes.node_kinds(expr) for expr in expressions)) - world.opened_nodes()):
        problems.append(f"node {node_kind} is not opened by the world")

    operations = {op.name: op for op in world.operations}
    refined_bases = {obj.name: obj.base for obj in world.objects if obj.form == "refine"}
    if isinstance(defn.spec, OperationSpec):
        if world.dialect != "legacy-v1" and any(edge.enter.startswith("fold(")
                                                 for edge in (*defn.spec.inputs, defn.spec.output)):
            problems.append("fold entry requires legacy-v1")
        output_object = resolve_kind(defn.spec.output.sort)
        if (isinstance(output_object, Definition) and output_object.kind == "object"
                and output_object.spec.form == "refine"):
            refined_bases[output_object.name] = output_object.spec.base

    def upcasts(actual, expected):
        seen = set()
        while actual in refined_bases and actual not in seen:
            seen.add(actual)
            actual = refined_bases[actual]
            if actual == expected:
                return True
        target = resolve_kind(actual)
        while isinstance(target, Definition) and target.kind == "object" and target.spec.form == "refine" and target.name not in seen:
            seen.add(target.name)
            actual = target.spec.base
            if actual == expected:
                return True
            target = resolve_kind(actual)
        return False

    def resolve(name):
        return resolve_kind(name) or operations.get(name)

    for param in sorted(op_params):  # a scope name would win over the parameter (kernel resolution order)
        if resolve(param) is not None:
            problems.append(f"operation parameter {param} has the name of a world operation or definition")

    def signature(name, local):
        if name in local:
            return local[name], None, None
        if name in op_params:
            return None, None, None
        target = defn if name == defn.name else resolve(name)
        if target is None:
            problems.append(f"unresolved call: {name}")
            return None, None, None
        if isinstance(target, kernel.Atom):
            return target.arity, None, None
        if isinstance(target, kernel.Defn):
            return len(target.params), None, None
        spec = target.spec if isinstance(target, Definition) else target
        if isinstance(spec, OperationSpec):
            return len(spec.inputs), tuple(edge.sort for edge in spec.inputs), spec.output.sort
        if isinstance(spec, CombinatorSpec):
            return len(spec.params), None, None
        return None, None, None

    def infer(node, bindings, local):
        if isinstance(node, nodes.Var):
            if isinstance(defn.spec, OperationSpec) and node.name not in bindings:
                problems.append(f"unbound variable: {node.name}")
            return bindings.get(node.name)
        if isinstance(node, nodes.Lit):
            value = node.value
            if isinstance(value, kernel.FnRef):
                return None
            if isinstance(value, Card):
                return value.sort
            return "bool" if type(value) is bool else "int" if type(value) is int else "str" if type(value) is str else None
        if isinstance(node, nodes.Call):
            arity, inputs, output = signature(node.fn, local)
            if arity is not None and len(node.args) != arity:
                problems.append(f"{node.fn} expects {arity} arguments, got {len(node.args)}")
            for index, arg in enumerate(node.args):
                actual = infer(arg, bindings, local)
                if (inputs and index < len(inputs) and actual not in WILDCARD_SORTS
                        and inputs[index] not in WILDCARD_SORTS and actual != inputs[index]
                        and refined_bases.get(inputs[index]) != actual and
                        not upcasts(actual, inputs[index])):
                    problems.append(f"{node.fn} argument {index + 1}: expected {inputs[index]}, got {actual}")
            return output
        if isinstance(node, nodes.Let):
            value = infer(node.value, bindings, local)
            return infer(node.body, {**bindings, node.name: value}, local)
        if isinstance(node, nodes.Case):
            for condition, body in node.arms:
                visit_condition(condition, bindings, local)
                infer(body, bindings, local)
            return infer(node.default, bindings, local) if node.default is not None else None
        if isinstance(node, nodes.Rec):
            mode = world.combinators["recursion"]
            if node.measure == "legacy" and (mode != "legacy" or world.dialect != "legacy-v1"):
                problems.append("legacy recursion requires a legacy-v1 world")
            elif node.measure == "fuel" and mode != "fuel":
                problems.append("fuel recursion requires fuel mode")
            elif (isinstance(node.measure, str) and node.measure not in ("legacy", "fuel")
                  or not isinstance(node.measure, (str, nodes.NODE_TYPES))):
                problems.append("recursion measure must be a node")
            argument_sorts = tuple(infer(arg, bindings, local) for arg in node.args)
            inner = {**bindings, **dict(zip(node.params, argument_sorts))}
            if not isinstance(node.measure, str):
                measure_sort = infer(node.measure, inner, {**local, node.fn: len(node.params)})
                if measure_sort and measure_sort != "int":
                    problems.append(f"recursion measure must be int, got {measure_sort}")
            infer(node.body, inner, {**local, node.fn: len(node.params)})
            if len(node.args) != len(node.params):
                problems.append(f"{node.fn} expects {len(node.params)} arguments, got {len(node.args)}")
            return None
        if isinstance(node, nodes.Blocks):
            block_bindings = dict(bindings)
            for name, init in node.vars:
                block_bindings[name] = infer(init, block_bindings, local)
            labels = {label for label, _ in node.blocks}
            if node.entry not in labels:
                problems.append(f"unknown block: {node.entry}")
            for _, block in node.blocks:
                current = dict(block_bindings)
                for name, expression in block.assigns:
                    current[name] = infer(expression, current, local)
                end = block.end
                if isinstance(end, nodes.Halt):
                    infer(end.value, current, local)
                else:
                    if isinstance(end, nodes.CondJump):
                        visit_condition(end.cond, current, local)
                        targets = (end.then, end.else_)
                    else:
                        targets = (end.target,)
                    for target in targets:
                        if target not in labels:
                            problems.append(f"unknown block: {target}")
        return None

    def visit_condition(condition, bindings, local):
        if isinstance(condition, nodes.Test):
            infer(condition.expr, bindings, local)
        elif isinstance(condition, (nodes.And, nodes.Or)):
            visit_condition(condition.left, bindings, local)
            visit_condition(condition.right, bindings, local)
        elif isinstance(condition, nodes.Not):
            visit_condition(condition.operand, bindings, local)

    inputs = (tuple(edge.sort for edge in defn.spec.inputs) if isinstance(defn.spec, OperationSpec)
              else ())
    params = (defn.spec.extra.get("input_names", ()) if isinstance(defn.spec, OperationSpec)
              else defn.spec.params if isinstance(defn.spec, CombinatorSpec) else ())
    if isinstance(defn.spec, OperationSpec) and not params:
        edges = tuple(edge.name for edge in defn.spec.inputs)
        params = edges if all(edges) else ()
    if len(params) != len(inputs) and isinstance(defn.spec, OperationSpec):
        params = tuple(f"arg{index}" for index in range(len(inputs)))
    body_sort = infer(defn.body, dict(zip(params, inputs)), {})
    if getattr(defn.spec, "memory", None):
        for expression in (defn.spec.memory["init"], defn.spec.memory["step"]):
            infer(expression, {}, {})
    if (isinstance(defn.spec, OperationSpec) and body_sort not in WILDCARD_SORTS
            and defn.spec.output.sort not in WILDCARD_SORTS | {body_sort}
            and not upcasts(body_sort, defn.spec.output.sort)
            and not (refined_bases.get(defn.spec.output.sort) == body_sort
                     and (defn.spec.output.enter in ("normalize", "bottom") or
                          defn.spec.output.enter.startswith("saturate(") or
                          world.dialect == "legacy-v1" and defn.spec.output.enter.startswith("fold(")))):
        problems.append(f"output: expected {defn.spec.output.sort}, got {body_sort}")

    def dependencies(name, seen):
        target = resolve(name)
        if not isinstance(target, Definition):
            return
        for dependency in target.depends_on:
            if dependency == defn.name:
                problems.append(f"dependency cycle through {name}")
            elif dependency not in seen:
                dependencies(dependency, seen | {dependency})

    for dependency in references:
        if dependency == defn.name:
            if defn.kind != "operation":
                problems.append("only operations may refer to themselves")
        else:
            if resolve(dependency) is None:
                problems.append(f"unresolved call: {dependency}")
            dependencies(dependency, {dependency})
    try:
        def layer_of(name):
            if name in operations:
                return 0
            owner = resolve(name.split(".", 1)[0]) if "." in name else None
            if isinstance(owner, Definition) and owner.kind == "object":
                return owner.layer
            if "." in name and any(obj.name == name.split(".", 1)[0] for obj in world.objects):
                return 0
            target = resolve(name)
            if isinstance(target, kernel.Atom):
                return 0
            return target.layer

        expected = compute_layer((name for name in references if name != defn.name),
                                 layer_of)
        if defn.layer < expected:  # a higher declared layer is allowed (design rows); lower is not
            problems.append(f"layer must be at least {expected}, got {defn.layer}")
    except (AttributeError, KeyError, TypeError):
        pass
    return list(dict.fromkeys(problems))
