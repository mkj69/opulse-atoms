"""Eleven invented tower cards with explicit observation verification gates."""

from functools import lru_cache

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.library import VerifyRequest
from opulse.atoms.observations import check_observation
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


def let(name, value, body):
    return n.Let(name, value, body)


def lets(bindings, body):
    for name, value in reversed(bindings):
        body = let(name, value, body)
    return body


def test(value):
    return n.Test(value)


def bit(value):
    return n.Case(((test(value), lit(1)),), lit(0))


def operation(name, params, body, sorts=None, output="any"):
    spec = OperationSpec(name, "transform", tuple(Edge(sort, name=param)
                         for param, sort in zip(params, sorts or ("any",) * len(params))),
                         Edge(output), f"Unfold {name} over byte-machine atoms.",
                         extra={"input_names": list(params)})
    return name, "operation", spec, body


def combinator(name, params, slots, body):
    return name, "combinator", CombinatorSpec(name, tuple(params), tuple(slots), body), body


def observation(name, params, reads, body):
    return name, "observation", ObservationSpec(name, tuple(reads), body), body


def object_type(name, base, fields):
    predicates = []
    for field in fields:
        member = call(f"{base}.{field}", var("x"))
        predicates.extend((n.Test(call("le", lit(0), member)),
                           n.Test(call("lt", member, lit(256)))))
    if name == "Vec":
        predicates.extend((n.Test(call("le", call("vec_base.len", var("x")), lit(32))),
                           n.Test(call("le", call("address", call("vec_base.start", var("x")),
                                                     call("vec_base.len", var("x"))), lit(255)))))
    condition = predicates[0]
    for predicate in predicates[1:]:
        condition = n.And(condition, predicate)
    valid = n.Case(((test(call(f"is_{base}", var("x"))),
                     n.Case(((condition, lit(True)),), lit(False))),), lit(False))
    spec = ObjectSpec(name, "refine", base=base, valid=valid,
                      sealed=True, interface=tuple(f"{name}.{field}" for field in fields) +
                      (f"{name}.make",), extra={"fields": list(fields)})
    return name, "object", spec, None


