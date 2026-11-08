"""Finite AND/NOT DAGs; all derived circuits expand into these two gates.

Inputs and outputs are LSB-first. The fixed domain is at most 16 inputs,
1024 gates, and 16 outputs. Equivalence is exhaustive only on this domain.
"""

from dataclasses import dataclass
from itertools import product
import json
from pathlib import Path


@dataclass(frozen=True)
class Circuit:
    inputs: int
    gates: tuple
    outputs: tuple

    def __post_init__(self):
        assert 0 <= self.inputs <= 16 and len(self.gates) <= 1024
        assert 1 <= len(self.outputs) <= 16
        for index, (kind, left, right) in enumerate(self.gates):
            assert kind in ("AND", "NOT")
            assert 0 <= left < self.inputs + index
            assert (right is None if kind == "NOT" else
                    isinstance(right, int) and 0 <= right < self.inputs + index)
        assert all(0 <= wire < self.inputs + len(self.gates) for wire in self.outputs)


class Builder:
    def __init__(self, inputs):
        assert 0 <= inputs <= 16
        self.inputs = inputs
        self.gates = []

    def and_gate(self, left, right):
        assert 0 <= left < self.inputs + len(self.gates)
        assert 0 <= right < self.inputs + len(self.gates)
        self.gates.append(("AND", left, right))
        return self.inputs + len(self.gates) - 1

    def not_gate(self, wire):
        assert 0 <= wire < self.inputs + len(self.gates)
        self.gates.append(("NOT", wire, None))
        return self.inputs + len(self.gates) - 1

    def embed(self, circuit, wires):
        assert len(wires) == circuit.inputs
        mapping = list(wires)
        for kind, left, right in circuit.gates:
            mapping.append(self.and_gate(mapping[left], mapping[right]) if kind == "AND"
                           else self.not_gate(mapping[left]))
        return tuple(mapping[wire] for wire in circuit.outputs)

    def finish(self, outputs):
        return Circuit(self.inputs, tuple(self.gates), tuple(outputs))


def eval_circuit(circuit, bits):
    assert len(bits) == circuit.inputs and all(bit in (0, 1) for bit in bits)
    wires = list(bits)
    for kind, left, right in circuit.gates:
        wires.append((wires[left] & wires[right]) if kind == "AND" else 1 - wires[left])
    return tuple(wires[wire] for wire in circuit.outputs)


def observe_out(circuit, bits, pin):
    assert isinstance(pin, int) and 0 <= pin < len(circuit.outputs)
    return eval_circuit(circuit, bits)[pin]


def compose(first, second):
    assert len(first.outputs) == second.inputs
    builder = Builder(first.inputs)
    wires = builder.embed(first, tuple(range(first.inputs)))
    return builder.finish(builder.embed(second, wires))


def and2():
    builder = Builder(2)
    return builder.finish((builder.and_gate(0, 1),))


def or_wire(builder, left, right):
    return builder.not_gate(builder.and_gate(builder.not_gate(left), builder.not_gate(right)))


def or2():
    builder = Builder(2)
    return builder.finish((or_wire(builder, 0, 1),))


def pair(left_factory, right_factory, arity):
    left, right = left_factory(), right_factory()
    assert left.inputs == right.inputs == arity
    builder = Builder(arity)
    wires = tuple(range(arity))
    return builder.finish(builder.embed(left, wires) + builder.embed(right, wires))


def and_not_right():
    builder = Builder(2)
    return builder.finish((builder.and_gate(0, builder.not_gate(1)),))


def not_left_and_right():
    builder = Builder(2)
    return builder.finish((builder.and_gate(builder.not_gate(0), 1),))


def xor():
    return compose(pair(and_not_right, not_left_and_right, 2), or2())


Xor = xor()


def table(circuit):
    assert circuit.inputs <= 16
    return tuple(eval_circuit(circuit, bits) for bits in product((0, 1), repeat=circuit.inputs))


def full_adder():
    builder = Builder(3)
    xor_gate = xor()
    partial = builder.embed(xor_gate, (0, 1))[0]
    result = builder.embed(xor_gate, (partial, 2))[0]
    carry = or_wire(builder, builder.and_gate(0, 1), builder.and_gate(partial, 2))
    return builder.finish((result, carry))


def ripple(full_adder_factory, width, cut=None):
    assert 1 <= width <= 8 and (cut is None or 1 <= cut < width)
    builder = Builder(2 * width)
    adder = full_adder_factory()
    zero = builder.and_gate(0, builder.not_gate(0))
    carry = zero
    sums = []
    for index in range(width):
        if index == cut:
            carry = zero
        result, carry = builder.embed(adder, (index, width + index, carry))
        sums.append(result)
    return builder.finish((*sums, carry))


Adder8 = ripple(full_adder, 8)


def cut_add8():
    return ripple(full_adder, 8, cut=4)


def multiply4():
    builder = Builder(8)
    zero = builder.and_gate(0, builder.not_gate(0))
    accumulator = (zero,) * 8
    adder = Adder8
    for shift in range(4):
        row = tuple(zero if index < shift or index >= shift + 4 else
                    builder.and_gate(index - shift, 4 + shift) for index in range(8))
        accumulator = builder.embed(adder, accumulator + row)[:8]
    return builder.finish(accumulator)


def multiply4_swap():
    builder = Builder(8)
    swapped = tuple(range(4, 8)) + tuple(range(4))
    return builder.finish(builder.embed(multiply4(), swapped))


