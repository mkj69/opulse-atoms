"""Reproducible depth-design dice export, evaluated by the core kernel."""

import json
from dataclasses import replace
from fractions import Fraction
from pathlib import Path

from opulse.atoms import kernel, nodes, notation
from opulse.atoms.spec import Cost
from opulse.atoms.values import Card, Ok, encode, encode_outcome
from opulse.worlds_v2.export_util import (
    body_sha256,
    finalize_export,
    source_matches,
    trace_json,
)

from . import hosts
from .story import build_library, call, example_args, lit

ROOT = Path(__file__).resolve().parents[4]
EXPORT_PATH = ROOT / "docs/assets/data/worlds_v2/dice.json"
DESIGN_PATH = ROOT / "worlds/catalogue/depth/dice.json"
TOWER_NAMES = ("independent", "total", "Event", "conditional", "score", "mean", "Belief", "update", "Walk", "advance", "hit_prob", "hitting")
TITLES = {
    "independent": ("Independent rolls", "Compose two die-to-distribution operations without sharing a roll."),
    "total": ("Pair total", "Add the two integer coordinates of a die pair."),
    "Event": ("Score interval", "Refine an inclusive score interval over the validated integer range."),
    "conditional": ("Conditional chance", "Divide the mass of an intersection by the evidence mass."),
    "score": ("Score distribution", "Push a distribution through a scoring operation and combine equal outcomes."),
    "mean": ("Exact expectation", "Sum value times rational probability across the finite distribution."),
    "Belief": ("Hidden-die prior", "Refine nonnegative rational weights that sum to one."),
    "update": ("Bayesian update", "Normalize the two hidden-die likelihoods against an observed event."),
    "Walk": ("Absorbing walk", "Refine a belief and a goal into a persistent hidden-die walk."),
    "step": ("Persistent-die transition", "Advance one state while preserving its hidden die index."),
    "advance": ("Repeated transition", "Expand the exact state distribution for the requested turn count."),
    "hit_prob": ("Finite-horizon hit chance", "Measure both absorbing goal states after a finite number of turns."),
    "hitting": ("Expected hitting time", "Solve the transient absorbing-chain equations with exact rational elimination."),
}

def _source_decl(definition):
    written = replace(definition, status="written", evidence=None, contract=None, id=None, cost=Cost())
    try:
        source = notation.print_definition(written)
    except (TypeError, ValueError):
        return None
    return source if source_matches(source, body_sha256(definition.body)) else None


def _english(name, fallback):
    return TITLES.get(name, (name.replace("_", " ").capitalize(), fallback.rstrip(".") + "."))


def _body_json(body):
    return nodes.to_json(body) if body is not None else None


def _example_expr(name, args):
    if name == "Event":
        invocation = call("Event.make", call("event", lit(args[0].fields[0]), lit(args[0].fields[1])))
    elif name == "Belief":
        invocation = call("Belief.make", call("belief", *(lit(part) for part in args[0].fields)))
    elif name == "Walk":
        prior = hosts.Card("Belief", "val", (hosts.belief(hosts.to_card(Fraction(1, 2)), hosts.to_card(Fraction(1, 2))),))
        high = hosts.Card("Event", "val", (hosts.event(10, 12),))
        invocation = call("Walk.make", call("walk", call("Belief.base", call("update", lit(prior), lit(high))),
                                            lit(args[0].fields[1])))
    else:
        invocation = call(name, *(lit(arg) for arg in args))
    if name == "independent":
        return call("mass", invocation, lit((hosts.pair(6, 6),)))
    if name == "score":
        return call("mass", invocation, lit((12,)))
    if name == "advance":
        return call("mass", invocation, lit((hosts.state(6, 0), hosts.state(6, 1))))
    return invocation


