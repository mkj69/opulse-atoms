"""Offline scripts exercise operation-only, object, and combinator invention."""

from opulse.atoms import nodes as n
from opulse.atoms.kernel import FnRef
from opulse.atoms.spec import (
    CombinatorSpec,
    Definition,
    Edge,
    LawSpec,
    ObjectSpec,
    OperationSpec,
)
from opulse.atoms.values import FALSE, Card

from .ascii import display, rename, render


def call(name, *args):
    return n.Call(name, args)


def var(index):
    return n.Var(f"arg{index}")


def normalize(numerator, denominator):
    signed = n.Case(((n.Test(call("lt", denominator, n.Lit(0))),
                      call("sub", n.Lit(0), numerator)),), numerator)
    positive_denominator = n.Case(((n.Test(call("lt", denominator, n.Lit(0))),
                                    call("sub", n.Lit(0), denominator)),), denominator)
    return (n.Let("signed_num", signed, n.Let("positive_den", positive_denominator,
            call("div", n.Var("signed_num"), call("gcd", n.Var("signed_num"), n.Var("positive_den"))))),
            n.Let("signed_num", signed, n.Let("positive_den", positive_denominator,
            call("div", n.Var("positive_den"), call("gcd", n.Var("signed_num"), n.Var("positive_den"))))))


def operation_definitions():
    expressions = normalize(n.Var("arg0"), n.Var("arg1"))
    return tuple(Definition(name, "operation", "invented", 1, tuple(sorted(n.references(body))),
                            OperationSpec(name, "transform", (Edge("int"), Edge("int")), Edge("int"),
                                          "canonical numerator" if index == 0 else "canonical denominator",
                                          extra={"input_names": ["arg0", "arg1"]}), body)
                 for index, (name, body) in enumerate(zip(("norm_num", "norm_den"), expressions)))


def frac_definition():
    numerator = call("Pair.num", n.Var("x"))
    denominator = call("Pair.den", n.Var("x"))
    valid = n.Case(((n.Test(call("eq", denominator, n.Lit(0))), n.Lit(FALSE)),),
                   n.Lit(Card("bool", "true")))
    normalized = normalize(numerator, denominator)
    canon = call("Pair.pair", *normalized)
    spec = ObjectSpec("Frac", "refine", base="Pair", valid=valid, canon=canon,
                      sealed=True, interface=("Frac.make", "Frac.num", "Frac.den"))
    return Definition("Frac", "object", "invented", 1,
                      tuple(sorted(n.references(valid) | n.references(canon))), spec, None)


def fraction_helpers():
    made = call("Frac.make", call("Pair.pair", n.Var("arg0"), n.Var("arg1")))
    return tuple(Definition(name, "operation", "invented", 2,
                            tuple(sorted(n.references(body))),
                            OperationSpec(name, "transform", (Edge("int"), Edge("int")), Edge("int"),
                                          "canonical fraction field", extra={"input_names": ["arg0", "arg1"]}), body)
                 for name, body in (("fraction_num", call("Frac.num", made)),
                                    ("fraction_den", call("Frac.den", made))))


def law_definition():
    statement = call("eq", call("add", n.Var("a"), n.Var("b")),
                     call("add", n.Var("b"), n.Var("a")))
    spec: LawSpec = LawSpec("#add_comm", (("a", "int"), ("b", "int")), statement)
    return Definition("#add_comm", "law", "invented", 1,
                      tuple(sorted(n.references(statement))), spec, statement)


def combinator_definition():
    body = call("f", n.Var("left"), n.Var("right"))
    return Definition("@combine", "combinator", "invented", 1, (),
                      CombinatorSpec("@combine", ("f", "left", "right"), ("f",), body), body)


def observation_definition():
    from .ascii import parse

    return parse("obs ?numerator{p} = add(Pair.num(p), 0)\n"
                 "save ?numerator\nop solve(a: Int) -> Int = a")[0][0]


def bridge_definition():
    from .ascii import parse

    return parse("bridge ~to_frac: Pair -> Frac = Frac.make(x) "
                 "commutes (Pair.num -> Frac.num, Pair.den -> Frac.den)\n"
                 "save ~to_frac\nop solve(a: Int) -> Int = a")[0][0]


