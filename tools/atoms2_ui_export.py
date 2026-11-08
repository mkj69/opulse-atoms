"""Export executable atoms-v2 kernel traces for the documentation viewer."""

from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.export_digest import inputs_sha256

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from opulse.atoms import nodes as n
from opulse.atoms import notation
from opulse.atoms.combinators import (
    combinator_defn,
    counter_atoms,
    fix_atoms,
    fix_spec,
    list_atoms,
    memoized_spec,
    turns_atoms,
    turns_spec,
)
from opulse.atoms.kernel import Atom, Defn, DictScope, FnRef, call
from opulse.atoms.objects import object_atoms
from opulse.atoms.spec import CombinatorSpec, Definition, ObjectSpec
from opulse.atoms.values import Bottom, Card, Ok, Unknown, encode

OUTPUT = Path(__file__).resolve().parents[1] / "docs/assets/js/atoms2/data.js"
ROOT = Path(__file__).resolve().parents[1]
CORE_DIGEST = inputs_sha256(ROOT, (ROOT / "src/opulse/atoms").glob("*.py"))
TITLE = {
    "mul_3_4": ("mul(3, 4)", "integer"),
    "dot": ("dot([1, 2], [3, 4])", "integer"),
    "twice_triple": ("twice(triple, 1)", "integer"),
    "front_free": ("front_free", "robot"),
}


def list_card(items):
    result = Card("list[int]", "nil")
    for item in reversed(items):
        result = Card("list[int]", "cons", (item, result))
    return result


def world():
    def head(items):
        return items.fields[0] if items.tag == "cons" else Bottom("invalid")

    def tail(items):
        return items.fields[1] if items.tag == "cons" else Bottom("invalid")

    atoms = [
        Atom("zero", 0, lambda: 0, kind="object"),
        Atom("succ", 1, lambda value: value + 1),
        Atom("dec", 1, lambda value: value - 1),
        Atom("neg", 1, lambda value: -value),
        Atom("is_zero", 1, lambda value: value == 0),
        Atom("add", 2, lambda left, right: left + right),
        Atom("mod", 2, lambda left, right: left % right if right else Bottom("div_zero")),
        Atom("head", 1, head),
        Atom("tail", 1, tail),
        Atom("is_nil", 1, lambda items: items.tag == "nil"),
    ]
    var, lit, invoke = n.Var, n.Lit, n.Call
    mul = n.Case(
        ((n.Test(invoke("is_zero", (var("b"),))), lit(0)),),
        n.Let("smaller", invoke("dec", (var("b"),)),
              n.Let("part", invoke("mul", (var("a"), var("smaller"))),
                    invoke("add", (var("a"), var("part"))))),
    )
    dot = n.Let("first_x", invoke("head", (var("x"),)),
          n.Let("first_y", invoke("head", (var("y"),)),
          n.Let("first", invoke("mul", (var("first_x"), var("first_y"))),
          n.Let("rest_x", invoke("tail", (var("x"),)),
          n.Let("second_x", invoke("head", (var("rest_x"),)),
          n.Let("rest_y", invoke("tail", (var("y"),)),
          n.Let("second_y", invoke("head", (var("rest_y"),)),
          n.Let("second", invoke("mul", (var("second_x"), var("second_y"))),
                invoke("add", (var("first"), var("second")))))))))))
    front_free = n.Case(
        ((n.Test(invoke("front_wall")), lit(False)),),
        n.Case(((n.Test(invoke("front_water")), lit(False)),), lit(True)),
    )
    definitions = [
        Defn("mul", ("a", "b"), mul),
        Defn("three", (), n.Let("base", invoke("zero"),
             n.Let("one", invoke("succ", (var("base"),)),
             n.Let("two", invoke("succ", (var("one"),)),
                   invoke("succ", (var("two"),))))), kind="object"),
        Defn("triple", ("x",), n.Let("factor", invoke("three"),
             invoke("mul", (var("x"), var("factor")))), layer=2),
        Defn("dot", ("x", "y"), dot, layer=2),
        Defn("twice", ("f", "x"),
             n.Let("once", invoke("f", (var("x"),)), invoke("f", (var("once"),))),
             kind="combinator"),
        Defn("front_free", (), front_free, kind="observation"),
    ]
    return DictScope(atoms=atoms, defns=definitions)


