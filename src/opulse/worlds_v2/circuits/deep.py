"""Kernel-node wiring templates; no invented circuit is evaluated by Python."""

from opulse.atoms import nodes as n
from opulse.atoms.values import Card


def lit(value):
    return n.Lit(value)


def var(name):
    return n.Var(name)


def call(name, *args):
    return n.Call(name, args)


def xor_graph():
    return call("Xor.base", call("Xor.make", call("xor_graph")))


def adder8_graph():
    return call("Adder8.base", call("Adder8.make", call("adder8_graph")))


def let(bindings, result):
    for name, value in reversed(tuple(bindings)):
        result = n.Let(name, value, result)
    return result


def choose(condition, yes, no):
    return n.Case(((n.Test(condition), yes),), no)


def plus(left, right):
    return call("integer_add", left, right)


def minus(left, right):
    return call("integer_sub", left, right)


def at(items, index):
    return call("get", items, index)


def wires(count):
    index, result = var("wire_index"), var("wire_list")
    return n.Rec("wire_range", ("wire_index", "wire_list"),
                 choose(call("integer_lt", index, count),
                        call("wire_range", plus(index, lit(1)), call("append", result, index)), result),
                 (lit(0), lit(())), minus(count, index))


def embed(source, target, pins):
    """Copy a DAG gate-by-gate, remapping each input and earlier gate wire."""
    remaining, mapping, graph = var("remaining"), var("mapping"), var("graph")
    gate = var("gate")
    sources = var("sources")
    first = at(mapping, at(sources, lit(0)))
    next_graph = choose(call("eq_str", call("gate_kind", gate), lit("and")),
                        call("and_gate", graph, first, at(mapping, at(sources, lit(1)))),
                        call("not_gate", graph, first))
    step = let((("gate", call("get_gate", remaining, lit(0))), ("sources", call("gate_wires", gate)),
                ("next_graph", next_graph)),
               call("copy_gate", call("tuple_tail", remaining),
                    call("append", mapping, plus(call("dag_inputs", graph),
                                                 call("tuple_len", call("dag_gates", graph)))),
                    var("next_graph")))
    copied = n.Rec("copy_gate", ("remaining", "mapping", "graph"),
                   choose(call("integer_lt", lit(0), call("tuple_len", remaining)),
                          step, call("pair", graph, mapping)),
                   (call("dag_gates", var("source_graph")), var("pins"), var("target_graph")),
                   call("tuple_len", remaining))
    output, result = var("output_index"), var("result_ports")
    remapped = n.Rec("map_ports", ("output_index", "result_ports"),
                     choose(call("integer_lt", output, call("tuple_len", call("dag_outputs", var("source_graph")))),
                            call("map_ports", plus(output, lit(1)),
                                 call("append", result, at(call("second", var("copied")),
                                                            at(call("dag_outputs", var("source_graph")), output)))),
                            result),
                     (lit(0), lit(())),
                     minus(call("tuple_len", call("dag_outputs", var("source_graph"))), output))
    return let((("source_graph", source), ("target_graph", target), ("pins", pins)),
               choose(call("structural_eq", call("dag_inputs", var("source_graph")),
                      call("tuple_len", var("pins"))),
                      let((("copied", copied),), call("pair", call("first", var("copied")), remapped)),
                      call("tuple_tail", lit(()))))


def or_from(graph, left, right):
    return let((("or_first", call("not_gate", graph, left)),
                ("or_left", minus(plus(call("dag_inputs", var("or_first")),
                                        call("tuple_len", call("dag_gates", var("or_first")))), lit(1))),
                ("or_second", call("not_gate", var("or_first"), right)),
                ("or_right", minus(plus(call("dag_inputs", var("or_second")),
                                         call("tuple_len", call("dag_gates", var("or_second")))), lit(1))),
                ("or_both", call("and_gate", var("or_second"), var("or_left"), var("or_right"))),
                ("or_last", minus(plus(call("dag_inputs", var("or_both")),
                                        call("tuple_len", call("dag_gates", var("or_both")))), lit(1))),
                ("or_result", call("not_gate", var("or_both"), var("or_last")))),
               call("with_outputs", var("or_result"),
                    call("append", lit(()), minus(plus(call("dag_inputs", var("or_result")),
                                     call("tuple_len", call("dag_gates", var("or_result")))), lit(1)))))


def take_outputs(graph, outputs):
    return call("with_outputs", graph, outputs)


def end_wire(graph):
    return minus(plus(call("dag_inputs", graph), call("tuple_len", call("dag_gates", graph))), lit(1))


