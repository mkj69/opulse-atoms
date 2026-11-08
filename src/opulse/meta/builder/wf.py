"""Ordered checks for finite world values (atoms-meta, section 6.2)."""

import itertools
import re

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.values import Card, Ok, Unknown
from opulse.atoms.world import BLOCK_ENDS, RECURSION_MODES
from opulse.meta import code as C
from opulse.meta import engine
from opulse.meta.builder import world_value as V
from opulse.meta.builder.instantiate import _assemble, domain


class _Invalid(ValueError):
    pass


def _need(condition, detail):
    if not condition:
        raise _Invalid(detail)


def _identifier(name):
    return isinstance(name, str) and re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", name) is not None


def _list(value):
    return C.items(value)


def _execution_card(card):
    """Assemble checked sorts and operations without hashing unchecked later fields."""
    fields = list(card.fields)
    fields[4:10] = (C.lst(("Var", "Lit", "Call", "Let", "Case", "Rec")),
                    "measure", C.lst(()), "full_state", C.lst(("operation",)), C.lst(()))
    return V.canonicalize(Card("world", "world", tuple(fields[:10])))


def _type(node, env, signatures, recursive=None):
    if isinstance(node, n.Var):
        _need(node.name in env, f"unbound variable {node.name}")
        return env[node.name]
    if isinstance(node, n.Lit):
        value = node.value
        if type(value) is int:
            return "int"
        if isinstance(value, str):
            return "str"
        if isinstance(value, Card):
            return value.sort
        raise _Invalid("unsupported literal")
    if isinstance(node, n.Call):
        _need(node.fn in signatures or recursive and node.fn == recursive[0],
              f"unknown or forward operation {node.fn}")
        inputs, output = (recursive[1:] if recursive and node.fn == recursive[0]
                          else signatures[node.fn])
        _need(len(node.args) == len(inputs), f"arity mismatch for {node.fn}")
        for arg, sort in zip(node.args, inputs):
            actual = _type(arg, env, signatures, recursive)
            _need(actual == sort or (sort == "int" and actual in signatures.get("_ranges", ()))
                  or (actual == "int" and sort in signatures.get("_ranges", ())),
                  f"input type mismatch for {node.fn}")
        return output
    if isinstance(node, n.Let):
        value = _type(node.value, env, signatures, recursive)
        return _type(node.body, {**env, node.name: value}, signatures, recursive)
    if isinstance(node, n.Case):
        types = []
        for cond, result in node.arms:
            for item in n.walk(cond):
                if isinstance(item, n.Test):
                    _need(_type(item.expr, env, signatures, recursive) == "bool", "case test must be bool")
            types.append(_type(result, env, signatures, recursive))
        if node.default is not None:
            types.append(_type(node.default, env, signatures, recursive))
        _need(types and len(set(types)) == 1, "case output types differ")
        return types[0]
    if isinstance(node, n.Rec):
        _need(len(node.params) == len(node.args), "recursive arity mismatch")
        inputs = tuple(_type(arg, env, signatures, recursive) for arg in node.args)
        _need(recursive is None, "nested recursion needs a distinct scope")
        result = _type(node.body, {**env, **dict(zip(node.params, inputs))}, signatures,
                       (node.fn, inputs, signatures["_expected"]))
        _need(result == signatures["_expected"], "recursive result type mismatch")
        if isinstance(node.measure, str):
            _need(node.measure == "fuel", "unsupported recursion measure")
        else:
            _need(_type(node.measure, {**env, **dict(zip(node.params, inputs))}, signatures) == "int",
                  "recursion measure must be int")
        return result
    if isinstance(node, n.Blocks):
        local = env.copy()
        for name, init in node.vars:
            local[name] = _type(init, local, signatures, recursive)
        outputs = []
        for _, block in node.blocks:
            block_env = local.copy()
            for name, expr in block.assigns:
                _need(name in local and _type(expr, block_env, signatures, recursive) == local[name],
                      "block assignment type mismatch")
                block_env[name] = local[name]
            if isinstance(block.end, n.Halt):
                outputs.append(_type(block.end.value, block_env, signatures, recursive))
            if isinstance(block.end, n.CondJump):
                for item in n.walk(block.end.cond):
                    if isinstance(item, n.Test):
                        _need(_type(item.expr, block_env, signatures, recursive) == "bool",
                              "jump test must be bool")
        _need(outputs and len(set(outputs)) == 1, "block halt types differ")
        return outputs[0]
    raise _Invalid(f"unsupported node {type(node).__name__}")


