"""Ten public constructions: exact Bayes updating and budgeted policy synthesis."""

from fractions import Fraction
from itertools import product

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.library import VerifyRequest
from opulse.atoms.spec import (
    CombinatorSpec,
    Contract,
    Definition,
    Edge,
    ObjectSpec,
    ObservationSpec,
    OperationSpec,
)
from opulse.atoms.values import Bottom, Card

from . import hosts
from .world import new_library


def call(name, *args):
    return n.Call(name, args)


def var(name):
    return n.Var(name)


def lit(value):
    return n.Lit(value)


def choose(condition, yes, no):
    return n.Case(((n.Test(condition), yes),), no)


def let(name, expression, body):
    return n.Let(name, expression, body)


def belief(red, blue):
    return Card("Belief", "val", (Card("BeliefPair", "pair", (hosts.rational(red), hosts.rational(blue))),))


def leaf(choice):
    return Card("Policy", "val", (hosts.node_leaf(choice),))


def ask(mode, red, blue):
    return Card("Policy", "val", (hosts.node_ask(mode, red.fields[0], blue.fields[0]),))


def modes(*items):
    return Card("Modes", "list", items)


def lamps(*items):
    return Card("Lamps", "list", items)


def operation(name, params, sorts, output, body, role="transform"):
    spec = OperationSpec(name, role, tuple(Edge(sort, name=param) for param, sort in zip(params, sorts)),
                         Edge(output), f"Exact public {name} construction.", extra={"input_names": list(params)})
    return Definition(name, "operation", "invented", 1, (), spec, body)


def reference(definition, layers):
    dependencies = tuple(sorted(n.references(definition.body) -
                                (set(definition.spec.op_params) if definition.kind == "combinator" else set())))
    layer = 1 + max((layers.get(name.split(".")[0], 0) for name in dependencies), default=0)
    return Definition(definition.name, definition.kind, definition.origin, layer, dependencies,
                      definition.spec, definition.body)


def likelihood(b, mode, lamp):
    return call("add", call("mul", call("Belief.r", b), call("weight", call("channel", mode, lit("R")), lamp)),
                call("mul", call("Belief.b", b), call("weight", call("channel", mode, lit("B")), lamp)))


def observed(b, mode, lamp):
    mass = likelihood(b, mode, lamp)
    return choose(call("eq", mass, lit(hosts.rational(0))), b, call("update", b, mode, lamp))


def policy_value_body():
    node = var("node")
    belief_value = var("belief")
    mode = call("node_mode", node)
    remaining = call("decrease", var("budget"), call("mode_cost", mode))
    def branch(lamp, accessor):
        return call("mul", likelihood(belief_value, mode, lit(lamp)),
                    call("walk", call("Policy.make", call(accessor, node)),
                         observed(belief_value, mode, lit(lamp)), remaining))
    body = let("node", call("Policy.base", var("policy")),
               choose(call("node_is_ask", node),
                      call("add", branch("red", "node_red"), branch("blue", "node_blue")),
                      choose(call("eq", call("node_choice", node), lit("R")),
                             call("Belief.r", belief_value), call("Belief.b", belief_value))))
    traversal = n.Rec("walk", ("policy", "belief", "budget"), body,
                      (var("policy"), var("belief"), var("budget")), var("budget"))
    return choose(call("less_int", var("budget"), lit(0)), call("fail", lit("budget")),
                  choose(call("less_int", lit(12), var("budget")), call("fail", lit("budget")),
                         traversal))


def optimize_body():
    current = var("belief")
    budget = var("budget")
    stop = call("Policy.make", call("node_leaf", choose(
        call("lt", call("Belief.r", current), call("Belief.b", current)), lit("B"), lit("R"))))

    def candidate(mode):
        remaining = call("decrease", budget, lit(hosts.mode_cost(mode)))
        red = call("plan", observed(current, lit(mode), lit("red")), remaining)
        blue = call("plan", observed(current, lit(mode), lit("blue")), remaining)
        return call("Policy.make", call("node_ask", lit(mode), call("Policy.base", red),
                                        call("Policy.base", blue)))

    def compare(mode, previous):
        return choose(call("less_int", budget, lit(hosts.mode_cost(mode))), previous,
                      let("candidate", candidate(mode),
                          choose(call("lt", call("score", previous, current, budget),
                                      call("score", var("candidate"), current, budget)),
                                 var("candidate"), previous)))

    body = let("stop", stop, let("best_b", compare("B", var("stop")),
                                   compare("A", var("best_b"))))
    planner = n.Rec("plan", ("belief", "budget"), body, (var("belief"), var("budget")),
                    budget, memo=True)
    return choose(call("less_int", budget, lit(0)), call("fail", lit("budget")),
                  choose(call("less_int", lit(12), budget), call("fail", lit("budget")), planner))


