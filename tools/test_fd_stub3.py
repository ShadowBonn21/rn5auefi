#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
test_fd_stub3.py — обход пролога PrePi.

Стаб подменяет ветвление FD[0] и делает только необходимое:
   1) полоса №8 (доказательство, что стаб работает)
   2) sp = PcdPrePiStackBase + PcdPrePiStackSize (0x8F290000 + 0x40000)
   3) ветвление сразу на CEntryPoint, минуя _ModuleEntryPoint:
      (выключение кешей/MMU, заполнение векторов, SPAN, обнуление стека)

Адрес CEntryPoint берём из самой прошивки: находим `bl CEntryPoint`
(инструкция перед `b .` в конце пролога) и декодируем цель.

Трактовка:
   полоса 8 + стадии 1..5 -> виноват пролог PrePi (кеши/MMU/векторы/стек)
   только полоса 8          -> CEntryPoint/PrePiMain падает и сам по себе
"""

import argparse
import gzip
import os
import struct
import sys
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mksmoke as M

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

UEFI_SIZE = 0x00800000
STUB_OFF = 0x400000
STACK_BASE = 0x8F290000
STACK_SIZE = 0x00040000
FB = M.FB_ADDR - 256


def decode_b(img, off):
    w = struct.unpack("<I", img[off:off + 4])[0]
    if (w >> 26) != 0x05:
        return None
    imm = w & 0x03FFFFFF
    if imm & 0x02000000:
        imm -= 0x04000000
    return off + imm * 4


def decode_bl(img, off):
    w = struct.unpack("<I", img[off:off + 4])[0]
    if (w >> 26) != 0x25:          # BL: 100101
        return None
    imm = w & 0x03FFFFFF
    if imm & 0x02000000:
        imm -= 0x04000000
    return off + imm * 4


def find_centry(fd, entry_off, span=0x600):
    """Ищем `bl` перед `b .` — это вызов CEntryPoint в конце пролога."""
    for off in range(entry_off, min(entry_off + span, len(fd) - 8), 4):
        w = struct.unpack("<I", fd[off:off + 4])[0]
        if w == 0x14000000:                      # b . (метка dead)
            target = decode_bl(fd, off - 4)
            if target:
                return target, off - 4
    return None, None


def build_stub(target_entry):
    code = []

    def emit(w):
        code.append(w & 0xFFFFFFFF)

    def mov_imm(rd, value, sf=1):
        emit(M.movz(rd, value & 0xFFFF, sf=sf, shift=0))
        if (value >> 16) & 0xFFFF:
            emit(M.movk(rd, (value >> 16) & 0xFFFF, sf=sf, shift=16))

    def add_x_reg(rd, rn, rm):
        return 0x8B000000 | ((rm & 0x1F) << 16) | ((rn & 0x1F) << 5) | (rd & 0x1F)

    # полоса 8
    mov_imm(11, FB)
    emit(M.movz(2, 0xFFFF, sf=0, shift=0))
    emit(M.movk(2, 0xFFFF, sf=0, shift=16))
    mov_imm(5, 800 * 2160)
    emit(add_x_reg(11, 11, 5))
    mov_imm(8, 50, sf=0)
    row = len(code)
    emit(M.mov_xd_xn(9, 11))
    mov_imm(7, 2160, sf=0)
    px = len(code)
    emit(M.str_wt_postinc(2, 11, 4))
    emit(M.subs_w_imm(7, 7, 1))
    emit(M.b_ne(px, len(code)))
    mov_imm(5, 2160)
    emit(add_x_reg(11, 9, 5))
    emit(M.subs_w_imm(8, 8, 1))
    emit(M.b_ne(row, len(code)))

    # стек и переход на CEntryPoint
    mov_imm(13, STACK_BASE + STACK_SIZE)          # sp
    emit(0x910001BF)                              # mov sp, x13
    # x0/x1 = StackBase/StackSize (как ждёт CEntryPoint)
    mov_imm(0, STACK_BASE)
    mov_imm(1, STACK_SIZE)

    here = STUB_OFF + len(code) * 4
    delta = target_entry - here
    assert delta % 4 == 0, delta
    # bl CEntryPoint
    emit(0x94000000 | ((delta // 4) & 0x03FFFFFF))
    # на всякий случай: вечный цикл
    emit(M.b_uncond(len(code), len(code)))

    return b"".join(struct.pack("<I", w) for w in code)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fd", default="build/ugg-art4/workspace/Build/ugg/RELEASE_GCC5/FV/MSM8937_UEFI.fd")
    ap.add_argument("--boot-img", default="build/boot-ugg.img")
    ap.add_argument("--dtblock", default="build/ugg.dtblock")
    ap.add_argument("--out", default="build/test-fd-stub3.img")
    args = ap.parse_args()

    fd = bytearray(open(args.fd, "rb").read())
    entry = decode_b(fd, 0)
    print("FD[0] -> пролог PrePi 0x%x" % entry)

    centry, bl_off = find_centry(fd, entry)
    if centry is None:
        sys.exit("не нашёл вызов CEntryPoint в прологе")
    print("bl CEntryPoint @0x%x -> 0x%x" % (bl_off, centry))

    stub = build_stub(centry)
    print("стаб: %d байт по FD+0x%x" % (len(stub), STUB_OFF))
    fd[STUB_OFF:STUB_OFF + len(stub)] = stub
    fd[0:4] = struct.pack("<I", 0x14000000 | ((STUB_OFF // 4) & 0x03FFFFFF))

    d = open(args.boot_img, "rb").read()
    ks = struct.unpack("<I", d[8:12])[0]
    page = struct.unpack("<I", d[36:40])[0]
    z = zlib.decompressobj(16 + zlib.MAX_WBITS)
    shim = z.decompress(d[page:page + ks])[:144]

    kernel = gzip.compress(shim + bytes(fd), 9)
    if os.path.exists(args.dtblock):
        kernel += open(args.dtblock, "rb").read()
    img = M.build_bootimg(kernel, b"", 0)
    open(args.out, "wb").write(img)
    print("bootimg: %s (%d байт)" % (args.out, len(img)))
    print()
    print("СМОТРЕТЬ: полоса №8 (~800-850) и далее стадии PrePi 1..5 (верх).")
    print("  8 + 1..5 -> пролог PrePi виноват")
    print("  только 8 -> падение в CEntryPoint/PrePiMain/MemoryPeim")
    return 0


if __name__ == "__main__":
    sys.exit(main())
