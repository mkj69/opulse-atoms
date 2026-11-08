"""Twelve kernel-defined arithmetic inventions with finite verification scopes."""

from copy import deepcopy
from itertools import product
from math import gcd

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.library import VerifyRequest, VerifyResult
from opulse.atoms.spec import (
    CombinatorSpec,
    Contract,
    Definition,
    Edge,
    ObjectSpec,
    ObservationSpec,
    OperationSpec,
    compute_layer,
)
from opulse.atoms.values import Bottom, Card, Ok, outcome_equal
from opulse.worlds_v2.integer.adapter import check_local
from opulse.worlds_v2.integer.world import new_library


def v(name):
    return n.Var(name)


def lit(value):
    return n.Lit(value)


def c(name, *args):
    return n.Call(name, args)


def when(test, yes, no):
    return n.Case(((n.Test(test), yes),), no)


def bind(name, expression, body):
    return n.Let(name, expression, body)


def numerator(expression):
    return c("numerator", expression)


def denominator(expression):
    return c("denominator", expression)


def frac(numerator, denominator):
    return Card("frac", "val", (pair(numerator, denominator),))


def natural(number):
    return Card("nat", "val", (number,))


def items(*members):
    return Card("list", "items", members)


def pair(left, right):
    return Card("pair", "items", (left, right))


