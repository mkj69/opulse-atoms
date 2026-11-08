from .nodes import Call, If, Let, Lit, Var


def calls(node):
    if isinstance(node, Call):
        yield node.name
        for arg in node.args:
            yield from calls(arg)
    elif isinstance(node, Let):
        yield from calls(node.bound)
        yield from calls(node.body)
    elif isinstance(node, If):
        yield from calls(node.cond)
        yield from calls(node.then)
        yield from calls(node.other)


def check_program(program, world, library):
    errors = []
    library_names = set(library.names()) if library is not None else set()
    definitions = {definition.name: definition for definition in program.defs}
    known = set(world.operations) | library_names | set(definitions)
    arities = {name: len(spec.inputs) for name, spec in world.operations.items()}
    if library is not None:
        arities.update({name: len(library.get(name).params) for name in library_names})
    arities.update({definition.name: len(definition.params) for definition in program.defs})
    signatures = {name: (tuple(sort.title() for sort in spec.inputs), spec.output.title())
                  for name, spec in world.operations.items()}
    if library is not None:
        signatures.update({name: (library.get(name).param_sorts or ("Nat",) * len(library.get(name).params),
                                  library.get(name).result_sort) for name in library_names})
    signatures.update({definition.name: (definition.param_sorts or ("Nat",) * len(definition.params),
                                         definition.result_sort) for definition in program.defs})
    seen = set()

    def inspect(node, bound, owner):
        if isinstance(node, Var):
            if node.name not in bound:
                errors.append(f"unbound variable {node.name} in {owner}")
            return bound.get(node.name)
        elif isinstance(node, Call):
            arg_sorts = [inspect(arg, bound, owner) for arg in node.args]
            if node.name not in known:
                errors.append(f"unknown call target {node.name} in {owner}")
            elif len(node.args) != arities[node.name]:
                errors.append(f"wrong arity for {node.name}: expected {arities[node.name]}, got {len(node.args)}")
            else:
                inputs, output = signatures[node.name]
                for index, (actual, expected) in enumerate(zip(arg_sorts, inputs), 1):
                    if actual is not None and actual != expected:
                        errors.append(f"argument {index} of {node.name} expects {expected}, got {actual} in {owner}")
                return output
        elif isinstance(node, Let):
            sort = inspect(node.bound, bound, owner)
            return inspect(node.body, {**bound, node.name: sort}, owner)
        elif isinstance(node, If):
            condition = inspect(node.cond, bound, owner)
            if condition is not None and condition != "Bool":
                errors.append(f"if condition must be Bool, got {condition} in {owner}")
            then = inspect(node.then, bound, owner)
            other = inspect(node.other, bound, owner)
            if then is not None and other is not None and then != other:
                errors.append(f"if branches must have the same sort, got {then} and {other} in {owner}")
            return then if then == other else None
        elif isinstance(node, Lit):
            return "Nat"
        else:
            raise TypeError(f"unexpected expression {node!r}")
        return None

    for definition in program.defs:
        if definition.name in seen:
            errors.append(f"duplicate definition {definition.name}")
        if definition.name in world.operations or definition.name in library_names:
            errors.append(f"definition {definition.name} shadows an existing name")
        seen.add(definition.name)
        params = {}
        for param, sort in zip(definition.params, definition.param_sorts):
            if param in params:
                errors.append(f"duplicate parameter {param} in {definition.name}")
            params[param] = sort
        actual = inspect(definition.body, params, definition.name)
        if actual is not None and actual != definition.result_sort:
            errors.append(f"result of {definition.name} expects {definition.result_sort}, got {actual}")

    saved = set(program.saves)
    seen_saves = set()
    if program.saves and not world.library_enabled:
        errors.append("saving definitions is not available in this world")
    for name in program.saves:
        if name in seen_saves:
            errors.append(f"{name} is saved twice")
        seen_saves.add(name)
        if name == "solve":
            errors.append("cannot save solve")
        elif name in library_names:
            errors.append(f"cannot save {name}: already in the library")
        elif name not in definitions:
            errors.append(f"cannot save unknown name {name}")
        else:
            for dependency in sorted(set(calls(definitions[name].body)) & (set(definitions) - saved)):
                errors.append(f"cannot save {name}: calls unsaved definition {dependency}")
    return errors
