"""Compare workshop fuel accounting with the layer-0 kernel."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from opulse.atoms import nodes as n
from opulse.atoms.kernel import Atom, Defn, DictScope, Limits, call
from opulse.atoms.values import Ok


ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")


def workshop(source, cases, library=(), extras=()):
    script = """
globalThis.window = globalThis;
const base = process.argv[1];
for (const name of ['kit', 'lab-preview-world', 'boundary', 'define']) require(base + '/' + name + '.js');
const input = JSON.parse(process.argv[2]);
const parsed = A2.define.parse(input.source, 'operation');
const library = input.library.map(source => {
  const entry = A2.define.parse(source, 'operation');
  return {world: 'integer', name: entry.name, kind: 'operation', origin: 'invented',
    layer: 1, spec: {params: entry.params}, body: entry.body};
}).concat(input.extras);
console.log(JSON.stringify(input.cases.map(([args, fuel]) => {
  const run = A2.define.evaluate(parsed, 'operation', 'integer', args, library, {fuel});
  return {outcome: run.outcome, steps: run.steps};
})));
"""
    result = subprocess.run(
        [NODE, "-e", script, str(ROOT / "docs/assets/js/atoms2"),
         json.dumps({"source": source, "cases": cases, "library": library, "extras": extras})],
        check=True, capture_output=True, text=True,
    )
    return json.loads(result.stdout)


def assert_matches_kernel(source, cases, body, atoms=(), definitions=(), library=(), extras=()):
    name = source.split("(", 1)[0].split()[-1]
    scope = DictScope(atoms=atoms, defns=(*definitions, Defn(name, ("a",), body)))
    for browser, (args, fuel) in zip(workshop(source, cases, library, extras), cases):
        core = call(name, args, scope, Limits(fuel=fuel))
        expected = ({"ok": {"t": "int", "v": core.outcome.value}} if isinstance(core.outcome, Ok)
                    else {"unknown": core.outcome.resource})
        assert browser == {"outcome": expected, "steps": core.steps}, (source, args, fuel)


@pytest.mark.skipif(not NODE, reason="Node.js required")
def test_identity_and_130_let_chain_charge_no_syntax_steps():
    cases = [([7], fuel) for fuel in (0, 1, 250)]
    assert_matches_kernel("op identity(a) = a L1", cases, n.Var("a"))
    body = " ".join(f"let v{index} = {'a' if index == 0 else f'v{index - 1}'} in" for index in range(130)) + " v129"
    core_body = n.Var("v129")
    for index in reversed(range(130)):
        core_body = n.Let(f"v{index}", n.Var("a" if index == 0 else f"v{index - 1}"), core_body)
    assert_matches_kernel(f"op chain(a) = {body} L1", cases, core_body)
    script = """
globalThis.window = globalThis;
const base = process.argv[1];
for (const name of ['kit', 'lab-preview-world', 'boundary', 'define']) require(base + '/' + name + '.js');
const preview = A2.define.pipeline(process.argv[2], 'operation', 'integer');
console.log(JSON.stringify({error: preview.error, steps: preview.sample && preview.sample.steps}));
"""
    result = subprocess.run(
        [NODE, "-e", script, str(ROOT / "docs/assets/js/atoms2"), f"op chain(a) = {body} L1"],
        check=True, capture_output=True, text=True,
    )
    assert json.loads(result.stdout) == {"error": None, "steps": 0}


@pytest.mark.skipif(not NODE, reason="Node.js required")
def test_nested_definitions_charge_only_given_calls():
    helper = "op helper(a) = succ(a) L1"
    body = n.Let("b", n.Call("helper", (n.Var("a"),)), n.Call("add", (n.Var("b"), n.Var("a"))))
    cases = [([9], fuel) for fuel in (0, 1, 2, 3)]
    assert_matches_kernel("op combined(a) = let b = helper(a) in add(b, a) L2", cases, body,
                          atoms=[Atom("succ", 1, lambda value: value + 1),
                                 Atom("add", 2, lambda left, right: left + right)],
                          definitions=[Defn("helper", ("a",), n.Call("succ", (n.Var("a"),)))],
                          library=[helper])


@pytest.mark.skipif(not NODE, reason="Node.js required")
def test_declared_given_cost_is_charged_before_call():
    given = {"world": "integer", "kind": "operation", "name": "succ", "origin": "given",
             "cost": 3, "spec": {"inputs": [{"sort": "int"}], "output": {"sort": "int"}}}
    cases = [([11], fuel) for fuel in (0, 1, 2, 3, 4)]
    assert_matches_kernel("op weighted(a) = succ(a) L1", cases, n.Call("succ", (n.Var("a"),)),
                          atoms=[Atom("succ", 1, lambda value: value + 1, cost=3)], extras=[given])


@pytest.mark.skipif(not NODE, reason="Node.js required")
def test_recursion_charges_only_evaluated_given_calls():
    body = n.Case(((n.Test(n.Call("is_zero", (n.Var("a"),))), n.Var("a")),),
                  n.Call("countdown", (n.Call("dec", (n.Var("a"),)),)))
    cases = [([value], fuel) for value, fuel in ((0, 0), (0, 1), (7, 0), (7, 1), (7, 14), (7, 15), (7, 16))]
    assert_matches_kernel("op countdown(a) = if is_zero(a) then a else countdown(dec(a)) L1",
                          cases, body, atoms=[Atom("is_zero", 1, lambda value: value == 0),
                                              Atom("dec", 1, lambda value: value - 1)])


@pytest.mark.skipif(not NODE, reason="Node.js required")
def test_zero_cost_recursion_hits_depth_limit_not_fuel():
    actual = workshop("op loop(a) = loop(a) L1", [([7], 0)])[0]
    assert actual == {"outcome": {"unknown": "depth"}, "steps": 0}