def definitions():
    state = var("s")
    loop_body = let("tested", call("branch", state, call("lt", lit(0), call("?b", state)), lit(2)),
        n.Case(((test(call("eq", call("?b", state), lit(0))), var("tested")),),
               call("loop", call("branch", call("body", var("tested")), lit(True), lit(0)))))
    while_b = combinator("@while_b", ("body", "s"), ("body",),
                         n.Rec("loop", ("s",), loop_body,
                               (call("branch", state, lit(True), lit(0)),), call("?b", state)))
    tick = operation("mul_tick", ("s",), call("dec", call("add", state, lit("A"), lit("C")), lit("B")),
                     ("Machine",), "Machine")
    multiply = operation("mul_into", ("s",), call("@while_b", lit(kernel.FnRef("mul_tick")), state),
                         ("Machine",), "Machine")
    vec = object_type("Vec", "vec_base", ("start", "len"))
    at = observation("?at", ("s", "addr"), ("?mem",),
                     call("?mem", state, var("addr")))
    dot_step = operation("dot_step", ("s", "xaddr", "yaddr"),
        let("left", call("load", state, lit("C"), var("xaddr")),
        let("right", call("load", var("left"), lit("B"), var("yaddr")),
        let("zero", call("put", var("right"), lit("A"), lit(0)),
        let("product", call("mul_into", var("zero")),
        let("total", call("load", var("product"), lit("D"), lit(255)),
        let("added", call("add", var("total"), lit("D"), lit("A")),
            call("store", var("added"), lit(255), lit("D")))))))),
        ("Machine", "Addr", "Addr"), "Machine")
    dot_step_again = operation("dot_step_again", ("s", "xaddr", "yaddr"),
                               call("dot_step", call("dot_step", state, var("xaddr"), var("yaddr")),
                                    var("xaddr"), var("yaddr")),
                               ("Machine", "Addr", "Addr"), "Machine")
    zip_body = n.Case(((test(call("lt", var("i"), call("Vec.len", var("x")))),
        call("zip_loop", call("step", var("acc"),
                           call("address", call("Vec.start", var("x")), var("i")),
                           call("address", call("Vec.start", var("y")), var("i"))),
             call("inc", var("i")))),), var("acc"))
    zip_fold = combinator("@zip_fold", ("step", "s", "x", "y"), ("step",),
        n.Case(((test(call("eq", call("Vec.len", var("x")), call("Vec.len", var("y")))),
                 n.Rec("zip_loop", ("acc", "i"), zip_body, (var("s"), lit(0)),
                       call("sub", call("Vec.len", var("x")), var("i")))),),
               call("zip_error")))
    dot = operation("dot", ("s", "x", "y"),
        let("zero", call("put", state, lit("D"), lit(0)),
            call("@zip_fold", lit(kernel.FnRef("dot_step")),
                 call("store", var("zero"), lit(255), lit("D")), var("x"), var("y"))),
        ("Machine", "Vec", "Vec"), "Machine")
    carry_tick = operation("carry_tick", ("s",),
        let("before", call("?out", state),
        let("added", call("add", state, lit("A"), lit("C")),
        let("counted", n.Case(((test(call("lt", call("?out", var("added")), var("before"))),
                              call("put", var("added"), lit("D"), call("inc", call("?d", var("added"))))),),
                              var("added")), call("dec", var("counted"), lit("B"))))),
        ("Machine",), "Machine")
    parts = operation("mul_parts", ("a", "b"),
        n.Rec("carry_loop", ("remaining", "low", "high"),
            n.Case(((test(call("lt", lit(0), var("remaining"))),
                let("next_low", call("byte_add", var("low"), var("a")),
                    call("carry_loop", call("sub", var("remaining"), lit(1)),
                         var("next_low"),
                         call("byte_add", var("high"),
                              bit(call("lt", var("next_low"), var("low"))))))),),
                   call("pair", var("high"), var("low"))),
            (var("b"), lit(0), lit(0)), var("remaining")),
        ("Byte", "Byte"), "pair")
    carry = operation("mul_carry", ("a", "b"),
                      call("first", call("mul_parts", var("a"), var("b"))),
                      ("Byte", "Byte"), "Byte")
    wide = object_type("Wide", "wide_base", ("lo", "mid", "hi"))
    initial = call("Wide.make", call("wide", lit(0), lit(0), lit(0)))
    bindings = (
        ("machine", call("first", var("acc"))),
        ("sum", call("second", var("acc"))),
        ("a", call("?at", var("machine"), var("xaddr"))),
        ("b", call("?at", var("machine"), var("yaddr"))),
        ("product", call("mul_into", call("machine_new", lit(0), var("b"), var("a"), lit(0)))),
        ("low", call("byte_add", call("Wide.lo", var("sum")), call("?out", var("product")))),
        ("carry_low", bit(call("lt", var("low"), call("Wide.lo", var("sum"))))),
        ("middle", call("byte_add", call("Wide.mid", var("sum")), call("mul_carry", var("a"), var("b")))),
        ("middle2", call("byte_add", var("middle"), var("carry_low"))),
        ("high", call("byte_add", call("Wide.hi", var("sum")),
                          call("byte_add", bit(call("lt", var("middle"), call("Wide.mid", var("sum")))),
                               bit(call("lt", var("middle2"), var("middle")))))),
    )
    wide_step = operation("wide_step", ("acc", "xaddr", "yaddr"),
        lets(bindings, call("pair", var("machine"),
             call("Wide.make", call("wide", var("low"), var("middle2"), var("high"))))),
        ("pair", "Addr", "Addr"), "pair")
    wide_dot = operation("wide_dot", ("s", "x", "y"),
        call("second", call("@zip_fold", lit(kernel.FnRef("wide_step")),
                            call("pair", state, initial), var("x"), var("y"))),
        ("Machine", "Vec", "Vec"), "Wide")
    wrap_step = lets((
        ("xaddr", call("address", call("Vec.start", var("x")), var("i"))),
        ("yaddr", call("address", call("Vec.start", var("y")), var("i"))),
        ("a", call("?at", state, var("xaddr"))),
        ("b", call("?at", state, var("yaddr"))),
        ("product", call("mul_parts", var("a"), var("b"))),
        ("low", call("byte_add", call("Wide.lo", var("sum")), call("second", var("product")))),
        ("carry_low", bit(call("lt", var("low"), call("Wide.lo", var("sum"))))),
        ("middle", call("byte_add", call("Wide.mid", var("sum")), call("first", var("product")))),
        ("middle2", call("byte_add", var("middle"), var("carry_low"))),
        ("high", call("byte_add", call("Wide.hi", var("sum")),
                      call("byte_add", bit(call("lt", var("middle"), call("Wide.mid", var("sum")))),
                           bit(call("lt", var("middle2"), var("middle")))))),
    ), call("wrap_loop", call("inc", var("i")),
            call("Wide.make", call("wide", var("low"), var("middle2"), var("high")))))
    wrap = observation("?dot_wrap", ("s", "x", "y"), ("?mem",),
        let("result", n.Case(((test(call("eq", call("Vec.len", var("x")),
                                                   call("Vec.len", var("y")))),
            n.Rec("wrap_loop", ("i", "sum"),
                n.Case(((test(call("lt", var("i"), call("Vec.len", var("x")))), wrap_step),),
                       var("sum")), (lit(0), initial),
                call("sub", call("Vec.len", var("x")), var("i")))),), call("zip_error")),
            n.Case(((test(call("lt", lit(0), call("Wide.mid", var("result")))), lit(True)),
                    (test(call("lt", lit(0), call("Wide.hi", var("result")))), lit(True))),
                   lit(False))))
    return (tick, while_b, multiply, vec, at, dot_step, dot_step_again, zip_fold, dot,
            carry_tick, parts, carry, wide, wide_step, wide_dot, wrap)


