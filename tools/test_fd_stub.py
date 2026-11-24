#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
test_fd_stub.py — доходит ли управление до содержимого UEFI FD?

Схема реального образа: kernel = gzip(BootShim.bin + FD) + DT-блок,
BootShim копирует 8 МиБ на 0x8EA00000 и прыгает туда.

FD[0] — ветвление на `_ModuleEntryPoint` PrePi. Здесь мы подменяем это
ветвление на свой стаб (кладём его в свободную область FD 0x400000), который:

   1) рисует белую полосу №8 (доказательство, что управление дошло до FD),
   2) прыгает на ОРИГИНАЛЬНЫЙ адрес входа PrePi.

Дальше PrePi сам красит свои стадии (1..5) — они уже вшиты paint_stages.py.

Итог на экране:
   полоса 8 + стадии 1..5 -> всё работает, проблема в DXE/драйвере
   только полоса 8         -> PrePi падает в прологе (_ModuleEntryPoint)
   полос нет               -> BootShim не доводит до FD (копирование/кеши)
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

UEFI_BASE = 0x8EA00000
UEFI_SIZE = 0x00800000
STUB_OFF = 0x400000          # свободная (0xFF) область FD
BAND = 8


def decode_b(img, off):
    w = struct.unpack("<I", img[off:off + 4])[0]
    if (w >> 26) != 0x05:
        return None
    imm = w & 0x03FFFFFF
    if imm & 0x02000000:
        imm -= 0x04000000
    return off + imm * 4


def emit_stub(target_off):
    code = []

    def emit(w):
        code.append(w & 0xFFFFFFFF)

    def mov_imm(rd, value, sf=1):
        emit(M.movz(rd, value & 0xFFFF, sf=sf, shift=0))
        if (value >> 16) & 0xFFFF:
            emit(M.movk(rd, (value >> 16) & 0xFFFF, sf=sf, shift=16))

    def add_x_reg(rd, rn, rm):
        return 0x8B000000 | ((rm & 0x1F) << 16) | ((rn & 0x1F) << 5) | (rd & 0x1F)

    # x11 = framebuffer (0x90000000 - 256), x0 не трогаем (там FDT!)
    emit(M.movz(11, (M.FB_ADDR - 256) >> 16, sf=1, shift=16))
    emit(M.movk(11, (M.FB_ADDR - 256) & 0xFFFF, sf=1, shift=0))
    # w2 = белый (24bpp)
    emit(M.movz(2, 0xFFFF, sf=0, shift=0))
    emit(M.movk(2, 0xFFFF, sf=0, shift=16))

    off = BAND * 100 * 2160
    mov_imm(5, off)
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

    # b <original entry>: считаем смещение от текущей инструкции
    here = STUB_OFF + len(code) * 4
    delta = target_off - here
    assert delta % 4 == 0
    emit(M.b_uncond(here // 4 + delta // 4, here // 4))
    return b"".join(struct.pack("<I", w) for w in code)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fd", default="build/ugg-art4/workspace/Build/ugg/RELEASE_GCC5/FV/MSM8937_UEFI.fd")
    ap.add_argument("--boot-img", default="build/boot-ugg.img")
    ap.add_argument("--dtblock", default="build/ugg.dtblock")
    ap.add_argument("--out", default="build/test-fd-stub.img")
    args = ap.parse_args()

    fd = bytearray(open(args.fd, "rb").read())
    print("FD: %d байт" % len(fd))

    target = decode_b(fd, 0)
    if target is None:
        sys.exit("FD[0] — не ветвление; разбор невозможен")
    print("оригинальное ветвление: FD[0] -> 0x%x" % target)
    print("байты по цели: %s" % fd[target:target + 8].hex(" "))

    stub = emit_stub(target)
    print("стаб: %d байт, кладём по FD+0x%x, полоса №%d" % (len(stub), STUB_OFF, BAND))
    if len(stub) > 0x1000:
        sys.exit("стаб слишком велик")
    fd[STUB_OFF:STUB_OFF + len(stub)] = stub

    # FD[0] = b STUB_OFF
    imm26 = (STUB_OFF // 4) & 0x03FFFFFF
    fd[0:4] = struct.pack("<I", 0x14000000 | imm26)
    print("новое ветвление: FD[0] -> 0x%x (проверка: %d)" % (decode_b(fd, 0), STUB_OFF))

    # BootShim из готового образа
    d = open(args.boot_img, "rb").read()
    ks = struct.unpack("<I", d[8:12])[0]
    page = struct.unpack("<I", d[36:40])[0]
    z = zlib.decompressobj(16 + zlib.MAX_WBITS)
    payload = z.decompress(d[page:page + ks])
    shim = payload[:144]
    print("BootShim: %d байт (UEFI_BASE=0x%08x, UEFI_SIZE=0x%x)" % (
        len(shim), struct.unpack("<Q", shim[0x48:0x50])[0], struct.unpack("<Q", shim[0x50:0x58])[0]))

    body = shim + bytes(fd)
    assert len(body) == 144 + UEFI_SIZE, len(body)
    kernel = gzip.compress(body, 9)
    print("gzip: %d байт" % len(kernel))
    if os.path.exists(args.dtblock):
        kernel += open(args.dtblock, "rb").read()
        print("+ DT-блок %d байт" % os.path.getsize(args.dtblock))

    img = M.build_bootimg(kernel, b"", 0)
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    open(args.out, "wb").write(img)
    print("bootimg: %s (%d байт)" % (args.out, len(img)))
    print()
    print("ОЖИДАНИЕ:")
    print("  видны полоса №8 и стадии 1..5 -> PrePi работает, копать DXE")
    print("  только полоса №8             -> падение в прологе PrePi")
    print("  полос нет                    -> BootShim не доводит до FD")
    return 0


if __name__ == "__main__":
    sys.exit(main())
