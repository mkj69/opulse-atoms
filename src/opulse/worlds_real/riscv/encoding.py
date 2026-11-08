"""RV32I instruction assembler: returns actual 32-bit little-endian instruction words."""

R = {"add": (0, 0), "sub": (0, 32), "sll": (1, 0),
     "slt": (2, 0), "sltu": (3, 0), "xor": (4, 0),
     "srl": (5, 0), "sra": (5, 32), "or": (6, 0), "and": (7, 0)}
I = {"addi": 0, "slti": 2, "sltiu": 3, "xori": 4, "ori": 6, "andi": 7}
SHIFT = {"slli": (1, 0), "srli": (5, 0), "srai": (5, 32)}
LOAD = {"lb": 0, "lh": 1, "lw": 2, "lbu": 4, "lhu": 5}
STORE = {"sb": 0, "sh": 1, "sw": 2}
BRANCH = {"beq": 0, "bne": 1, "blt": 4, "bge": 5, "bltu": 6, "bgeu": 7}


def _reg(reg: int) -> int:
    if type(reg) is not int or not 0 <= reg < 32:
        raise ValueError("register must be x0..x31")
    return reg


def _imm(imm: int, bits: int, alignment: int = 1) -> int:
    if type(imm) is not int or not -(1 << (bits - 1)) <= imm < 1 << (bits - 1) or imm % alignment:
        raise ValueError(f"immediate must be signed {bits}-bit and aligned to {alignment}")
    return imm & ((1 << bits) - 1)


def encode(name: str, rd: int = 0, rs1: int = 0, rs2: int = 0, imm: int = 0) -> int:
    """Assemble one supported instruction; branch/jump immediates are PC-relative bytes."""
    rd, rs1, rs2 = _reg(rd), _reg(rs1), _reg(rs2)
    if name in R:
        funct3, funct7 = R[name]
        return funct7 << 25 | rs2 << 20 | rs1 << 15 | funct3 << 12 | rd << 7 | 0x33
    if name in I or name in SHIFT:
        if name in SHIFT:
            funct3, funct7 = SHIFT[name]
            if not 0 <= imm < 32:
                raise ValueError("shift count must be 0..31")
            field = funct7 << 5 | imm
        else:
            funct3, field = I[name], _imm(imm, 12)
        return field << 20 | rs1 << 15 | funct3 << 12 | rd << 7 | 0x13
    if name in LOAD or name == "jalr":
        field = _imm(imm, 12)
        funct3, opcode = (LOAD[name], 3) if name in LOAD else (0, 0x67)
        return field << 20 | rs1 << 15 | funct3 << 12 | rd << 7 | opcode
    if name in STORE:
        field = _imm(imm, 12)
        return (field >> 5) << 25 | rs2 << 20 | rs1 << 15 | STORE[name] << 12 | (field & 31) << 7 | 0x23
    if name in BRANCH:
        field = _imm(imm, 13, 2)
        return ((field >> 12) & 1) << 31 | ((field >> 5) & 63) << 25 | rs2 << 20 | rs1 << 15 | BRANCH[name] << 12 | ((field >> 1) & 15) << 8 | ((field >> 11) & 1) << 7 | 0x63
    if name == "jal":
        field = _imm(imm, 21, 2)
        return ((field >> 20) & 1) << 31 | ((field >> 1) & 1023) << 21 | ((field >> 11) & 1) << 20 | ((field >> 12) & 255) << 12 | rd << 7 | 0x6f
    if name in ("lui", "auipc"):
        if type(imm) is not int or not 0 <= imm < 1 << 20:
            raise ValueError("upper immediate must be a 20-bit field")
        return imm << 12 | rd << 7 | (0x37 if name == "lui" else 0x17)
    raise ValueError(f"unsupported instruction: {name}")
