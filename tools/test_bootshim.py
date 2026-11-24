#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
test_bootshim.py — проверка BootShim отдельно от UEFI.

Логика ровно как в реальном образе:
    kernel = gzip( BootShim.bin + <payload> + нули до 8 МиБ ) + DT-блок

BootShim (144 байта, UEFI_BASE=0x8EA00000, UEFI_SIZE=0x800000) копирует
8 МиБ от _Payload на 0x8EA00000 и прыгает туда. _Payload — это наш тестовый
код, поэтому если после прыжка появятся белые полосы, значит BootShim
(копирование + переход) работает, и виноват уже сам FD/PrePi.

Если полос нет — проблема в BootShim (адрес, размер, выравнивание).
"""

import argparse
import gzip
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mksmoke as M

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

UEFI_BASE = 0x8EA00000
UEFI_SIZE = 0x00800000
BOOTSHIM_LEN = 144


def extract_bootshim(boot_img_path):
    d = open(boot_img_path, "rb").read()
    ks = struct.unpack("<I", d[8:12])[0]
    page = struct.unpack("<I", d[36:40])[0]
    import zlib
    z = zlib.decompressobj(16 + zlib.MAX_WBITS)
    payload = z.decompress(d[page:page + ks])
    shim = bytearray(payload[:BOOTSHIM_LEN])

    base = struct.unpack("<Q", shim[0x48:0x50])[0]
    size = struct.unpack("<Q", shim[0x50:0x58])[0]
    print("BootShim: UEFI_BASE=0x%08x  UEFI_SIZE=0x%x" % (base, size))
    if base != UEFI_BASE or size != UEFI_SIZE:
        print("  !! ожидалось 0x%08x / 0x%x" % (UEFI_BASE, UEFI_SIZE))
    return bytes(shim)


def paint_code():
    """Код: рисует 3 белые полосы (24bpp, stride 2160) и висит."""
    code = []

    def emit(w):
        code.append(w & 0xFFFFFFFF)

    def mov_imm(rd, value, sf=1):
        emit(M.movz(rd, value & 0xFFFF, sf=sf, shift=0))
        if (value >> 16) & 0xFFFF:
            emit(M.movk(rd, (value >> 16) & 0xFFFF, sf=sf, shift=16))

    def add_x_reg(rd, rn, rm):
        return 0x8B000000 | ((rm & 0x1F) << 16) | ((rn & 0x1F) << 5) | (rd & 0x1F)

    emit(M.movz(0, (M.FB_ADDR - 256) >> 16, sf=1, shift=16))
    emit(M.movk(0, (M.FB_ADDR - 256) & 0xFFFF, sf=1, shift=0))
    emit(M.movz(2, 0xFFFF, sf=0, shift=0))
    emit(M.movk(2, 0xFFFF, sf=0, shift=16))

    for band in (1, 2, 3):
        off = band * 100 * 2160
        mov_imm(5, off)
        emit(add_x_reg(11, 0, 5))
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
    end = len(code)
    emit(M.b_uncond(end - 1, len(code)))

    body = b"".join(struct.pack("<I", w) for w in code)
    return body


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--boot-img", default="build/boot-ugg.img", help="откуда взять BootShim.bin")
    ap.add_argument("--out", default="build/test-bootshim.img")
    ap.add_argument("--dtblock", default="build/ugg.dtblock")
    args = ap.parse_args()

    shim = extract_bootshim(args.boot_img)
    stub = paint_code()
    print("тестовый код: %d байт (ляжет сразу за BootShim, на 0x%08x)" % (len(stub), UEFI_BASE))

    body = shim + stub
    body += b"\x00" * (UEFI_SIZE - len(body))      # ровно 8 МиБ, как реальный FD
    print("полезная нагрузка: %d байт (8 МиБ)" % len(body))

    kernel = gzip.compress(body, 9)
    print("gzip: %d байт" % len(kernel))
    if os.path.exists(args.dtblock):
        with open(args.dtblock, "rb") as f:
            kernel += f.read()
        print("+ DT-блок %d байт" % os.path.getsize(args.dtblock))

    img = M.build_bootimg(kernel, b"", 0)
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "wb") as f:
        f.write(img)
    print("bootimg: %s (%d байт)" % (args.out, len(img)))
    print()
    print("ОЖИДАНИЕ: 3 белые полосы (значит BootShim копирует и передаёт управление).")
    print("  полосы есть -> виноват сам FD/PrePi")
    print("  полос нет   -> виноват BootShim (адрес/размер/ветвление)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
