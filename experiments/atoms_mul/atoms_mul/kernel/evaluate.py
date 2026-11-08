from dataclasses import dataclass

from .nodes import Call, If, Let, Lit, Var, node_from_json
from .ops import MAX_NAT, compute


@dataclass(frozen=True)
class Ok:
    value: int | bool


@dataclass(frozen=True)
class Bottom:
    reason: str


@dataclass(frozen=True)
class Unknown:
    resource: str


Outcome = Ok | Bottom | Unknown


@dataclass(frozen=True)
class Run:
    outcome: Outcome
    steps: int
    boundary_steps: int
    calls: dict[str, int]


def _operation(name, args):
    ok, payload = compute(name, args)
    return Ok(payload) if ok else Bottom(payload)


def evaluate(name, args, *, world, program=None, library=None,
             fuel=200_000, max_depth=2_000, boundary=frozenset()):
    definitions = {definition.name: definition for definition in program.defs} if program else {}
    cached_library = {}
    steps = boundary_steps = 0
    calls = {}
    stack = [("invoke", name, tuple(args), 0, False)]
    result = Ok(0)

    while stack:
        frame = stack.pop()
        action = frame[0]
        if action == "invoke":
            _, target, values, depth, hidden = frame
            if target in world.operations:
                if len(values) != len(world.operations[target].inputs):
                    result = Bottom(f"wrong arity for {target}")
                elif steps >= fuel:
                    result = Unknown("fuel")
                else:
                    steps += 1
                    if not hidden:
                        boundary_steps += 1
                    result = _operation(target, values)
                continue
            definition = definitions.get(target)
            if definition is None and library is not None:
                if target not in cached_library:
                    entry = library.get(target)
                    cached_library[target] = (entry.params, node_from_json(entry.body)) if entry else None
                definition = cached_library[target]
            if definition is None:
                result = Bottom(f"no such name {target}")
                continue
            params, body = ((definition.params, definition.body)
                            if hasattr(definition, "params") else definition)
            if len(values) != len(params):
                result = Bottom(f"wrong arity for {target}")
            elif depth >= max_depth:
                result = Unknown("depth")
            else:
                calls[target] = calls.get(target, 0) + 1
                if not hidden and target in boundary:
                    boundary_steps += 1
                stack.append(("eval", body, dict(zip(params, values)), depth + 1,
                              hidden or target in boundary))
        elif action == "eval":
            _, node, env, depth, hidden = frame
            if isinstance(node, Lit):
                result = Ok(node.value) if 0 <= node.value <= MAX_NAT else Bottom("overflow")
            elif isinstance(node, Var):
                result = Ok(env[node.name]) if node.name in env else Bottom(f"no such name {node.name}")
            elif isinstance(node, Let):
                stack.append(("let", node, env, depth, hidden))
                stack.append(("eval", node.bound, env, depth, hidden))
            elif isinstance(node, If):
                stack.append(("if", node, env, depth, hidden))
                stack.append(("eval", node.cond, env, depth, hidden))
            elif isinstance(node, Call):
                if node.args:
                    stack.append(("args", node, env, depth, hidden, 0, ()))
                    stack.append(("eval", node.args[0], env, depth, hidden))
                else:
                    stack.append(("invoke", node.name, (), depth, hidden))
            else:
                raise TypeError(f"unexpected expression {node!r}")
        elif action == "let":
            _, node, env, depth, hidden = frame
            if isinstance(result, Ok):
                stack.append(("eval", node.body, {**env, node.name: result.value}, depth, hidden))
        elif action == "if":
            _, node, env, depth, hidden = frame
            if isinstance(result, Bottom):
                result = Bottom("nan_condition")  # spec 6.1: a failed condition aborts its Case
            elif isinstance(result, Ok):
                if type(result.value) is not bool:
                    result = Bottom("type: condition is not a bool")
                else:
                    stack.append(("eval", node.then if result.value else node.other, env, depth, hidden))
        elif action == "args":
            _, node, env, depth, hidden, index, values = frame
            if isinstance(result, Ok):
                values += (result.value,)
                if index + 1 < len(node.args):
                    stack.append(("args", node, env, depth, hidden, index + 1, values))
                    stack.append(("eval", node.args[index + 1], env, depth, hidden))
                else:
                    stack.append(("invoke", node.name, values, depth, hidden))
    return Run(result, steps, boundary_steps, calls)