def definitions():
    result = []
    layers = {}

    def add(definition):
        definition = reference(definition, layers) if definition.kind != "object" else definition
        result.append(definition)
        layers[definition.name] = definition.layer

    walk = choose(call("empty", var("remaining")), call("reverse", var("output")),
                  call("collect", call("tail", var("remaining")),
                       call("prepend", call("step_lamp", call("head", var("remaining"))), var("output"))))
    body = n.Rec("collect", ("remaining", "output"), walk,
                 (call("history", var("view")), lit(lamps())), call("size", var("remaining")))
    add(Definition("lamps", "observation", "invented", 1, (),
                   ObservationSpec("lamps", ("view",), body), body))

    red_part = call("BeliefPair.r", var("x"))
    blue_part = call("BeliefPair.b", var("x"))
    valid = n.Case(((n.And(n.Test(call("le", lit(hosts.rational(0)), red_part)),
                           n.And(n.Test(call("le", lit(hosts.rational(0)), blue_part)),
                                 n.Test(call("eq", call("add", red_part, blue_part),
                                             lit(hosts.rational(1)))))),
                      lit(True)),), lit(False))
    canon = call("BeliefPair.pair", call("div", red_part, lit(hosts.rational(1))),
                 call("div", blue_part, lit(hosts.rational(1))))
    spec = ObjectSpec("Belief", "refine", base="BeliefPair",
                      valid=valid, canon=canon,
                      sealed=True, interface=("Belief.make", "Belief.r", "Belief.b"),
                      extra={"fields": ("r", "b")})
    add(Definition("Belief", "object", "invented", 1,
                   tuple(sorted(n.references(valid) | n.references(canon))), spec, None))

    red = call("mul", call("Belief.r", var("belief")),
               call("weight", call("channel", var("mode"), lit("R")), var("lamp")))
    blue = call("mul", call("Belief.b", var("belief")),
                call("weight", call("channel", var("mode"), lit("B")), var("lamp")))
    body = let("red", red, let("blue", blue, let("total", call("add", var("red"), var("blue")),
               call("Belief.make", call("BeliefPair.pair", call("div", var("red"), var("total")),
                                                         call("div", var("blue"), var("total")))))))
    add(operation("update", ("belief", "mode", "lamp"), ("Belief", "Mode", "Lamp"), "Belief", body))
    add(operation("update_copy", ("belief", "mode", "lamp"), ("Belief", "Mode", "Lamp"),
                  "Belief", call("update", var("belief"), var("mode"), var("lamp"))))

    body = choose(call("empty", var("remaining_modes")),
                  choose(call("empty", var("remaining_lamps")), var("state"), call("fail", lit("unpaired"))),
                  choose(call("empty", var("remaining_lamps")), call("fail", lit("unpaired")),
                         call("scan_loop", call("step", var("state"), call("head", var("remaining_modes")),
                                                call("head", var("remaining_lamps"))),
                              call("tail", var("remaining_modes")), call("tail", var("remaining_lamps")))))
    body = n.Rec("scan_loop", ("state", "remaining_modes", "remaining_lamps"), body,
                 (var("belief"), var("modes"), var("lamps")), call("size", var("remaining_modes")))
    add(Definition("scan", "combinator", "invented", 1, (),
                   CombinatorSpec("scan", ("step", "belief", "modes", "lamps"), ("step",), body), body))

    body = choose(call("lt", call("Belief.r", var("belief")), call("Belief.b", var("belief"))),
                  call("Belief.b", var("belief")), call("Belief.r", var("belief")))
    add(Definition("confidence", "observation", "invented", 1, (),
                   ObservationSpec("confidence", ("belief",), body), body))

    spec = ObjectSpec("Policy", "refine", base="PolicyNode",
                      valid=call("node_valid", var("x")), sealed=True,
                      interface=("Policy.make", "Policy.base"))
    add(Definition("Policy", "object", "invented", 1, ("node_valid",), spec, None))

    add(operation("value", ("policy", "belief", "budget"),
                  ("Policy", "Belief", "int"), "Rational", policy_value_body()))
    add(operation("value_copy", ("policy", "belief", "budget"), ("Policy", "Belief", "int"),
                  "Rational", call("value", var("policy"), var("belief"), var("budget"))))

    body = optimize_body()
    add(Definition("optimize", "combinator", "invented", 1, (),
                   CombinatorSpec("optimize", ("score", "belief", "budget"), ("score",), body), body))

    body = let("node", call("Policy.base", var("policy")),
               choose(call("node_is_ask", var("node")), call("node_mode", var("node")),
                      choose(call("eq", call("node_choice", var("node")), lit("R")),
                             lit("guess_R"), lit("guess_B"))))
    add(Definition("first", "observation", "invented", 1, (),
                   ObservationSpec("first", ("policy",), body), body))

    body = call("sub", call("value", call("optimize", lit(kernel.FnRef("value")),
                                               var("belief"), var("budget")),
                                     var("belief"), var("budget")),
                call("value", var("policy"), var("belief"), var("budget")))
    add(operation("regret", ("policy", "belief", "budget"),
                  ("Policy", "Belief", "int"), "Rational", body))
    return tuple(result)


