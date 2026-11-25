#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
decode_guid_barcode.py — расшифровать GUID драйвера из фото экрана.

Прошивка рисует штрихкод: рамка 4 px, внутри 16 строк (байты GUID) по 8 клеток
(биты, старший слева), клетка 40 px. Скрипт находит рамку, строит гомографию
(фото под углом) и сэмплирует центры клеток.

Использование:
    python decode_guid_barcode.py <фото.jpg>
"""

import sys

import numpy as np
from PIL import Image, ImageOps

CELL = 40
COLS = 8
ROWS = 16
FRAME = 4
BLOCK_W = COLS * CELL + 2 * FRAME      # 328
BLOCK_H = ROWS * CELL + 2 * FRAME      # 648


def homography(src, dst):
    """Матрица 3x3: src[i] -> dst[i] (4 точки)."""
    A = []
    b = []
    for (x, y), (u, v) in zip(src, dst):
        A.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        A.append([0, 0, 0, x, y, 1, -v * x, -v * y])
        b.append(u)
        b.append(v)
    A = np.array(A, dtype=np.float64)
    b = np.array(b, dtype=np.float64)
    h = np.linalg.solve(A, b)
    return np.array([[h[0], h[1], h[2]],
                     [h[3], h[4], h[5]],
                     [h[6], h[7], 1.0]])


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: decode_guid_barcode.py <photo.jpg>")
    img = ImageOps.exif_transpose(Image.open(sys.argv[1])).convert("L")
    g = np.asarray(img, dtype=np.float32)
    print("фото: %dx%d" % (g.shape[1], g.shape[0]))

    bright = g > 100

    # 1) грубо (шаг 8) находим сам блок как крупнейшую связную область
    # игнорируем края и нижнюю плашку с подписью
    H0, W0 = bright.shape
    bright[:int(H0 * 0.08), :] = False
    bright[int(H0 * 0.80):, :] = False
    bright[:, :int(W0 * 0.03)] = False
    bright[:, int(W0 * 0.97):] = False

    st = 8
    coarse = bright[::st, ::st]
    ch, cw = coarse.shape
    seen = np.zeros_like(coarse, dtype=bool)
    best = None
    for y0 in range(ch):
        for x0 in range(cw):
            if not coarse[y0, x0] or seen[y0, x0]:
                continue
            stack = [(y0, x0)]
            seen[y0, x0] = True
            pts = []
            while stack:
                cy, cx = stack.pop()
                pts.append((cy, cx))
                for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    ny, nx = cy + dy, cx + dx
                    if 0 <= ny < ch and 0 <= nx < cw and coarse[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        stack.append((ny, nx))
            ys_ = [p[0] for p in pts]
            xs_ = [p[1] for p in pts]
            bh = (max(ys_) - min(ys_) + 1)
            bw = (max(xs_) - min(xs_) + 1)
            ar = bw / float(bh)
            if len(pts) < 200 or not (0.30 <= ar <= 0.80):
                continue
            if best is None or len(pts) > len(best):
                best = pts
    if not best or len(best) < 50:
        sys.exit("не нашёл блок штрихкода")

    cys = np.array([p[0] for p in best])
    cxs = np.array([p[1] for p in best])
    y0f, y1f = cys.min() * st, (cys.max() + 1) * st
    x0f, x1f = cxs.min() * st, (cxs.max() + 1) * st
    print("блок (фото): x %d..%d, y %d..%d" % (x0f, x1f, y0f, y1f))

    # 2) в пределах блока берём 4 крайние точки = углы рамки
    sub = bright[y0f:y1f, x0f:x1f]
    ys, xs = np.nonzero(sub)
    ys = ys + y0f
    xs = xs + x0f
    if len(xs) < 1000:
        sys.exit("блок слишком мал")

    s = xs + ys
    d = xs - ys
    tl = (xs[np.argmin(s)], ys[np.argmin(s)])
    br = (xs[np.argmax(s)], ys[np.argmax(s)])
    tr = (xs[np.argmax(d)], ys[np.argmax(d)])
    bl = (xs[np.argmin(d)], ys[np.argmin(d)])
    print("углы (фото): TL=%s TR=%s BR=%s BL=%s" % (tl, tr, br, bl))

    H = homography([tl, tr, br, bl],
                   [(0, 0), (BLOCK_W, 0), (BLOCK_W, BLOCK_H), (0, BLOCK_H)])
    Hi = np.linalg.inv(H)

    # сэмплируем центры клеток
    bits = np.zeros((ROWS, COLS), dtype=np.uint8)
    vals = np.zeros((ROWS, COLS), dtype=np.float32)
    for i in range(ROWS):
        for j in range(COLS):
            u = FRAME + j * CELL + CELL / 2.0
            v = FRAME + i * CELL + CELL / 2.0
            p = Hi @ np.array([u, v, 1.0])
            px, py = int(round(p[0] / p[2])), int(round(p[1] / p[2]))
            if not (0 <= py < g.shape[0] and 0 <= px < g.shape[1]):
                sys.exit("точка вне фото: (%d,%d)" % (px, py))
            # среднее по пятну 5x5
            patch = g[max(0, py - 3):py + 4, max(0, px - 3):px + 4]
            m = float(patch.mean())
            vals[i, j] = m
            bits[i, j] = 1 if m > 110 else 0

    print()
    print("уровни яркости клеток (0..255), чтобы видеть надёжность:")
    for i in range(ROWS):
        print("  " + " ".join("%3d" % v for v in vals[i]))

    data = bytearray()
    for i in range(ROWS):
        byte = 0
        for j in range(COLS):
            byte = (byte << 1) | int(bits[i, j])
        data.append(byte)

    # проверка на «серую зону» (неуверенные клетки)
    unsure = [(i, j, vals[i, j]) for i in range(ROWS) for j in range(COLS)
              if 60 < vals[i, j] < 160]
    if unsure:
        print("\nНЕУВЕРЕННЫЕ клетки (%d):" % len(unsure))
        for i, j, v in unsure[:20]:
            print("   строка %d, столбец %d: яркость %.0f" % (i, j, v))

    raw = bytes(data[:16]).hex()
    print("\nбайты GUID: %s" % raw)
    d1 = int.from_bytes(data[0:4], "little")
    d2 = int.from_bytes(data[4:6], "little")
    d3 = int.from_bytes(data[6:8], "little")
    d4 = data[8:10].hex()
    d5 = data[10:16].hex()
    print("GUID: %08X-%04X-%04X-%s-%s" % (d1, d2, d3, d4, d5))
    return 0


if __name__ == "__main__":
    sys.exit(main())
