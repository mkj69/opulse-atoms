"""Deep circuits assembled by public kernel-node wiring rules."""

from dataclasses import replace
from functools import lru_cache
from itertools import product

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.check import all_dependencies, check_definition
from opulse.atoms.library import bounded, exhaustive
from opulse.atoms.spec import (
    CombinatorSpec,
    Contract,
    Definition,
    Edge,
    LawSpec,
    ObjectSpec,
    ObservationSpec,
    OperationSpec,
    compute_layer,
)
from opulse.atoms.values import Card, Ok
from opulse.worlds_v2.circuits import adapter, deep, hosts
from opulse.worlds_v2.circuits.world import new_library
from opulse.worlds_v2.export_util import bound_evidence


def definition(name, kind, body, lib, params=(), op_params=()):
    if kind == "operation":
        spec = OperationSpec(name, "combine", tuple(Edge("unknown", name=param) for param in params),
                             Edge("circuit"), f"Construct {name} from AND/NOT wiring.",
                             extra={"input_names": list(params)})
    elif kind == "combinator":
        spec = CombinatorSpec(name, tuple(params), tuple(op_params), body)
    elif kind == "object":
        pins = 2 if name == "Xor" else 16
        valid = deep.call("eq_int", deep.call("dag_inputs", deep.var("x")), deep.lit(pins))
        output_count = 1 if name == "Xor" else 9
        valid = deep.choose(valid,
                            deep.call("eq_int", deep.call("tuple_len",
                                      deep.call("dag_outputs", deep.var("x"))),
                                      deep.lit(output_count)), deep.lit(False))
        if name == "Xor":
            for bits, result in reversed(tuple(zip(product((0, 1), repeat=2), (0, 1, 1, 0)))):
                valid = deep.choose(valid,
                    deep.call("eq_bit", deep.call("out_pin", deep.var("x"),
                              deep.lit(hosts.bit_list(bits)), deep.lit(0)), deep.lit(result)),
                    deep.lit(False))
        else:
            canonical = lib.run("ripple", (kernel.FnRef("full_adder"), 8)).outcome.value
            _, canonical_gates, canonical_outputs = hosts.deep_from_card(canonical)
            valid = deep.choose(valid, deep.choose(
                deep.call("integer_lt", deep.call("tuple_len", deep.call("dag_gates", deep.var("x"))),
                          deep.lit(len(canonical_gates))), deep.lit(False),
                deep.choose(deep.call("eq_tuple", deep.call("dag_outputs", deep.var("x")),
                                      deep.lit(canonical_outputs)),
                            deep.call("eq_tuple", deep.take(deep.call("dag_gates", deep.var("x")),
                                                             deep.lit(len(canonical_gates))),
                                      deep.lit(canonical_gates)), deep.lit(False))), deep.lit(False))
        spec = ObjectSpec(name, "refine", base="circuit",
                          valid=valid,
                          canon=deep.var("x"), sealed=False, body=body)
    else:
        spec = ObservationSpec(name, ("out_pin",), body)
    depends = tuple(sorted(all_dependencies(Definition(name, kind, "invented", 1,
                                                       (), spec, body)) - set(op_params)))
    layer = compute_layer(depends, lambda key: lib.get(key.split(".")[0]).layer
                          if "." in key and key.split(".")[0] in lib.definitions else lib.get(key).layer)
    return Definition(name, kind, "invented", layer, depends, spec, body)


@lru_cache(maxsize=1)
def small_circuits():
    graphs = []
    for count in range(4):
        candidates = [()]
        for index in range(count):
            choices = [Card("gate", "not", (wire,)) for wire in range(2 + index)]
            choices += [Card("gate", "and", (left, right))
                        for left, right in product(range(2 + index), repeat=2)]
            candidates = [(*previous, gate) for previous in candidates for gate in choices]
        for gates in candidates:
            for output in range(2 + count):
                graphs.append(hosts.deep_to_card(2, gates, (output,)))
    return tuple(graphs)


