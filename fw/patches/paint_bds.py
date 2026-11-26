#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
paint_bds.py — три независимых сигнала о BDS, без подвисающих вызовов.

Что рисуется (24bpp, stride 2160, база 0x90000000-256):

    цифра 1 в (660,10) — BdsInitialize (точка входа драйвера) начал работу
    полоса на строке 200 — gST->ConOut существует, и OutputString ВЕРНУЛСЯ
    полоса на строке 260 — gST->ConOut == NULL (консоли нет вовсе)
    цифра 1 в (680,10) — BdsEntry начал работу
    полоса на строке 320 — в BdsEntry OutputString вернулся

Порядок важен: маркер ставится ДО вызова OutputString, поэтому если полосы
200/260 нет — значит завис именно вывод в консоль (или код до него).

Идемпотентно.
"""

import os
import sys

MARK = "MsmPaintBdsState"

HELPER = r'''
//
// Отладка без UART: состояние BDS (fw/patches/paint_bds.py)
//
STATIC
VOID
MsmPaintBdsDigit (
  IN UINTN  X,
  IN UINTN  Digit
  )
{
  STATIC CONST UINT8  Seg[10] = {
    0x3F, 0x06, 0x5B, 0x4F, 0x66, 0x6D, 0x7D, 0x07, 0x7F, 0x6F
  };
  UINT8  *Base = (UINT8 *)(UINTN)(0x90000000ULL - 256ULL);
  UINTN  Y0 = 10;
  UINTN  W = 36;
  UINTN  H = 72;
  UINTN  T = 7;
  UINTN  S = Seg[Digit % 10];
  UINTN  Row;
  UINTN  Col;
  UINT8  *Ptr;
  CONST UINTN  Rect[7][4] = {
    { 0, 0, W, T },
    { W - T, 0, T, H / 2 },
    { W - T, H / 2, T, H / 2 },
    { 0, H - T, W, T },
    { 0, H / 2, T, H / 2 },
    { 0, 0, T, H / 2 },
    { 0, H / 2 - T / 2, W, T }
  };
  UINTN  I;

  for (Row = 0; Row < 100; Row++) {
    Ptr = Base + (Y0 + Row) * 2160 + X * 3;
    for (Col = 0; Col < 46; Col++) {
      Ptr[Col * 3 + 0] = 0x00;
      Ptr[Col * 3 + 1] = 0x00;
      Ptr[Col * 3 + 2] = 0x00;
    }
  }

  for (I = 0; I < 7; I++) {
    if ((S & (1u << I)) == 0) {
      continue;
    }
    for (Row = 0; Row < Rect[I][3]; Row++) {
      Ptr = Base + (Y0 + Rect[I][1] + Row) * 2160 + (X + Rect[I][0]) * 3;
      for (Col = 0; Col < Rect[I][2]; Col++) {
        Ptr[Col * 3 + 0] = 0xFF;
        Ptr[Col * 3 + 1] = 0xFF;
        Ptr[Col * 3 + 2] = 0xFF;
      }
    }
  }
}

STATIC
VOID
MsmPaintBdsBar (
  IN UINTN  Row0
  )
{
  UINT8  *Base = (UINT8 *)(UINTN)(0x90000000ULL - 256ULL);
  UINTN  Y;
  UINTN  X;
  UINT8  *Row;

  for (Y = Row0; Y < Row0 + 24; Y++) {
    Row = Base + Y * 2160;
    for (X = 0; X < 2160; X++) {
      Row[X] = 0xFF;
    }
  }
}

'''

INIT_CODE = (
    "  MsmPaintBdsDigit (660, 1);\n"
    "  if (gST->ConOut != NULL) {\n"
    '    gST->ConOut->OutputString (gST->ConOut, L"UGG-BDS-INIT\\r\\n");\n'
    "    MsmPaintBdsBar (200);\n"
    "  } else {\n"
    "    MsmPaintBdsBar (260);\n"
    "  }\n"
)

ENTRY_CODE = (
    "  MsmPaintBdsDigit (680, 1);\n"
    "  if (gST->ConOut != NULL) {\n"
    '    gST->ConOut->OutputString (gST->ConOut, L"UGG-BDS-ENTRY\\r\\n");\n'
    "    MsmPaintBdsBar (320);\n"
    "  }\n"
)

HOOKS = [
    ("  EFI_HANDLE  Handle;", INIT_CODE, True),
    ("  HotkeyTriggered = NULL;", ENTRY_CODE, True),
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

    anchor_fn = "EFI_STATUS\nEFIAPI\nBdsInitialize ("
    if anchor_fn not in src:
        sys.exit("paint_bds: не найден BdsInitialize")
    src = src.replace(anchor_fn, HELPER + anchor_fn, 1)

    added = 0
    for anchor, code, before in HOOKS:
        if anchor not in src:
            print("  !! не найден якорь: %s" % anchor.strip()[:55])
            continue
        repl = (code + anchor) if before else (anchor + "\n" + code)
        src = src.replace(anchor, repl, 1)
        added += 1

    if added == 0:
        sys.exit("paint_bds: ни одной точки не найдено")

    with open(path, "w", encoding="utf-8") as f:
        f.write(src)
    print("paint_bds: маркеров %d (цифры + полосы-признаки)" % added)
    return 0


if __name__ == "__main__":
    sys.exit(main())
