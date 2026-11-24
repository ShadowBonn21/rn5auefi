#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
mkfbverify3.py — проверка сдвига X с ПРЯМОЙ компенсацией.

Измерения по фото (шаг сетки 120 fb-px = 169 px фото, масштаб 1.411):
  * вертикальный сдвиг 0 (верхняя рамка точно у верхнего края);
  * горизонтальный сдвиг +86 px, т.е. MDSS сканирует на ~258 байт РАНЬШЕ
    0x90000000 (кандидат: 0x8FFFFF00 = 256 байт = 85.33 px, либо 288 байт).

Здесь рисуем всё, СДВИНУВ УКАЗАТЕЛЬ на -258 байт (BASE_DRAW), чтобы наши
координаты совпали с координатами панели. Плюс рисуем «линейку»: насечки
каждые 60 px и метку на x=0, чтобы увидеть, попадает ли край ровно.

Ожидание при верной компенсации: рамка вплотную ко всем краям, крест
точно в центре, сетка равномерная, насечки линейки видны целиком.
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

FB_BASE = 0x90000000            # что видит MDSS (по измерениям — сдвинуто)
X_SHIFT_BYTES = 256             # 256 байт = 85.33 px; кратно 4 (иначе STR W -> alignment fault)
DRAW_BASE = FB_BASE - X_SHIFT_BYTES
assert DRAW_BASE % 4 == 0, "DRAW_BASE должен быть кратен 4: 0x%x" % DRAW_BASE


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
    # ВАЖНО: оба полубайта пишем 64-битными инструкциями (sf=1), иначе
    # MOVK W0 занулит старшую половину адреса и запись уйдёт в мусор.
    g.mov_imm(0, DRAW_BASE)

    g.fill_white(REGION // 4)

    g.emit(M.movz(2, 0, sf=0, shift=0))
    g.emit(M.movz(14, 0, sf=0, shift=0))
    g.emit(M.movz(6, 0, sf=0, shift=0))

    # рамка по краям панели
    g.rect(0, 0, W, 4)
    g.rect(0, H - 4, W, 4)
    g.rect(0, 0, 4, H)
    g.rect(W - 4, 0, 4, H)

    # угловые маркеры
    g.rect(0, 0, 60, 60)
    g.rect(W - 60, 0, 60, 60)
    g.rect(W - 60, H - 60, 60, 60)
    g.rect(0, H - 60, 60, 60)

    # крест в центре
    g.rect(W // 2 - 60, H // 2 - 2, 120, 4)
    g.rect(W // 2 - 2, H // 2 - 60, 4, 120)

    # сетка
    for x in range(120, W, 120):
        g.rect(x, 0, 2, H)
    for y in range(160, H, 160):
        g.rect(0, y, W, 2)

    # линейка: насечки каждые 60 px по верхнему краю (высота 30)
    for x in range(60, W, 60):
        g.rect(x, 0, 2, 30)

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
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="build/fbverify3.img")
    ap.add_argument("--dtblock", default="build/ugg.dtblock")
    args = ap.parse_args()

    payload = build_payload()
    kernel = gzip.compress(payload, 9)
    print("payload : %d байт, gzip -> %d" % (len(payload), len(kernel)))
    if os.path.exists(args.dtblock):
        with open(args.dtblock, "rb") as f:
            kernel += f.read()
    img = M.build_bootimg(kernel, b"", 0)
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "wb") as f:
        f.write(img)
    print("BOOTIMG : %s (%d байт)" % (args.out, len(img)))
    print("DRAW_BASE = 0x%08x (сдвиг -%d байт от 0x90000000)" % (DRAW_BASE, X_SHIFT_BYTES))
    print()
    print("ОЖИДАНИЕ: рамка ВПЛОТНУЮ ко всем 4 краям, маркеры в углах, крест в центре,")
    print("сетка ровная, линейка (насечки по 60 px) видна целиком до правого края.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
