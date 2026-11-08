"""Optional independent GNU assembler comparison (no toolchain required in CI)."""

import shutil
import subprocess

import pytest

from opulse.worlds_real.riscv import encode


def test_gnu_as_real_encoding(tmp_path):
    assembler = shutil.which("riscv64-unknown-elf-as") or shutil.which("riscv32-unknown-elf-as")
    objcopy = shutil.which("riscv64-unknown-elf-objcopy") or shutil.which("riscv32-unknown-elf-objcopy")
    if not assembler or not objcopy:
        pytest.skip("no RISC-V GNU assembler plus objcopy installed")
    source = tmp_path / "instructions.s"
    object_file = tmp_path / "instructions.o"
    binary = tmp_path / "instructions.bin"
    source.write_text(".text\n.option norvc\naddi x1,x0,1\nadd x3,x1,x2\n"
                      "sub x3,x1,x2\nlw x1,8(x2)\nsw x1,8(x2)\njalr x0,0(x1)\n")
    subprocess.run([assembler, "-march=rv32i", "-mabi=ilp32", "-o", str(object_file), str(source)], check=True)
    subprocess.run([objcopy, "-O", "binary", "--only-section=.text", str(object_file), str(binary)], check=True)
    expected = [encode("addi", rd=1, imm=1), encode("add", rd=3, rs1=1, rs2=2),
                encode("sub", rd=3, rs1=1, rs2=2), encode("lw", rd=1, rs1=2, imm=8),
                encode("sw", rs1=2, rs2=1, imm=8), encode("jalr", rs1=1)]
    assert binary.read_bytes() == b"".join(word.to_bytes(4, "little") for word in expected)
