"""Layer-zero typed Boolean gates, wiring, and circuit evaluation."""

from functools import lru_cache

from opulse.atoms.values import Bottom, Card


def bit_valid(value):
    return type(value) is int and value in (0, 1)


def deep_bits_valid(value):
    return (isinstance(value, Card) and value.sort == "bits" and value.tag == "list"
            and len(value.fields) <= 16 and all(bit_valid(bit) for bit in value.fields))


def circuit_valid(value):
    return deep_inspect(value) is None


def deep_inspect(value):
    if not isinstance(value, Card):
        return "invalid"
    try:
        return _deep_inspect_cached(value)
    except (TypeError, RecursionError):
        return "invalid"


@lru_cache(maxsize=4096)
def _deep_inspect_cached(value):
    if not isinstance(value, Card) or (value.sort, value.tag) != ("circuit", "dag") or len(value.fields) != 3:
        return "invalid"
    inputs, gates, outputs = value.fields
    if (type(inputs) is not int or inputs < 0 or inputs > 16
            or not isinstance(gates, Card) or (gates.sort, gates.tag) != ("gates", "list")
            or not isinstance(outputs, Card) or (outputs.sort, outputs.tag) != ("ports", "list")):
        return "invalid"
    if len(gates.fields) > 1024:
        return "size"
    if not 1 <= len(outputs.fields) <= 16:
        return "invalid"
    for index, gate in enumerate(gates.fields):
        if not isinstance(gate, Card) or gate.sort != "gate" or gate.tag not in ("and", "not"):
            return "invalid"
        if len(gate.fields) != (2 if gate.tag == "and" else 1):
            return "invalid"
        if any(type(source) is not int or source < 0 for source in gate.fields):
            return "invalid"
        if any(source >= inputs + index for source in gate.fields):
            return "cycle"
    if any(type(port) is not int or port < 0 or port >= inputs + len(gates.fields)
           for port in outputs.fields):
        return "cycle"
    return None


def deep_to_card(inputs, gates, outputs):
    try:
        circuit = Card("circuit", "dag", (inputs, Card("gates", "list", tuple(gates)),
                                             Card("ports", "list", tuple(outputs))))
    except (TypeError, ValueError):
        return Bottom("invalid")
    reason = deep_inspect(circuit)
    if reason is not None:
        return Bottom(reason)
    return circuit


def deep_from_card(circuit):
    reason = deep_inspect(circuit)
    if reason is not None:
        return Bottom("invalid")
    inputs, gates, outputs = circuit.fields
    return inputs, gates.fields, outputs.fields


def deep_and_gate(circuit, left, right):
    parts = deep_from_card(circuit)
    if isinstance(parts, Bottom):
        return parts
    inputs, gates, _ = parts
    if len(gates) >= 1024:
        return Bottom("size")
    if any(type(wire) is not int or wire < 0 for wire in (left, right)):
        return Bottom("invalid")
    if left >= inputs + len(gates) or right >= inputs + len(gates):
        return Bottom("cycle")
    return Card("circuit", "dag", (inputs,
        Card("gates", "list", (*gates, Card("gate", "and", (left, right)))),
        circuit.fields[2]))


def deep_not_gate(circuit, source):
    parts = deep_from_card(circuit)
    if isinstance(parts, Bottom):
        return parts
    inputs, gates, _ = parts
    if len(gates) >= 1024:
        return Bottom("size")
    if type(source) is not int or source < 0:
        return Bottom("invalid")
    if source >= inputs + len(gates):
        return Bottom("cycle")
    return Card("circuit", "dag", (inputs,
        Card("gates", "list", (*gates, Card("gate", "not", (source,)))),
        circuit.fields[2]))


def deep_and2():
    return deep_to_card(2, (Card("gate", "and", (0, 1)),), (2,))


def deep_eval(circuit, bits):
    if not deep_bits_valid(bits):
        return Bottom("invalid")
    try:
        return _deep_eval_cached(circuit, bits)
    except TypeError:
        return Bottom("invalid")


