#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
paint_dispatcher.py — счётчики диспетчера DXE без UART.

Что рисуется (24bpp, stride 2160, база 0x90000000-256):

  * СЕМИСЕГМЕНТНЫЕ ЦИФРЫ в левом верхнем углу (x=10 и x=60, y=10) —
    количество ЗАПУЩЕННЫХ драйверов (обновляется перед каждым запуском).

  * ТАКИЕ ЖЕ ЦИФРЫ правее (x=150 и x=200, y=10) — количество ОБНАРУЖЕННЫХ
    драйверов (рисуется в конце CoreDispatcher). Разница между числами
    показывает, сколько драйверов диспетчер не смог загрузить.

  * ШТРИХКОД GUID последнего запускаемого драйвера (8 столбцов x 16 строк,
    клетка 40 px, начиная с (40,200)) — расшифровывается по фото.

Идемпотентно.
"""

import os
import sys

MARK = "MsmPaintDriverNumber"

HELPER = r'''
//
// Отладка без UART: счётчики диспетчера DXE (fw/patches/paint_dispatcher.py)
//
STATIC UINTN  mUggDispatchCount = 0;

STATIC
VOID
MsmPaintDigit (
  IN UINTN  X,
  IN UINTN  Y,
  IN UINTN  Digit
  )
{
  /* биты сегментов: a=1, b=2, c=4, d=8, e=16, f=32, g=64 */
  STATIC CONST UINT8  Seg[10] = {
    0x3F, 0x06, 0x5B, 0x4F, 0x66, 0x6D, 0x7D, 0x07, 0x7F, 0x6F
  };
  UINT8  *Base = (UINT8 *)(UINTN)(0x90000000ULL - 256ULL);
  UINTN  W = 36;
  UINTN  H = 72;
  UINTN  T = 7;
  UINTN  S = Seg[Digit % 10];
  UINTN  Row;
  UINTN  Col;
  UINT8  *Ptr;
  CONST UINTN  Rect[7][4] = {
    { 0, 0, W, T },                 /* a */
    { W - T, 0, T, H / 2 },         /* b */
    { W - T, H / 2, T, H / 2 },     /* c */
    { 0, H - T, W, T },             /* d */
    { 0, H / 2, T, H / 2 },         /* e */
    { 0, 0, T, H / 2 },             /* f */
    { 0, H / 2 - T / 2, W, T }      /* g */
  };
  UINTN  I;

  for (I = 0; I < 7; I++) {
    if ((S & (1u << I)) == 0) {
      continue;
    }
    for (Row = 0; Row < Rect[I][3]; Row++) {
      Ptr = Base + (Y + Rect[I][1] + Row) * 2160 + (X + Rect[I][0]) * 3;
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
MsmPaintDriverNumber (
  VOID
  )
{
  UINT8  *Base = (UINT8 *)(UINTN)(0x90000000ULL - 256ULL);
  UINTN  N = ++mUggDispatchCount;
  UINTN  Row;
  UINTN  Col;
  UINT8  *Ptr;

  /* стереть область под двумя цифрами */
  for (Row = 0; Row < 100; Row++) {
    Ptr = Base + Row * 2160;
    for (Col = 0; Col < 260; Col++) {
      Ptr[Col * 3 + 0] = 0x00;
      Ptr[Col * 3 + 1] = 0x00;
      Ptr[Col * 3 + 2] = 0x00;
    }
  }

  MsmPaintDigit (10, 10, (N / 10) % 10);
  MsmPaintDigit (60, 10, N % 10);
}

STATIC
VOID
MsmPaintDiscoveredCount (
  VOID
  )
{
  LIST_ENTRY  *Link;
  UINTN        Count = 0;

  for (Link = mDiscoveredList.ForwardLink; Link != &mDiscoveredList; Link = Link->ForwardLink) {
    Count++;
  }

  /* правее: количество обнаруженных драйверов */
  MsmPaintDigit (150, 10, (Count / 10) % 10);
  MsmPaintDigit (200, 10, Count % 10);
}

STATIC
VOID
MsmPaintGuid (
  IN EFI_GUID  *Guid
  )
{
  UINT8  *Base = (UINT8 *)(UINTN)(0x90000000ULL - 256ULL);
  UINT8  *G    = (UINT8 *)Guid;
  UINTN  Cell  = 40;
  UINTN  OX    = 40;
  UINTN  OY    = 200;
  UINTN  Row;
  UINTN  Col;
  UINTN  I;
  UINTN  B;
  UINT8  *Ptr;
  UINT8  Bit;

  for (Row = 0; Row < Cell * 16 + 8; Row++) {
    Ptr = Base + (OY - 4 + Row) * 2160 + (OX - 4) * 3;
    for (Col = 0; Col < Cell * 8 + 8; Col++) {
      UINT8 V = ((Row < 4) || (Row >= Cell * 16 + 4) ||
                 (Col < 4) || (Col >= Cell * 8 + 4)) ? 0xFF : 0x00;
      Ptr[Col * 3 + 0] = V;
      Ptr[Col * 3 + 1] = V;
      Ptr[Col * 3 + 2] = V;
    }
  }

  for (I = 0; I < 16; I++) {
    for (B = 0; B < 8; B++) {
      Bit = (UINT8)((G[I] >> (7 - B)) & 1);
      for (Row = 0; Row < Cell - 2; Row++) {
        Ptr = Base + (OY + I * Cell + Row) * 2160 + (OX + B * Cell) * 3;
        for (Col = 0; Col < Cell - 2; Col++) {
          Ptr[Col * 3 + 0] = Bit ? 0xFF : 0x00;
          Ptr[Col * 3 + 1] = Bit ? 0xFF : 0x00;
          Ptr[Col * 3 + 2] = Bit ? 0xFF : 0x00;
        }
      }
    }
  }
}

'''

ANCHOR_START = "        Status = CoreStartImage (DriverEntry->ImageHandle, NULL, NULL);"
ANCHOR_END = "  CoreCloseEvent (DxeDispatchEvent);"


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: paint_dispatcher.py <edk2-msm-dir>")
    path = os.path.join(sys.argv[1], "Common/edk2/MdeModulePkg/Core/Dxe/Dispatcher/Dispatcher.c")
    if not os.path.isfile(path):
        sys.exit("нет файла: %s" % path)

    with open(path, "r", encoding="utf-8") as f:
        src = f.read()

    if MARK in src:
        print("paint_dispatcher: уже пропатчено")
        return 0

    if ANCHOR_START not in src:
        sys.exit("paint_dispatcher: не найден вызов CoreStartImage")
    if ANCHOR_END not in src:
        sys.exit("paint_dispatcher: не найден CoreCloseEvent в конце CoreDispatcher")

    anchor_fn = "EFI_STATUS\nEFIAPI\nCoreDispatcher ("
    idx = src.find(anchor_fn)
    if idx < 0:
        sys.exit("paint_dispatcher: не найдено определение CoreDispatcher")
    src = src[:idx] + HELPER + src[idx:]

    src = src.replace(
        ANCHOR_START,
        "        MsmPaintDriverNumber ();\n"
        "        MsmPaintGuid (&DriverEntry->FileName);\n" + ANCHOR_START,
        1,
    )
    src = src.replace(ANCHOR_END, "  MsmPaintDiscoveredCount ();\n" + ANCHOR_END, 1)

    with open(path, "w", encoding="utf-8") as f:
        f.write(src)
    print("paint_dispatcher: добавлены счётчик запусков, счётчик обнаруженных и штрихкод")
    return 0


if __name__ == "__main__":
    sys.exit(main())
