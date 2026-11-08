"""Declaration and runtime for code@1 (atoms-meta sections 2 and 7)."""

from pathlib import Path

from opulse.atoms.spec import Edge, ObjectSpec, OperationSpec
from opulse.atoms.world import WorldDecl
from opulse.meta import code_world
from opulse.meta.export_util import host_rule

from . import hosts

DECL = Path(__file__).resolve().parents[5] / "worlds/decl/meta/code@1.json"


TAGS = {"domain": "program", "modalities": ["text"],
        "open_kinds": ["object", "operation", "combinator", "observation", "law", "bridge"],
        "star_kind": "operation", "reasoning": ["compute", "search", "equivalence"],
        "state": "stateless", "outcomes": "deterministic", "visibility": "full",
        "agents": 1, "scale": "224 finite source programs; 17 invented definitions",
        "difficulty": "syntax up to semantics-preserving specialization",
        "uses": ["evaluation", "interpretability", "teaching"]}


def _fields(*spec):
    return [[name, sort] for name, sort in spec]


def declaration():
    """Build the code world from source-backed given atoms (atoms-meta 8)."""
    shapes = {
        "expr": {"var": "name:str", "lit": "value:any", "fn": "name:str",
                 "call": "fn:str args:list", "let": "name:str value:expr body:expr",
                 "case": "arms:list default:opt",
                 "rec": "fn:str params:list body:expr args:list measure:measure",
                 "blocks": "vars:list entry:str blocks:list"},
        "cond": {"test": "expr:expr", "and": "l:cond r:cond", "or": "l:cond r:cond",
                 "not": "c:cond", "always": ""},
        "measure": {"fuel": "", "legacy": "", "node": "expr:expr"},
        "opt": {"none": "", "some": "value:expr"},
        "arm": {"arm": "cond:cond body:expr"},
        "bind": {"bind": "name:str value:expr"},
        "block": {"block": "label:str assigns:list end:end"},
        "end": {"jump": "target:str", "cjump": "cond:cond then:str else:str",
                "halt": "value:expr"},
        "edge": {"edge": "sort:str enter:str"},
        "atom": {"atom": "name:str digest:str"},
    }
    objects = [ObjectSpec(name, "given") for name in ("int", "str", "bool")]
    objects.append(ObjectSpec("list", "compose", tags={"items": {"items": "any"}}))
    objects.append(code_world.code_object())
    objects.extend(code_world.signature_objects())
    objects.extend(ObjectSpec(sort, "compose", tags={tag: _fields(*(
        tuple(part.split(":")) for part in fields.split())) for tag, fields in variants.items()})
                   for sort, variants in shapes.items())
    specs = (
        ("add", "combine", "int int", "int", "Integer addition", ""),
        ("sub", "combine", "int int", "int", "Integer subtraction", ""),
        ("mul", "combine", "int int", "int", "Integer multiplication", ""),
        ("div", "combine", "int int", "int", "Floor division", "div_zero"),
        ("is_zero", "decide", "int", "bool", "Test zero", ""),
        ("eq", "decide", "any any", "bool", "Canonical equality", ""),
        ("lt", "decide", "int int", "bool", "Integer less than", ""),
        ("tag_of", "transform", "any", "str", "Read card tag", "invalid"),
        ("field", "transform", "any int", "any", "Read card field", "invalid"),
        ("with_field", "transform", "any int any", "any", "Replace card field", "invalid"),
        ("mk", "combine", "str str list", "any", "Construct canonical card", "invalid"),
        ("list_len", "transform", "list", "int", "List length", "invalid"),
        ("list_get", "transform", "list int", "any", "List item", "invalid"),
        ("list_append", "combine", "list any", "list", "Append list item", "invalid"),
        ("list_cons", "combine", "any list", "list", "Prepend list item", "invalid"),
        ("str_eq", "decide", "str str", "bool", "Text equality", ""),
        ("size", "transform", "any", "int", "Card tree node count", ""),
    )
    operations = [OperationSpec(name, role, tuple(Edge(sort) for sort in inputs.split()), Edge(output),
                                rule, tuple(errors.split()), host_rule(getattr(hosts, name)), 1)
                  for name, role, inputs, output, rule, errors in specs]
    operations.extend(code_world.operations({"code_hash": hosts.code_hash}))
    return WorldDecl("code", 1, "atoms-v2", {}, {}, tuple(objects), tuple(operations),
                     {"nodes": ["Var", "Lit", "Call", "Let", "Case", "Rec"], "recursion": "measure"},
                     {"truth": None, "show": "values", "judge_view": "full_state"}, {}, {"tags": TAGS},
                     ("object", "operation", "combinator", "observation", "law", "bridge"))


def load_world():
    return declaration()


def library():
    return code_world.MeteredLibrary(load_world(), hosts.atoms())
