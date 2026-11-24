#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
measure_panel.py — точное измерение геометрии framebuffer по фото экрана.

Порядок:
  1) экран выделяется по цвету (он голубоватый: B > R), а не по яркости —
     так стол/дерево в кадр не попадают;
  2) границы активной области ищутся как ЛИНИИ (устойчивая регрессия по
     крайним точкам маски в средней части кадра), а не как bounding box —
     иначе скруглённые углы и засветка завышают ширину;
  3) кадр выпрямляется по найденному четырёхугольнику в 720x1280;
  4) в нём ищутся тёмные линии нашей картинки и сравниваются с ожидаемыми
     координатами.

Использование:
    python tools/measure_panel.py <фото.jpg> [--save build/_panel.png]
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
GRID_X = [120, 240, 360, 480, 600]
GRID_Y = [160, 320, 480, 640, 800, 960, 1120]


def screen_mask(img):
    a = np.asarray(img).astype(np.int16)
    R, G, B = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    return (B - R) > 8


def fit_edge(points_xy, vertical=True):
    """Робастная прямая по точкам: x = a*y+b (vertical) или y = a*x+b."""
    p = np.asarray(points_xy, dtype=np.float64)
    if vertical:
        y, x = p[:, 1], p[:, 0]
    else:
        y, x = p[:, 0], p[:, 1]
    keep = np.ones(len(x), dtype=bool)
    a = b = 0.0
    for _ in range(5):                      # несколько итераций отбраковки
        if keep.sum() < 10:
            break
        a, b = np.polyfit(y[keep], x[keep], 1)
        pred = a * y + b
        resid = np.abs(x - pred)
        keep = resid < max(3.0, 2.5 * np.median(resid))
    return a, b


def panel_quad(mask):
    h, w = mask.shape
    left_pts, right_pts = [], []
    for y in range(int(h * 0.15), int(h * 0.85)):
        xs = np.nonzero(mask[y])[0]
        if len(xs) < 50:
            continue
        left_pts.append((xs.min(), y))
        right_pts.append((xs.max(), y))
    top_pts, bot_pts = [], []
    for x in range(int(w * 0.15), int(w * 0.85)):
        ys = np.nonzero(mask[:, x])[0]
        if len(ys) < 50:
            continue
        top_pts.append((x, ys.min()))
        bot_pts.append((x, ys.max()))

    la, lb = fit_edge(left_pts, True)       # x = la*y + lb
    ra, rb = fit_edge(right_pts, True)
    ta, tb = fit_edge(top_pts, False)       # y = ta*x + tb
    ba, bb = fit_edge(bot_pts, False)

    def inter(v_a, v_b, h_a, h_b):
        # x = v_a*y+v_b ; y = h_a*x+h_b  ->  x = v_a*(h_a*x+h_b)+v_b
        den = 1.0 - v_a * h_a
        x = (v_a * h_b + v_b) / den
        y = h_a * x + h_b
        return x, y

    tl = inter(la, lb, ta, tb)
    tr = inter(ra, rb, ta, tb)
    br = inter(ra, rb, ba, bb)
    bl = inter(la, lb, ba, bb)
    return np.array([tl, bl, br, tr]), (la, lb, ra, rb, ta, tb, ba, bb)


def dips(prof, frac=0.90, gap=6, maxw=40):
    med = np.median(prof)
    if med <= 1:
        return []
    idx = np.where(prof < med * frac)[0]
    groups, cur = [], []
    for i in idx:
        if cur and i - cur[-1] > gap:
            groups.append(cur)
            cur = []
        cur.append(i)
    if cur:
        groups.append(cur)
    out = []
    for gr in groups:
        if len(gr) <= maxw:
            out.append((float(np.mean(gr)), len(gr), float(prof[gr].min() / med)))
    return out


def near(value, targets):
    best = min(targets, key=lambda t: abs(t - value))
    return best, value - best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("photo")
    ap.add_argument("--save", default="build/_panel.png")
    args = ap.parse_args()

    img = Image.open(args.photo).convert("RGB")
    mask = screen_mask(img)
    print("фото %dx%d, пикселей экрана %d" % (img.width, img.height, mask.sum()))

    quad, coeffs = panel_quad(mask)
    w_top = np.linalg.norm(quad[3] - quad[0])
    h_left = np.linalg.norm(quad[1] - quad[0])
    print("углы панели:", " ".join("(%.0f,%.0f)" % tuple(p) for p in quad))
    print("сторона сверху %.0f, слева %.0f, аспект %.4f (панель 720x1280 = %.4f)"
          % (w_top, h_left, w_top / h_left, W / H))

    warped = img.transform((W, H), Image.QUAD, tuple(quad.flatten().tolist()), Image.BICUBIC)
    warped.save(args.save)
    print("выпрямлено -> %s" % args.save)

    g = np.asarray(warped.convert("L")).astype(np.float64)

    vs = dips(g[250:1050, :].mean(axis=0))
    hs = dips(g[:, 150:570].mean(axis=1))

    print("\nвертикальные линии (fb-x, ширина, контраст) и отклонение от сетки/рамки:")
    targets_x = [0] + GRID_X + [W - 1]
    for p, w, r in vs:
        if r > 0.5:       # очень тёмное = край корпуса/засветка, пропускаем
            continue
        t, d = near(p, targets_x)
        print("   x=%6.1f  w=%2d  %.2f   ближайшее %3d  ->  %+5.1f px" % (p, w, r, t, d))

    print("\nгоризонтальные линии (fb-y, ширина, контраст):")
    targets_y = [0] + GRID_Y + [H - 1]
    for p, w, r in hs:
        if r > 0.5:
            continue
        t, d = near(p, targets_y)
        print("   y=%6.1f  w=%2d  %.2f   ближайшее %4d  ->  %+5.1f px" % (p, w, r, t, d))

    print("\nИНТЕРПРЕТАЦИЯ:")
    print("  |отклонение| <= 5 px  -> геометрия верна")
    print("  одинаковый сдвиг у всех линий -> смещение базы (PcdFbBaseOffset)")
    print("  растущее отклонение -> неверный stride")
    return 0


if __name__ == "__main__":
    sys.exit(main())