TOWER = ("@while_b", "mul_into", "Vec", "?at", "dot_step", "@zip_fold", "dot",
         "mul_carry", "Wide", "wide_dot", "?dot_wrap")
OBS_PARAMS = {"?at": ("s", "addr"),
              "?dot_wrap": ("s", "x", "y")}


def vector(start, length):
    return Card("Vec", "val", (hosts.vec(start, length),))


def wide_value(lo, mid, hi):
    return Card("Wide", "val", (hosts.wide(lo, mid, hi),))


def vector_fields(value):
    return value.fields[0].fields


def wide_fields(value):
    return value.fields[0].fields


def oracle_tick(current):
    return hosts.dec(hosts.add(current, "A", "C"), "B")


def oracle_loop(current, tick=oracle_tick):
    current = hosts.branch(current, True, 0)
    while hosts.b(current):
        current = hosts.branch(current, True, 2)
        current = hosts.branch(tick(current), True, 0)
    return hosts.branch(current, False, 2)


def oracle_multiply(current):
    regs, memory, _, z = hosts.fields(current)
    result = list(regs)
    result[0] = (regs[0] + regs[1] * regs[2]) % 256
    result[1] = 0
    return hosts.machine(result, memory, 1, 1 if regs[1] else z)


def oracle_dot_step(current, xaddr, yaddr):
    current = hosts.load(current, "C", xaddr)
    current = hosts.load(current, "B", yaddr)
    current = hosts.put(current, "A", 0)
    current = oracle_multiply(current)
    current = hosts.load(current, "D", 255)
    current = hosts.add(current, "D", "A")
    return hosts.store(current, 255, "D")


def oracle_fold(step, current, left, right):
    first, length = vector_fields(left)
    second, other_length = vector_fields(right)
    if length != other_length:
        return Bottom("zip_length_mismatch")
    for offset in range(length):
        current = step(current, first + offset, second + offset)
    return current


def oracle_dot(current, left, right):
    return oracle_fold(oracle_dot_step, hosts.store(hosts.put(current, "D", 0), 255, "D"), left, right)


