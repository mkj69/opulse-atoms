"""vn/1 assembler tests (meta spec section 4.1)."""

import random

import pytest

from opulse.meta.vn.asm import assemble, disassemble


def test_labels_comments_and_data():
    source = "; setup\nloop: ADD 10 ; read\n ST @loop+1\n JZ @loop\n DB 7\n HALT\n"
    assert assemble(source, 16) == [4, 10, 3, 1, 7, 0, 7, 0, 0]
    assert assemble(disassemble(assemble(source, 16)), 16) == assemble(source, 16)


def test_round_trip_all_byte_values_and_odd_tails():
    rng = random.Random(319)
    for size in (16, 32, 64, 256):
        for _ in range(30):
            code = [rng.randrange(256) for _ in range(rng.randrange(size + 1))]
            assert assemble(disassemble(code), size) == code


@pytest.mark.parametrize("source, line", [("\nBAD 2", 2), ("LD @missing", 1),
                                          ("HALT 1", 1), ("ADD", 1), ("DB 256", 1),
                                          ("x: DB 1\nx: DB 2", 2), ("LDI -1", 1)])
def test_errors_report_source_line(source, line):
    with pytest.raises(ValueError, match=f"line {line}:"):
        assemble(source, 16)