def _literal_text(value):
    if isinstance(value, kernel.FnRef):
        return value.name
    if isinstance(value, Card):
        if value.sort in ("Event", "Belief", "Walk") and value.tag == "val":
            return _card_text(value)
        if value.sort == "fraction":
            return _card_text(value)
        if value.sort == "die":
            return "Fair<>" if value == hosts.FAIR else "Tilt<>" if value == hosts.TILT else f"Die<{','.join(map(str, value.fields))}>"
        if value.sort == "dist":
            return "Dist<" + ",".join(f"{_literal_text(entry.fields[0])}:{entry.fields[1]}/{entry.fields[2]}" for entry in value.fields) + ">"
        return f"{value.sort.capitalize()}<{','.join(_literal_text(part) for part in value.fields)}>"
    if isinstance(value, tuple):
        return "Set<" + ",".join(_literal_text(part) for part in value) + ">"
    return str(value)


def _example_text(name, args):
    if name in ("total", "update", "hit_prob", "hitting"):
        expression = _example_expr(name, args)
        context = {"kinds": {"hit_prob": "observation", "hitting": "observation"},
                   "observation_arity": {"hit_prob": 2, "hitting": 1}}
        source = notation.print_expr(expression, context)
        if name in ("hit_prob", "hitting"):
            source = source.replace(f"?{name}{{", f"{name}(", 1)[:-1] + ")"
        assert notation.parse_expr(source) == expression
        return source
    if name == "Event":
        return f"Event.make(event({args[0].fields[0]},{args[0].fields[1]}))"
    if name == "Belief":
        return "Belief.make(belief(" + ",".join(_literal_text(part) for part in args[0].fields) + "))"
    if name == "Walk":
        return f"Walk.make(walk(Belief.base(update(Belief<1/2,1/2>,Event<10,12>)),{args[0].fields[1]}))"
    arguments = ",".join(_literal_text(part) for part in args)
    if name in ("independent", "score"):
        slots = ",".join(_literal_text(part) for part in args[:2 if name == "independent" else 1])
        values = ",".join(_literal_text(part) for part in args[2 if name == "independent" else 1:])
        expression = f"@{name}[{slots}]({values})"
    elif name == "advance":
        expression = f"@advance[{','.join(_literal_text(part) for part in args[:3])}]({','.join(_literal_text(part) for part in args[3:])})"
    elif name in ("mean", "hit_prob", "hitting"):
        expression = f"?{name}{{{arguments}}}"
    else:
        expression = f"{name}({arguments})"
    if name == "independent":
        return f"?mass{{{expression},Set<Pair<6,6>>}}"
    if name == "score":
        return f"?mass{{{expression},Set<12>}}"
    if name == "advance":
        return f"?mass{{{expression},Set<State<6,0>,State<6,1>>}}"
    return expression


def _run_expr(library, expr):
    return library.run_example(expr)


def _card_text(value):
    if isinstance(value, Card) and value.tag == "val" and value.sort in ("Event", "Belief", "Walk"):
        return _card_text(value.fields[0])
    if isinstance(value, Card) and value.sort == "fraction":
        return str(hosts.from_card(value))
    if isinstance(value, Card) and value.sort == "event":
        return f"Event<{value.fields[0]},{value.fields[1]}>"
    if isinstance(value, Card) and value.sort == "belief":
        return f"Belief<{_card_text(value.fields[0])},{_card_text(value.fields[1])}>"
    if isinstance(value, Card) and value.sort == "walk":
        return f"Walk<{_card_text(value.fields[0])},{value.fields[1]}>"
    return "true" if value is True else "false" if value is False else str(value)


def _given_text(text):
    return text.split(" — ", 1)


