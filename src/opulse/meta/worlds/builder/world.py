"""The builder@1 declaration (atoms-meta sections 6 and 7)."""

from functools import lru_cache

from opulse.atoms.spec import Edge, ObjectSpec, OperationSpec
from opulse.atoms.world import WorldDecl
from opulse.meta import code_world
from opulse.meta.builder.instantiate import instantiate
from opulse.meta.export_util import host_rule
from opulse.meta.worlds.builder import hosts

TAGS = {
    "domain": "program", "modalities": ["text"],
    "open_kinds": ["object", "operation", "combinator", "observation", "law", "bridge"],
    "star_kind": "operation", "reasoning": ["compute", "equivalence", "search"],
    "state": "stateless", "outcomes": "deterministic", "visibility": "partial",
    "agents": 1, "scale": "finite tables with at most 4096 tuples",
    "difficulty": "five levels from cards to verified world composition",
    "uses": ["teaching", "evaluation", "experiment"],
}


@lru_cache(maxsize=1)
def declaration():
    """Every given rule records sha256(inspect.getsource(rule))."""
    objects = [ObjectSpec(sort, "given") for sort in ("world", "sort", "op", "row", "cell",
                                                    "tag", "report", "list", "int", "str", "bool",
                                                    "sig", "expr", "z")]
    objects.append(code_world.code_object())
    signatures = {
        "tag_of": (("any",), "str"), "field": (("any", "int"), "any"),
        "with_field": (("any", "int", "any"), "any"),
        "mk": (("str", "str", "list"), "any"),
        "list_len": (("list",), "int"), "list_get": (("list", "int"), "any"),
        "list_append": (("list", "any"), "list"),
        "list_concat": (("list", "list"), "list"),
        "str_eq": (("str", "str"), "bool"),
        "eq": (("any", "any"), "bool"),
        "int_add": (("int", "int"), "int"), "int_sub": (("int", "int"), "int"),
        "int_eq": (("int", "int"), "bool"), "int_lt": (("int", "int"), "bool"),
        "int_mul": (("int", "int"), "int"), "int_div": (("int", "int"), "int"),
        "int_mod": (("int", "int"), "int"), "int_text": (("int",), "str"),
        "str_concat": (("str", "str"), "str"), "str_len": (("str",), "int"),
        "list_index": (("list", "any"), "int"),
        "list_contains": (("list", "any"), "bool"),
        "domain_values": (("world", "str"), "list"),
        "size": (("world",), "int"), "wf": (("world",), "report"),
        "world_hash": (("world",), "str"),
        "call_in": (("world", "str", "list"), "any"),
    }
    rules = {**{name: rule for name, (rule, _) in hosts.RULES.items()}, "call_in": hosts.call_in}
    operations = [OperationSpec(name, "decide" if name in ("eq", "str_eq", "int_eq", "int_lt")
                                else "transform", tuple(Edge(sort) for sort in inputs), Edge(output),
                                f"Given card primitive {name}",
                                impl=host_rule(rules[name]))
                  for name, (inputs, output) in signatures.items()]
    operations.extend(code_world.operations())
    from opulse.meta.worlds.builder.story import z5

    operations.extend(op for op in instantiate(z5())[0].operations
                      if op.name in ("add5", "mul5"))
    return WorldDecl("builder", 1, "atoms-v2", {}, {}, tuple(objects), tuple(operations),
                     {"nodes": ["Var", "Lit", "Call", "Let", "Case", "Rec"],
                      "library": [], "recursion": "measure"},
                     {"truth": "world", "show": {"input": "World<...>", "result": "value"},
                      "probes": [{"name": "wf", "op": "wf"},
                                 {"name": "world_hash", "op": "world_hash"}],
                      "judge_view": "full_state"}, {}, {"tags": TAGS}, tuple(TAGS["open_kinds"]))
