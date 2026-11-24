#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
mkfbcal.py (v5) — финальное подтверждение геометрии framebuffer ugg.

Прошлая серия (регион + счётные линии) дала: ровные линии в фазе 1
(24bpp, stride 2160) и частично в фазе 4 (32bpp, 2880). Проверяем «рамкой»:

  * весь регион сплэша (8 МиБ) заливается белым — не зависит от геометрии;
  * поверх рисуется ЧЁРНАЯ РАМКА по краям прямоугольника 720x1280
    (верх, низ, левый и правый край) + угловые маркеры;
  * число угловых маркеров = номер гипотезы.

Если геометрия верна — рамка прилипает к краям экрана со всех четырёх сторон,
углы сходятся, маркеры ровные квадраты. Если неверна — правый край «уезжает»,
верх/низ идут лесенкой, квадраты превращаются в параллелограммы.

Фазы: 1 -> 24bpp/2160, 2 -> 24bpp/2176, 3 -> 32bpp/2880.
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
REGION = 0x00800000
BORDER = 4          # толщина рамки, пикселей
MARK = 60           # размер углового маркера

PHASES = (
    (24, 2160, 1),
    (24, 2176, 2),
    (32, 2880, 3),
)

PX = {24: 3, 32: 4}


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

    def delay(self, hi=0x0300):
        self.emit(M.movz(3, hi, sf=1, shift=16))
        d = len(self.code)
        self.emit(M.subs_x_imm(3, 3, 1))
        self.emit(M.b_ne(d, len(self.code)))

    # --- примитивы -------------------------------------------------------
    def px_black(self, bpp):
        if bpp == 24:
            self.emit(strb_imm(2, 11, 0))
            self.emit(strb_imm(14, 11, 1))
            self.emit(strb_imm(6, 11, 2))
            self.emit(add_x_imm(11, 11, 3))
        else:
            self.emit(M.str_wt_postinc(2, 11, 4))

    def fill_region_white(self, words):
        self.emit(M.mov_xd_xn(11, 0))
        self.mov_imm(7, words, sf=0)
        self.emit(M.movz(2, 0xFFFF, sf=0, shift=0))
        self.emit(M.movk(2, 0xFFFF, sf=0, shift=16))
        px = len(self.code)
        self.emit(M.str_wt_postinc(2, 11, 4))
        self.emit(M.subs_w_imm(7, 7, 1))
        self.emit(M.b_ne(px, len(self.code)))

    def row_run(self, offset, count, bpp):
        """count чёрных пикселей, начиная с байтового offset от базы."""
        self.mov_imm(5, offset)
        self.emit(add_x_reg(11, 0, 5))
        self.mov_imm(8, count, sf=0)
        px = len(self.code)
        self.px_black(bpp)
        self.emit(M.subs_w_imm(8, 8, 1))
        self.emit(M.b_ne(px, len(self.code)))

    def rect(self, bpp, stride, buf_off, x, y, w, h):
        """Прямоугольник: h строк по w пикселей."""
        step = PX[bpp]
        base_off = buf_off + y * stride + x * step
        row_stride_off = stride
        self.mov_imm(5, base_off)
        self.emit(add_x_reg(11, 0, 5))
        self.mov_imm(8, h, sf=0)
        row = len(self.code)
        self.emit(M.mov_xd_xn(9, 11))
        self.mov_imm(7, w, sf=0)
        px = len(self.code)
        self.px_black(bpp)
        self.emit(M.subs_w_imm(7, 7, 1))
        self.emit(M.b_ne(px, len(self.code)))
        self.mov_imm(5, row_stride_off)
        self.emit(add_x_reg(11, 9, 5))
        self.emit(M.subs_w_imm(8, 8, 1))
        self.emit(M.b_ne(row, len(self.code)))

    def vertical_border(self, bpp, stride, buf_off, x, h):
        """h строк по BORDER чёрных пикселей в колонке x."""
        step = PX[bpp]
        off = buf_off + x * step
        self.mov_imm(5, off)
        self.emit(add_x_reg(11, 0, 5))
        self.mov_imm(8, h, sf=0)
        row = len(self.code)
        self.emit(M.mov_xd_xn(9, 11))
        self.mov_imm(7, BORDER, sf=0)
        px = len(self.code)
        self.px_black(bpp)
        self.emit(M.subs_w_imm(7, 7, 1))
        self.emit(M.b_ne(px, len(self.code)))
        self.mov_imm(5, stride)
        self.emit(add_x_reg(11, 9, 5))
        self.emit(M.subs_w_imm(8, 8, 1))
        self.emit(M.b_ne(row, len(self.code)))


def build_payload():
    g = Gen()
    g.emit(M.movz(0, M.FB_ADDR >> 16, sf=1, shift=16))     # x0 = 0x90000000

    loop = len(g.code)
    for bpp, stride, marks in PHASES:
        # регион заливаем ОДИН раз на фазу (покрывает оба буфера)
        g.fill_region_white(REGION // 4)
        # чёрный цвет
        g.emit(M.movz(2, 0, sf=0, shift=0))
        g.emit(M.movz(14, 0, sf=0, shift=0))
        g.emit(M.movz(6, 0, sf=0, shift=0))
        for buf_off in (0, stride * H):
            # рамка
            g.rect(bpp, stride, buf_off, 0, 0, W, BORDER)                    # верх
            g.rect(bpp, stride, buf_off, 0, H - BORDER, W, BORDER)            # низ
            g.vertical_border(bpp, stride, buf_off, 0, H)                     # лево
            g.vertical_border(bpp, stride, buf_off, W - BORDER, H)            # право
            # угловые маркеры: marks штук
            corners = ((0, 0), (W - MARK, 0), (W - MARK, H - MARK))
            for (mx, my) in corners[:marks]:
                g.rect(bpp, stride, buf_off, mx, my, MARK, MARK)
        g.delay()
    g.emit(M.b_uncond(loop, len(g.code)))

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
    ap = argparse.ArgumentParser(description="финальная калибровка рамкой (ugg)")
    ap.add_argument("--out", default="build/fbcal.img")
    ap.add_argument("--dtblock", default="build/ugg.dtblock")
    args = ap.parse_args()

    payload = build_payload()
    kernel = gzip.compress(payload, 9)
    print("payload : %d байт, gzip -> %d" % (len(payload), len(kernel)))
    if os.path.exists(args.dtblock):
        with open(args.dtblock, "rb") as f:
            kernel += f.read()
    else:
        print("!! нет %s" % args.dtblock)

    img = M.build_bootimg(kernel, b"", 0)
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "wb") as f:
        f.write(img)
    print("bootimg : %d байт -> %s" % (len(img), os.path.abspath(args.out)))
    print()
    print("СМОТРЕТЬ: белый экран с ЧЁРНОЙ РАМКОЙ по всему периметру и чёрными")
    print("квадратами в углах (1, 2 или 3 квадрата = номер гипотезы):")
    for bpp, stride, n in PHASES:
        print("  %d квадрат(а) -> %2dbpp, stride %d" % (n, bpp, stride))
    print("  рамка везде прилипает к краям, углы сходятся -> геометрия верна")
    print("  правая/нижняя сторона 'уезжает' -> stride не тот")
    return 0


if __name__ == "__main__":
    sys.exit(main())
