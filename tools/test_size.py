#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
test_size.py — проверка: справляется ли LK с распаковкой large payload.

Гипотеза: маленькие payload'ы (КБ) грузятся, а 8.39 МиБ (BootShim+FD) — нет.
Тест: тот же простой код (рисует 3 белые полосы), но раздутый нулями до
ровно 8 388 752 байт — как наш реальный kernel (BootShim + FD).

Если полосы появятся — LK с размером справляется, и проблема внутри UEFI.
Если нет — упёрлись в лимит декомпрессора/загрузчика.
"""

import argparse
import gzip
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mksmoke as M
import mkfbverify2 as V   # переиспользуем примитивы (rect/fill)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

TARGET = 8388752          # ровно как BootShim(144) + FD(0x800000)


def build_payload():
    g = V.Gen()
    g.emit(M.movz(0, M.FB_ADDR >> 16, sf=1, shift=16))      # x0 = 0x90000000
    # белый цвет в w2 (24bpp: 0xFF по трём байтам)
    g.emit(M.movz(2, 0xFFFF, sf=0, shift=0))
    g.emit(M.movk(2, 0xFFFF, sf=0, shift=16))

    for band in (1, 2, 3):
        # полоса: строки band*100 .. +50, во всю ширину (2160 байт), stride 2160
        off = band * 100 * 2160
        g.mov_imm(5, off)
        g.emit(V.add_x_reg(11, 0, 5))
        g.mov_imm(8, 50, sf=0)
        row = len(g.code)
        g.emit(M.mov_xd_xn(9, 11))
        g.mov_imm(7, 2160, sf=0)
        px = len(g.code)
        g.emit(M.str_wt_postinc(2, 11, 4))
        g.emit(M.subs_w_imm(7, 7, 1))
        g.emit(M.b_ne(px, len(g.code)))
        g.mov_imm(5, 2160)
        g.emit(V.add_x_reg(11, 9, 5))
        g.emit(M.subs_w_imm(8, 8, 1))
        g.emit(M.b_ne(row, len(g.code)))
    end = len(g.code)
    g.emit(M.b_uncond(end - 1, len(g.code)))

    body = b"".join(struct.pack("<I", w) for w in g.code)
    total = 64 + len(body)
    header = struct.pack("<IIQQQQQQII", M.b_uncond(16, 0), M.NOP,
                         0, TARGET, 0, 0, 0, 0, 0x644D5241, 0)
    img = header + body
    if len(img) > TARGET:
        sys.exit("payload больше цели")
    img += b"\x00" * (TARGET - len(img))
    return img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="build/test-size.img")
    ap.add_argument("--dtblock", default="build/ugg.dtblock")
    ap.add_argument("--size", type=int, default=TARGET)
    args = ap.parse_args()

    payload = build_payload()
    print("payload: %d байт (Image header 64 + код %d + нули)" % (len(payload), len(payload) - 64))
    kernel = gzip.compress(payload, 9)
    print("gzip   : %d байт" % len(kernel))
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
    print("ОЖИДАНИЕ: 3 белые горизонтальные полосы в верхней трети экрана.")
    print("  полосы есть -> LK тянет 8.39 МиБ, проблема внутри UEFI")
    print("  полос нет   -> LK режет размер; нужен другой способ загрузки")
    return 0


if __name__ == "__main__":
    sys.exit(main())