def ui_value(value):
    if isinstance(value, (Bottom, Unknown)):
        return {"bottom": value.reason} if isinstance(value, Bottom) else {"unknown": value.resource}
    if isinstance(value, Ok):
        return ui_value(value.value)
    if isinstance(value, FnRef):
        return value.name
    if isinstance(value, Card):
        return encode(value)
    if isinstance(value, tuple):
        result = {"t": "list[value]", "tag": "nil", "f": []}
        for item in reversed(value):
            result = {"t": "list[value]", "tag": "cons", "f": [
                ui_value(item) if isinstance(item, tuple) else encode(item), result]}
        return result
    if type(value) in (bool, int, str):
        return value
    raise TypeError(f"cannot show {value!r} in a derivation")


def to_ui(node, serial, path=(), replayed=False):
    serial[0] += 1
    return {
        "id": f"n{serial[0]}", "path": list(path),
        "def": "triple" if node.name == "f" else node.name,
        "kind": node.kind, "layer": node.layer, "given": node.given,
        "cache_hit": node.memo_hit and not replayed, "cached_replay": replayed or node.memo_hit,
        "args": [ui_value(item) for item in node.inputs],
        "result": ui_value(node.outcome),
        "children": [to_ui(child, serial, path + (index,), replayed or node.memo_hit)
                     for index, child in enumerate(node.children)],
    }


def traces():
    integer = world()
    state = {"front_wall": False, "front_water": True}
    robot = DictScope(atoms=[
        Atom("front_wall", 0, lambda: state["front_wall"], kind="observation"),
        Atom("front_water", 0, lambda: state["front_water"], kind="observation"),
    ], defns=[integer.defns["front_free"]])
    examples = {
        "mul_3_4": (integer, "mul", (3, 4)),
        "dot": (integer, "dot", (list_card((1, 2)), list_card((3, 4)))),
        "twice_triple": (integer, "twice", (FnRef("triple"), 1)),
        "front_free": (robot, "front_free", ()),
    }
    derivations, runs = {}, {}
    for key, (scope, name, args) in sorted(examples.items()):
        run = call(name, args, scope, trace=True)
        if run.trace is None or len(run.trace.children) != 1:
            raise ValueError(f"missing root call for {key}")
        root = to_ui(run.trace.children[0], [0])
        if root["result"] != ui_value(run.outcome) or count_leaves(root) != run.steps:
            raise ValueError(f"trace does not account for kernel run: {key}")
        title, world_name = TITLE[key]
        derivations[key] = {"title": title, "world": world_name, "root": root}
        runs[key] = {"steps": run.steps, "outcome": ui_value(run.outcome)}
    return {"derivations": derivations, "runs": runs}


def count_leaves(node):
    return sum(map(count_leaves, node["children"])) if node["children"] else 1