def expressions(family, *, use_object=False, use_combinator=False, use_helper=False,
                use_observation=False, use_bridge=False):
    def plus(left, right):
        return (call("@combine", n.Lit(FnRef("add")), left, right)
                if use_combinator else call("add", left, right))

    def fraction(index):
        return var(index), var(index + 1)

    if family == "mixed":
        raw = (plus(call("mul", var(0), var(2)), var(1)), var(2))
    elif family == "compare":
        if use_helper:
            left_num, left_den = call("fraction_num", *fraction(0)), call("fraction_den", *fraction(0))
            right_num, right_den = call("fraction_num", *fraction(2)), call("fraction_den", *fraction(2))
        elif use_object:
            maker = "~to_frac" if use_bridge else "Frac.make"
            left = call(maker, call("Pair.pair", *fraction(0)))
            right = call(maker, call("Pair.pair", *fraction(2)))
            left_num, left_den = call("Frac.num", left), call("Frac.den", left)
            right_num, right_den = call("Frac.num", right), call("Frac.den", right)
        else:
            left_num, left_den = call("norm_num", *fraction(0)), call("norm_den", *fraction(0))
            right_num, right_den = call("norm_num", *fraction(2)), call("norm_den", *fraction(2))
        condition = call("lt", call("mul", left_num, right_den), call("mul", right_num, left_den))
        return (n.Case(((n.Test(condition), n.Lit(1)),), n.Lit(0)),)
    elif family == "sum":
        raw = (plus(call("mul", var(0), var(3)), call("mul", var(2), var(1))),
               call("mul", var(1), var(3)))
    else:
        terms = [fraction(index) for index in (0, 2, 4, 6)]
        if family == "dot":
            first = (call("mul", terms[0][0], terms[1][0]), call("mul", terms[0][1], terms[1][1]))
            second = (call("mul", terms[2][0], terms[3][0]), call("mul", terms[2][1], terms[3][1]))
            raw = (plus(call("mul", first[0], second[1]), call("mul", second[0], first[1])),
                   call("mul", first[1], second[1]))
        elif family == "average":
            acc = terms[0]
            for item in terms[1:]:
                acc = (plus(call("mul", acc[0], item[1]), call("mul", item[0], acc[1])),
                       call("mul", acc[1], item[1]))
            raw = acc[0], call("mul", acc[1], n.Lit(4))
        else:
            raise ValueError(family)
    if use_helper:
        numerator, denominator = call("fraction_num", *raw), call("fraction_den", *raw)
        return (call("?numerator", call("Pair.pair", numerator, denominator))
                if use_observation else numerator), denominator
    if use_object:
        result = call("~to_frac" if use_bridge else "Frac.make", call("Pair.pair", *raw))
        numerator, denominator = call("Frac.num", result), call("Frac.den", result)
        return (call("?numerator", call("Pair.pair", numerator, denominator))
                if use_observation else numerator), denominator
    return call("norm_num", *raw), call("norm_den", *raw)


class ScriptedPolicy:
    def __init__(self, name):
        self.name = name

    def reset(self, *, group, episode, seed):
        self.group = group
        self.first = True

    def act(self, observation):
        invents_object = self.name in ("object", "observation", "bridge")
        if invents_object and self.group != "K1" or self.name == "refused":
            definitions = (frac_definition(),)
            use_object = True
        else:
            definitions = operation_definitions()
            use_object = False
        if self.group in ("K3", "K4", "K5", "K6") and invents_object:
            definitions += (combinator_definition(),)
        if use_object and invents_object:
            definitions += fraction_helpers()
        if self.name == "refused_observation":
            definitions += (observation_definition(),)
        if self.name == "refused_bridge":
            definitions += (bridge_definition(),)
        if self.group in ("K4", "K5", "K6") and invents_object:
            definitions += (law_definition(),)
        use_observation = self.group in ("K5", "K6") and self.name in ("observation", "bridge")
        use_bridge = self.group == "K6" and self.name == "bridge"
        if use_observation:
            definitions += (observation_definition(),)
        if use_bridge:
            definitions += (bridge_definition(),)
        answer = expressions(observation["task"]["family"], use_object=use_object,
                             use_combinator=self.group in ("K3", "K4", "K5", "K6") and invents_object,
                             use_helper=use_object and invents_object and not use_bridge,
                             use_observation=use_observation, use_bridge=use_bridge)
        names = "abcdefgh"[:observation["task"]["arity"]]
        params = ", ".join(f"{name}: Int" for name in names)
        result = answer[0] if len(answer) == 1 else call("Pair.pair", *answer)
        result = rename(result, {f"arg{index}": name for index, name in enumerate(names)})
        output = "Int" if len(answer) == 1 else "Pair"
        declarations = [render(item).rsplit(" L", 1)[0] for item in definitions] if self.first else []
        saves = [f"save {item.name}" for item in definitions] if self.first else []
        self.first = False
        return "\n".join([*declarations, *saves,
                          f"op solve({params}) -> {output} = {display(result)}"])