def build_library(*, limit=None):
    library = new_library()
    for definition in definitions()[:limit]:
        library.write(definition)
        library.check(definition.name)
        sample = samples(definition.name)[:1]
        if definition.kind == "combinator":
            sample = [(kernel.FnRef("update" if definition.name == "scan" else "value"), *sample[0])]
        library.make_callable(definition.name, sample)
        request = evidence_request(definition.name)
        library.verify(definition.name, request)
        library.account(definition.name)
        library.promote(definition.name, Contract(f"Exact public {definition.name} on the recorded finite family."))
    return library


def samples(name):
    pairs = ("A", "B")
    policy_family = [hosts.node_ask(mode, hosts.node_ask("B", hosts.node_leaf(red),
                                                         hosts.node_leaf(blue)), hosts.node_leaf(guess))
                     for mode, red, blue, guess in product(pairs, hosts.CARDS, hosts.CARDS, hosts.CARDS)]
    policies = [hosts.node_ask(mode, left, right)
                for mode in pairs for left, right in product(policy_family[:8], repeat=2)]
    policies = policies[:32] + policies[64:96]
    domain = {
        "lamps": [(hosts.receiver(hosts.state("R", tuple(zip(
            ("A", "B", "A", "B", "A", "B"), lamps_values)))),)
                  for lamps_values in product(hosts.LAMPS, repeat=6)],
        "Belief": [(Card("BeliefPair", "pair", (hosts.rational(Fraction(red, 64)), hosts.rational(Fraction(64 - red, 64)))),)
                   for red in range(65)],
        "update": [(belief(Fraction(red, 16), Fraction(16 - red, 16)), mode, lamp)
                   for red, mode, lamp in product(range(17), hosts.MODES, hosts.LAMPS)],
        "scan": [(belief(Fraction(red, 8), Fraction(8 - red, 8)), modes(*mode_values), lamps(*lamp_values))
                 for red in range(1, 8) for mode_values in product(pairs, repeat=2)
                 for lamp_values in product(hosts.LAMPS, repeat=2)],
        "confidence": [(belief(Fraction(red, 64), Fraction(64 - red, 64)),) for red in range(65)],
        "Policy": [(policy,) for policy in policies[:64]],
        "value": [(ask("B", leaf(red), leaf(blue)), belief(Fraction(index, 16), Fraction(16 - index, 16)), budget)
                  for index in range(17) for red, blue in (("R", "B"), ("B", "R"))
                  for budget in (1, 2)],
        "optimize": [(belief(Fraction(index, 32), Fraction(32 - index, 32)), budget)
                     for index in range(17) for budget in (0, 1, 2)],
        "first": [(Card("Policy", "val", (policy,)),) for policy in policies[:62]]
                 + [(leaf("R"),), (leaf("B"),)],
        "regret": [(ask("B", leaf(red), leaf(blue)), belief(Fraction(index, 16), Fraction(16 - index, 16)), budget)
                   for index in range(17) for red, blue in (("R", "B"), ("B", "R"))
                   for budget in (1, 2)],
    }
    domain["update_copy"] = domain["update"]
    domain["value_copy"] = domain["value"]
    return domain[name]