def mode_cases():
    """Return fresh executable scopes and inputs, never cached display-only answers."""
    roads = json.loads((OUTPUT.parents[2] / "data/atoms2/roads.json").read_text())
    edges = tuple((key[0], key[1]) for key in roads["graph"]["edges"])

    def reach(known):
        seen = set(known)
        return tuple(sorted(seen | {right for left, right in edges if left in seen} |
                            {left for left, right in edges if right in seen}))

    fix = fix_spec()
    base = [*counter_atoms(), *list_atoms(), *fix_atoms(), *turns_atoms()]
    fix_scope = DictScope([*base, Atom("reach", 1, reach)], [combinator_defn(fix)])

    var, invoke, literal = n.Var, n.Call, n.Lit
    fib = CombinatorSpec("fib", ("value",), (), n.Rec(
        "fib_local", ("index",),
        n.Case(((n.Test(invoke("comb_le", (var("index"), literal(1)))), var("index")),),
               invoke("comb_add", (
                   invoke("fib_local", (invoke("comb_dec", (var("index"),)),)),
                   invoke("fib_local", (invoke("comb_sub", (var("index"), literal(2))),))))),
        (var("value"),), var("index")))
    fib_memo = memoized_spec(fib)
    memo_scope = DictScope([*base, Atom("comb_add", 2, lambda left, right: left + right)],
                           [combinator_defn(fib), combinator_defn(fib_memo)])

    def apply(move, agent, state):
        first, second, total = state
        return (move, second, total + move) if agent == 0 else (first, move, total + move)

    turns = turns_spec(2)
    turns_scope = DictScope([*base,
        Atom("observe0", 1, lambda state: state[0], kind="observation"),
        Atom("observe1", 1, lambda state: state[1], kind="observation"),
        Atom("choose0", 1, lambda own: own + 2),
        Atom("choose1", 1, lambda own: own * 2),
        Atom("apply", 3, apply)], [combinator_defn(turns)])

    tree = ObjectSpec("Tree", "compose", tags={
        "Leaf": (("value", "int"),),
        "Branch": (("left", "Tree"), ("right", "Tree"))})
    library = SimpleNamespace(world=SimpleNamespace(objects=(tree,)), definitions={})
    derived = object_atoms(tree, library)
    fold_scope = DictScope([*base, *[entry for entry in derived if isinstance(entry, Atom)],
        Atom("leaf_weight", 1, lambda value: value * value),
        Atom("combine_weight", 2, lambda left, right: left + 2 * right)],
        [*[entry for entry in derived if isinstance(entry, Defn)],
         Defn("fold_tree", ("value",), invoke("Tree.fold", (
              literal(FnRef("leaf_weight")), literal(FnRef("combine_weight")), var("value"))),
              kind="combinator", layer=2)])
    leaf = lambda value: Card("Tree", "Leaf", (value,))
    branch = lambda left, right: Card("Tree", "Branch", (left, right))
    tree_value = branch(branch(leaf(2), leaf(7)), branch(leaf(3), branch(leaf(5), leaf(11))))
    return {
        "fixpoint": (fix_scope, "fix", (FnRef("reach"), ("A",), len(roads["graph"]["nodes"])),
                     {"world": "roads", "fixture": "docs/assets/data/atoms2/roads.json"}),
        "memo": (memo_scope, "fib", (9,), {"world": "integer", "comparison": "fib_memo"}),
        "turns": (turns_scope, "turns", (FnRef("observe0"), FnRef("choose0"),
                   FnRef("observe1"), FnRef("choose1"), FnRef("apply"), (5, 9, 0),
                   (0, 1, 1, 0, 1, 0)), {"world": "agents"}),
        "fold": (fold_scope, "fold_tree", (tree_value,), {"world": "Tree", "object": tree}),
    }


def unfold_memo_charges(node):
    """Display the recorded first unfolding for replayed memo charges."""
    completed = {}

    def visit(frame):
        for child in frame.children:
            visit(child)
        if frame.name != "fib_local":
            return
        key = (frame.name, repr(frame.inputs))
        if frame.memo_hit:
            original = completed.get(key)
            if original is None or original.steps != frame.steps:
                raise ValueError("memo replay has no matching charged unfolding")
            frame.children = deepcopy(original.children)
        else:
            completed[key] = frame

    visit(node)
    return node


def memo_hits(node):
    return int(node.memo_hit) + sum(memo_hits(child) for child in node.children)


def executed_memo_hits(node, replayed=False):
    return (int(node.memo_hit and not replayed) +
            sum(executed_memo_hits(child, replayed or node.memo_hit)
                for child in node.children))