def _check_names(card):
    sorts, ops, probes = (_list(card.fields[index]) for index in (2, 3, 6))
    for label, names in (("sort", [entry.fields[0] for entry in sorts]),
                         ("op", [entry.fields[0] for entry in ops]), ("probe", probes)):
        _need(all(_identifier(name) for name in names), f"invalid {label} name")
        _need(len(names) == len(set(names)), f"duplicate {label} name")
    _need("__range_le" not in [entry.fields[0] for entry in ops], "reserved operation name")


def _check_sorts(card):
    sorts = {}
    for definition in _list(card.fields[2]):
        _need(isinstance(definition, Card) and definition.sort == "sort", "invalid sort declaration")
        name = definition.fields[0]
        _need(name not in ("int", "bool"), f"reserved sort {name}")
        if definition.tag == "enum":
            tags = _list(definition.fields[1])
            _need(0 < len(tags) <= 256 and all(_identifier(tag) for tag in tags)
                  and len(tags) == len(set(tags)), f"invalid enum {name}")
        elif definition.tag == "range":
            lo, hi = definition.fields[1:]
            _need(type(lo) is int and type(hi) is int and lo <= hi and hi - lo < 256,
                  f"invalid range {name}")
        else:
            raise _Invalid(f"invalid sort {name}")
        sorts[name] = definition
    for op in _list(card.fields[3]):
        if op.tag == "table":
            names = (*_list(op.fields[2]), op.fields[3])
        else:
            _need(op.tag == "body" and isinstance(op.fields[1], Card), "invalid body declaration")
            code = op.fields[1]
            _need(code.sort == "code" and code.tag == "def", "body needs code")
            signature = code.fields[1]
            _need(signature.tag == "op", "body needs operation signature")
            names = (*(edge.fields[0] for edge in _list(signature.fields[0])),
                     signature.fields[1].fields[0])
        _need(all(name in sorts or name in ("int", "bool", "str") for name in names),
              f"unknown sort in {op.fields[0]}")


def _check_tables(card):
    sorts = {entry.fields[0]: entry for entry in _list(card.fields[2])}
    for op in _list(card.fields[3]):
        if op.tag != "table":
            continue
        name, role, inputs, output, errors, rows, cost = op.fields
        _need(role in ("transform", "combine", "decide", "relate", "act") and type(cost) is int
              and cost >= 0, f"invalid role or cost for {name}")
        _need(all(isinstance(reason, str) for reason in _list(errors))
              and len(set(_list(errors))) == len(_list(errors)), f"invalid errors in {name}")
        domains = [domain(sort, sorts) for sort in _list(inputs)]
        _need(all(values is not None for values in domains), f"infinite table input in {name}")
        size = 1
        for values in domains:
            size *= len(values)
        _need(size <= 4096, f"table too large: {name}")
        expected = set(itertools.product(*domains))
        observed = set()
        for entry in _list(rows):
            _need(isinstance(entry, Card) and entry.sort == "row" and entry.tag == "row"
                  and len(entry.fields) == 2, f"invalid row in {name}")
            args, cell = entry.fields
            args = tuple(_list(args))
            _need(args in expected and args not in observed, f"invalid or duplicate row in {name}")
            observed.add(args)
            _need(isinstance(cell, Card) and cell.sort == "cell" and len(cell.fields) == 1,
                  f"invalid cell in {name}")
            if cell.tag == "val":
                values = domain(output, sorts)
                value = cell.fields[0]
                _need((type(value) is int if output == "int" else isinstance(value, str)
                       if output == "str" else value in values), f"invalid output in {name}")
            else:
                _need(cell.tag == "err" and cell.fields[0] in _list(errors),
                      f"unlisted error in {name}")
        _need(observed == expected, f"incomplete table: {name}")