def _check_object(lib, name, rows, expected):
    graph = lib.run("xor_graph" if name == "Xor" else "adder8_graph", ()).outcome.value
    if hosts.deep_inspect(graph) is not None:
        raise ValueError(f"{name} must construct a well-typed DAG")
    scope = lib.scope()
    for bits in rows:
        if kernel.call("eval_bits", (graph, bits), scope).outcome != Ok(expected(bits)):
            raise ValueError(f"{name} disagrees with the independent oracle")
    input_count, gates, outputs = hosts.deep_from_card(graph)
    domain = tuple(hosts.deep_to_card(input_count,
                   (*gates, *(Card("gate", "not", (0,)) for _ in range(extra))), outputs)
                   for extra in range(64))
    request = bounded((domain,), "bounded: 64 valid circuits of the required input width")
    lib.verify(name, request)


def _promote(lib, definition, sample, request=None, *, oracle=None, rows=None, scope_size=None):
    name = definition.name
    lib.write(definition)
    if definition.kind != "observation":
        lib.check(name)
        if definition.kind == "object":
            graph = lib.run("xor_graph" if name == "Xor" else "adder8_graph", ()).outcome.value
            lib.make_callable(name, ((graph,),))
        else:
            lib.make_callable(name, sample)
        if definition.kind == "object":
            _check_object(lib, name, oracle[0], oracle[1])
        else:
            lib.verify(name, request)
        checked_domain = []
        if rows is not None:
            scope = lib.scope()
            for graph, bits, expected in rows():
                if kernel.call("eval_bits", (graph, bits), scope).outcome != Ok(expected):
                    raise ValueError(f"{name} truth-row counterexample: {bits!r}")
                checked_domain.append((graph, bits))
            if scope_size is not None and len(checked_domain) != scope_size:
                raise ValueError(f"{name} checked {len(checked_domain)} rows instead of {scope_size}")
        if rows is not None or scope_size is not None:
            verified = lib.get(name)
            evidence = verified.evidence
            checked_inputs = (checked_domain if scope_size is not None and rows is not None
                              else tuple((kernel.FnRef(first), kernel.FnRef(second), *arguments)
                                         for first, second in product(request.extra["op_family"], repeat=2)
                                         for arguments in request.domain)
                              if scope_size is not None else request.domain)
            if scope_size is not None and len(checked_inputs) != scope_size:
                raise ValueError(f"{name} checked {len(checked_inputs)} cases instead of {scope_size}")
            amended = replace(evidence, scope={**evidence.scope,
                              "size": len(checked_inputs)},
                              checks=(*evidence.checks, "truth_rows") if rows is not None else evidence.checks)
            lib._definitions[name] = replace(verified, evidence=bound_evidence(
                lib, name, amended, checked_inputs))
            lib._library_checked.discard(name)
    lib.account(name)
    lib.promote(name, Contract(f"Verified on exactly {lib.get(name).evidence.scope['domain']}"))


def _constructor(names, input_pins, output_pin):
    graph = deep.var("graph")
    bindings = [("graph", deep.call("empty_circuit", deep.lit(input_pins)))]
    for index, (kind, wires) in enumerate(names):
        step = (deep.call("and_gate", graph, *wires) if kind == "and" else
                deep.call("not_gate", graph, wires[0]))
        bindings.append((f"gate_{index}", step))
        graph = deep.var(f"gate_{index}")
    return deep.let(bindings, deep.take_outputs(graph, deep.lit((output_pin,))))


