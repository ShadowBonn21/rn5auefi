#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
mkfbverify2.py — проверка гипотезы «MDSS показывает окно со сдвигом».

Измерения по фото показали: экран = buffer_x + 72, причём buffer_x = 600 уже
не виден (окно шириной 576 = 720 - 2*72, как отцентрованный логотип LK).

Здесь всё рисуется с учётом этого:
  * рамка по краям ВИДИМОГО окна: buffer x = 72..75 и 644..647;
  * маркеры в углах окна;
  * сетка внутри окна (шаг 120): 192, 312, 432, 552;
  * горизонтальные линии как раньше (160..1120), крест в центре окна.

Если гипотеза верна — на экране будет ровная рамка ВПЛОТНУЮ ко всем краям
панели, и все линии встанут на свои места.

Если рамка окажется сдвинутой — значит сдвиг не 72, и мы уточним его по фото
(tools/measure_panel.py).
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

W, H = 720, 1280
STRIDE = 2160
REGION = 0x00800000
XOFF = 72                 # сдвиг, измеренный по фото
VIS = W - 2 * XOFF        # 576 — видимая ширина


def add_x_reg(rd, rn, rm):
    return 0x8B000000 | ((rm & 0x1F) << 16) | ((rn & 0x1F) << 5) | (rd & 0x1F)


def strb_imm(rt, rn, imm12):
    return 0x39000000 | ((imm12 & 0xFFF) << 10) | ((rn & 0x1F) << 5) | (rt & 0x1F)


def add_x_imm(rd, rn, imm12):
    return 0x91000000 | ((imm12 & 0xFFF) << 10) | ((rn & 0x1F) << 5) | (rd & 0x1F)


class Gen:
    def __init__(self):
        self.code = []

    def emit(self, w):
        self.code.append(w & 0xFFFFFFFF)

    def mov_imm(self, rd, value, sf=1):
        self.emit(M.movz(rd, value & 0xFFFF, sf=sf, shift=0))
        if (value >> 16) & 0xFFFF:
            self.emit(M.movk(rd, (value >> 16) & 0xFFFF, sf=sf, shift=16))

    def fill_white(self, words):
        self.emit(M.mov_xd_xn(11, 0))
        self.mov_imm(7, words, sf=0)
        self.emit(M.movz(2, 0xFFFF, sf=0, shift=0))
        self.emit(M.movk(2, 0xFFFF, sf=0, shift=16))
        px = len(self.code)
        self.emit(M.str_wt_postinc(2, 11, 4))
        self.emit(M.subs_w_imm(7, 7, 1))
        self.emit(M.b_ne(px, len(self.code)))

    def rect(self, x, y, w, h):
        off = y * STRIDE + x * 3
        self.mov_imm(5, off)
        self.emit(add_x_reg(11, 0, 5))
        self.mov_imm(8, h, sf=0)
        row = len(self.code)
        self.emit(M.mov_xd_xn(9, 11))
        self.mov_imm(7, w, sf=0)
        px = len(self.code)
        self.emit(strb_imm(2, 11, 0))
        self.emit(strb_imm(14, 11, 1))
        self.emit(strb_imm(6, 11, 2))
        self.emit(add_x_imm(11, 11, 3))
        self.emit(M.subs_w_imm(7, 7, 1))
        self.emit(M.b_ne(px, len(self.code)))
        self.mov_imm(5, STRIDE)
        self.emit(add_x_reg(11, 9, 5))
        self.emit(M.subs_w_imm(8, 8, 1))
        self.emit(M.b_ne(row, len(self.code)))


def build_payload():
    g = Gen()
    g.emit(M.movz(0, M.FB_ADDR >> 16, sf=1, shift=16))

    g.fill_white(REGION // 4)

    g.emit(M.movz(2, 0, sf=0, shift=0))
    g.emit(M.movz(14, 0, sf=0, shift=0))
    g.emit(M.movz(6, 0, sf=0, shift=0))

    x0 = XOFF
    x1 = XOFF + VIS - 4

    # рамка по краям видимого окна
    g.rect(x0, 0, VIS, 4)
    g.rect(x0, H - 4, VIS, 4)
    g.rect(x0, 0, 4, H)
    g.rect(x1, 0, 4, H)

    # маркеры в углах окна
    g.rect(x0, 0, 60, 60)
    g.rect(x1 + 4 - 60, 0, 60, 60)
    g.rect(x1 + 4 - 60, H - 60, 60, 60)
    g.rect(x0, H - 60, 60, 60)

    # крест в центре окна
    cx = XOFF + VIS // 2
    g.rect(cx - 60, H // 2 - 2, 120, 4)
    g.rect(cx - 2, H // 2 - 60, 4, 120)

    # сетка внутри окна
    for k in range(1, VIS // 120 + 1):
        g.rect(x0 + k * 120, 0, 2, H)
    for y in range(160, H, 160):
        g.rect(x0, y, VIS, 2)

    end = len(g.code)
    g.emit(M.b_uncond(end - 1, len(g.code)))

    body = b"".join(struct.pack("<I", w) for w in g.code)
    total = 64 + len(body)
    header = struct.pack(
        "<IIQQQQQQII",
        M.b_uncond(16, 0), M.NOP,
        0, total, 0, 0, 0, 0,
        0x644D5241, 0,
    )
    return header + body


def main():
    ap = argparse.ArgumentParser(description="проверка окна MDSS (offset 72)")
    ap.add_argument("--out", default="build/fbverify2.img")
    ap.add_argument("--dtblock", default="build/ugg.dtblock")
    args = ap.parse_args()

    payload = build_payload()
    kernel = gzip.compress(payload, 9)
    print("payload : %d байт, gzip -> %d" % (len(payload), len(kernel)))
    if os.path.exists(args.dtblock):
        with open(args.dtblock, "rb") as f:
            kernel += f.read()
            print("dtblock : %s" % args.dtblock)

    img = M.build_bootimg(kernel, b"", 0)
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "wb") as f:
        f.write(img)
    print("bootimg : %d байт -> %s" % (len(img), os.path.abspath(args.out)))
    print()
    print("ГИПОТЕЗА: видимое окно = buffer x 72..647 (576 px).")
    print("ОЖИДАНИЕ: чёрная рамка ВПЛОТНУЮ ко всем четырём краям панели,")
    print("маркеры в углах, крест в центре, ровная сетка (шаг 120 по X, 160 по Y).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