def evidence_request(name):
    from importlib.util import module_from_spec, spec_from_file_location
    from pathlib import Path

    path = Path(__file__).resolve().parents[4] / "worlds/catalogue/depth/hidden.py"
    spec = spec_from_file_location("hidden_depth_oracle", path)
    oracle = module_from_spec(spec)
    import sys
    sys.modules[spec.name] = oracle
    spec.loader.exec_module(oracle)

    domain = samples(name)
    families = {
        "lamps": "all 64 red/blue words of length 6 with fixed A,B,A,B,A,B modes",
        "Belief": "65 distinct rational pairs with r=k/64 for k=0..64",
        "update": "17 priors r=k/16 for k=0..16, both modes and both lamps (68 tuples)",
        "update_copy": "17 priors r=k/16 for k=0..16, both modes and both lamps (68 tuples)",
        "scan": "7 priors r=k/8 for k=1..7, all 4 two-mode and 4 two-lamp words (112 tuples)",
        "confidence": "65 priors r=k/64 for k=0..64",
        "Policy": "64 distinct finite trees, 32 rooted at A and 32 rooted at B",
        "value": "17 priors r=k/16, two one-ask policies, budgets 1 and 2 (68 tuples)",
        "value_copy": "17 priors r=k/16, two one-ask policies, budgets 1 and 2 (68 tuples)",
        "optimize": "17 priors r=k/32 for k=0..16, budgets 0,1,2 (51 tuples)",
        "first": "62 distinct two-mode-root trees and two guess leaves",
        "regret": "17 priors r=k/16, two one-ask policies, budgets 1 and 2 (68 tuples)",
    }
    description = f"bounded: {families[name]}"
    if name in ("lamps", "confidence", "first"):
        description += "; paired R/B sealed truths per input with equal public views"
    if name == "Belief":
        return VerifyRequest("bounded", domain, {"domain": description, "size": len(domain)},
                             extra={"interface_ops": {"Belief.r": [0], "Belief.b": [0]}})
    if name == "Policy":
        return VerifyRequest("bounded", domain, {"domain": description, "size": len(domain)},
                             extra={"interface_ops": {"Policy.base": [0]}})
    if name in ("scan", "optimize"):
        family = ("update", "update_copy") if name == "scan" else ("value", "value_copy")

        def comb_reference(assignment, args):
            if name == "scan":
                known, mode_list, lamp_list = args
                answer = oracle.scan(oracle.Belief(*(hosts.fraction(item) for item in known.fields[0].fields)),
                                     mode_list.fields, lamp_list.fields)
                return belief(answer.r, answer.b)
            known, budget = args
            policy = oracle.optimize(oracle.Belief(*(hosts.fraction(item) for item in known.fields[0].fields)), budget)

            def convert(node):
                if isinstance(node, oracle.Leaf):
                    return hosts.node_leaf(node.choice)
                return hosts.node_ask(node.mode, convert(node.red), convert(node.blue))

            return Card("Policy", "val", (convert(policy),))

        return VerifyRequest("bounded", domain, {"domain": description, "size": len(domain),
                                                  "op_family": list(family)},
                             reference=comb_reference, extra={"op_family": list(family)})

    def expected(*args):
        if name == "lamps":
            return lamps(*oracle.lamps(oracle.ReceiverView(tuple(step.fields for step in args[0].fields[0].fields))))
        if name == "confidence":
            return hosts.rational(max(hosts.fraction(args[0].fields[0].fields[0]),
                                      hosts.fraction(args[0].fields[0].fields[1])))
        if name == "first":
            node = args[0].fields[0]
            return node.fields[0] if node.tag == "Ask" else "guess_" + node.fields[0]
        if name in ("update", "update_copy"):
            current, mode, lamp = args
            try:
                answer = oracle.update(oracle.Belief(*(hosts.fraction(v) for v in current.fields[0].fields)), mode, lamp)
                return belief(answer.r, answer.b)
            except ValueError:
                return Bottom("impossible")
        if name in ("value", "value_copy", "regret"):
            policy, current, budget = args
            def convert(node):
                return (oracle.Leaf(node.fields[0]) if node.tag == "Leaf" else
                        oracle.Ask(node.fields[0], convert(node.fields[1]), convert(node.fields[2])))
            known = oracle.Belief(*(hosts.fraction(v) for v in current.fields[0].fields))
            result = oracle.value(convert(policy.fields[0]), known, budget) if name != "regret" else oracle.regret(
                convert(policy.fields[0]), known, budget)
            return hosts.rational(result)
        raise ValueError(name)

    return VerifyRequest("bounded", domain, {"domain": description, "size": len(domain)}, reference=expected)
