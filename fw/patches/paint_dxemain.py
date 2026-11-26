#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
paint_dxemain.py — метка передачи управления от ядра DXE к BDS.

Ставит одну полоску в самом верху экрана (строки 0..14) непосредственно перед
вызовом gBds->Entry (gBds). Если полоска есть, а меток BDS нет — значит ядро
дошло до вызова, и проблема внутри BDS (либо gBds указывает в никуда).

Идемпотентно.
"""

import os
import sys

MARK = "MsmPaintDxeHandoff"

HELPER = r'''
//
// Отладка без UART: перед передачей управления в BDS (fw/patches/paint_dxemain.py)
//
STATIC
VOID
MsmPaintDxeHandoff (
  VOID
  )
{
  UINT8  *Base = (UINT8 *)(UINTN)(0x90000000ULL - 256ULL);
  UINTN  Y;
  UINTN  X;
  UINT8  *Row;

  for (Y = 10; Y < 82; Y++) {
    Row = Base + Y * 2160;
    for (X = 560; X < 596; X++) {
      Row[X] = 0xFF;
    }
  }
}

'''

ANCHOR = "  gBds->Entry (gBds);"
CALL = "  MsmPaintDxeHandoff ();\n"


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: paint_dxemain.py <edk2-msm-dir>")
    path = os.path.join(sys.argv[1], "Common/edk2/MdeModulePkg/Core/Dxe/DxeMain/DxeMain.c")
    if not os.path.isfile(path):
        sys.exit("нет файла: %s" % path)

    with open(path, "r", encoding="utf-8") as f:
        src = f.read()

    if MARK in src:
        print("paint_dxemain: уже пропатчено")
        return 0

    if ANCHOR not in src:
        sys.exit("paint_dxemain: не найден вызов gBds->Entry")

    anchor_fn = "VOID\nEFIAPI\nDxeMain ("
    if anchor_fn not in src:
        sys.exit("paint_dxemain: не найдено определение DxeMain")
    src = src.replace(anchor_fn, HELPER + anchor_fn, 1)
    src = src.replace(ANCHOR, CALL + ANCHOR, 1)

    with open(path, "w", encoding="utf-8") as f:
        f.write(src)
    print("paint_dxemain: метка передачи управления добавлена")
    return 0


if __name__ == "__main__":
    sys.exit(main())
