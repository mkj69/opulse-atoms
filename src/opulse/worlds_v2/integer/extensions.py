"""Bounded arithmetic laws and two instances of the quotient-object template."""

from itertools import product
from math import gcd

from opulse.atoms import nodes as n
from opulse.atoms.laws import replay_rewrite, rewrite
from opulse.atoms.library import VerifyRequest
from opulse.atoms.spec import Contract, Definition, LawSpec, TemplateSpec
from opulse.atoms.templates import instantiate
from opulse.worlds_v2.integer.story import (
    abs_node,
    c,
    canonical_reference,
    lit,
    operation,
    pair,
    v,
    when,
)

LAW_DESCRIPTIONS = {
    "add_comm": "Addition has the same sum in either operand order.",
    "mul_comm": "Signed repeated addition has the same product in either operand order.",
    "mul_distrib": "Multiplication distributes across a sum on the right.",
    "gcd_comm": "The greatest common divisor ignores operand order.",
    "gcd_mul_lcm": "The product of the gcd and lcm is the absolute product.",
}


def _operation_definition(name, params, body, *, sorts=None, output="int", layer=5):
    _, kind, spec, body = operation(name, params, body, sorts, output)
    return Definition(name, kind, "invented", layer, tuple(sorted(n.references(body))), spec, body)


def _install(library, definition, request, sample=None):
    library.write(definition)
    library.check(definition.name)
    library.make_callable(definition.name, sample or request.domain[:1])
    library.verify(definition.name, request)
    library.account(definition.name)
    library.promote(definition.name, Contract(f"Exact on the bounded {definition.name} family"))


def _finite_request(domain, description, reference=None, **extra):
    return VerifyRequest("bounded", tuple(domain), {"domain": description, "size": len(domain)},
                         reference=reference, extra=extra)


def _laws():
    a, b, d = v("a"), v("b"), v("d")
    return {
        "add_comm": (("a", "b"), c("add", a, b), c("add", b, a)),
        "mul_comm": (("a", "b"), c("mul", a, b), c("mul", b, a)),
        "mul_distrib": (("a", "b", "d"), c("mul", a, c("add", b, d)),
                        c("add", c("mul", a, b), c("mul", a, d))),
        "gcd_comm": (("a", "b"), c("gcd", a, b), c("gcd", b, a)),
        "gcd_mul_lcm": (("a", "b"), c("mul", c("gcd", a, b), c("lcm", a, b)),
                        c("abs_int", c("mul", a, b))),
    }


def _quotient_template():
    spec = TemplateSpec("Quot", (("T", "sort"), ("canon", "operation")), "object", {
        "form": "refine", "base": "$T",
        "valid": n.to_json(c("quot_valid", v("x"), lit("$T"))),
        "canon": n.to_json(c("$canon", v("x"))), "params": ["x"], "sealed": False,
        "interface": [],
    }, {"family": [{"T": "pair", "canon": "reduce_ratio"},
                  {"T": "int", "canon": "mod12"}]})
    return Definition("Quot", "template", "invented", 1, (), spec, lit("Quot[T, canon]"))


def _frac_request():
    domain = tuple((pair(top, bottom),) for top in range(-2, 3)
                   for bottom in (-3, -2, -1, 1, 2, 3))
    return _finite_request(domain, "30 signed integer pairs (-2..2 over nonzero -3..3)")


def _hour_request():
    domain = tuple((value,) for value in range(-24, 25))
    return _finite_request(domain, "49 integers -24..24")


def extend_library(library):
    if "Quot" in library.definitions:
        original = c("mul", lit(2), lit(-1))
        return replay_rewrite(original, rewrite(original, library.get("mul_comm"), library),
                              "mul_comm", library, {})
    gcd_product = c("gcd", v("a"), v("b"))
    lcm_body = when(c("eq", gcd_product, lit(0)), lit(0),
                    c("quotient", c("abs_int", c("mul", v("a"), v("b"))), gcd_product))
    helpers = (
        (_operation_definition("abs_int", ("x",), abs_node(v("x")), layer=1),
         tuple((value,) for value in range(-8, 9)), lambda value: abs(value)),
        (_operation_definition("lcm", ("a", "b"), lcm_body, layer=4),
         tuple(product(range(-3, 4), repeat=2)),
         lambda left, right: 0 if left * right == 0 else abs(left * right) // gcd(left, right)),
    )
    for definition, domain, reference in helpers:
        _install(library, definition,
                 _finite_request(domain, f"{len(domain)} bounded integer tuples", reference))

    for name, (variables, left, right) in _laws().items():
        statement = c("eq", left, right)
        spec = LawSpec(name, tuple((variable, "int") for variable in variables), statement)
        dependencies = tuple(sorted(n.references(statement)))
        definition = Definition(name, "law", "invented",
                                1 + max((library.get(dep).layer for dep in dependencies), default=0),
                                dependencies, spec, statement)
        values = range(-2, 3) if len(variables) == 2 else range(-1, 3)
        domain = tuple(product(values, repeat=len(variables)))
        _install(library, definition, _finite_request(domain,
                 f"all {len(domain)} ordered tuples in {values.start}..{values.stop - 1}"))

    original = c("mul", lit(2), lit(-1))
    rewritten = rewrite(original, library.get("mul_comm"), library)
    derivation = replay_rewrite(original, rewritten, "mul_comm", library, {})

    reduce_body = library.get("frac").spec.canon
    reduce_definition = _operation_definition("reduce_ratio", ("x",), reduce_body,
                                              sorts=("pair",), output="pair", layer=1)
    reduce_domain = tuple((pair(top, bottom),) for top in range(-2, 3)
                          for bottom in (-3, -2, -1, 1, 2, 3))
    _install(library, reduce_definition, _finite_request(reduce_domain,
             "30 signed integer pairs with nonzero denominator",
             lambda value: canonical_reference(*value.fields).fields[0]))
    mod_body = c("second", c("cf_divmod", v("x"), lit(12)))
    mod_definition = _operation_definition("mod12", ("x",), mod_body, layer=2)
    _install(library, mod_definition, _finite_request(tuple((value,) for value in range(-24, 25)),
             "49 integers -24..24", lambda value: value % 12))

    quot_valid = _operation_definition("quot_valid", ("x", "base"),
        when(c("is_base", v("x"), v("base")),
             when(c("is_pair", v("x")), c("ne", c("second", v("x")), lit(0)), lit(True)),
             lit(False)), sorts=("any", "str"), output="bool", layer=1)
    valid_domain = tuple((pair(top, bottom), "pair") for top in range(-2, 3)
                         for bottom in range(-2, 3)) + tuple((value, "int") for value in range(-24, 25))
    _install(library, quot_valid, _finite_request(valid_domain,
             "25 pair values (-2..2) and 49 integers (-24..24)",
             lambda value, base: value.fields[1] != 0 if base == "pair" else True))

    template = _quotient_template()
    family = list(template.spec.extra["family"])
    request = _finite_request(tuple((entry["T"], entry["canon"]) for entry in family),
             "two instantiations: pair/reduce_ratio and int/mod12",
             family=family, member_requests=(_frac_request(), _hour_request()))
    request.scope["family"] = family
    _install(library, template, request, sample=(("pair", "reduce_ratio"),))
    instances = (("quot_frac", family[0], _frac_request()),
                 ("hour", family[1], _hour_request()))
    for name, arguments, member_request in instances:
        member = instantiate(library.get("Quot"), arguments, name, lib=library)
        _install(library, member, member_request)
    return derivation