def compose_body():
    first_graph, second_graph = var("first_graph"), var("second_graph")
    result = let((("first_graph", call("f")), ("second_graph", call("g")),
                ("first_result", embed(first_graph, call("empty_circuit", call("dag_inputs", first_graph)),
                                       wires(call("dag_inputs", first_graph)))),
                ("second_result", embed(second_graph, call("first", var("first_result")),
                                        call("second", var("first_result"))))),
               call("with_outputs", call("first", var("second_result")),
                    call("second", var("second_result"))))
    return choose(call("structural_eq", var("n"), call("dag_inputs", call("f"))),
                  result, call("tuple_tail", lit(())))


def pair_body():
    first_graph, second_graph = var("first_graph"), var("second_graph")
    result = let((("first_graph", call("f")), ("second_graph", call("g")),
                ("first_result", embed(first_graph, call("empty_circuit", call("dag_inputs", first_graph)),
                                       wires(call("dag_inputs", first_graph)))),
                ("second_result", embed(second_graph, call("first", var("first_result")),
                                        wires(call("dag_inputs", first_graph))))),
               choose(call("structural_eq", call("dag_inputs", first_graph),
                           call("dag_inputs", second_graph)),
                      call("with_outputs", call("first", var("second_result")),
                           call("concat", call("second", var("first_result")),
                                call("second", var("second_result")))),
                      call("tuple_tail", lit(()))))
    return choose(call("structural_eq", var("n"), call("dag_inputs", call("f"))),
                  result, call("tuple_tail", lit(())))


def all_outputs(graph, bits):
    index, result = var("pin_index"), var("seen_outputs")
    return n.Rec("read_pin", ("pin_index", "seen_outputs"),
                 choose(call("integer_lt", index, call("tuple_len", call("dag_outputs", graph))),
                        call("read_pin", plus(index, lit(1)), call("append_bit", result,
                            call("out_pin", graph, bits, index))), result),
                 (lit(0), lit(())), minus(call("tuple_len", call("dag_outputs", graph)), index))


def bit_pattern(number, width):
    index, result = var("bit_index"), var("built_bits")
    return n.Rec("binary_digits", ("bit_index", "built_bits"),
                 choose(call("integer_lt", index, width),
                        call("binary_digits", plus(index, lit(1)),
                             call("append", result, call("integer_mod",
                                  call("integer_div", number, call("integer_pow2", index)), lit(2)))),
                        call("bit_list", result)),
                 (lit(0), lit(())), minus(width, index))


def bits_integer(bits):
    index, total = var("integer_index"), var("integer_total")
    return n.Rec("read_integer", ("integer_index", "integer_total"),
                 choose(call("integer_lt", index, call("tuple_len", bits)),
                        call("read_integer", plus(index, lit(1)),
                             plus(total, call("integer_times", at(bits, index), call("integer_pow2", index)))),
                        total),
                 (lit(0), lit(0)), minus(call("tuple_len", bits), index))


def full_adder_body():
    first_result = embed(xor_graph(), call("empty_circuit", lit(3)), lit((0, 1)))
    second_result = embed(xor_graph(), call("first", var("first_result")),
                          call("append", call("second", var("first_result")), lit(2)))
    first_part = call("and_gate", call("first", var("second_result")), lit(0), lit(1))
    second_part = call("and_gate", var("first_carry"),
                       at(call("second", var("first_result")), lit(0)), lit(2))
    return let((("first_result", first_result), ("second_result", second_result),
                ("first_carry", first_part), ("second_carry", second_part),
                ("carry_result", or_from(var("second_carry"),
                                          end_wire(var("first_carry")),
                                          end_wire(var("second_carry"))))),
               take_outputs(var("carry_result"), call("pair_int",
                   at(call("second", var("second_result")), lit(0)),
                   end_wire(var("carry_result")))))


def ripple_body(cut=None):
    index, graph, carry, sums = (var(name) for name in ("ripple_index", "ripple_graph",
                                                      "ripple_carry", "ripple_sums"))
    current_carry = choose(call("structural_eq", index, lit(cut)), var("zero_wire"), carry) if cut else carry
    pins = call("append", call("pair_int", index, plus(index, var("n"))), current_carry)
    next_result = embed(call("f"), graph, pins)
    step = let((("ripple_next", next_result),),
               call("run_ripple", plus(index, lit(1)), call("first", var("ripple_next")),
                    at(call("second", var("ripple_next")), lit(1)),
                    call("append", sums, at(call("second", var("ripple_next")), lit(0)))))
    loop = n.Rec("run_ripple", ("ripple_index", "ripple_graph", "ripple_carry", "ripple_sums"),
                 choose(call("integer_lt", index, var("n")), step,
                        take_outputs(graph, call("append", sums, carry))),
                 (lit(0), var("initial_graph"), var("zero_wire"), lit(())),
                 minus(var("n"), index))
    return let((("negative", call("not_gate", call("empty_circuit", plus(var("n"), var("n"))), lit(0))),
                ("initial_graph", call("and_gate", var("negative"), lit(0), end_wire(var("negative")))),
                ("zero_wire", end_wire(var("initial_graph")))),
               choose(call("eq_int", call("dag_inputs", call("f")),
                           call("dag_inputs", call("full_adder"))), loop,
                      call("tuple_tail", lit(()))))


