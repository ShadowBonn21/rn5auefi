#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
analyze_fbcal.py — измерить по фотографии, где оказалась нарисованная рамка.

Без OpenCV: экран находится как самая большая яркая область, ориентация —
через PCA, затем гомография по четырём углам выпрямляет кадр в 720x1280,
после чего ищутся самые тёмные строки/столбцы (наша рамка).

Использование:
    python tools/analyze_fbcal.py <фото> [--stride 2160] [--bpp 24]
"""

import argparse
import sys

import numpy as np
from PIL import Image

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

W, H = 720, 1280


def largest_bright_blob(gray, thresh=120, step=2):
    """Маска самой большой яркой связной области (BFS по сетке с шагом step)."""
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


def pca_quad(pts):
    """Четырёхугольник вокруг области: габариты в системе главных осей."""
    c = pts.mean(axis=0)
    q = pts - c
    cov = np.cov(q.T)
    evals, evecs = np.linalg.eigh(cov)
    # главная ось — собственный вектор с большей дисперсией (обычно вертикаль)
    major = evecs[:, np.argmax(evals)]
    minor = np.array([-major[1], major[0]])
    u = q @ np.array([minor[0], minor[1]])
    v = q @ np.array([major[0], major[1]])
    # обрезаем 1% выбросов (блики/шум)
    def trim(a):
        lo, hi = np.percentile(a, 0.5), np.percentile(a, 99.5)
        return lo, hi

    u0, u1 = trim(u)
    v0, v1 = trim(v)
    corners_uv = np.array([[u0, v0], [u1, v0], [u1, v1], [u0, v1]])
    M = np.stack([np.array([minor[0], minor[1]]), np.array([major[0], major[1]])], axis=1)
    corners = corners_uv @ M.T + c
    return corners          # порядок: (u0,v0) (u1,v0) (u1,v1) (u0,v1)


def order_quad(corners):
    """Упорядочить: TL, BL, LR, UR (порядок нужен PIL.QUAD)."""
    s = corners[:, 0] + corners[:, 1]
    d = corners[:, 0] - corners[:, 1]
    tl = corners[np.argmin(s)]
    br = corners[np.argmax(s)]
    tr = corners[np.argmax(d)]
    bl = corners[np.argmin(d)]
    return np.array([tl, bl, br, tr])


def warp(img, quad):
    data = tuple(quad.flatten().tolist())
    return img.transform((W, H), Image.QUAD, data, Image.BICUBIC)


def profile_lines(prof, label, frac=0.85):
    med = np.median(prof)
    thr = med * frac
    idx = np.where(prof < thr)[0]
    groups, cur = [], []
    for i in idx:
        if cur and i - cur[-1] > 4:
            groups.append(cur)
            cur = []
        cur.append(i)
    if cur:
        groups.append(cur)
    out = [(int(np.mean(g)), float(prof[g].min() / med)) for g in groups]
    out.sort(key=lambda t: t[1])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("photo")
    ap.add_argument("--stride", type=int, default=2160)
    ap.add_argument("--bpp", type=int, default=24)
    args = ap.parse_args()

    img = Image.open(args.photo).convert("RGB")
    # даунскейл для поиска экрана
    scale = 500.0 / img.width
    small = img.resize((500, int(img.height * scale)), Image.BILINEAR)
    gray = np.array(small.convert("L")).astype(np.float64)

    pts = largest_bright_blob(gray)
    if pts is None or len(pts) < 3000:
        sys.exit("не нашёл яркую область экрана")
    quad = pca_quad(pts) / scale
    quad = order_quad(quad)
    print("углы экрана (фото):", " ".join("(%.0f,%.0f)" % tuple(p) for p in quad))

    warped = warp(img, quad)
    warped.save("build/_warped.png")
    wg = np.array(warped.convert("L")).astype(np.float64)
    print("выпрямлено -> build/_warped.png (%dx%d)" % (W, H))

    rows = profile_lines(wg.mean(axis=1), "rows")
    cols = profile_lines(wg.mean(axis=0), "cols")
    print("самые тёмные СТРОКИ (row, яркость/медиана):")
    for r, v in rows[:6]:
        print("   row=%4d  %.2f" % (r, v))
    print("самые тёмные СТОЛБЦЫ (col, яркость/медиана):")
    for c, v in cols[:6]:
        print("   col=%4d  %.2f" % (c, v))

    if rows and cols:
        r0, v0 = rows[0]
        c0, w0 = cols[0]
        px = args.bpp // 8
        off = r0 * args.stride + c0 * px
        print()
        print("рамка (наша точка 0,0) на экране: x=%d, y=%d" % (c0, r0))
        print("байтовое смещение: %d (0x%x)  [y*stride + x*%d]" % (off, off, px))
        print("предполагаемая база сканирования: 0x%08x" % (0x90000000 - off))
    return 0


if __name__ == "__main__":
    sys.exit(main())
