"""Replay the original x86 opacity loop against English and Chinese glyphs."""
import struct
import sys
from pathlib import Path

from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc, UcError
from unicorn.x86_const import (
    UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_EDX,
    UC_X86_REG_EDI, UC_X86_REG_ESI, UC_X86_REG_ESP, UC_X86_REG_EIP,
)

IMAGE_BASE = 0x400000
LOOP = 0x4B9955
EXIT = 0x4B99D0
FAULT = 0x4B999C
DATA = 0x700000


def replay(executable, label, glyph_indices):
    raw = Path(executable).read_bytes()
    pe, = struct.unpack_from("<I", raw, 0x3C)
    sections, = struct.unpack_from("<H", raw, pe + 6)
    optional_size, = struct.unpack_from("<H", raw, pe + 20)
    section_table = pe + 24 + optional_size

    cpu = Uc(UC_ARCH_X86, UC_MODE_32)
    cpu.mem_map(IMAGE_BASE, 0x300000)
    cpu.mem_map(DATA, 0x4000)
    for i in range(sections):
        _, rva, size, offset = struct.unpack_from("<IIII", raw, section_table + 40*i + 8)
        if size:
            cpu.mem_write(IMAGE_BASE + rva, raw[offset:offset+size])

    def write(address, value):
        cpu.mem_write(address, struct.pack("<I", value))

    sprite = DATA + 0x1000
    scene = DATA + 0x200
    form = DATA + 0x400
    frame = DATA + 0x2000
    cpu.mem_write(DATA, label)
    write(0x5F2674 + 16, DATA)
    write(0x5BF7B8, scene)
    write(scene, form)
    write(form + 0x2F8, form)
    write(form + 0x34, form)
    write(sprite + 0x90, sprite)
    write(sprite + 0x18, sprite)
    write(sprite + 0x1C, sprite)
    cpu.mem_write(frame + 8, struct.pack("<f", 0.5))
    cpu.reg_write(UC_X86_REG_EBX, 1)
    cpu.reg_write(UC_X86_REG_EDI, 1)
    cpu.reg_write(UC_X86_REG_ESI, len(label))
    cpu.reg_write(UC_X86_REG_ESP, frame - 0x80)
    cpu.reg_write(UC_X86_REG_EBP, frame)

    visited = []
    updated = []

    def mock_game_calls(cpu, pc, _size, _user):
        stack_bytes = 0
        if pc == 0x4B92C0:
            visited.append(cpu.reg_read(UC_X86_REG_EDX))
        elif pc == 0x47D680:
            cpu.reg_write(UC_X86_REG_EAX, sprite if visited[-1] in glyph_indices else 0)
        elif pc == 0x403BCC:
            pass
        elif pc == 0x472FC4:
            updated.append(visited[-1])
            stack_bytes = 4
        else:
            return
        sp = cpu.reg_read(UC_X86_REG_ESP)
        result, = struct.unpack("<I", cpu.mem_read(sp, 4))
        cpu.reg_write(UC_X86_REG_ESP, sp + 4 + stack_bytes)
        cpu.reg_write(UC_X86_REG_EIP, result)

    cpu.hook_add(UC_HOOK_CODE, mock_game_calls)
    try:
        cpu.emu_start(LOOP, EXIT, count=1500)
    except UcError:
        if cpu.reg_read(UC_X86_REG_EIP) != FAULT or cpu.reg_read(UC_X86_REG_EDX) != 0:
            raise
        return visited, updated, FAULT
    assert cpu.reg_read(UC_X86_REG_EIP) == EXIT
    return visited, updated, None


if __name__ == "__main__":
    old, fixed = sys.argv[1:]
    assert replay(old, b"a~05f~000 b", [1, 2, 6, 11]) == ([1, 2, 3], [1, 2], FAULT)
    for label, indices in (
        (b"inn keeper", [1, 2, 3, 5, 6, 7, 8, 9, 10]),
        (b"~0af", [1]),
        (b"a~05f~000 b", [1, 2, 6, 11]),
        (b" ~000 ~152 ", [2, 7]),
    ):
        assert replay(fixed, label, indices) == (indices, indices, None), label
    print("Previous EXE reproduces 004B999C; corrected x86 loop passes all four scenarios.")