def basic_definitions(lib):
    body = deep.or_from(deep.call("empty_circuit", deep.lit(2)), deep.lit(0), deep.lit(1))
    or2 = definition("or2", "operation", body, lib)
    _promote(lib, or2, ((),), replace(exhaustive((), "the one 2-input OR wiring and all 4 truth rows"),
                                    reference=lambda: hosts.deep_to_card(2, (
                                        Card("gate", "not", (0,)), Card("gate", "not", (1,)),
                                        Card("gate", "and", (2, 3)), Card("gate", "not", (4,))), (5,))),
             rows=lambda: ((lib.run("or2", ()).outcome.value, hosts.bit_list(bits),
                            hosts.bit_list((bits[0] | bits[1],)))
                           for bits in product((0, 1), repeat=2)))

    identity = definition("identity2", "operation", deep.call("with_outputs",
                          deep.call("empty_circuit", deep.lit(2)), deep.lit((0, 1))), lib)
    _promote(lib, identity, ((),), replace(exhaustive((), "the one 2-input identity wiring"),
                                       reference=lambda: hosts.deep_to_card(2, (), (0, 1))))

    def branch(name, invert):
        graph = deep.call("not_gate", deep.call("empty_circuit", deep.lit(2)), deep.lit(invert))
        body = deep.let((("negated", graph), ("joined", deep.call("and_gate", deep.var("negated"),
                           deep.end_wire(deep.var("negated")) if invert == 0 else deep.lit(0),
                           deep.lit(1) if invert == 0 else deep.end_wire(deep.var("negated"))))),
                        deep.take_outputs(deep.var("joined"),
                                          deep.call("append", deep.lit(()), deep.end_wire(deep.var("joined")))))
        entry = definition(name, "operation", body, lib)
        expected = (Card("gate", "not", (invert,)), Card("gate", "and", (2, 1) if invert == 0 else (0, 2)))
        _promote(lib, entry, ((),), replace(exhaustive((), "the one 2-input branch wiring"),
                                           reference=lambda: hosts.deep_to_card(2, expected, (3,))))

    branch("and_not_right", 1)
    branch("not_left_and_right", 0)

    for name, output in (("left2", 0), ("right2", 1)):
        body = deep.call("with_outputs", deep.call("empty_circuit", deep.lit(2)),
                         deep.lit((output,)))
        _promote(lib, definition(name, "operation", body, lib), ((),),
                 replace(exhaustive((), "the one two-input projection graph"),
                         reference=lambda output=output: hosts.deep_to_card(2, (), (output,))))
    _promote(lib, definition("not_left2", "operation",
             _constructor((("not", (deep.lit(0),)),), 2, 2), lib), ((),),
             replace(exhaustive((), "the one NOT-left graph"),
                     reference=lambda: hosts.deep_to_card(2, (Card("gate", "not", (0,)),), (2,))))

    for name, body in (("pair_graph", deep.pair_body()),):
        entry = definition(name, "combinator", body, lib, ("f", "g", "n"), ("f", "g"))
        sample = ((kernel.FnRef("and2"), kernel.FnRef("or2"), 2),)
        family = ("identity2", "and2", "or2", "and_not_right", "not_left_and_right",
                  "left2", "right2", "not_left2")
        description = "bounded: 64 ordered slot pairs at width 2 and all 4 input rows per pair"
        request = replace(bounded(((2,),), description),
                          scope={"domain": description, "description": description,
                                 "size": 1, "operation_cases": 64, "op_family": list(family)},
                          extra={"op_family": family})
        def paired_rows(family=family):
            graphs = {name: lib.run(name, ()).outcome.value for name in family}
            for first, second in product(family, repeat=2):
                paired = lib.run("pair_graph", (kernel.FnRef(first), kernel.FnRef(second), 2)).outcome.value
                for bits in product((0, 1), repeat=2):
                    row = hosts.bit_list(bits)
                    expected = hosts.bit_list((*hosts.deep_eval(graphs[first], row).fields,
                                              *hosts.deep_eval(graphs[second], row).fields))
                    yield paired, row, expected
        _promote(lib, entry, sample, request, rows=paired_rows, scope_size=256)

    paired = definition("paired_disjoint", "operation", deep.call("pair_graph",
                        deep.lit(kernel.FnRef("and_not_right")),
                        deep.lit(kernel.FnRef("not_left_and_right")), deep.lit(2)), lib)
    oracle_pair = hosts.deep_to_card(2, (Card("gate", "not", (1,)),
                        Card("gate", "and", (0, 2)), Card("gate", "not", (0,)),
                        Card("gate", "and", (4, 1))), (3, 5))
    _promote(lib, paired, ((),), replace(exhaustive((), "the one paired disjoint wiring"),
                                       reference=lambda: oracle_pair))

    xor_body = deep.call("compose", deep.lit(kernel.FnRef("paired_disjoint")),
                         deep.lit(kernel.FnRef("or2")), deep.lit(2))
    _promote(lib, definition("xor_graph", "operation", xor_body, lib), ((),),
             replace(exhaustive((), "the one XOR graph"), reference=lambda: hosts.deep_to_card(2, (
                 Card("gate", "not", (1,)), Card("gate", "and", (0, 2)),
                 Card("gate", "not", (0,)), Card("gate", "and", (4, 1)),
                 Card("gate", "not", (3,)), Card("gate", "not", (5,)),
                 Card("gate", "and", (6, 7)), Card("gate", "not", (8,))), (9,))))
    xor = definition("Xor", "object", deep.choose(
        deep.call("eq_int", deep.call("dag_inputs", deep.call("paired_disjoint")), deep.lit(2)),
        deep.call("xor_graph"), deep.call("tuple_tail", deep.lit(()))), lib)
    rows = tuple(Card("bits", "list", (first, second))
                 for first in (0, 1) for second in (0, 1))
    _promote(lib, xor, ((),), oracle=(rows, lambda bits: Card("bits", "list", (bits.fields[0] ^ bits.fields[1],))))
    return rows