@lru_cache(maxsize=4096)
def _deep_eval_cached(circuit, bits):
    reason = deep_inspect(circuit)
    if reason is not None:
        return Bottom(reason)
    inputs, gates, outputs = deep_from_card(circuit)
    if len(bits.fields) != inputs:
        return Bottom("arity")
    wires = list(bits.fields)
    for gate in gates:
        wires.append(wires[gate.fields[0]] & wires[gate.fields[1]] if gate.tag == "and"
                     else 1 - wires[gate.fields[0]])
    return Card("bits", "list", tuple(wires[wire] for wire in outputs))


def deep_out(circuit, bits, pin):
    if type(pin) is not int:
        return Bottom("invalid")
    result = deep_eval(circuit, bits)
    if isinstance(result, Bottom):
        return result
    return result.fields[pin] if 0 <= pin < len(result.fields) else Bottom("port")


def empty_circuit(inputs):
    if type(inputs) is not int or not 1 <= inputs <= 16:
        return Bottom("size")
    return deep_to_card(inputs, (), (0,))


def with_outputs(circuit, outputs):
    parts = deep_from_card(circuit)
    if isinstance(parts, Bottom):
        return parts
    inputs, gates, _ = parts
    return deep_to_card(inputs, gates, outputs)


def dag_inputs(circuit):
    reason = deep_inspect(circuit)
    return Bottom(reason) if reason else circuit.fields[0]


def dag_gates(circuit):
    reason = deep_inspect(circuit)
    return Bottom(reason) if reason else circuit.fields[1].fields


def dag_outputs(circuit):
    reason = deep_inspect(circuit)
    return Bottom(reason) if reason else circuit.fields[2].fields


def gate_kind(gate):
    return gate.tag if _valid_gate(gate) else Bottom("invalid")


def gate_wires(gate):
    return gate.fields if _valid_gate(gate) else Bottom("invalid")


def _valid_gate(gate):
    return (isinstance(gate, Card) and gate.sort == "gate" and gate.tag in ("and", "not")
            and len(gate.fields) == (2 if gate.tag == "and" else 1)
            and all(type(wire) is int and wire >= 0 for wire in gate.fields))


def get(items, index):
    if (not isinstance(items, tuple) or type(index) is not int
            or not 0 <= index < len(items)):
        return Bottom("index")
    return items[index]


def get_gate(items, index):
    return get(items, index)


def append(items, value):
    return (*items, value) if isinstance(items, tuple) else Bottom("invalid")


def concat(first, second):
    return first + second if isinstance(first, tuple) and isinstance(second, tuple) else Bottom("invalid")


def tuple_len(items):
    return len(items) if isinstance(items, tuple) else Bottom("invalid")


def tuple_tail(items):
    return items[1:] if isinstance(items, tuple) and items else Bottom("index")


def first(items):
    return get(items, 0)


def second(items):
    return get(items, 1)


def pair(first_value, second_value):
    return first_value, second_value


def pair_int(first_value, second_value):
    return first_value, second_value


def integer_add(first_value, second_value):
    return first_value + second_value


def integer_sub(first_value, second_value):
    return first_value - second_value


def integer_lt(first_value, second_value):
    return first_value < second_value


def structural_eq(first_value, second_value):
    return first_value == second_value


def integer_div(first_value, second_value):
    return first_value // second_value if second_value else Bottom("zero")


def integer_mod(first_value, second_value):
    return first_value % second_value if second_value else Bottom("zero")


def integer_pow2(exponent):
    return 1 << exponent if type(exponent) is int and 0 <= exponent <= 16 else Bottom("size")


def integer_times(first_value, second_value):
    return first_value * second_value


def bit_list(items):
    result = Card("bits", "list", items)
    return result if deep_bits_valid(result) else Bottom("invalid")


def bits_values(bits):
    return bits.fields if deep_bits_valid(bits) else Bottom("invalid")


def witness(first_value, second_value, before, after):
    return Card("witness", "first", (first_value, second_value, before, after))