def to_bits(number, width):
    assert 0 <= number < 1 << width
    return tuple((number >> index) & 1 for index in range(width))


def to_int(bits):
    return sum(bit << index for index, bit in enumerate(bits))


def first_diff(first, second):
    assert first.inputs == second.inputs and len(first.outputs) == len(second.outputs)
    assert first.inputs <= 16 and first.inputs % 2 == 0
    half = first.inputs // 2
    for left in range(1 << half):
        for right in range(1 << half):
            bits = to_bits(left, half) + to_bits(right, half)
            before = to_int(eval_circuit(first, bits))
            after = to_int(eval_circuit(second, bits))
            if before != after:
                return left, right, before, after
    return None


def equiv(first_factory, second_factory, arity):
    first, second = first_factory(), second_factory()
    assert first.inputs == second.inputs == arity
    return int(first_diff(first, second) is None)


def compute_showcase():
    product_bits = eval_circuit(multiply4(), to_bits(13, 4) + to_bits(11, 4))
    product_value = to_int(product_bits)
    sum_bits = eval_circuit(Adder8, product_bits + to_bits(91, 8))
    return product_value, to_int(sum_bits[:8]), sum_bits[8]


def invert_showcase():
    circuit = multiply4()
    return tuple((left, right) for left in range(16) for right in range(16)
                 if to_int(eval_circuit(circuit, to_bits(left, 4) + to_bits(right, 4))) == 90)


def decide_showcase():
    return equiv(multiply4, multiply4_swap, 8), first_diff(Adder8, cut_add8())


def verify():
    assert len(Xor.gates) == 8 and len(Adder8.gates) <= 1024
    assert len(multiply4().gates) <= 1024
    assert all(gate[0] in ("AND", "NOT") for circuit in
               (Xor, full_adder(), Adder8, cut_add8(), multiply4(), multiply4_swap())
               for gate in circuit.gates)
    assert table(Xor) == ((0,), (1,), (1,), (0,))
    assert all(to_int(eval_circuit(Adder8, to_bits(left, 8) + to_bits(right, 8)))
               == left + right for left in range(256) for right in range(256))
    assert all(to_int(eval_circuit(multiply4(), to_bits(left, 4) + to_bits(right, 4)))
               == left * right for left in range(16) for right in range(16))

    examples = {
        "?out{or2(),Bits<0,1>,0}": 1,
        "?out{@pair[and2,or2](2),Bits<1,0>,1}": 1,
        "?out{Xor,Bits<1,0>,0}": 1,
        "?table{Xor}": "List<0,1,1,0>",
        "?out{full_adder(),Bits<1,1,1>,1}": 1,
        "?out{@ripple[full_adder](4),Bits<1,1,0,1,1,0,1,0>,4}": 1,
        "?out{Adder8,Bits<0,0,0,1,0,0,1,1,0,0,1,0,0,1,1,0>,8}": 1,
        "?out{multiply4(),Bits<1,0,1,1,1,1,0,1>,7}": 1,
        "?first_diff{Adder8,cut_add8()}": "Witness<1,15,16,0>",
        "@equiv[multiply4,multiply4_swap](8)": 1,
    }
    computed = (
        observe_out(or2(), (0, 1), 0),
        observe_out(pair(and2, or2, 2), (1, 0), 1),
        observe_out(Xor, (1, 0), 0),
        "List<" + ",".join(str(row[0]) for row in table(Xor)) + ">",
        observe_out(full_adder(), (1, 1, 1), 1),
        observe_out(ripple(full_adder, 4), to_bits(13, 4) + to_bits(5, 4), 4),
        observe_out(Adder8, to_bits(200, 8) + to_bits(100, 8), 8),
        observe_out(multiply4(), to_bits(13, 4) + to_bits(11, 4), 7),
        "Witness<" + ",".join(map(str, first_diff(Adder8, cut_add8()))) + ">",
        equiv(multiply4, multiply4_swap, 8),
    )
    assert dict(zip(examples, computed)) == examples
    assert compute_showcase() == (143, 234, 0)
    assert invert_showcase() == ((6, 15), (9, 10), (10, 9), (15, 6))
    assert decide_showcase() == (1, (1, 15, 16, 0))

    catalog = json.loads(Path(__file__).with_suffix(".json").read_text(encoding="utf-8"))
    assert catalog["id"] == "circuits" and len(catalog["tower"]) == len(examples)
    assert [item["kind"] for item in catalog["tower"]].count("object") >= 2
    assert [item["kind"] for item in catalog["tower"]].count("observation") >= 2
    assert [item["kind"] for item in catalog["tower"]].count("combinator") >= 2
    assert [item["kind"] for item in catalog["tower"]].count("operation") >= 2
    for index, item in enumerate(catalog["tower"], start=1):
        assert item["layer"] == index
        assert item["example"] in examples and item["value"] == examples[item["example"]]
        assert item["value"] == computed[index - 1]
    showcase_answers = (
        "Result<" + ",".join(map(str, compute_showcase())) + ">",
        "List<" + ",".join("Pair<%s,%s>" % pair_value for pair_value in invert_showcase()) + ">",
        "Result<%s,Witness<%s>>" % (decide_showcase()[0],
                                     ",".join(map(str, decide_showcase()[1]))),
    )
    for item, answer in zip(catalog["showcase"], showcase_answers):
        assert item["answer"] == answer
    assert len(catalog["showcase"]) == 3 and len(catalog["ladder"]) == 5


if __name__ == "__main__":
    verify()
    print("OK")
