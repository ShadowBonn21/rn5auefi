#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
apply_simplefb_stride.py — патч SimpleFbDxe из edk2-msm под framebuffer ugg.

Проблема: SimpleFbDxe считает, что строка экрана = width * 4 байта
(720*4 = 2880) и ставит PixelsPerScanLine = width. У ugg на самом деле:

    /sys/class/graphics/fb0/stride          = 2944   (ALIGN(2880, 64))
    /sys/class/graphics/fb0/bits_per_pixel  = 32
    /sys/class/graphics/fb0/virtual_size    = 720,2560 (два буфера)

Без патча консоль UEFI поедет «косыми полосами», как было в пробе G0.

Патч идемпотентный и проверяемый: если шаблон не найден — падаем с ошибкой,
чтобы не собрать молча сломанную прошивку.

Использование:
    python fw/patches/apply_simplefb_stride.py < edk2-msm >
"""

import os
import sys

TARGET = "Silicon/Qualcomm/QcomPkg/Drivers/SimpleFbDxe/SimpleFbDxe.c"

OLD_LINE = (
    "  UINT32               LineLength = MipiFrameBufferWidth * VNBYTES(VIDEO_BPP32);"
)
NEW_LINE = (
    "  /* ugg: MDSS pitch = ALIGN(width*4, 64) = 2944; PCD задаётся в ugg.dsc */\n"
    "  UINT32               LineLength = FixedPcdGet32(PcdFbStride);"
)

OLD_PPS = "  mDisplay.Mode->Info->PixelsPerScanLine = MipiFrameBufferWidth;"
NEW_PPS = (
    "  mDisplay.Mode->Info->PixelsPerScanLine =\n"
    "      LineLength / VNBYTES(VIDEO_BPP32);"
)

MARKER = "ugg: MDSS pitch"


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: apply_simplefb_stride.py <edk2-msm-dir>")
    root = sys.argv[1]
    path = os.path.join(root, TARGET)
    if not os.path.isfile(path):
        sys.exit("нет файла: %s" % path)

    with open(path, "r", encoding="utf-8") as f:
        src = f.read()

    if MARKER in src:
        print("SimpleFbDxe: патч уже применён")
        return 0

    if OLD_LINE not in src or OLD_PPS not in src:
        sys.exit(
            "SimpleFbDxe.c не совпадает с ожидаемым шаблоном.\n"
            "Апстрим изменился — проверьте вручную:\n  %s" % path
        )

    src = src.replace(OLD_LINE, NEW_LINE, 1)
    src = src.replace(OLD_PPS, NEW_PPS, 1)

    # PCD нужно объявить: SimpleFbDxe.inf должен видеть наш токен-спейс
    inf = os.path.join(os.path.dirname(path), "SimpleFbDxe.inf")
    if os.path.isfile(inf):
        with open(inf, "r", encoding="utf-8") as f:
            itxt = f.read()
        if "PcdFbStride" not in itxt:
            itxt = itxt.replace("[Pcd]", "[Pcd]\n  gMsm8937PkgTokenSpaceGuid.PcdFbStride", 1) \
                       if "[Pcd]" in itxt else \
                       itxt + "\n[Pcd]\n  gMsm8937PkgTokenSpaceGuid.PcdFbStride\n"
            if "Silicon/Qualcomm/msm8937/msm8937.dec" not in itxt and "msm8937.dec" not in itxt:
                itxt = itxt.replace("[Packages]", "[Packages]\n  Silicon/Qualcomm/msm8937/msm8937.dec", 1)
            with open(inf, "w", encoding="utf-8") as f:
                f.write(itxt)
            print("SimpleFbDxe.inf: добавлен PcdFbStride")

    with open(path, "w", encoding="utf-8") as f:
        f.write(src)
    print("SimpleFbDxe.c: stride исправлен (PixelsPerScanLine = stride/4)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
