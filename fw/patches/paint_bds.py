#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
paint_bds.py — «прогресс-бар» внутри BdsDxe: высота белой области = стадия.

Почему так: отдельные полосы близко по высоте и их легко спутать. Здесь каждая
пройденная стадия «докрашивает» область сверху вниз до новой высоты, поэтому
достаточно посмотреть, ДО КУДА белое — и всё понятно без счёта.

Высоты (строки из 1280, 24bpp stride 2160, база 0x90000000-256):
    150 — BdsEntry начался
    300 — строка DEBUG("[Bds] Entry...") пройдена
    450 — BdsFormalizeEfiGlobalVariable() пройдена
    600 — перед PlatformBootManagerBeforeConsole()
    750 — BeforeConsole вернулся
    900 — AfterConsole вернулся

Плюс сам UggFbDxe рисует полосу на 1200-й строке ПОСЛЕ установки GOP
(PcdDebugStageBands) — «драйвер дисплея полностью готов».

Идемпотентно.
"""

import os
import sys

MARK = "MsmPaintProgress"

HELPER = r'''
//
// Отладка без UART: «прогресс-бар» — закрасить строки [0, Rows)
// (fw/patches/paint_bds.py; ugg: 24bpp, stride 2160, база 0x90000000-256)
//
STATIC
VOID
MsmPaintProgress (
  IN UINTN  Rows
  )
{
  UINT8  *Base = (UINT8 *)(UINTN)(0x90000000ULL - 256ULL);
  UINTN  Y;
  UINTN  X;
  UINT8  *Row;

  for (Y = 0; Y < Rows; Y++) {
    Row = Base + Y * 2160;
    for (X = 0; X < 2160; X++) {
      Row[X] = 0xFF;
    }
  }
}

'''

# (якорь, высота прогресса, ставить ДО якоря?)
HOOKS = [
    ("  HotkeyTriggered = NULL;", 150, True),
    ('  DEBUG ((DEBUG_INFO, "[Bds] Entry...\\n"));', 300, False),
    ("  BdsFormalizeEfiGlobalVariable ();", 450, False),
    ("  PlatformBootManagerBeforeConsole ();", 600, True),
    ('  PERF_INMODULE_END ("PlatformBootManagerBeforeConsole");', 750, False),
    ('  PERF_INMODULE_END ("PlatformBootManagerAfterConsole");', 900, False),
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
    for anchor, rows, before in HOOKS:
        if anchor not in src:
            print("  !! не найден якорь: %s" % anchor.strip()[:60])
            continue
        call = "  MsmPaintProgress (%d);" % rows
        repl = (call + "\n" + anchor) if before else (anchor + "\n" + call)
        src = src.replace(anchor, repl, 1)
        added += 1

    if added == 0:
        sys.exit("paint_bds: ни одной точки не найдено")

    with open(path, "w", encoding="utf-8") as f:
        f.write(src)
    print("paint_bds: точек прогресса %d" % added)
    return 0


if __name__ == "__main__":
    sys.exit(main())