def build_export():
    library = build_library()
    design = json.loads(DESIGN_PATH.read_text(encoding="utf-8"))
    world = library.world.to_dict()
    examples = example_args()
    tower = []
    for name, design_card in zip(TOWER_NAMES, design["tower"]):
        definition = library.get(name)
        args = examples[name]
        run = _run_expr(library, _example_expr(name, args))
        assert isinstance(run.outcome, Ok) and _card_text(run.outcome.value) == design_card["value"], name
        encoded_args = [({"t": "fn", "v": item.name} if isinstance(item, kernel.FnRef) else encode(item)) for item in args]
        example = {"text": _example_text(name, args), "inputs": encoded_args,
                   "outcome": encode_outcome(run.outcome), "steps": run.steps, "trace": trace_json(run.trace, max_nodes=32),
                   "learner_view": {"result": encode_outcome(run.outcome)}}
        if name == "conditional":
            failure_args = (hosts.pure(hosts.pair(6, 6)), hosts.Card("Event", "val", (hosts.event(10, 12),)), hosts.Card("Event", "val", (hosts.event(2, 2),)))
            failure = library.run(name, failure_args, trace=True)
            assert encode_outcome(failure.outcome) == {"bottom": "domain"}
            example_failure = {"text": _example_text(name, failure_args),
                               "inputs": [encode(item) for item in failure_args], "outcome": encode_outcome(failure.outcome),
                               "steps": failure.steps, "trace": trace_json(failure.trace, max_nodes=32),
                               "learner_view": {"result": encode_outcome(failure.outcome)}}
            instances = [example, example_failure]
        else:
            instances = [example]
        tower.append({"layer": design_card["layer"], "def_layer": definition.layer, "kind": definition.kind,
                      "name": name, "title": TITLES[name][0], "definition": TITLES[name][1],
                      "body_sha256": body_sha256(definition.body), "design_decl": design_card["decl"],
                      **({"decl": source} if (source := _source_decl(definition)) else {}),
                      "plain_zh": design_card["plain"],
                      "symbol": (name + "<...>" if definition.kind == "object" else
                                 "@" + name + "[f,g](a,b)" if name == "independent" else
                                 "@" + name + "[f](dist)" if name == "score" else
                                 "@advance[roll,total,jump](walk,turns)" if name == "advance" else
                                 "?" + name + "{dist}" if name == "mean" else
                                 "?" + name + "{walk,turns}" if name == "hit_prob" else
                                 "?" + name + "{walk}" if name == "hitting" else
                                 name + "(...)"),
                      "title_zh": design_card["plain"].split("，")[0], "definition_zh": design_card["plain"],
                      "depends_on": list(definition.depends_on), "body": _body_json(definition.body),
                      "status": definition.status, "evidence": definition.evidence.to_dict(),
                      "contract": definition.contract.to_dict(), "cost": definition.cost.to_dict(), "examples": instances})

    posterior_walk = examples["hitting"][0]
    answer = library.run("hitting", (posterior_walk,)).outcome
    assert isinstance(answer, Ok) and _card_text(answer.value) == design["showcase"][0]["answer"]
    before = library.run("hit_prob", (posterior_walk, 6)).outcome
    after = library.run("hit_prob", (posterior_walk, 7)).outcome
    assert isinstance(before, Ok) and isinstance(after, Ok)
    assert hosts.from_card(before.value) <= Fraction(3, 4) < hosts.from_card(after.value)
    low = hosts.Card("Event", "val", (hosts.event(2, 4),))
    updated_twice = library.run("update", (examples["update"][0], hosts.Card("Event", "val", (hosts.event(10, 12),)))).outcome
    assert isinstance(updated_twice, Ok)
    second = library.run("update", (updated_twice.value, low)).outcome
    assert isinstance(second, Ok)
    decision = library.run("hitting", (hosts.Card("Walk", "val", (hosts.walk(second.value.fields[0], 6),)),)).outcome
    assert isinstance(decision, Ok)
    assert (_card_text(decision.value), hosts.from_card(decision.value) < 10) == ("697388245129321047792/69631886654752860061", False)
    showcase = [{**{key + "_zh" if key in ("check", "why_hard") else key: value for key, value in task.items()},
                 "answer_checked": True, "answer_check_method": method} for task, method in zip(design["showcase"],
                ("kernel hitting exact fraction", "kernel hit_prob at 6 and 7, absorbing monotonicity", "kernel sequential update and hitting exact comparison"))]
    given_objects = {_given_text(item)[0].split()[1].split("<", 1)[0]: _given_text(item) for item in design["layer0"]["objects"]}
    given_operations = {_given_text(item)[0].split()[1].split("(", 1)[0]: _given_text(item) for item in design["layer0"]["operations"]}
    object_names = {"die": "Die", "dist": "Dist", "state": "State"}
    bind_decl, bind_doc = _given_text(design["layer0"]["combinators"][0])
    mass_decl, mass_doc = _given_text(design["layer0"]["observations"][0])
    return {"schema": "opulse.world_v2_export/1", "world": "dice", "version": 1, "wave": 1,
            "title": "Hidden Dice and Absorbing Walk", "title_zh": design["name"], "pitch_zh": design["pitch"],
            "modality_zh": "概率／文本／图像", "modalities_zh": design["modalities"], "toy_risk_zh": design["toy_risk"],
            "tags": {"domain": "probability", "modalities": ["text", "image"], "open_kinds": ["object", "operation", "combinator", "observation"],
                     "star_kind": "observation", "reasoning": ["compute", "probability", "inference"], "state": "stateful",
                     "outcomes": "probabilistic", "visibility": "partial", "agents": 1, "scale": "up to 64 transient states; 12 tower cards",
                     "difficulty": "single exact die to rational absorbing-chain elimination", "uses": ["rl-training", "evaluation", "teaching"]},
            "open_kinds": ["object", "operation", "combinator", "observation"], "tower_source": "depth",
            "decl": world, "layer0": {"objects": [{"name": item["name"], "form": item["form"], "symbol": object_names.get(item["name"], item["name"]).capitalize() + "<...>",
                                                 "title": _english(item["name"], item.get("doc", "Declared object."))[0],
                                                 "definition": _english(item["name"], item.get("doc", "Declared object."))[1],
                                                 "decl": given_objects.get(object_names.get(item["name"], item["name"]),
                                                                           ("obj " + item["name"] + " given", None))[0],
                                                 "doc": item.get("doc"), "doc_zh": given_objects.get(object_names.get(item["name"], item["name"]),
                                                                                                      (None, item.get("doc")))[1]}
                                                for item in world["objects"]],
                                "operations": [{"name": item["name"], "symbol": item["symbol"],
                                                "title": _english(item["name"], item["rule"])[0],
                                                "definition": _english(item["name"], item["rule"])[1],
                                                "decl": given_operations.get(item["name"], ("op " + item["symbol"] + " given", None))[0],
                                                "rule": item["rule"], "rule_zh": given_operations.get(item["name"], (None, item["rule"]))[1],
                                                "errors": item["errors"], "cost": item["cost"],
                                                "inputs": [{"name": edge["name"], "sort": edge["sort"]} for edge in item["inputs"]],
                                                "output": item["output"]["sort"]} for item in world["operations"]],
                                "combinators": {**world["combinators"], "symbol": "@bind[k](dist,context)", "title": "Distribution bind",
                                                "definition": "Multiply branch masses and merge equal results from a continuation.",
                                                "decl": bind_decl, "doc_zh": bind_doc},
                                "observation": {key: world["observation"][key] for key in ("truth", "show", "judge_view")} |
                                {"symbol": "?mass{dist,event}", "title": "Exact probability probe", "definition": "Reveal rational mass for a selected event without changing the distribution.",
                                 "probes": [{"name": item["name"], "sort": item["sort"], "reveals": item["reveals"],
                                             "symbol": "?mass{dist,event}",
                                             "title": "Exact mass", "definition": "Read the probability of a finite event.",
                                             "decl": mass_decl, "doc_zh": mass_doc}
                                            for item in world["observation"]["probes"]]}},
            "story": tower, "ladder": [{"level": level["level"], "knobs": level["knobs"], "what_changes_zh": level["what_changes"]}
                                        for level in design["ladder"]], "showcase": showcase,
            "emerges_zh": design["pitch"], "checking_zh": "通过内核核对每层精确值、层零步数以及有理线性方程。"}



_build_export_raw = build_export


def build_export(*args, **kwargs):
    """The export after the shared last step (export_util.finalize_export)."""
    return finalize_export(_build_export_raw(*args, **kwargs))


if __name__ == "__main__":
    EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    EXPORT_PATH.write_text(json.dumps(build_export(), sort_keys=True, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