def _check_graph_operation(lib, name, rows, expected, description):
    lib.check(name)
    if name == "multiply4_swap":
        lib._advance(name, "callable")
    else:
        lib.make_callable(name, ((),))
    construction = lib.run(name, ())
    if not isinstance(construction.outcome, Ok) or hosts.deep_inspect(construction.outcome.value) is not None:
        raise ValueError(f"{name} must construct a valid circuit")
    graph = construction.outcome.value
    scope = lib.scope()
    for bits in rows:
        if kernel.call("eval_bits", (graph, bits), scope).outcome != Ok(expected(bits)):
            raise ValueError(f"{name} failed row {bits}")
    request = (exhaustive((), description) if name in ("full_adder", "multiply4", "multiply4_swap")
               else bounded((), description))
    lib.verify(name, replace(request, reference=lambda: graph))
    verified = lib.get(name)
    checked_inputs = tuple((bits,) for bits in rows)
    evidence = replace(verified.evidence,
                       scope={**verified.evidence.scope, "size": len(checked_inputs)},
                       checks=(*verified.evidence.checks, "valid", "truth_rows"))
    lib._definitions[name] = replace(verified, evidence=bound_evidence(
        lib, name, evidence, checked_inputs))
    lib._library_checked.discard(name)
    lib._steps[name] = [construction.steps + 1] * len(rows)
    lib.account(name)
    lib.promote(name, Contract(f"Verified only for {description}"))


