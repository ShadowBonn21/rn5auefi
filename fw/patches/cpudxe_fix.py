#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
cpudxe_fix.py — рабочая правка CpuDxe для ugg (без отладочных меток).

Что делает: отключает вызов SyncCacheConfig() в CpuDxeInitialize.

Зачем: SyncCacheConfig обходит страничные таблицы и приводит атрибуты GCD
в соответствие с MMU. На карте памяти ugg (пять DDR-регионов с разными
атрибутами + MMIO) этот обход уходит в бесконечный цикл — проверено на
устройстве: после установки CPU-протокола выполнение не возвращается.

Без SyncCacheConfig атрибуты GCD остаются как задал PrePi/MemoryPeim, что
для bring-up допустимо: защиты памяти отключены PCD'ами в ugg.dsc.

Идемпотентно.
"""

import os
import sys

MARK = "ugg: SyncCacheConfig отключён"


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: cpudxe_fix.py <edk2-msm-dir>")
    path = os.path.join(sys.argv[1], "Common/edk2/ArmPkg/Drivers/CpuDxe/CpuDxe.c")
    if not os.path.isfile(path):
        sys.exit("нет файла: %s" % path)

    with open(path, "r", encoding="utf-8") as f:
        src = f.read()

    if MARK in src:
        print("cpudxe_fix: уже применено")
        return 0

    if "  SyncCacheConfig (&mCpu);" not in src:
        sys.exit("cpudxe_fix: не найден вызов SyncCacheConfig")

    src = src.replace(
        "  SyncCacheConfig (&mCpu);",
        "  /* ugg: SyncCacheConfig отключён (fw/patches/cpudxe_fix.py) */",
        1,
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(src)
    print("cpudxe_fix: SyncCacheConfig отключён")
    return 0


if __name__ == "__main__":
    sys.exit(main())