def oracle_wide_step(acc, xaddr, yaddr):
    current, total = acc.fields
    left, right = hosts.fields(current)[1][xaddr], hosts.fields(current)[1][yaddr]
    lo, mid, hi = wide_fields(total)
    amount = lo + mid * 256 + hi * 65536 + left * right
    return hosts.pair(current, wide_value(amount % 256, amount // 256 % 256, amount // 65536))


def oracle_wide_dot(current, left, right):
    result = oracle_fold(oracle_wide_step, hosts.pair(current, wide_value(0, 0, 0)), left, right)
    return result.fields[1] if isinstance(result, Card) else result


def sample_states(count=64):
    return tuple(hosts.state((index * 13 % 256, index % 7, index * 17 % 256, index * 3 % 256),
                             {16: index * 19 % 256, 64: index * 11 % 256,
                              17: index * 7 % 256, 65: index * 23 % 256, 255: index * 5 % 256},
                             pc=index * 9 % 256, z=index % 2)
                 for index in range(count))


def request_for(name, lib):
    states = sample_states()
    if name in ("dot_step", "dot_step_again", "@zip_fold", "dot", "wide_step", "wide_dot", "?dot_wrap"):
        states = tuple(hosts.state((index * 13 % 256, index % 7, index * 17 % 256, index % 9),
                                   {16: index % 8, 17: (index + 3) % 8,
                                    64: (index * 3) % 8, 65: (index * 5) % 8,
                                    255: index * 5 % 256}, pc=index * 9 % 256, z=index % 2)
                       for index in range(64))
    left, right = vector(16, 2), vector(64, 2)
    if name == "mul_tick":
        domain = [(state,) for state in states]
        reference = oracle_tick
    elif name == "@while_b":
        domain = [(hosts.state((index * 13 % 256, count, index * 17 % 256, index * 3 % 256),
                               {16: index * 19 % 256, 255: index * 5 % 256},
                               pc=index * 9 % 256, z=index % 2),)
                  for count in range(256) for index in range(2)]
        return VerifyRequest("bounded", domain,
            {"domain": "bound: every B in 0..255 in two fixed full-state contexts; two decrementing operation slots",
             "size": len(domain), "op_family": ["mul_tick", "carry_tick"]},
            reference=lambda ops, args: oracle_loop(args[0],
                oracle_tick if ops["body"] == "mul_tick" else oracle_carry_tick),
            extra={"op_family": ("mul_tick", "carry_tick")})
    elif name == "mul_into":
        domain = [(state,) for state in states]
        reference = oracle_multiply
    elif name == "Vec":
        bases = [hosts.vec(index, index % 17) for index in range(50)]
        bases += [hosts.vec(224 + index, 32) for index in range(12)]
        bases += [hosts.wide(1, 2, 3), 9]
        return VerifyRequest("bounded", [(value,) for value in bases],
                             {"domain": "bound: 50 valid vector bases, 12 out-of-range bases, two wrong sorts",
                              "size": len(bases)})
    elif name == "?at":
        from random import Random

        random = Random(173)
        samples = [hosts.state(changes={addr: random.randrange(256) for addr in hosts.MEMORY_GRANTS},
                               pc=random.randrange(256)) for _ in range(4)]
        first = [21, 33, 47, 58, 69, 72, 85, 96, 107, 118, 129, 140]
        second = [119, 108, 97, 86, 75, 64, 53, 42, 31, 20, 9, 254]
        cells = {**dict(enumerate(first, 80)), **dict(enumerate(second, 120))}
        samples.append(hosts.state(changes=cells))
        samples.append(hosts.state(changes={**cells, 91: 12}))
        domain = [(machine, addr) for machine in (*states[:8], *samples)
                  for addr in sorted(hosts.MEMORY_GRANTS)]
        reference = lambda state, addr: hosts.fields(state)[1][addr]
    elif name == "dot_step":
        domain = [(state, 16, 64) for state in states]
        reference = oracle_dot_step
    elif name == "dot_step_again":
        domain = [(state, 16, 64) for state in states]
        reference = lambda state, xaddr, yaddr: oracle_dot_step(oracle_dot_step(state, xaddr, yaddr), xaddr, yaddr)
    elif name == "@zip_fold":
        domain = [(state, left, right) for state in states]
        family = ("dot_step", "dot_step_again")
        return VerifyRequest("bounded", domain,
            {"domain": "bound: 64 varied machines, vector length 2, two distinct step programs",
             "size": len(domain), "op_family": list(family)},
            reference=lambda ops, args: oracle_fold(
                oracle_dot_step if ops["step"] == "dot_step" else
                lambda state, xaddr, yaddr: oracle_dot_step(oracle_dot_step(state, xaddr, yaddr), xaddr, yaddr),
                *args), extra={"op_family": family})
    elif name == "dot":
        domain = [(state, left, right) for state in states]
        reference = oracle_dot
    elif name == "carry_tick":
        domain = [(state,) for state in states]
        reference = oracle_carry_tick
    elif name == "mul_carry":
        domain = [(index * 11 % 256, index % 7) for index in range(64)]
        reference = lambda a, b: a * b // 256
    elif name == "mul_parts":
        domain = [(index * 11 % 256, index % 7) for index in range(64)]
        reference = lambda a, b: hosts.pair(a * b // 256, a * b % 256)
    elif name == "Wide":
        bases = [hosts.wide(index, index * 17 % 256, index % 4) for index in range(50)]
        bases += [hosts.wide(256 + index, 1, 0) for index in range(12)]
        bases += [hosts.vec(1, 2), 9]
        return VerifyRequest("bounded", [(value,) for value in bases],
                             {"domain": "bound: 50 valid wide bases, 12 out-of-range bases, two wrong sorts",
                              "size": len(bases)})
    elif name == "wide_step":
        domain = [(hosts.pair(state, wide_value(index, index % 9, 0)), 16, 64)
                  for index, state in enumerate(states)]
        reference = oracle_wide_step
    elif name == "wide_dot":
        domain = [(state, left, right) for state in states]
        reference = oracle_wide_dot
    elif name == "?dot_wrap":
        domain = [(state, left, right) for state in states]
        reference = lambda state, x, y: any(wide_fields(oracle_wide_dot(state, x, y))[1:])
    else:
        raise KeyError(name)
    method = "bounded"
    bounds = {"mul_tick": "B 0..6, varied A,C,D,pc,z and memory",
              "mul_into": "B 0..6, varied A,C,D,pc,z and memory",
              "carry_tick": "B 0..6, varied A,C,D,pc,z and memory",
              "?at": "all granted addresses 16..47, 64..95, 120..131 across 8 varied, 4 seeded random and both showcase full states",
              "dot_step": "fixed addresses 16,64, byte values 0..7 across 64 full contexts",
              "dot_step_again": "fixed addresses 16,64, byte values 0..7 across 64 full contexts",
              "dot": "vectors (16,2),(64,2), byte values 0..7 across 64 full contexts",
              "mul_carry": "64 distinct first bytes, second bytes 0..6",
              "mul_parts": "64 distinct first bytes, second bytes 0..6",
              "wide_step": "fixed addresses 16,64 and 64 varied full states and Wide accumulators",
              "wide_dot": "vectors (16,2),(64,2), byte values 0..7 across 64 full contexts",
              "?dot_wrap": "vectors (16,2),(64,2), byte values 0..7 across 64 full contexts"}
    description = f"bound: {bounds[name]}"
    return VerifyRequest(method, domain, {"domain": description, "size": len(domain)}, reference=reference)


def oracle_carry_tick(current):
    old = hosts.out(current)
    current = hosts.add(current, "A", "C")
    if hosts.out(current) < old:
        current = hosts.put(current, "D", hosts.d(current) + 1)
    return hosts.dec(current, "B")


@lru_cache(maxsize=3)
def build_library(*, use_mul_artifact=True, use_while_artifact=True):
    library = new_library()
    definitions_by_name = {item[0]: item for item in definitions()}
    order = ("mul_tick", "carry_tick", "@while_b", "mul_into", "Vec", "?at", "dot_step",
             "dot_step_again", "@zip_fold", "dot", "mul_parts", "mul_carry", "Wide", "wide_step",
             "wide_dot", "?dot_wrap")
    states = sample_states(1)
    examples = {"mul_tick": (states[0],), "carry_tick": (states[0],),
                "@while_b": (kernel.FnRef("mul_tick"), states[0]), "mul_into": (states[0],),
                "Vec": (hosts.vec(16, 8),), "?at": (states[0], 16),
                "dot_step": (states[0], 16, 64), "dot_step_again": (states[0], 16, 64),
                "@zip_fold": (kernel.FnRef("dot_step"), states[0], vector(16, 2), vector(64, 2)),
                "dot": (states[0], vector(16, 2), vector(64, 2)),
                "mul_parts": (17, 3), "mul_carry": (17, 3), "Wide": (hosts.wide(1, 2, 3),),
                "wide_step": (hosts.pair(states[0], wide_value(0, 0, 0)), 16, 64),
                "wide_dot": (states[0], vector(16, 2), vector(64, 2)),
                "?dot_wrap": (states[0], vector(16, 2), vector(64, 2))}
    for name in order:
        _, kind, spec, body = definitions_by_name[name]
        if kind == "object":
            references = n.references(spec.valid)
            if spec.canon is not None:
                references |= n.references(spec.canon)
        else:
            references = (n.references(body) | n.operation_literals(body)) - (
                set(spec.op_params) if kind == "combinator" else set())
        dependencies = tuple(sorted(references))
        layer = 1 + max((library.get(dependency).layer if dependency in library.definitions else
                         library.get(dependency.split(".", 1)[0]).layer
                         if dependency.split(".", 1)[0] in library.definitions else 0
                         for dependency in dependencies), default=0)
        definition = Definition(name, kind, "invented", layer, dependencies, spec, body)
        library.write(definition)
        library.check(name)
        library.make_callable(name, (examples[name],))
        if kind == "observation" and check_observation(library.get(name), library):
            library.account(name)
            continue
        if name == "@while_b" and use_while_artifact:
            from .verify_mul import apply_while_artifact

            apply_while_artifact(library)
        elif name == "mul_into" and use_mul_artifact:
            from .verify_mul import apply_artifact

            apply_artifact(library)
        else:
            library.verify(name, request_for(name, library))
        library.account(name)
        library.promote(name, Contract(f"Full-state equality to the layer-zero unfolding of {name}."))
    return library