def canonical_reference(numerator, denominator):
    if denominator == 0:
        return Bottom("invalid")
    factor = gcd(numerator, denominator)
    return frac(numerator // factor * (1 if denominator > 0 else -1),
                abs(denominator) // factor)


def abs_node(expression):
    return when(c("lt", expression, lit(0)), c("neg", expression), expression)


def operation(name, params, body, sorts=None, output="int"):
    spec = OperationSpec(name, "combine", tuple(Edge(sort, name=param) for param, sort in
                zip(params, sorts or ("int",) * len(params))), Edge(output),
                         "Unfold arithmetic through lower-layer definitions.",
                         extra={"input_names": list(params)})
    return (name, "operation", spec, body)


def object_def(name, params, body, valid, *, base="int", sealed=False, interface=()):
    return (name, "object", ObjectSpec(name, "refine", base=base, valid=valid,
            canon=body, sealed=sealed, interface=interface, params=params), None)


def combinator(name, params, ops, body):
    return (name, "combinator", CombinatorSpec(name, params, ops, body), body)


def observation(name, params, body):
    return (name, "observation", ObservationSpec(name, params, body), body)


def cards():
    nat_valid = c("le", lit(0), c("value", v("x")))
    yield object_def("nat", ("x",), None, nat_valid)

    repeat_body = n.Rec("loop", ("remaining", "current"),
        when(c("eq", v("remaining"), lit(0)), v("current"),
             c("loop", c("sub", v("remaining"), lit(1)), c("step", v("current")))),
        (c("nat.base", v("times")), v("seed")), v("remaining"))
    yield combinator("repeat", ("step", "seed", "times"), ("step",), repeat_body)

    mul_body = bind("left_negative", c("lt", c("value", v("left")), lit(0)),
        bind("right_negative", c("lt", c("value", v("right")), lit(0)),
        bind("magnitude_left", abs_node(v("left")),
        bind("magnitude_right", abs_node(v("right")),
        bind("counter", c("repeat", lit(kernel.FnRef("succ")), lit(0), c("nat.make", v("magnitude_right"))),
        bind("product", n.Rec("multiply_loop", ("remaining", "total"),
             when(c("eq", v("remaining"), lit(0)), v("total"),
                  c("multiply_loop", c("sub", v("remaining"), lit(1)),
                    c("add", v("total"), v("magnitude_left")))),
             (v("counter"), lit(0)), v("remaining")),
             when(c("ne", v("left_negative"), v("right_negative")),
                  c("neg", v("product")), v("product"))))))))
    yield operation("mul", ("left", "right"), mul_body)

    canonical = bind("factor", c("gcd", v("numerator"), v("denominator")),
        bind("top", c("quotient", v("numerator"), v("factor")),
        bind("bottom", c("quotient", v("denominator"), v("factor")),
            when(c("lt", v("bottom"), lit(0)),
                c("pair", c("neg", v("top")), c("neg", v("bottom"))),
                c("pair", v("top"), v("bottom"))))))
    frac_body = bind("numerator", c("first", v("x")),
                     bind("denominator", c("second", v("x")), canonical))
    yield object_def("frac", ("x",), frac_body,
                     c("ne", c("second", v("x")), lit(0)), base="pair", sealed=True,
                     interface=("frac.make",))

    yield observation("whole", ("q",), c("eq", c("value", denominator(v("q"))), lit(1)))

    yield operation("qadd", ("left", "right"),
        c("frac.make", c("pair", c("add", c("mul", numerator(v("left")), denominator(v("right"))),
                            c("mul", numerator(v("right")), denominator(v("left")))),
                  c("mul", denominator(v("left")), denominator(v("right"))))), ("frac", "frac"), "frac")
    yield operation("qmul", ("left", "right"),
        c("frac.make", c("pair", c("mul", numerator(v("left")), numerator(v("right"))),
                  c("mul", denominator(v("left")), denominator(v("right"))))), ("frac", "frac"), "frac")

    fold_body = n.Rec("fold_loop", ("rest", "total"),
        when(c("is_empty", v("rest")), v("total"),
             c("fold_loop", c("tail", v("rest")), c("step", v("total"), c("head", v("rest"))))),
        (v("xs"), v("seed")), c("length", v("rest")))
    yield combinator("fold_frac", ("step", "xs", "seed"), ("step",), fold_body)

    negative_loop = n.Rec("negative_loop", ("quotient", "remainder"),
        when(c("lt", v("remainder"), lit(0)),
             bind("raised", c("add", v("remainder"), v("divisor")),
                  when(c("lt", v("raised"), lit(0)),
                       c("negative_loop", c("add", v("quotient"), lit(-1)), v("raised")),
                       c("pair", c("add", v("quotient"), lit(-1)), v("raised")))),
             c("pair", v("quotient"), v("remainder"))),
        (lit(0), v("number")), abs_node(v("remainder")))
    positive_loop = n.Rec("positive_loop", ("quotient", "remainder"),
        when(c("lt", v("remainder"), v("divisor")), c("pair", v("quotient"), v("remainder")),
             c("positive_loop", c("succ", v("quotient")),
                  c("add", v("remainder"), c("neg", v("divisor"))))),
        (c("first", v("initial")), c("second", v("initial"))), v("remainder"))
    div_body = when(c("le", c("value", v("divisor")), lit(0)), c("failure", lit("divisor")),
                    bind("initial", negative_loop, positive_loop))
    yield operation("cf_divmod", ("number", "divisor"), div_body, output="pair")

    cf_tail_valid = n.Rec("canonical_tail", ("rest",),
        when(c("is_empty", v("rest")), lit(True),
             when(c("is_empty", c("tail", v("rest"))),
                  c("le", lit(2), c("head", v("rest"))),
                  when(c("le", lit(1), c("head", v("rest"))),
                       c("canonical_tail", c("tail", v("rest"))), lit(False)))),
        (c("tail", v("x")),), c("length", v("rest")))
    cf_list_valid = when(c("is_empty", v("x")), lit(False),
        when(c("le", c("head", v("x")), c("head", v("x"))),
             cf_tail_valid, lit(False)))
    cf_body = when(c("is_cf_data", v("x")), v("x"),
        bind("start", numerator(v("x")),
        bind("divisor", denominator(v("x")),
        n.Rec("expand", ("number", "divisor"),
            when(c("eq", v("divisor"), lit(0)), c("list_empty"),
                bind("division", c("cf_divmod", v("number"), v("divisor")),
                     c("cons", c("first", v("division")),
                          c("expand", v("divisor"), c("second", v("division")))))),
            (v("start"), v("divisor")), v("divisor")))))
    yield object_def("cf", ("x",), cf_body,
                     when(c("is_cf_data", v("x")), cf_list_valid,
                          c("ne", denominator(v("x")), lit(0))),
                     base="list", sealed=True, interface=("cf.make", "cf.base"))

    def state_part(state, side, field):
        return c(field, c(side, state))

    state = v("state")
    step_body = c("pair",
        c("pair", c("add", c("mul", v("digit"), state_part(state, "first", "first")),
                              state_part(state, "first", "second")), state_part(state, "first", "first")),
        c("pair", c("add", c("mul", v("digit"), state_part(state, "second", "first")),
                              state_part(state, "second", "second")), state_part(state, "second", "first")))
    yield operation("cf_step", ("state", "digit"), step_body, ("pair", "int"), "pair")

    converge_body = n.Rec("converge_loop", ("rest", "state", "result"),
        when(c("is_empty", v("rest")), v("result"),
            bind("next_state", c("step", v("state"), c("head", v("rest"))),
                 c("converge_loop", c("tail", v("rest")), v("next_state"),
                   c("append", v("result"), c("frac.make", c("pair", state_part(v("next_state"), "first", "first"),
                                                        state_part(v("next_state"), "second", "first"))))))),
        (c("cf.base", v("continued")), c("pair", c("pair", lit(1), lit(0)),
                                            c("pair", lit(0), lit(1))), c("list_empty")), c("length", v("rest")))
    yield combinator("convergents", ("step", "continued"), ("step",), converge_body)

    bounded_body = bind("limit", c("nat.base", c("second", v("p"))),
        bind("series", c("convergents", lit(kernel.FnRef("cf_step")), c("first", v("p"))),
             n.Rec("select", ("rest", "choice"),
                 when(c("is_empty", v("rest")),
                      when(c("eq", v("choice"), lit(0)), c("failure", lit("no_convergent")), v("choice")),
                      bind("candidate", c("head", v("rest")),
                           c("select", c("tail", v("rest")),
                              when(c("le", c("value", denominator(v("candidate"))), v("limit")),
                                   v("candidate"), v("choice"))))),
                 (v("series"), lit(0)), c("length", v("rest")))))
    yield observation("bounded_convergent", ("p",), bounded_body)


def definitions():
    layers = {"sequence": 0}
    given = {"succ", "add", "neg", "gcd", "value", "lt", "le", "eq", "ne", "sub",
             "quotient", "failure", "pair", "first", "second", "list_empty", "cons",
             "append", "is_empty", "head", "tail", "length", "numerator",
             "denominator", "digits", "count", "is_cf_data"}
    from opulse.atoms import nodes
    for name, kind, spec, body in cards():
        references = set(nodes.all_dependencies(body)) if body is not None else (
            set(nodes.all_dependencies(spec.valid)) |
            (set(nodes.all_dependencies(spec.canon)) if spec.canon else set()))
        dependencies = tuple(sorted(references - set(spec.op_params if kind == "combinator" else ())))
        layer = compute_layer(dependencies, lambda dependency: layers.get(dependency.split(".")[0], 0))
        assert {dependency.split(".")[0] for dependency in dependencies} <= given | layers.keys(), name
        layers[name] = layer
        yield Definition(name, kind, "invented", layer, dependencies, spec, body)


def verify_generic(definition, library, request):
    steps = []
    checks = ("reference", "dependency", "facts_unchanged", "non_interference", "unfold_equivalence")
    for arguments in request.domain:
        before = deepcopy(arguments)
        actual = library.run(definition.name, arguments)
        expected = request.reference(*arguments)
        expected = expected if isinstance(expected, Bottom) else Ok(expected)
        if not outcome_equal(actual.outcome, expected):
            return VerifyResult(False, (), [f"reference mismatch for {definition.name} {arguments}: {actual.outcome} != {expected}"], steps)
        unfolded = kernel.evaluate(kernel.inline(n.Call(definition.name, tuple(n.Lit(item) for item in arguments)),
                                   library.scope()), scope=library.scope())
        if not outcome_equal(actual.outcome, unfolded.outcome) or actual.steps != unfolded.steps:
            return VerifyResult(False, (), [f"unfold mismatch for {definition.name} {arguments}"], steps)
        environment = dict(zip(definition.spec.reads, arguments))
        another = kernel.evaluate(definition.body, {**environment, "ungranted": "different"},
                                  scope=library.scope()).outcome
        if another != actual.outcome or arguments != before:
            return VerifyResult(False, (), [f"observation interference for {definition.name} {arguments}"], steps)
        steps.append(actual.steps)
    return VerifyResult(True, checks, [], steps)


def scope_for(name):
    rationals = tuple(canonical_reference(top, bottom) for top, bottom in
                      ((-2, 1), (-1, 1), (-1, 2), (-1, 3), (0, 1),
                       (1, 4), (1, 3), (1, 2), (2, 3), (1, 1)))
    canonical = tuple(sorted({canonical_reference(top, bottom)
                              for top in range(-6, 7) for bottom in range(1, 9)},
                             key=lambda value: value.fields[0].fields))
    continued = tuple(Card("cf", "val", (items(*_cf_digits(value)),)) for value in canonical)
    cf_samples = tuple((canonical_reference(top, bottom),) for top in range(-5, 6)
                       for bottom in range(1, 5))
    samples = {
        "nat": tuple((number,) for number in range(-20, 41)),
        "mul": tuple((left, right) for left in range(-6, 7) for right in range(-6, 7)),
        "frac": tuple((pair(top, bottom),) for top in range(-6, 7) for bottom in range(-6, 7)),
        "whole": tuple((candidate,) for candidate in canonical),
        "qadd": tuple((left, right) for left in rationals for right in rationals),
        "qmul": tuple((left, right) for left in rationals for right in rationals),
        "cf_divmod": tuple((number, divisor) for number in range(-12, 13)
                           for divisor in range(1, 7)) + ((1, 0),),
        "cf": cf_samples + tuple((items(*digits),) for digits in
                                  ((), (1, 1), (0, 1), (2, 0, 3), (2, -1, 3))),
        "cf_step": tuple((pair(pair(1, 0), pair(0, 1)), digit) for digit in range(-4, 5)),
        "bounded_convergent": tuple((pair(expansion, natural(index % 5)),)
                                     for index, expansion in enumerate(continued)),
    }
    if name in ("repeat", "fold_frac", "convergents"):
        args = {"repeat": tuple((seed, natural(times)) for seed in range(-2, 3) for times in range(10)),
                "fold_frac": tuple((items(*members), frac(0, 1))
                                   for length in range(4) for members in product(rationals[4:8], repeat=length)),
                "convergents": tuple((expansion,) for expansion in continued)}[name]
        family = {"repeat": ("succ", "neg"), "fold_frac": ("qadd", "qmul"),
                  "convergents": ("cf_step", "pair")}[name]
        descriptions = {
            "repeat": "bound seeds -2..2 and counts 0..9",
            "fold_frac": "bound all lists of length 0..3 from four canonical fractions and seed 0/1",
            "convergents": "bound all 65 canonical fractions with numerator -6..6 and denominator 1..8, expanded into CF",
        }
        reference = {"repeat": _repeat_reference, "fold_frac": _fold_reference,
                     "convergents": _convergents_reference}[name]
        request = VerifyRequest("bounded", args, {"domain": descriptions[name] + f"; {len(args)} input tuples, slots {family}",
                   "size": len(args), "op_family": list(family)}, reference=reference, extra={"op_family": family})
        return request
    reference = {
        "nat": lambda number: Bottom("range") if number < 0 else natural(number),
        "mul": lambda left, right: left * right,
        "frac": canonical_reference,
        "whole": lambda q: q.fields[0].fields[1] == 1,
        "qadd": lambda left, right: canonical_reference(left.fields[0].fields[0] * right.fields[0].fields[1] + right.fields[0].fields[0] * left.fields[0].fields[1], left.fields[0].fields[1] * right.fields[0].fields[1]),
        "qmul": lambda left, right: canonical_reference(left.fields[0].fields[0] * right.fields[0].fields[0], left.fields[0].fields[1] * right.fields[0].fields[1]),
        "cf_divmod": lambda number, divisor: Bottom("divisor") if divisor <= 0 else pair(number // divisor, number % divisor),
        "cf": lambda q: Card("cf", "val", (items(*_cf_digits(q)),)),
        "cf_step": lambda state, digit: pair(pair(digit, 1), pair(1, 0)),
        "bounded_convergent": _bounded_reference,
    }[name]
    domain = samples[name]
    return VerifyRequest("bounded", domain, {"domain": "bound explicit finite inputs, " + str(len(domain)) + " cases; " +
                          {"nat": "integers -20..40", "mul": "signed pairs -6..6", "frac": "integer pairs -6..6",
                           "whole": "all 65 distinct canonical fractions from numerator -6..6, denominator 1..8",
                           "qadd": "all 10x10 canonical fraction pairs",
                           "qmul": "all 10x10 canonical fraction pairs", "cf_divmod": "numerator -12..12, divisor 1..6 and zero",
                           "cf": "44 fractions (numerator -5..5, divisor 1..4) and five invalid digit lists",
                           "cf_step": "digits -4..4 on initial state",
                           "bounded_convergent": "65 distinct rational CF expansions from numerator -6..6, denominator 1..8, each with bound index mod 5 (0..4)"}[name], "size": len(domain)}, reference=reference)


def _repeat_reference(assignment, inputs):
    seed, count = inputs
    for _ in range(count.fields[0]):
        seed = seed + 1 if assignment["step"] == "succ" else -seed
    return seed


def _fold_reference(assignment, inputs):
    members, seed = inputs
    for member in members.fields:
        left_top, left_bottom = seed.fields[0].fields
        right_top, right_bottom = member.fields[0].fields
        if assignment["step"] == "qadd":
            seed = canonical_reference(left_top * right_bottom + right_top * left_bottom,
                                       left_bottom * right_bottom)
        else:
            seed = canonical_reference(left_top * right_top, left_bottom * right_bottom)
    return seed


def _convergents_reference(assignment, inputs):
    digits = inputs[0].fields[0].fields
    if assignment["step"] == "pair" and digits:
        return Bottom("type")
    previous_top, older_top, previous_bottom, older_bottom = 1, 0, 0, 1
    result = []
    for digit in digits:
        current_top = digit * previous_top + older_top
        current_bottom = digit * previous_bottom + older_bottom
        result.append(canonical_reference(current_top, current_bottom))
        previous_top, older_top = current_top, previous_top
        previous_bottom, older_bottom = current_bottom, previous_bottom
    return items(*result)


def _bounded_reference(state):
    continued, bound = state.fields
    options = _convergents_reference({"step": "cf_step"}, (continued,)).fields
    allowed = [value for value in options if value.fields[0].fields[1] <= bound.fields[0]]
    return allowed[-1] if allowed else Bottom("no_convergent")


def _cf_digits(q):
    number, denominator = q.fields[0].fields
    result = []
    while denominator:
        quotient, remainder = divmod(number, denominator)
        result.append(quotient)
        number, denominator = denominator, remainder
    return result


def build_library():
    library = new_library()
    for definition in definitions():
        library.write(definition)
        if definition.name in {"mul", "whole", "cf_step", "convergents", "bounded_convergent"}:
            check_local(library, definition.name)
        else:
            library.check(definition.name)
        request = scope_for(definition.name)
        if definition.kind == "observation":
            library._advance(definition.name, "callable")
        else:
            sample = (kernel.FnRef(request.extra["op_family"][0]), *request.domain[0]) if definition.kind == "combinator" else request.domain[0]
            if definition.kind == "object":
                sample = (sample[0],)
            library.make_callable(definition.name, (sample,))
        library.verify(definition.name, request)
        library.account(definition.name)
        library.promote(definition.name, Contract(f"{definition.name}: exact over the stated finite scope"))
    from opulse.worlds_v2.integer.extensions import extend_library

    extend_library(library)
    return library