def take(items, count):
    index, result = var("take_index"), var("take_result")
    return n.Rec("take_first", ("take_index", "take_result"),
                 choose(call("integer_lt", index, count),
                        call("take_first", plus(index, lit(1)), call("append", result, at(items, index))),
                 result), (lit(0), lit(())), minus(count, index))


def repeat(wire, count):
    index, result = var("repeat_index"), var("repeated")
    return n.Rec("repeat_zero", ("repeat_index", "repeated"),
                 choose(call("integer_lt", index, count),
                        call("repeat_zero", plus(index, lit(1)), call("append", result, wire)),
                        result), (lit(0), lit(())), minus(count, index))


def multiply4_body():
    shift, graph, accumulator = var("shift"), var("product_graph"), var("accumulator")
    index, row, growing = var("row_index"), var("row_wires"), var("row_graph")
    make_gate = let((("next_row", call("and_gate", growing, minus(index, shift), plus(lit(4), shift))),),
                    call("build_row", plus(index, lit(1)), var("next_row"),
                         call("append", row, end_wire(var("next_row")))))
    make_zero = call("build_row", plus(index, lit(1)), growing,
                     call("append", row, var("product_zero")))
    row_loop = n.Rec("build_row", ("row_index", "row_graph", "row_wires"),
                     choose(call("integer_lt", index, lit(8)),
                            choose(call("integer_lt", index, shift), make_zero,
                                   choose(call("integer_lt", index, plus(shift, lit(4))),
                                          make_gate, make_zero)),
                            call("pair", growing, row)),
                     (lit(0), graph, lit(())), minus(lit(8), index))
    stage = let((("partial_row", row_loop),
                 ("sum_graph", embed(adder8_graph(), call("first", var("partial_row")),
                                     call("concat", accumulator, call("second", var("partial_row")))))),
                call("accumulate", plus(shift, lit(1)), call("first", var("sum_graph")),
                     take(call("second", var("sum_graph")), lit(8))))
    loop = n.Rec("accumulate", ("shift", "product_graph", "accumulator"),
                 choose(call("integer_lt", shift, lit(4)), stage, take_outputs(graph, accumulator)),
                 (lit(0), var("product_start"), var("zeros")), minus(lit(4), shift))
    return let((("product_negative", call("not_gate", call("empty_circuit", lit(8)), lit(0))),
                ("product_start", call("and_gate", var("product_negative"), lit(0),
                                       end_wire(var("product_negative")))),
                ("product_zero", end_wire(var("product_start"))),
                ("zeros", repeat(var("product_zero"), lit(8)))), loop)


def first_diff_body():
    index = var("search_index")
    half = var("half_width")
    x_value, y_value = var("x_value"), var("y_value")
    row_bits = var("row_bits")
    first_outputs, second_outputs = var("first_outputs"), var("second_outputs")
    evaluate_pair = let((("x_value", call("integer_div", index, call("integer_pow2", half))),
                         ("y_value", call("integer_mod", index, call("integer_pow2", half))),
                         ("row_bits", call("bit_list", call("concat", call("bits_values", bit_pattern(x_value, half)),
                                                               call("bits_values", bit_pattern(y_value, half))))),
                         ("first_outputs", all_outputs(var("left"), row_bits)),
                         ("second_outputs", all_outputs(var("right"), row_bits))),
                        choose(call("eq_tuple", first_outputs, second_outputs),
                               call("scan_inputs", plus(index, lit(1))),
                               call("witness", x_value, y_value,
                                    bits_integer(first_outputs), bits_integer(second_outputs))))
    loop = n.Rec("scan_inputs", ("search_index",),
                 choose(call("integer_lt", index, call("integer_pow2", var("input_count"))),
                        evaluate_pair, lit(Card("witness", "none"))),
                 (lit(0),), minus(call("integer_pow2", var("input_count")), index))
    search = choose(call("eq_int", var("input_count"), lit(2)),
                    choose(call("eq_int", call("tuple_len", call("dag_outputs", var("left"))), lit(1)),
                           choose(call("eq_tuple", call("truth_table", var("left")),
                                       call("truth_table", var("right"))),
                                  lit(Card("witness", "none")), loop), loop), loop)
    return let((("input_count", call("dag_inputs", var("left"))),
                ("half_width", call("integer_div", var("input_count"), lit(2)))),
               choose(call("eq_int", var("input_count"), call("dag_inputs", var("right"))),
                      choose(call("eq_int", call("tuple_len", call("dag_outputs", var("left"))),
                                  call("tuple_len", call("dag_outputs", var("right")))),
                             search, call("tuple_tail", lit(()))),
                      call("tuple_tail", lit(()))))
