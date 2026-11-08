"""Rebuild the kernel-backed Learn/Checks pipeline fixture."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from opulse.atoms import bridges, kernel, laws
from opulse.atoms import nodes as n
from opulse.atoms.library import (
    Library,
    PipelineError,
    VerifyRequest,
    checked_scope,
    sampled,
)
from opulse.atoms.notation import print_definition, print_value
from opulse.atoms.spec import (
    BridgeSpec,
    CombinatorSpec,
    Contract,
    Definition,
    Edge,
    LawSpec,
    ObjectSpec,
    ObservationSpec,
    OperationSpec,
)
from opulse.atoms.values import Bottom, Card, Ok, Unknown
from opulse.atoms.world import WorldDecl
from tools.export_digest import inputs_sha256

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs/assets/data/atoms2/walk.json"


def build_library() -> Library:
    def advance(value):
        if not isinstance(value, Card) or value.sort != "Even" or value.tag != "val":
            return Bottom("wrong_tag")
        return Card("Even", "val", (value.fields[0] + 2,))

    operations = (
        OperationSpec("add", "combine", (Edge("int"), Edge("int")), Edge("int"), "integer addition"),
        OperationSpec("is_even", "decide", (Edge("int"),), Edge("bool"), "even parity"),
        OperationSpec("advance", "transform", (Edge("Even"),), Edge("Even"), "add two to an even value"),
        OperationSpec("read_number", "decide", (Edge("Even"),), Edge("int"), "granted even-card probe"),
    )
    world = WorldDecl("walk-integers", 1, "atoms-v2", {}, {}, (ObjectSpec("int", "given"), ObjectSpec("Record", "given")),
                      operations, {"nodes": list(n.NODE_NAMES), "recursion": "fuel"},
                      {"truth": "Even", "probes": [{"name": "read_number"}],
                       "capabilities": {"learner": {"probes": "all"}}}, {})
    return Library(world, (kernel.Atom("add", 2, lambda left, right: left + right),
                           kernel.Atom("is_even", 1, lambda value: value % 2 == 0),
                           kernel.Atom("advance", 1, advance),
                           kernel.Atom("read_number", 1, lambda state: state.fields[0], kind="observation")))


def definitions() -> tuple[Definition, ...]:
    value = n.Var("x")
    valid = n.Call("is_even", (value,))
    even = ObjectSpec("Even", "refine", base="Record", valid=valid,
                      extra={"notation_fields": (("value", "int"),)})
    obj = Definition("Even", "object", "invented", 1, ("is_even",), even, valid)
    twice_more = n.Call("advance", (n.Var("arg0"),))
    bump_spec = OperationSpec("bump_even", "transform", (Edge("Even", name="arg0"),),
                              Edge("Even"), "ASCII definition")
    bump = Definition("bump_even", "operation", "invented", 1, ("advance",), bump_spec, twice_more)
    body = n.Call("f", (n.Call("f", (n.Var("x"),)),))
    comb_spec = CombinatorSpec("twice", ("f", "x"), ("f",), body)
    comb = Definition("twice", "combinator", "invented", 1, (), comb_spec, body)
    obs_body = n.Var("read_number")
    obs_spec = ObservationSpec("number", ("read_number",), obs_body)
    obs = Definition("number", "observation", "invented", 1, (), obs_spec, obs_body)
    return obj, bump, comb, obs


def outcome_text(outcome) -> str:
    if isinstance(outcome, Ok):
        return "Ok(" + print_value(outcome.value) + ")"
    if isinstance(outcome, Bottom):
        return "Bottom(" + outcome.reason + ")"
    if isinstance(outcome, Unknown):
        return "Unknown(" + outcome.resource + ")"
    raise TypeError("unexpected kernel outcome")


def trace_nodes(node) -> list[dict]:
    if node is None:
        return []
    record = {"call": node.name or "root", "layer": node.layer, "steps": node.steps,
              "leaf": not node.children,
              "outcome": outcome_text(node.outcome)}
    return [record, *(child for item in node.children for child in trace_nodes(item))]


def requests(kind: str) -> VerifyRequest:
    values = tuple(range(0, 25, 2))
    cards = tuple(Card("Even", "val", (value,)) for value in values)
    if kind == "object":
        return VerifyRequest("exhaustive", tuple((value,) for value in range(25)),
                             {"domain": "integers 0..24 (finite test domain)", "size": 25})
    if kind == "operation":
        return VerifyRequest("exhaustive", tuple((value,) for value in cards),
                             {"domain": "even integers 0..24", "size": len(values)},
                             reference=lambda value: Card("Even", "val", (value.fields[0] + 2,)))
    if kind == "combinator":
        return VerifyRequest("bounded", tuple((value,) for value in cards),
                             {"domain": "even integers 0..24, bound 24; operation family bump_even",
                              "size": len(values), "op_family": ["bump_even"]},
                             reference=lambda assignment, inputs: Card("Even", "val", (inputs[0].fields[0] + 4,)),
                             extra={"op_family": ["bump_even"]})
    states = cards
    return VerifyRequest("exhaustive", tuple((value,) for value in states),
                         {"domain": "even-card truth states 0..24", "size": len(states)},
                         reference=lambda state: state.fields[0], extra={"states": states})


def station(lib: Library, definition: Definition, stage: str) -> dict:
    current = lib.get(definition.name)
    evidence = current.evidence.to_dict() if current.evidence else None
    return {"station": stage, "status": current.status, "content_hash": lib.content_hash(definition.name),
            "evidence": evidence, "contract": current.contract.to_dict() if current.contract else None,
            "cost": current.cost.to_dict() if stage in ("verified", "promoted") else None}


def failures(lib: Library) -> dict:
    bad_valid = n.Call("is_even", (n.Var("x"),))
    broken = ObjectSpec("Broken", "refine", base="int", valid=bad_valid,
                        canon=n.Call("add", (n.Var("x"), n.Lit(2))))
    lib.write(Definition("Broken", "object", "invented", 1, ("add", "is_even"), broken, None))
    lib.check("Broken")
    lib.make_callable("Broken", [(0,)])
    try:
        lib.verify("Broken", VerifyRequest("bounded", [(0,), (2,)],
                   {"domain": "even integers 0..2, bound 2", "size": 2}))
    except PipelineError as error:
        object_failure = str(error)
    else:
        raise AssertionError("bad canon unexpectedly verified")

    sample_library = build_library()
    operation = definitions()[1]
    for item in definitions()[:2]:
        sample_library.write(item)
        sample_library.check(item.name)
        sample_library.make_callable(item.name, [(0,) if item.kind == "object" else
                                                (Card("Even", "val", (0,)),)])
    sample_request = sampled(lambda randomizer: (Card("Even", "val", (randomizer.choice((0, 2)),)),),
                             2, 17, "seeded even integers 0..2")
    sample_request = replace(sample_request, reference=lambda value: Card("Even", "val", (value.fields[0] + 2,)))
    sample_evidence = sample_library.verify(operation.name, sample_request).evidence.to_dict()
    try:
        sample_library.promote(operation.name, Contract("add two to even integers"))
    except PipelineError as error:
        operation_failure = str(error)
    else:
        raise AssertionError("sampled evidence unexpectedly promoted")

    unknown = lib.run("twice", (kernel.FnRef("bump_even"), Card("Even", "val", (18,))), fuel=1)
    observation_body = n.Var("secret")
    bad_obs = Definition("secret_number", "observation", "invented", 1, (),
                         ObservationSpec("secret_number", ("secret",), observation_body), observation_body)
    lib.write(bad_obs)
    try:
        lib.check(bad_obs.name)
    except PipelineError as error:
        observation_failure = str(error)
    else:
        raise AssertionError("ungranted probe unexpectedly accepted")
    return {"object": {"attempt": "Broken canon add(x, 2)", "error": object_failure},
            "operation": {"attempt": "Promote seeded sample (seed 17)", "error": operation_failure,
                          "evidence": sample_evidence},
            "combinator": {"attempt": "@twice[bump_even](Even.val<18>) with fuel 1",
                           "error": outcome_text(unknown.outcome), "steps": unknown.steps},
            "observation": {"attempt": "Read secret without a grant", "error": observation_failure}}


def law_and_bridge() -> dict:
    arithmetic = (
        ("add", 2, "int", lambda left, right: left + right),
        ("mul", 2, "int", lambda left, right: left * right),
        ("eq", 2, "bool", lambda left, right: left == right),
    )
    specs = tuple(OperationSpec(name, "decide" if name == "eq" else "combine",
                                (Edge("int"),) * arity, Edge(result), name)
                  for name, arity, result, _ in arithmetic)
    law_world = WorldDecl("walk-law", 1, "atoms-v2", {}, {}, (ObjectSpec("int", "given"),),
                          specs, {"nodes": list(n.NODE_NAMES), "recursion": "fuel"}, {}, {}, open_kinds=("law",))
    law_lib = Library(law_world, tuple(kernel.Atom(name, arity, fn)
                                       for name, arity, _, fn in arithmetic))
    left = n.Call("mul", (n.Var("a"), n.Var("b")))
    right = n.Call("mul", (n.Var("b"), n.Var("a")))
    statement = n.Call("eq", (left, right))
    law = Definition("mul_comm", "law", "invented", 1, ("eq", "mul"),
                     LawSpec("mul_comm", (("a", "int"), ("b", "int")), statement), statement)
    law_declaration = print_definition(law)
    law_lib.write(law)
    law_lib.check(law.name)
    law_lib.make_callable(law.name, ((5, 7),))
    domain = tuple((first, second) for first in range(8) for second in range(8))
    law_request = VerifyRequest("bounded", domain, {"domain": "both integer operands 0..7",
                                                   "size": len(domain)})
    law_lib.verify(law.name, law_request)
    law_lib.promote(law.name, Contract("Only operands 0..7; replay within checked tuples"))
    before = n.Call("add", (n.Call("mul", (n.Lit(5), n.Lit(7))),
                            n.Call("mul", (n.Lit(7), n.Lit(5)))))
    after = n.Call("add", (n.Call("mul", (n.Lit(7), n.Lit(5))),
                           n.Call("mul", (n.Lit(7), n.Lit(5)))))
    replay = laws.replay_rewrite(before, after, law_lib.get(law.name), law_lib, {})
    before_run = kernel.evaluate(before, scope=law_lib.scope())
    after_run = kernel.evaluate(after, scope=law_lib.scope())

    pair_specs = (
        OperationSpec("pair_add", "combine", (Edge("Pair"), Edge("Pair")), Edge("Pair"), "pair sum"),
        OperationSpec("difference", "transform", (Edge("Pair"),), Edge("Int"), "pair difference"),
        OperationSpec("add_int", "combine", (Edge("Int"), Edge("Int")), Edge("Int"), "integer sum"),
    )
    bridge_world = WorldDecl("walk-bridge", 1, "atoms-v2", {}, {},
                             (ObjectSpec("Pair", "given"), ObjectSpec("Int", "given")), pair_specs,
                             {"nodes": list(n.NODE_NAMES), "recursion": "fuel"}, {}, {}, open_kinds=("bridge",))
    bridge_lib = Library(bridge_world, (
        kernel.Atom("pair_add", 2, lambda first, second: (first[0] + second[0], first[1] + second[1])),
        kernel.Atom("difference", 1, lambda value: value[0] - value[1]),
        kernel.Atom("add_int", 2, lambda first, second: first + second),
    ))
    bridge_spec = BridgeSpec("to_difference", "Pair", "Int",
                             n.Call("difference", (n.Var("x"),)),
                             interface=(("pair_add", "add_int"),))
    bridge = Definition("to_difference", "bridge", "invented", 1, ("difference",),
                        bridge_spec, bridges.bridge_defn(bridge_spec).body)
    bridge_declaration = print_definition(bridge)
    bridge_lib.write(bridge)
    bridge_lib.check(bridge.name)
    values = tuple((first, second) for first in range(4) for second in range(4))
    bridge_request = VerifyRequest("bounded", tuple((value,) for value in values),
                                   {"domain": "pair components 0..3", "size": len(values)})
    bridge_result = bridges.verify_bridge(bridge_lib.get(bridge.name), bridge_lib, bridge_request)
    if not bridge_result.ok:
        raise AssertionError(bridge_result.problems)
    bridge_evidence = {"method": bridge_request.method,
                       "scope": {"domain": "pair components 0..3", "size": len(values),
                                 "checked": {**checked_scope(bridge_request.domain), "by": "bridge verifier"},
                                 "domain_size": bridge_request.scope["domain_size"],
                                 "pairs_checked": bridge_request.scope["pairs_checked"]},
                       "checks": list(bridge_result.checks), "content_hash": bridge_lib.content_hash(bridge.name),
                       "checker": "opulse.atoms.bridges.verify_bridge"}
    translated = kernel.call(bridge.name, ((3, 1),),
                             bridge_lib.scope().extend((bridges.bridge_defn(bridge_spec),)))
    return {
        "law": {"declaration": law_declaration,
                "method": law_lib.get(law.name).evidence.method,
                "scope": "all 64 ordered pairs with each operand 0..7",
                "content_hash": law_lib.content_hash(law.name),
                "evidence": {**law_lib.get(law.name).evidence.to_dict(),
                             "checker": "opulse.atoms.library.Library.verify"},
                "before": "add(mul(5, 7), mul(7, 5))",
                "after": "add(mul(7, 5), mul(7, 5))",
                "before_outcome": outcome_text(before_run.outcome),
                "after_outcome": outcome_text(after_run.outcome),
                "rewrite_steps": laws.derivation_length(replay), "charged_steps": replay.charged_steps},
        "bridge": {"declaration": bridge_declaration,
                   "method": bridge_request.method, "scope": "all 16 pairs with components 0..3",
                   "evidence": bridge_evidence,
                   "domain_size": bridge_request.scope["domain_size"],
                   "pairs_checked": bridge_request.scope["pairs_checked"],
                   "checks": list(bridge_result.checks), "input": "~to_difference(Pair<3, 1>)",
                   "outcome": outcome_text(translated.outcome), "layer0_steps": translated.steps,
                   "diagram": "~to_difference(pair_add(Pair<2, 3>, Pair<3, 1>)) = add_int(~to_difference(Pair<2, 3>), ~to_difference(Pair<3, 1>)) = 1"}
    }


def export() -> dict:
    lib = build_library()
    rows = []
    prior_result = None
    for definition in definitions():
        name = definition.name
        declaration = print_definition(definition, lib)
        lib.write(definition)
        stages = [station(lib, definition, "written")]
        lib.check(name)
        stages.append(station(lib, definition, "checked"))
        sample = ((kernel.FnRef("bump_even"), Card("Even", "val", (18,))) if definition.kind == "combinator"
                  else (Card("Even", "val", (18,)),) if definition.kind in ("operation", "observation") else (0,))
        lib.make_callable(name, [sample])
        stages.append(station(lib, definition, "callable"))
        request = requests(definition.kind)
        lib.verify(name, request)
        lib.account(name)
        stages.append(station(lib, definition, "verified"))
        lib.promote(name, Contract("Only within " + request.scope["domain"]))
        stages.append(station(lib, definition, "promoted"))
        if definition.kind == "object":
            run = lib.run("Even.make", (18,), trace=True)
            expression = "Even.make(18)"
        elif definition.kind == "combinator":
            run = lib.run(name, (kernel.FnRef("bump_even"), Card("Even", "val", (20,))), trace=True)
            expression = "@twice[bump_even](Even.val<20>)"
            prior_result = run.outcome.value if isinstance(run.outcome, Ok) else None
        elif definition.kind == "observation":
            from opulse.atoms.observations import observe
            if prior_result is None:
                raise AssertionError("the combinator produced no state for the observation")
            expression = "?number{" + print_value(prior_result) + "}"
            run = lib.run("read_number", (prior_result,), trace=True)
            observed = observe(lib.get(name), lib, [prior_result])[0]
            if observed != run.outcome:
                raise AssertionError("observation and traced kernel call diverge")
            if run.steps != lib.get(name).cost.steps["min"]:
                raise AssertionError("observation probe and kernel accounting diverge")
        else:
            run = lib.run(name, (Card("Even", "val", (18,)),), trace=True)
            expression = "bump_even(Even.val<18>)"
        rows.append({"kind": definition.kind, "name": name, "declaration": declaration,
                     "depends_on": list(definition.depends_on), "stages": stages,
                     "example": {"input": expression, "outcome": outcome_text(run.outcome),
                                 "layer0_steps": run.steps, "trace": trace_nodes(run.trace)},
                     "demonstrates": {"object": "An even-only refinement rejects odd inputs.",
                                      "operation": "Construction and unboxing preserve the refined type.",
                                      "combinator": "Two uses of the invented operation unfold to the same given calls.",
                                      "observation": "The prior combinator's result becomes a truth state; only the granted probe exposes its value."}[definition.kind]})
    rejected_link = n.Call("twice", (n.Lit(kernel.FnRef("bump_even")), n.Var("read_number")))
    attempted = Definition("number_twice", "observation", "invented", 2, ("twice",),
                           ObservationSpec("number_twice", ("read_number",), rejected_link), rejected_link)
    lib.write(attempted)
    try:
        lib.check(attempted.name)
    except PipelineError as error:
        link_error = str(error)
    else:
        raise AssertionError("unexpectedly accepted truth-sort input to bump_even/advance")
    errors = failures(lib)
    for row in rows:
        row["failure"] = errors[row["kind"]]
    core_digest = inputs_sha256(ROOT, (ROOT / "src/opulse/atoms").glob("*.py"))
    return {"schema": "opulse.walk/1", "core_digest": core_digest, "world_hash": lib.world.world_hash(),
            "layer0": {"objects": [{"name": obj.name} for obj in lib.world.objects] +
                       [{"name": "Pair"}, {"name": "Int"}],
                       "operations": [{"name": op.name} for op in lib.world.operations
                                      if op.name != "read_number"] +
                       [{"name": name} for name in ("mul", "eq", "pair_add", "difference", "add_int")],
                       "observations": [{"name": "read_number"}]},
            "artifact": "docs/assets/data/atoms2/walk.json", "definitions": rows,
            "law_and_bridge": law_and_bridge(),
            "link_limit": {"attempt": "?number_twice{s} through @twice[bump_even]", "error": link_error,
                           "meaning": "Spec 0.5 rejects ?number_twice: bump_even and advance take the truth sort Even. Pure definitions may act on already observed or explicitly public values, not on the truth sort."}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail when the committed export is stale")
    args = parser.parse_args()
    from opulse.notation3.export import add_notation3

    serialized = json.dumps(add_notation3(export(), 'atoms2', source='atoms2/walk.json'),
                            indent=2, ensure_ascii=True) + "\n"
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != serialized:
            parser.error(f"stale generated data: {OUTPUT}")
    else:
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(serialized, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    from tools import atoms2_walk_export

    raise SystemExit(atoms2_walk_export.main())
