#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
paint_bds.py — метки внутри BdsDxe (Common/edk2), чтобы найти точку падения BDS.

ВАЖНО: BdsDxe имеет Depex = TRUE и отрабатывает РАНЬШЕ нашего драйвера дисплея,
поэтому любые метки, нарисованные до очистки экрана, стираются. Здесь метки
ставятся внутри BdsEntry — они рисуются уже после UggFbDxe и остаются видны.

Полосы (24bpp, stride 2160, база 0x90000000-256):
    1 — первая строка BdsEntry            (строка ~100)
    2 — после BdsFormalizeEfiGlobalVariable (~200)
    3 — перед PlatformBootManagerBeforeConsole (~300)
    4 — после BeforeConsole               (~400)
    5 — после PlatformBootManagerAfterConsole (~500)

Трактовка:
    нет 1        -> BdsEntry не исполняется (DXE не дошёл до BDS)
    1 есть, 2 нет -> падение в первых строках (CRC системной таблицы, alloc)
    2 есть, 3 нет -> падение на переменных/политике переменных
    3 есть, 4 нет -> падение внутри PlatformBootManagerBeforeConsole
    4 есть, 5 нет -> падение на коннекте консолей/AfterConsole
    5 есть        -> BDS дошёл до загрузки опций

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

# (якорь, метка, ставить ДО якоря?)
HOOKS = [
    ("  HotkeyTriggered = NULL;", 1, True),
    ('  DEBUG ((DEBUG_INFO, "[Bds] Entry...\\n"));', 6, False),
    ("  BdsFormalizeEfiGlobalVariable ();", 2, False),
    ("  PlatformBootManagerBeforeConsole ();", 3, True),
    ('  PERF_INMODULE_END ("PlatformBootManagerBeforeConsole");', 4, False),
    ('  PERF_INMODULE_END ("PlatformBootManagerAfterConsole");', 5, False),
]


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
    for anchor, band, before in HOOKS:
        if anchor not in src:
            print("  !! не найден якорь: %s" % anchor.strip()[:60])
            continue
        call = "  MsmPaintBand (%d);" % band
        repl = (call + "\n" + anchor) if before else (anchor + "\n" + call)
        src = src.replace(anchor, repl, 1)
        added += 1

    if added == 0:
        sys.exit("paint_bds: ни одной точки не найдено")

    with open(path, "w", encoding="utf-8") as f:
        f.write(src)
    print("paint_bds: добавлено меток %d" % added)
    return 0


if __name__ == "__main__":
    sys.exit(main())