def mode_traces():
    derivations, runs = {}, {}
    for key, (scope, name, args, details) in mode_cases().items():
        result = call("fib_memo" if key == "memo" else name, args, scope, trace=True)
        if result.trace is None or len(result.trace.children) != 1:
            raise ValueError(f"missing trace for {key}")
        hit_count = memo_hits(result.trace) if key == "memo" else 0
        executed_hits = executed_memo_hits(result.trace) if key == "memo" else 0
        root = to_ui(unfold_memo_charges(result.trace.children[0]) if key == "memo"
                     else result.trace.children[0], [0])
        if root["result"] != ui_value(result.outcome) or count_leaves(root) != result.steps:
            raise ValueError(f"mode trace does not account for kernel run: {key}")
        if key == "fold":
            tree = details["object"]
            definition = Definition(tree.name, "object", "invented", 1, (), tree, None)
            declaration = notation.print_definition(definition)
        else:
            declaration = None
        ctx = {"kinds": {name: "combinator"} if key in ("fixpoint", "turns") else {}}
        expression = n.Call(name, tuple(n.Lit(arg) for arg in args))
        if key in ("fixpoint", "turns"):
            count = 1 if key == "fixpoint" else 5
            ctx["op_arity"] = {name: count}
        if key == "fold":
            ctx = {"kinds": {name: "combinator"}, "op_arity": {name: 0}}
        if key == "memo":
            ctx = {"kinds": {"fib": "operation", "fib_memo": "operation"}}
        text = notation.print_expr(expression, ctx)
        if notation.parse_expr(text, ctx) != expression:
            raise ValueError(f"notation round trip failed for {key}")
        derivations[key] = {"title": text, "world": details["world"], "root": root}
        run = {"expression": text, "outcome": ui_value(result.outcome),
               "outcome_text": ("Ok(" + notation.print_value(result.outcome.value) + ")"
                                if isinstance(result.outcome, Ok) else str(result.outcome)),
               "steps": result.steps, "work": result.work, "core_digest": CORE_DIGEST}
        if declaration is not None:
            run["declaration"] = declaration
        if "fixture" in details:
            run["fixture"] = details["fixture"]
        if key == "memo":
            plain = call("fib", args, scope, trace=True)
            if plain.outcome != result.outcome or plain.steps != result.steps:
                raise ValueError("memo changed outcome or charged layer-0 steps")
            run["steps"] = plain.steps
            run["work"] = plain.work
            run["memo_steps"] = result.steps
            run["memo_work"] = result.work
            run["memo_expression"] = notation.print_expr(n.Call("fib_memo", (n.Lit(args[0]),)), ctx)
            run["expression"] = run["memo_expression"]
            derivations[key]["title"] = run["expression"]
            run["cache_hits"] = hit_count
            run["executed_cache_hits"] = executed_hits
        runs[key] = run
    return {"derivations": derivations, "runs": runs,
            "layer0": {details["world"]: [{"name": atom.name, "kind": atom.kind}
                                            for atom in scope.atoms.values()]
                       for scope, _, _, details in mode_cases().values()},
            "definitions": {details["world"]: [{"name": defn.name, "kind": defn.kind,
                                                  "layer": defn.layer}
                                                 for defn in scope.defns.values()]
                            for scope, _, _, details in mode_cases().values()}}


def render():
    data = traces()
    data["modes"] = mode_traces()
    from opulse.notation3.export import add_notation3

    add_notation3(data, 'data_js', source='data.js')
    data = json.dumps(data, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return ("/* Generated by tools/atoms2_ui_export.py from opulse.atoms.kernel; do not edit. */\n"
            "(function(root){var A2=root.A2||(root.A2={});A2.kernelData=" + data + ";"
            "if(A2.mock){A2.mock.derivations=A2.kernelData.derivations;A2.mock.source=\"kernel\";}"
            "})(typeof window!==\"undefined\"?window:globalThis);\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if generated data is stale")
    args = parser.parse_args()
    content = render()
    if args.check:
        if not OUTPUT.is_file() or OUTPUT.read_text(encoding="utf-8") != content:
            parser.exit(1, f"stale generated data: {OUTPUT}\n")
    else:
        OUTPUT.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    main()