def _check_bodies(card):
    if not any(op.tag == "body" for op in _list(card.fields[3])):
        return
    _need("operation" in _list(card.fields[8]), "operation kind is closed")
    decl, executable = _assemble(_execution_card(card))
    signatures = {"_ranges": tuple(entry.fields[0] for entry in _list(card.fields[2]) if entry.tag == "range")}
    previous = {}
    sorts = {entry.fields[0]: entry for entry in _list(card.fields[2])}
    scope_atoms = [entry for entry in executable if isinstance(entry, kernel.Atom) and entry.name != "__range_le"]
    scope_defns = []
    for op in _list(card.fields[3]):
        name = op.fields[0]
        if op.tag == "table":
            signatures[name] = (tuple(_list(op.fields[2])), op.fields[3])
        else:
            code = op.fields[1]
            try:
                _need(C.is_canonical(code), f"noncanonical code in {name}")
                decoded = C.decode(code)
                _need(decoded.kind == "operation" and not decoded.deps, f"unsupported dependencies in {name}")
                _need(all(atom_name in previous and digest == C.atom_digest(previous[atom_name])
                          for atom_name, digest in decoded.atoms), f"foreign or forward atom in {name}")
                _need(n.node_kinds(decoded.main.body) <= set(_list(card.fields[4])),
                      f"closed node in {name}")
                for node in n.walk(decoded.main.body):
                    if isinstance(node, n.Blocks):
                        _need(all(type(block.end).__name__ in _list(card.fields[4])
                                  for _, block in node.blocks), f"closed block terminator in {name}")
                    if isinstance(node, n.Rec):
                        mode = card.fields[5]
                        _need(mode != "none" and (mode == "fuel" or not isinstance(node.measure, str)),
                              f"invalid recursion in {name}")
                inputs_card, output_card = decoded.sig.fields
                inputs = tuple(edge.fields[0] for edge in _list(inputs_card))
                output = output_card.fields[0]
                actual = _type(decoded.main.body, dict(zip(decoded.main.params, inputs)),
                               {**signatures, "_expected": output})
                _need(actual == output or output in signatures["_ranges"] and actual == "int",
                      f"output type mismatch in {name}")
                product = [domain(sort, sorts) for sort in inputs]
                _need(all(values is not None for values in product), f"infinite body input in {name}")
                scope = kernel.DictScope(scope_atoms, scope_defns)
                for args in itertools.product(*product):
                    result = engine.evaluate(decoded.main.body, dict(zip(decoded.main.params, args)), scope,
                                             kernel.Limits(fuel=10_000))
                    _need(not isinstance(result.outcome, Unknown), f"body does not terminate: {name}")
                    if isinstance(result.outcome, Ok):
                        values = domain(output, sorts)
                        value = result.outcome.value
                        _need((type(value) is int if output == "int" else isinstance(value, str)
                               if output == "str" else value in values), f"body output outside {output}: {name}")
                scope_defns.append(kernel.Defn(name, decoded.main.params, decoded.main.body))
                signatures[name] = (inputs, output)
            except (C.CodeError, TypeError, KeyError, IndexError, RecursionError) as exc:
                raise _Invalid(f"invalid body {name}: {exc}") from exc
        previous[name] = next(entry for entry in decl.operations if entry.name == name)


def _check_probes(card):
    roles, dependencies = {}, {}
    for op in _list(card.fields[3]):
        name = op.fields[0]
        if op.tag == "table":
            roles[name], dependencies[name] = op.fields[1], set()
        else:
            roles[name] = "decide" if op.fields[1].fields[1].fields[1].fields[0] == "bool" else "transform"
            dependencies[name] = {ref for ref in n.references(C.decode(op.fields[1]).main.body) if ref in roles}
    for probe in _list(card.fields[6]):
        _need(probe in roles and roles[probe] in ("decide", "transform"), f"invalid probe {probe}")
        pending, seen = [probe], set()
        while pending:
            name = pending.pop()
            if name in seen:
                continue
            seen.add(name)
            _need(roles[name] != "act", f"probe {probe} depends on act {name}")
            pending.extend(dependencies[name])


def _check_laws(card):
    if len(card.fields) == 10:
        return
    declared = _list(card.fields[10])
    names = set()
    for entry in declared:
        _need(isinstance(entry, Card) and entry.sort == "law" and entry.tag == "statement"
              and len(entry.fields) == 2, "invalid law declaration")
        name = entry.fields[0]
        _need(_identifier(name) and name not in names, f"invalid or duplicate law {name}")
        names.add(name)
    sorts = {entry.fields[0]: entry for entry in _list(card.fields[2])}
    decl, entries = _assemble(_execution_card(card))
    signatures = {op.name: (tuple(edge.sort for edge in op.inputs), op.output.sort)
                  for op in decl.operations}
    signatures["_ranges"] = tuple(name for name, entry in sorts.items() if entry.tag == "range")
    scope = kernel.DictScope([entry for entry in entries if isinstance(entry, kernel.Atom)],
                             [entry for entry in entries if isinstance(entry, kernel.Defn)])
    for entry in declared:
        name, code = entry.fields
        _need(C.is_canonical(code), f"noncanonical law code: {name}")
        decoded = C.decode(code)
        _need(decoded.kind == "law" and not decoded.deps, f"invalid law code: {name}")
        variables = tuple(var.fields for var in _list(decoded.sig.fields[0]))
        _need(len(variables) == len(decoded.main.params)
              and len({variable for variable, _ in variables}) == len(variables)
              and all(_identifier(variable) and sort in (*sorts, "bool")
                      for variable, sort in variables), f"invalid law variables: {name}")
        _need(n.node_kinds(decoded.main.body) <= set(_list(card.fields[4])), f"closed law node: {name}")
        _need(all(atom_name in signatures and digest == C.atom_digest(
            next(op for op in decl.operations if op.name == atom_name))
                  for atom_name, digest in decoded.atoms), f"foreign law atom: {name}")
        _need(_type(decoded.main.body, dict(zip(decoded.main.params,
                  (sort for _, sort in variables))), signatures) == "bool", f"law not boolean: {name}")
        domains = [domain(sort, sorts) for _, sort in variables]
        _need(all(values is not None for values in domains), f"infinite law domain: {name}")
        size = 1
        for values in domains:
            size *= len(values)
        _need(size <= 4096, f"law product too large: {name}")
        for values in itertools.product(*domains):
            result = engine.evaluate(decoded.main.body, dict(zip(decoded.main.params, values)),
                                     scope, kernel.Limits(fuel=10_000))
            _need(result.outcome == Ok(Card("bool", "true")),
                  f"law {name} fails at {values!r}: {result.outcome!r}")


