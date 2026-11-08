# RV32I atoms-v2 world

Real, little-endian, 32-bit RISC-V instructions, not a toy computer. `encoding.py`
assembles supported RV32I instructions; `machine.py` decodes and executes them
from **unified**, byte-addressed memory (stores can change future instructions).
`oracle.py` independently decodes bit strings; the test-side cross-check compares
every register, byte, PC, trap and executed trace. The 3,000 seeded single-instruction oracle cases
cover every supported mnemonic plus PC-relative edge offsets, signed arithmetic,
misalignment and register zero. A multi-step call/return comparison and known
instruction words are tested separately; if GNU RISC-V binutils are installed,
the test suite also compares emitted assembler bytes against ours.

Supported: LUI, AUIPC, JAL, JALR, six branches, LB/LH/LW/LBU/LHU,
SB/SH/SW, ADDI/SLTI/SLTIU/XORI/ORI/ANDI, SLLI/SRLI/SRAI,
ADD/SUB/SLL/SLT/SLTU/XOR/SRL/SRA/OR/AND. Encodings outside this
subset (including system, fence, CSR, compressed, atomics, multiply/divide)
trap as `illegal_instruction`; no privileged-mode emulation is claimed.
Instruction fetch and control transfers require 4-byte alignment. Data
misalignment traps; the chosen execution environment is bounded 64 KiB RAM,
zero-initialized, and out-of-range addresses trap. Architecture registers and
PC wrap at 32 bits. `run` stops **before** executing its explicit `stop_pc`;
fuel exhaustion is a trap, not normal termination. Each trace event is
`(pc, instruction_word, next_pc)`; there is no implicit halt opcode.

`declaration.py` supplies the core `opulse.world/2` schema, ASCII four-kind
layer-0 descriptions and eleven structured, written definition records at
kernel layer 1 (their separate curriculum stages do not assert verification),
five curriculum levels and world tags. `showcase.py` supplies five
oracle-graded tasks. Create is a **finite contract**, not universal program
equivalence: it checks 36 explicit byte arrays with programs of at most 256
words (ending before input at `0x400`), returns a signed-byte sum,
compares the final PC, all 32 registers and all RAM outside the candidate and
reference code region (the entire candidate-side code region must remain unchanged).
Instruction traces and initial code bytes are intentionally excluded: distinct
correct programs need not have identical traces or encodings. The grader uses
the independent oracle for both reference and candidate on every supplied case;
it does not certify arbitrary inputs. The assembly-style
`assemble` helper resolves byte-offset labels into actual instruction words.

Run: `PYTHONPATH=src python -m pytest -q tests/worlds_real/riscv`.

Semantics and encoding reference: *RISC-V Unprivileged ISA Specification*,
RV32I Base Integer Instruction Set, instruction formats and register table;
*RISC-V ELF psABI*, integer register convention. The independent decoder and
published-format fixtures are used when no external toolchain is available.
