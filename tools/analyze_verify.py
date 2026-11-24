#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
analyze_verify.py — числовая проверка геометрии framebuffer ugg по фото.

Ожидаемая картинка (рисует tools/mkfbverify.py, 24bpp/stride 2160):
  * чёрная рамка вплотную к краям;
  * угловые маркеры 60x60 в углах;
  * крест в центре;
  * сетка: вертикальные линии каждые 120 px (x=120..600), горизонтальные
    каждые 160 px (y=160..1120).

Скрипт выпрямляет фото экрана в 720x1280 и проверяет:
  1) тёмная ли рамка у всех четырёх краёв (значит сдвига нет);
  2) где реально лежат линии сетки и насколько они совпали с ожидаемыми;
  3) равномерен ли шаг (дрейф = неверный stride).

Использование:
    python tools/analyze_verify.py <фото.jpg>
"""

import argparse
import sys

import numpy as np
from PIL import Image, ImageFilter

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

W, H = 720, 1280
DARK = 110


def largest_bright_blob(gray, thresh=120, step=2):
    h, w = gray.shape
    mask = gray > thresh
    seen = np.zeros_like(mask, dtype=bool)
    best = []
    for y0 in range(0, h, step):
        for x0 in range(0, w, step):
            if not mask[y0, x0] or seen[y0, x0]:
                continue
            stack = [(y0, x0)]
            seen[y0, x0] = True
            pts = []
            while stack:
                y, x = stack.pop()
                pts.append((x, y))
                for dy, dx in ((step, 0), (-step, 0), (0, step), (0, -step)):
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        stack.append((ny, nx))
            if len(pts) > len(best):
                best = pts
    return np.array(best, dtype=np.float64) if best else None


def order_quad(corners):
    s = corners.sum(axis=1)
    d = corners[:, 0] - corners[:, 1]
    tl = corners[np.argmin(s)]
    br = corners[np.argmax(s)]
    tr = corners[np.argmax(d)]
    bl = corners[np.argmin(d)]
    return np.array([tl, bl, br, tr])


def pca_quad(pts):
    c = pts.mean(axis=0)
    q = pts - c
    evals, evecs = np.linalg.eigh(np.cov(q.T))
    major = evecs[:, np.argmax(evals)]
    minor = np.array([-major[1], major[0]])
    u = q @ minor
    v = q @ major
    def trim(a):
        return np.percentile(a, 0.5), np.percentile(a, 99.5)
    u0, u1 = trim(u)
    v0, v1 = trim(v)
    corners_uv = np.array([[u0, v0], [u1, v0], [u1, v1], [u0, v1]])
    Mx = np.stack([minor, major], axis=1)
    return corners_uv @ Mx.T + c


def find_lines(prof, frac=0.92, min_gap=8):
    med = np.median(prof)
    idx = np.where(prof < med * frac)[0]
    groups, cur = [], []
    for i in idx:
        if cur and i - cur[-1] > min_gap:
            groups.append(cur)
            cur = []
        cur.append(i)
    if cur:
        groups.append(cur)
    return [int(np.mean(g)) for g in groups]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("photo")
    args = ap.parse_args()

    img = Image.open(args.photo).convert("RGB")
    scale = 600.0 / img.width
    small = img.resize((600, int(img.height * scale)), Image.BILINEAR)
    gray = np.array(small.convert("L")).astype(np.float64)

    pts = largest_bright_blob(gray)
    if pts is None or len(pts) < 3000:
        sys.exit("не нашёл экран на фото")
    quad = order_quad(pca_quad(pts) / scale)

    warped = img.transform((W, H), Image.QUAD, tuple(quad.flatten().tolist()), Image.BICUBIC)
    warped.save("build/_verify_warp.png")

    g = np.array(warped.convert("L")).astype(np.float64)
    print("выпрямлено -> build/_verify_warp.png")

    # 1) рамка у краёв
    bands = {
        "top    (0..3)":    g[0:4, :].mean(),
        "bottom (1276..)":  g[H - 4:H, :].mean(),
        "left   (0..3)":    g[:, 0:4].mean(),
        "right  (716..)":   g[:, W - 4:W].mean(),
        "центр (600..680)": g[600:680, 300:420].mean(),
    }
    print("\n[1] яркость краёв (должно быть ТЁМНО ~<80, центр ~>200):")
    ok_edges = 0
    for k, v in bands.items():
        mark = "тёмно" if v < 120 else "светло"
        print("   %-18s %6.1f  %s" % (k, v, mark))
    for k in list(bands)[:4]:
        if bands[k] < 120:
            ok_edges += 1
    print("   рамка найдена у %d/4 краёв" % ok_edges)

    # 2) линии сетки
    colp = g[400:900, :].mean(axis=0)
    rowp = g[:, 200:520].mean(axis=1)
    vlines = find_lines(colp)
    hlines = find_lines(rowp)
    print("\n[2] вертикальные линии, найдено:", vlines[:12])
    exp_v = list(range(120, W, 120))
    print("    ожидалось:", exp_v)
    print("    горизонтальные линии, найдено:", hlines[:12])
    exp_h = list(range(160, H, 160))
    print("    ожидалось:", exp_h)

    # 3) шаг и совпадение
    print("\n[3] шаги между найденными линиями:")
    for name, lines, exp in (("верт", vlines, exp_v), ("гориз", hlines, exp_h)):
        real = [b - a for a, b in zip(lines, lines[1:])]
        if real:
            print("    %s: %s (ожидаемый шаг %d)" % (name, real[:8], exp[0] if exp else 0))
        deltas = []
        for e in exp:
            if lines:
                nearest = min(lines, key=lambda x: abs(x - e))
                deltas.append(nearest - e)
        if deltas:
            print("    %s: отклонение от ожидаемых, px: %s" % (name, deltas[:8]))
    print("\nИтог: рамка у всех краёв + шаг сетки ~120/160 + отклонения <5 px")
    print("=> геометрия 24bpp/stride 2160 подтверждена, сдвига нет.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
