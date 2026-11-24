#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
paint_bds.py — метки внутри BdsDxe (Common/edk2), чтобы понять, где стоит BDS.

Полосы (строки framebuffer'а, 24bpp stride 2160, база 0x90000000-256):
    9  — BdsEntry начался            (строка ~900)
    10 — перед PlatformBootManagerBeforeConsole  (~1000)
    11 — после BeforeConsole         (~1100)
    12 — после AfterConsole          (~1200)

Трактовка:
    9 есть, 10 нет      -> BDS упал в начале (переменные/CRC/Formalize)
    10 есть, 11 нет     -> падение внутри PlatformBootManagerBeforeConsole
    11 есть, 12 нет     -> падение между консолями (ConnectAllDefaultConsoles)
    12 есть             -> BDS дошёл до загрузки опций (дальше логотип/меню)

Идемпотентно.
"""

import os
import sys

MARK = "MsmPaintBand"

HELPER = r'''
//
// Отладка без UART: белая полоса N (fw/patches/paint_bds.py)
//
STATIC
VOID
MsmPaintBand (
  IN UINTN  Band
  )
{
  UINT8  *Base = (UINT8 *)(UINTN)(0x90000000ULL - 256ULL);
  UINTN  Y;
  UINTN  X;
  UINT8  *Row;

  for (Y = Band * 100; Y < Band * 100 + 50; Y++) {
    Row = Base + Y * 2160;
    for (X = 0; X < 2160; X++) {
      Row[X] = 0xFF;
    }
  }
}

'''

HOOKS = [
    ('  DEBUG ((DEBUG_INFO, "[Bds] Entry...\\n"));', "  MsmPaintBand (9);"),
    ("  PlatformBootManagerBeforeConsole ();", "  MsmPaintBand (10);"),
    ("  PlatformBootManagerAfterConsole ();", "  MsmPaintBand (12);"),
]

AFTER_BEFORE = ("  PERF_INMODULE_END (\"PlatformBootManagerBeforeConsole\");", "  MsmPaintBand (11);")


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: paint_bds.py <edk2-msm-dir>")
    path = os.path.join(sys.argv[1], "Common/edk2/MdeModulePkg/Universal/BdsDxe/BdsEntry.c")
    if not os.path.isfile(path):
        sys.exit("нет файла: %s" % path)

    with open(path, "r", encoding="utf-8") as f:
        src = f.read()

    if MARK in src:
        print("paint_bds: уже пропатчено")
        return 0

    anchor = "VOID\nEFIAPI\nBdsEntry ("
    if anchor not in src:
        sys.exit("paint_bds: не найден BdsEntry")
    src = src.replace(anchor, HELPER + anchor, 1)

    added = 0
    for anchor, call in HOOKS + [AFTER_BEFORE]:
        if anchor in src:
            src = src.replace(anchor, call + "\n" + anchor, 1)
            added += 1
        else:
            print("  !! не найден якорь: %s" % anchor.strip()[:60])

    if added == 0:
        sys.exit("paint_bds: ни одной точки не найдено")

    with open(path, "w", encoding="utf-8") as f:
        f.write(src)
    print("paint_bds: добавлено меток %d" % added)
    return 0


if __name__ == "__main__":
    sys.exit(main())
