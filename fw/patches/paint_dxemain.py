#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
paint_dxemain.py — «прогресс-бар» внутри ядра DXE (Common/edk2).

Нужен, когда BDS не запускается и непонятно, где останавливается DXE.
Полосы (24bpp, stride 2160, база 0x90000000-256):

    150 — DxeMain дошёл до CoreInitializeDispatcher()
    300 — CoreDispatcher() завершился (все драйверы отработали)
    450 — перед вызовом gBds->Entry(gBds)

Трактовка:
    нет 150      -> DXE-ядро падает в самом начале (HOB/память/GCD)
    150 без 300  -> диспетчеризация не завершилась: какой-то драйвер завис/упал
    300 без 450  -> между диспетчеризацией и вызовом BDS (подготовка BDS)
    450 есть     -> BDS вызван; если экран пуст — виноват уже BDS/консоль

Идемпотентно.
"""

import os
import sys

MARK = "MsmPaintProgressDxe"

HELPER = r'''
//
// Отладка без UART: прогресс внутри ядра DXE (fw/patches/paint_dxemain.py)
//
STATIC
VOID
MsmPaintProgressDxe (
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

HOOKS = [
    ("  CoreInitializeDispatcher ();", "  MsmPaintProgressDxe (150);", True),
    ("  CoreDispatcher ();", "  MsmPaintProgressDxe (300);", False),
    ("  gBds->Entry (gBds);", "  MsmPaintProgressDxe (450);", True),
]


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

    anchor = "VOID\nEFIAPI\nDxeMain ("
    if anchor not in src:
        sys.exit("paint_dxemain: не найден DxeMain")
    src = src.replace(anchor, HELPER + anchor, 1)

    n = 0
    for anchor, call, before in HOOKS:
        if anchor not in src:
            print("  !! не найден якорь: %s" % anchor.strip()[:50])
            continue
        repl = (call + "\n" + anchor) if before else (anchor + "\n" + call)
        src = src.replace(anchor, repl, 1)
        n += 1

    if n == 0:
        sys.exit("paint_dxemain: ни одной точки не найдено")

    with open(path, "w", encoding="utf-8") as f:
        f.write(src)
    print("paint_dxemain: точек %d" % n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
