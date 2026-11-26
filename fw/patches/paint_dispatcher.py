#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
paint_dispatcher.py — счётчики диспетчера DXE цифрами (без UART).

Раскладка цифр в верхней строке экрана (y=10, семисегментные, 36x72):

    x=10,  60   — запущено драйверов
    x=110, 160  — обнаружено драйверов
    x=460, 510  — номер последнего запускаемого драйвера (по списку обнаружения,
                  то есть по порядку файлов в FV)  <-- главный ориентир
    (x=210, 260/310, 360, 410, 560, 610 — другие модули)

Идемпотентно.
"""

import os
import sys

MARK = "MsmPaintDriverNumber"

HELPER = r'''
//
// Отладка без UART: цифры диспетчера DXE (fw/patches/paint_dispatcher.py)
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
    { 0, 0, W, T },
    { W - T, 0, T, H / 2 },
    { W - T, H / 2, T, H / 2 },
    { 0, H - T, W, T },
    { 0, H / 2, T, H / 2 },
    { 0, 0, T, H / 2 },
    { 0, H / 2 - T / 2, W, T }
  };
  UINTN  I;

  /* стереть область под цифрой */
  for (Row = 0; Row < 100; Row++) {
    Ptr = Base + (Y + Row) * 2160 + X * 3;
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
  IN EFI_CORE_DRIVER_ENTRY  *DriverEntry
  )
{
  LIST_ENTRY  *Link;
  UINTN        Index = 0;
  UINTN        N = ++mUggDispatchCount;

  /* сколько запущено */
  MsmPaintDigit (10, 10, (N / 10) % 10);
  MsmPaintDigit (60, 10, N % 10);

  /* порядковый номер этого драйвера в списке обнаружения */
  for (Link = mDiscoveredList.ForwardLink; Link != &mDiscoveredList; Link = Link->ForwardLink) {
    Index++;
    if (Link == &DriverEntry->Link) {
      break;
    }
  }
  MsmPaintDigit (460, 10, (Index / 10) % 10);
  MsmPaintDigit (510, 10, Index % 10);
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

  MsmPaintDigit (110, 10, (Count / 10) % 10);
  MsmPaintDigit (160, 10, Count % 10);
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

    src = src.replace(ANCHOR_START, "        MsmPaintDriverNumber (DriverEntry);\n" + ANCHOR_START, 1)
    src = src.replace(ANCHOR_END, "  MsmPaintDiscoveredCount ();\n" + ANCHOR_END, 1)

    with open(path, "w", encoding="utf-8") as f:
        f.write(src)
    print("paint_dispatcher: добавлены цифры (запущено / обнаружено / номер драйвера)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
