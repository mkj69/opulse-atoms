"""Generate the grammar's versioned layer-zero declaration."""

import json
from pathlib import Path

from opulse.atoms import nodes as n
from opulse.atoms.spec import CombinatorSpec
from opulse.tasks_v2.decl import WorldFile, compute_lock, host_digest

PATH = Path(__file__).resolve().parents[4] / "worlds/decl/v2/grammar@1.json"
HOST = "opulse.worlds_v2.grammar.hosts:"


def obj(name, tags=None, doc=""):
    return {"kind": "object", "name": name, "form": "given", "base": None, "tags": tags,
            "group": [], "valid": None, "canon": None, "sealed": False, "interface": [],
            "params": [], "equality": "canonical", "canon_cost": "counted", "body": None,
            "host": None, "doc": doc}


def operation(name, inputs, output, rule, errors=(), role="transform"):
    reference = HOST + name
    return {"kind": "operation", "name": name, "symbol": name, "role": role,
            "inputs": [{"name": f"arg{index}", "sort": sort, "enter": "bottom"}
                       for index, sort in enumerate(inputs)],
            "output": {"sort": output, "enter": "bottom"}, "rule": rule,
            "errors": list(errors), "impl": {"host": reference, "digest": host_digest(reference)},
            "cost": 1, "strict": True, "reads_params": []}


def bounded_rec_spec():
    word = n.Var("span")
    rec_body = n.Case(((n.Test(n.Call("le", (n.Call("length", (word,)), n.Lit(1)))),
                        n.Call("leaf", (word,))),),
                      n.Let("mid", n.Call("sub", (n.Call("length", (word,)), n.Lit(1))),
                            n.Call("join", (word,
                                            n.Call("recurse", (n.Call("slice_word", (word, n.Lit(0), n.Var("mid"))),)),
                                            n.Call("recurse", (n.Call("slice_word", (
                                                word, n.Var("mid"), n.Call("length", (word,)))),))))))
    return CombinatorSpec("bounded_rec", ("leaf", "join", "w"), ("leaf", "join"),
                          n.Rec("recurse", ("span",), rec_body, (n.Var("w"),),
                                n.Call("length", (word,)), memo=True))


def build():
    operations = [
        operation("expand", ("Draft", "List", "Rule"), "Draft",
                  "Expand exactly one E leaf by a grammar production, respecting 40 nodes and the public word bounds.",
                  ("path", "rule", "not_leaf", "size", "depth")),
        operation("list0", (), "List", "Construct an empty list."),
        operation("list1", ("any",), "List", "Construct a singleton list."),
        operation("list2", ("any", "any"), "List", "Construct a two-element list."),
        operation("list3", ("any", "any", "any"), "List", "Construct a three-element list."),
        operation("word_new", ("List",), "Word", "Check and construct a bounded public token word.",
                  ("size", "depth", "parenthesis", "token")),
        operation("length", ("any",), "int", "Length of a word or list."),
        operation("at", ("any", "int"), "any", "Read the indexed item.", ("index",)),
        operation("slice_word", ("Word", "int", "int"), "Word", "Slice a public word without reordering.", ("index",)),
        operation("append", ("List", "any"), "List", "Append one value to a list."),
        operation("concat", ("any", "any"), "any", "Concatenate equally typed sequences."),
        operation("make_draft", ("str", "List"), "Draft", "Construct a complete grammar node.", ("invalid",)),
        operation("pair", ("any", "any"), "Pair", "Construct a generic ordered pair."),
        operation("hist", ("List",), "Hist", "Construct a frequency sequence from ordered pairs."),
        operation("witness", ("List",), "Witness", "Construct a generic ordered triple."),
        operation("sorted_items", ("List",), "List", "Sort a finite list of integers."),
        operation("tag", ("any",), "str", "Read a tagged constructor."),
        operation("field", ("any", "int"), "any", "Read a tagged constructor field.", ("index",)),
        *[operation(name, ("int", "int"), "int", f"Integer {name}.") for name in ("add", "sub", "mul", "mod", "div")],
        *[operation(name, ("any", "any"), "bool", f"Structural {name} comparison.", role="decide")
          for name in ("eq", "lt", "le")],
        operation("is_int", ("any",), "bool", "Test whether a token is an integer digit.", role="decide"),
        operation("fail", ("str",), "any", "Raise a declared domain failure.", ("rank", "no_parse", "none", "target", "family")),
        operation("minimum", ("List",), "int", "Smallest value in a nonempty list.", ("empty",)),
        operation("maximum", ("List",), "int", "Largest value in a nonempty list.", ("empty",)),
    ]
    probe = HOST + "yield_probe"
    data = {"schema": "opulse.world/2", "world": "grammar", "version": 1,
            "dialect": "atoms-v2", "title": "Two Trees for One Sentence",
            "source": {"kind": "catalogue", "id": "grammar"}, "params": {}, "constants": {},
            "objects": [obj("Word", {"tokens": {"items": "any"}},
                            "Public ordered tokens, up to 48 tokens, 12 numerals, and eight parentheses levels."),
                        obj("Draft", {"E": {}, "num": {"digit": "int"},
                            "+": {"left": "Draft", "right": "Draft"},
                            "*": {"left": "Draft", "right": "Draft"},
                            "group": {"inner": "Draft"}},
                            "Incomplete E derivation with at most 40 rule nodes."),
                        obj("Rule", {"num": {"digit": "int"}, "+": {}, "*": {}, "group": {}},
                            "One of num(1..9), add, mul, or group productions."),
                        obj("List", {"items": {"items": "any"}},
                            "Generic finite ordered list used by kernel recursion."),
                        obj("bool"), obj("int"), obj("str"), obj("any"),
                        obj("Pair", {"pair": {"first": "any", "second": "any"}}),
                        obj("Hist", {"entries": {"items": "Pair"}}),
                        obj("Witness", {"triple": {"items": "any"}})],
            "operations": operations,
            "combinators": {"nodes": ["Var", "Lit", "Call", "Let", "Case", "Rec"],
                            "library": ["seq", bounded_rec_spec().to_dict()], "recursion": "measure"},
            "observation": {"truth": "Draft", "probes": [{"name": "yield_probe", "sort": "Word",
                            "reads": "Draft", "reveals": ["public_word"],
                            "impl": {"host": probe, "digest": host_digest(probe)}}],
                            "capabilities": {"learner": {"channels": ["public_word"], "probes": ["yield_probe"]}},
                            "show": {"input": "public_word", "result": "public_word"}, "judge_view": "full_state"},
            "codec": {}, "lock": {}}
    data["lock"] = compute_lock(WorldFile.from_dict(data))
    return data


def main():
    PATH.write_text(json.dumps(build(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
