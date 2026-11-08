"""Regression checks for canonical origins and source-backed ASCII (meta 2.2, 8)."""

from dataclasses import replace

import pytest

from opulse.atoms import kernel, nodes
from opulse.atoms.spec import Definition, Edge, OperationSpec, TemplateSpec
from opulse.atoms.values import Bottom, Card, encode
from opulse.meta import code, engine
from opulse.meta.check import export_problems
from opulse.meta.export_util import ascii_definition, parse_meta_definition
from opulse.meta.identity import Ledger


def test_definition_origin_commits_to_resolved_kind_name_and_hash():
    operation = Definition("increment", "operation", "invented", 1, (),
                           OperationSpec("increment", "transform", (Edge("int"),), Edge("int"), "add"),
                           nodes.Call("add", (nodes.Var("arg0"), nodes.Lit(1))))
    dependency = code.quote(operation, lambda _: None, {"add": "digest-add"})
    pattern = {"name": "made", "role": "transform", "rule": "f", "inputs": [{"sort": "int"}],
               "output": {"sort": "int"}, "definition_body": nodes.Call("$f", (nodes.Var("arg0"),)),
               "input_names": ["arg0"]}
    template = code.quote(Definition("Apply", "template", "invented", 1, (),
                                     TemplateSpec("Apply", (("f", "operation"),), "operation", pattern), None),
                          lambda _: None, {})
    resolver = lambda name: (code.Resolved(code=dependency) if name == "increment" else
                             code.Resolved(digest="digest-add") if name == "add" else None)
    original = code.instantiate_code(template, (operation,), resolver)
    assert code.is_canonical(original)
    origin = code.items(original.fields[4])[-1]
    for name, kind, digest in (("increment", "operation", "0" * 64),
                               ("other", "operation", operation.content_hash()),
                               ("increment", "object", operation.content_hash())):
        forged = replace(origin, fields=(template, code.lst((Card("pattern", "definition", (name, kind, digest)),))))
        changed = replace(original, fields=(*original.fields[:4], code.lst((*code.items(original.fields[4])[:-1], forged))))
        assert not code.is_canonical(changed)
        with pytest.raises(ValueError):
            Ledger().add(changed, "world")
        record = Ledger()
        record.add(original, "world")
        imported = record.to_dict()
        imported["records"][0]["code"] = encode(changed)
        with pytest.raises(ValueError):
            Ledger.from_dict(imported)
        atom = kernel.Atom("add", 2, lambda left, right: left + right)
        scope = kernel.DictScope((atom, engine.eval_atom((atom,), {"add": "digest-add"})))
        assert engine.call("eval", (changed, code.lst((3,))), scope).outcome == Bottom("ill_formed")
    assert code.code_hash(original) == Ledger().add(original, "world")


def test_strict_export_rejects_fabricated_result_and_changed_declaration():
    definition = parse_meta_definition("op increment(x: int) -> int = add(x, 1) L1")
    entry = {"name": "increment", "kind": "operation", "symbol": "increment",
             "definition": "Add one to the input.", "status": "callable",
             "body": nodes.to_json(definition.body), "ascii": "op increment(x: int) -> int = x L1",
             "examples": [{"ascii": "increment(2) = 100", "inputs": [encode(2)],
                           "outcome": {"kind": "Ok", "value": encode(3)}}]}
    assert any("declaration" in problem for problem in export_problems({"story": [entry]}, "probe", strict=True))
    entry["ascii"] = "op increment(x: int) -> int = add(x, 1) L1"
    assert any("outcome" in problem for problem in export_problems({"story": [entry]}, "probe", strict=True))
    entry.update(ascii="op increment(x: int) -> int = x L1", body=nodes.to_json(nodes.Var("x")))
    entry["examples"] = [{"ascii": "increment(2) = 100"}]
    assert any("declaration evaluation" in problem for problem in export_problems(
        {"story": [entry]}, "probe", strict=True))
    entry["spec"] = definition.spec.to_dict()
    entry["ascii"] = "op increment(x: str) -> int = x L1"
    assert any("signature" in problem for problem in export_problems({"story": [entry]}, "probe", strict=True))
    entry["ascii"] = "op increment(x: int) -> int = x L1"
    entry["examples"] = [{"ascii": "increment(4) = 4", "inputs": [encode(2)],
                          "outcome": {"kind": "Ok", "value": encode(4)}}]
    assert any("call inputs" in problem for problem in export_problems({"story": [entry]}, "probe", strict=True))


def test_meta_literal_printer_preserves_unrelated_string():
    source = parse_meta_definition("op evaluate(x: int) -> int = x L1")
    program = code.make_code("operation", code.sig_op([], ("int", "bottom")), (), nodes.Lit(2), lambda _: None)
    for literal in ("normal", "__meta_body_0__"):
        body = nodes.Let("unused", nodes.Lit(literal), nodes.Lit(program))
        printed, reason = ascii_definition(replace(source, body=body), None)
        assert reason is None
        assert parse_meta_definition(printed).body == body