def _check_kinds(card):
    kinds = _list(card.fields[8])
    _need(bool(kinds) and all(isinstance(kind, str) for kind in kinds)
          and set(kinds) <= {"object", "operation", "combinator", "observation", "law", "bridge"},
          "invalid open_kinds")
    _need(len(kinds) == len(set(kinds)), "duplicate open_kinds")
    names = _list(card.fields[4])
    _need(len(names) == len(set(names)) and set(names) <= set(n.NODE_NAMES) | BLOCK_ENDS,
          "invalid nodes")
    recursion = card.fields[5]
    _need(recursion in RECURSION_MODES and not (recursion == "none" and "Rec" in names),
          "invalid recursion")
    _need(card.fields[7] == "full_state", "invalid judge_view")


def _check_tags(card):
    required = {"domain", "modalities", "open_kinds", "star_kind", "reasoning", "state",
                "outcomes", "visibility", "agents", "scale", "difficulty", "uses"}
    entries = _list(card.fields[9])
    _need(all(isinstance(entry, Card) and entry.sort == "tag" and entry.tag == "tag"
              and len(entry.fields) == 2 and isinstance(entry.fields[0], str)
              for entry in entries), "invalid tag cards")
    tags = dict(entry.fields for entry in entries)
    _need(len(tags) == len(entries) and required == tags.keys(),
          "missing, duplicate or unknown tags")

    def one(key, options):
        _need(isinstance(tags[key], str) and tags[key] in options, f"invalid tag {key}")

    def many(key, options, nonempty=False):
        values = _list(tags[key])
        _need((bool(values) or not nonempty) and len(values) == len(set(values))
              and set(values) <= options, f"invalid tag {key}")
        return set(values)

    kinds = {"object", "operation", "combinator", "observation", "law", "bridge"}
    one("domain", {"math", "logic", "language", "perception", "agent", "probability", "music", "program", "social", "resource", "time"})
    many("modalities", {"text", "image", "audio"}, True)
    _need(many("open_kinds", kinds, True) == set(_list(card.fields[8])), "tag open_kinds mismatch")
    one("star_kind", kinds)
    _need(tags["star_kind"] in _list(card.fields[8]), "star_kind is closed")
    many("reasoning", {"compute", "search", "planning", "counting", "probability", "equivalence", "parsing", "geometry", "inference", "strategy"}, True)
    for key, options in (("state", {"stateless", "stateful"}),
                         ("outcomes", {"deterministic", "multi-valued", "probabilistic"}),
                         ("visibility", {"full", "partial"}), ("agents", {"1", "2+"})):
        one(key, options)
    many("uses", {"rl-training", "evaluation", "interpretability", "teaching", "experiment"}, True)
    for key in ("scale", "difficulty"):
        _need(isinstance(tags[key], str) and bool(tags[key].strip()), f"invalid tag {key}")


def wf(card):
    """Return the first exact report.ok() or report.bad(check, detail) card."""
    try:
        _need(isinstance(card, Card) and card.sort == "world" and card.tag == "world"
              and len(card.fields) in (10, 11) and _identifier(card.fields[0])
              and type(card.fields[1]) is int and card.fields[1] >= 1, "invalid world name or version")
        for name, check in (("names", _check_names), ("sorts", _check_sorts),
                            ("tables", _check_tables), ("bodies", _check_bodies),
                            ("laws", _check_laws),
                            ("probes", _check_probes), ("kinds", _check_kinds),
                            ("tags", _check_tags)):
            try:
                check(card)
            except _Invalid as exc:
                return Card("report", "bad", (name, str(exc)))
            except (ValueError, TypeError, IndexError, KeyError, AttributeError, C.CodeError) as exc:
                return Card("report", "bad", (name, f"invalid {name}: {exc}"))
    except (_Invalid, ValueError, TypeError, IndexError, KeyError, AttributeError) as exc:
        return Card("report", "bad", ("names", str(exc)))
    return Card("report", "ok")