def _check_depth_observation(lib, name, graphs, rows, oracle, description):
    definition = lib.get(name)
    problems = check_definition(definition, lib.world, lib.definitions.get)
    if definition.body != definition.spec.body or definition.spec.reads != ("out_pin",):
        problems.append("observation must read the authorized output-pin probe")
    calls = {node.fn for node in n.walk(definition.body) if isinstance(node, n.Call)}
    if "out_pin" not in calls or "eval_bits" in calls:
        problems.append("observation bypasses the selective output-pin probe")
    if problems:
        raise ValueError(problems)
    lib._advance(name, "checked")
    argument_tuples = [(graph,) if name == "truth_table" else graph for graph in graphs]
    probe_rows = []
    steps = []
    for args in argument_tuples:
        if any(hosts.deep_inspect(graph) is not None for graph in args):
            raise ValueError("invalid observation truth")
        before = tuple(args)
        scope = lib.scope().extend((kernel.Defn(name, lib._params(definition),
                                                definition.body, "observation", definition.layer),))
        run = kernel.call(name, args, scope)
        if run.outcome != Ok(oracle(*args)) or args != before:
            raise ValueError(f"{name} changed truth or misreported its observation: {args!r}, {run.outcome!r}, {oracle(*args)!r}")
        views = tuple(tuple(hosts.deep_out(graph, row, pin)
                            for pin in range(len(hosts.deep_from_card(graph)[2])))
                      for graph in args for row in (
                          tuple(hosts.bit_list((number // 2, number % 2)) for number in range(4))
                          if hosts.deep_from_card(graph)[0] == 2 else rows))
        probe_rows.append((views, run.outcome))
        steps.append(run.steps)
    lib._advance(name, "callable")
    for index, (first_view, first_result) in enumerate(probe_rows):
        for second_view, second_result in probe_rows[index + 1:]:
            if first_view == second_view and first_result != second_result:
                raise ValueError("non-interference failure")
    request = replace(bounded((graphs,), description), domain=tuple(tuple(args) for args in argument_tuples))
    adapter._record(lib, name, request, ("dependency", "facts_unchanged",
                                         "non_interference", "reference"), steps, request.domain)
    lib.account(name)
    lib.promote(name, Contract(f"Verified only for {description}"))


def adder_definitions(lib, rows):
    table_rows = tuple(Card("bits", "list", (first, second))
                       for first in (0, 1) for second in (0, 1))
    table_body = deep.call("bit_list", deep.call("append_bit", deep.call("append_bit",
                     deep.call("append_bit", deep.call("append_bit", deep.lit(()),
                     deep.call("out_pin", deep.var("circuit"), deep.lit(table_rows[0]), deep.lit(0))),
                     deep.call("out_pin", deep.var("circuit"), deep.lit(table_rows[1]), deep.lit(0))),
                     deep.call("out_pin", deep.var("circuit"), deep.lit(table_rows[2]), deep.lit(0))),
                     deep.call("out_pin", deep.var("circuit"), deep.lit(table_rows[3]), deep.lit(0))))
    table_def = definition("truth_table", "observation", table_body, lib)
    lib.write(table_def)
    xor_graph = lib.run("xor_graph", ()).outcome.value
    xor_inputs, xor_gates, xor_outputs = hosts.deep_from_card(xor_graph)
    equivalent_graph = hosts.deep_to_card(xor_inputs,
        (*xor_gates, Card("gate", "not", (0,))), xor_outputs)
    graphs = (*small_circuits()[:64], xor_graph, equivalent_graph,
              lib.run("and2", ()).outcome.value, lib.run("or2", ()).outcome.value)
    _check_depth_observation(lib, "truth_table", graphs, table_rows,
                             lambda graph: Card("bits", "list", tuple(
                                 hosts.deep_out(graph, bits, 0) for bits in table_rows)),
                             "bounded: 64 two-input graphs with <=2 gates plus 4 AND/OR/XOR variants, each on all 4 rows")

    full_adder = definition("full_adder", "operation", deep.full_adder_body(), lib)
    lib.write(full_adder)
    adder_rows = tuple(Card("bits", "list", bits) for bits in (
        (first, second, carry) for first in (0, 1) for second in (0, 1) for carry in (0, 1)))
    _check_graph_operation(lib, "full_adder", adder_rows,
        lambda bits: Card("bits", "list", ((sum(bits.fields) % 2), (sum(bits.fields) // 2))),
        "bounded: all eight 3-input rows of the 22-gate full adder")

    _promote(lib, definition("full_adder_copy", "operation", deep.call("full_adder"), lib),
             ((),), replace(exhaustive((), "the copied full-adder graph"),
                            reference=lambda: lib.run("full_adder", ()).outcome.value))

    ripple = definition("ripple", "combinator", deep.ripple_body(), lib,
                        ("f", "n"), ("f",))
    family = ("full_adder", "full_adder_copy")
    description = "bounded: width 4 across 2 slots; all 256 four-bit operand pairs per slot"
    request = replace(bounded(((4,),), description),
                      scope={"domain": description, "description": description, "size": 1,
                             "operation_cases": 2, "op_family": list(family)}, extra={"op_family": family})
    def ripple_rows():
        for name in family:
            graph = lib.run("ripple", (kernel.FnRef(name), 4)).outcome.value
            for left, right in product(range(16), repeat=2):
                yield (graph, hosts.bit_list(_binary(left, 4) + _binary(right, 4)),
                       hosts.bit_list(_binary(left + right, 5)))
    _promote(lib, ripple, ((kernel.FnRef("full_adder"), 4),), request,
             rows=ripple_rows, scope_size=512)

    adder_body = deep.call("ripple", deep.lit(kernel.FnRef("full_adder")), deep.lit(8))
    _promote(lib, definition("adder8_graph", "operation", adder_body, lib), ((),),
             replace(exhaustive((), "the one 8-bit adder graph"),
                     reference=lambda: lib.run("ripple", (kernel.FnRef("full_adder"), 8)).outcome.value))
    adder = definition("Adder8", "object", adder_body, lib)
    adder_rows = tuple(Card("bits", "list", tuple((left >> index) & 1 for index in range(8)) +
                             tuple((right >> index) & 1 for index in range(8)))
                       for left, right in (*product(range(16), repeat=2), (200, 100), (255, 1)))
    _promote(lib, adder, ((),), oracle=(adder_rows, lambda bits: Card("bits", "list", tuple(
        ((sum(bits.fields[index] << index for index in range(8)) +
          sum(bits.fields[8 + index] << index for index in range(8))) >> index) & 1
        for index in range(9)))))


def _binary(number, width):
    return tuple((number >> index) & 1 for index in range(width))


def _as_integer(bits):
    return sum(bit << index for index, bit in enumerate(bits))


def _cut_sum(left, right):
    return ((left + right) & 15) + (((left >> 4) + (right >> 4)) << 4)


def advanced_definitions(lib):
    multiply = definition("multiply4", "operation", deep.multiply4_body(), lib)
    lib.write(multiply)
    multiply_rows = tuple(hosts.bit_list(_binary(left, 4) + _binary(right, 4))
                          for left in range(16) for right in range(16))
    _check_graph_operation(lib, "multiply4", multiply_rows,
        lambda bits: hosts.bit_list(_binary(_as_integer(bits.fields[:4]) *
                                             _as_integer(bits.fields[4:]), 8)),
        "bounded: all 256 ordered 4-bit input pairs of the 730-gate product")

    cut = definition("ripple_cut", "combinator", deep.ripple_body(cut=4), lib, ("f", "n"), ("f",))
    family = ("full_adder", "full_adder_copy")
    request = replace(bounded(((8,),),
                              "bounded: one 8-bit ripple width with carry cut at bit 4"),
                      scope={"domain": "bounded: one 8-bit ripple width with carry cut at bit 4",
                             "size": 1, "op_family": list(family)}, extra={"op_family": family})
    _promote(lib, cut, ((kernel.FnRef("full_adder"), 8),), request)
    cut8 = definition("cut_add8", "operation", deep.call("ripple_cut",
                      deep.lit(kernel.FnRef("full_adder")), deep.lit(8)), lib)
    lib.write(cut8)
    cut_rows = tuple(hosts.bit_list(_binary(left, 8) + _binary(right, 8))
                     for left, right in (*product(range(16), repeat=2), (200, 100), (255, 1)))
    _check_graph_operation(lib, "cut_add8", cut_rows, lambda bits: hosts.bit_list(
        _binary(_cut_sum(_as_integer(bits.fields[:8]), _as_integer(bits.fields[8:])), 9)),
        "bounded: three 8-bit pairs including the minimal cut-carry witness")

    swap = definition("multiply4_swap", "operation", deep.let((("swapped", deep.embed(
                      deep.call("multiply4"), deep.call("empty_circuit", deep.lit(8)),
                      deep.lit((4, 5, 6, 7, 0, 1, 2, 3)))),),
                      deep.call("with_outputs", deep.call("first", deep.var("swapped")),
                                deep.call("second", deep.var("swapped")))), lib)
    lib.write(swap)
    _check_graph_operation(lib, "multiply4_swap", multiply_rows,
        lambda bits: hosts.bit_list(_binary(_as_integer(bits.fields[:4]) *
                                             _as_integer(bits.fields[4:]), 8)),
        "bounded: all 256 ordered 4-bit input pairs with swapped wiring")

    first_diff = definition("first_diff", "observation", deep.first_diff_body(), lib)
    lib.write(first_diff)
    left, right = lib.run("adder8_graph", ()).outcome.value, lib.run("cut_add8", ()).outcome.value
    expected = Card("witness", "first", (1, 15, 16, 0))
    for x_value in range(2):
        for y_value in range(256 if x_value == 0 else 16):
            actual = x_value + y_value
            faulty = _cut_sum(x_value, y_value)
            if (x_value, y_value) == (1, 15):
                if (actual, faulty) != (16, 0):
                    raise AssertionError("incorrect first witness")
            elif actual != faulty:
                raise AssertionError("non-minimal witness")
    inputs, gates, outputs = hosts.deep_from_card(left)
    equivalent_left = hosts.deep_to_card(inputs,
        (*gates, Card("gate", "not", (0,))), outputs)
    rows = tuple(hosts.bit_list(_binary(x_value, 8) + _binary(y_value, 8))
                 for x_value, y_value in ((0, 0), (1, 15)))
    candidates = small_circuits()[:26]
    pairs = tuple((candidate, candidate) for candidate in candidates) + tuple(
        (candidate, candidates[-1]) for candidate in candidates[:-1])
    pairs += ((left, right), (equivalent_left, right))
    def witness(first, second):
        if hosts.deep_from_card(first)[0] == 16:
            return expected
        for number in range(4):
            bits = hosts.bit_list((number // 2, number % 2))
            before = hosts.deep_out(first, bits, 0)
            after = hosts.deep_out(second, bits, 0)
            if before != after:
                return Card("witness", "first", (number // 2, number % 2, before, after))
        return Card("witness", "none")
    _check_depth_observation(lib, "first_diff", pairs, rows, witness,
                             "bounded: 53 circuit pairs (51 two-input and 2 sixteen-input), full finite search per pair")

    equiv_body = deep.let((("equiv_left", deep.call("f")),
                           ("equiv_right", deep.call("g"))),
        deep.choose(deep.call("eq_int", deep.var("n"), deep.call("dag_inputs", deep.var("equiv_left"))),
            deep.choose(deep.call("eq_int", deep.var("n"),
                                  deep.call("dag_inputs", deep.var("equiv_right"))),
                deep.choose(deep.call("eq_witness", deep.call("first_diff",
                            deep.var("equiv_left"), deep.var("equiv_right")),
                            deep.lit(Card("witness", "none"))), deep.lit(1), deep.lit(0)),
                deep.call("tuple_tail", deep.lit(()))),
            deep.call("tuple_tail", deep.lit(()))))
    equiv = definition("equiv", "combinator", equiv_body, lib,
                       ("f", "g", "n"), ("f", "g"))
    sample = ((kernel.FnRef("or2"), kernel.FnRef("or2"), 2),)
    family = ("or2", "and2", "and_not_right", "not_left_and_right",
              "left2", "right2", "not_left2", "xor_graph")
    description = "bounded: all 64 ordered pairs from 8 two-input operations over all 4 input rows"
    request = replace(bounded(((2,),), description),
                      scope={"domain": description, "description": description,
                             "size": 1, "operation_cases": 64, "op_family": list(family)},
                      extra={"op_family": family},
                      reference=lambda assignment, inputs: int(all(
                          hosts.deep_out(lib.run(assignment["f"], ()).outcome.value, bits, 0) ==
                          hosts.deep_out(lib.run(assignment["g"], ()).outcome.value, bits, 0)
                          for bits in (hosts.bit_list(row) for row in product((0, 1), repeat=2)))))
    _promote(lib, equiv, sample, request, scope_size=64)


def invariant_laws(lib):
    """Check finite input domains against the promoted AND/NOT circuits."""
    lib.agent = "judge"
    graphs = {
        "xor_value": ("xor_graph", 1),
        "adder_value": ("ripple", 4),
        "mult_value": ("multiply4", 4),
    }
    for name, (graph_name, width) in graphs.items():
        graph_args = (kernel.FnRef("full_adder"), 4) if graph_name == "ripple" else ()
        graph = lib.run(graph_name, graph_args).outcome.value
        bits = deep.call("bit_list", deep.call("concat",
                         deep.call("bits_values", deep.bit_pattern(deep.var("a"), deep.lit(width))),
                         deep.call("bits_values", deep.bit_pattern(deep.var("b"), deep.lit(width)))))
        value = deep.bits_integer(deep.call("bits_values",
                                  deep.call("eval_bits", deep.lit(graph), bits)))
        spec = OperationSpec(name, "combine", (Edge("int", name="a"), Edge("int", name="b")),
                             Edge("int"), "Read output pins of the checked circuit.",
                             extra={"input_names": ["a", "b"]})
        depends = tuple(sorted(all_dependencies(Definition(name, "operation", "invented", 1,
                                                       (), spec, value))))
        entry = Definition(name, "operation", "invented",
                           compute_layer(depends, lambda key: lib.get(key).layer), depends, spec, value)
        _promote(lib, entry, ((0, 0),), replace(
            bounded(((0,), (0,)), "bounded: 1 zero operand pair"), reference=lambda a, b: 0))

    a, b = deep.var("a"), deep.var("b")
    for name, operation, domain, statement in (
        ("xor_comm", "xor_value", range(2), deep.call("eq",
            deep.call("xor_value", a, b), deep.call("xor_value", b, a))),
        ("adder_correct", "adder_value", range(16), deep.call("eq",
            deep.call("adder_value", a, b), deep.plus(a, b))),
        ("mult_comm", "mult_value", range(16), deep.call("eq",
            deep.call("mult_value", a, b), deep.call("mult_value", b, a))),
    ):
        spec = LawSpec(name, (("a", "int"), ("b", "int")), statement)
        depends = tuple(sorted(all_dependencies(Definition(name, "law", "invented", 1,
                                                       (), spec, statement))))
        entry = Definition(name, "law", "invented",
                           compute_layer(depends, lambda key: lib.get(key).layer),
                           depends, spec, statement)
        lib.write(entry)
        lib.check(name)
        lib.make_callable(name, ((0, 0),))
        lib.verify(name, bounded((domain, domain),
                   f"bounded: every ordered pair of {len(domain)}-value {operation} operands"))
        lib.account(name)
        lib.promote(name, Contract(f"For both operands in 0..{len(domain) - 1}"))
    lib.agent = "learner"


def build_depth_library(lib=None):
    fresh = lib is None
    lib = new_library() if fresh else lib
    lib._stable_world = lib.world
    lib.agent = "judge"
    try:
        if fresh:
            rows = basic_definitions(lib)
        else:
            rows = tuple(Card("bits", "list", (first, second))
                         for first in (0, 1) for second in (0, 1))
        adder_definitions(lib, rows)
        advanced_definitions(lib)
        invariant_laws(lib)
    finally:
        lib._stable_world = None
    return lib
