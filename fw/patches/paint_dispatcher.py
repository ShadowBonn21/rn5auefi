#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
paint_dispatcher.py — «счётчик драйверов» в диспетчере DXE.

Перед запуском каждого драйвера рисуем белую область сверху высотой
count*6 строк (24bpp, stride 2160, база 0x90000000-256).

Поскольку UggFbDxe при инициализации очищает экран, всё нарисованное до него
стирается, а метки, поставленные после, остаются. Поэтому итоговая высота
делится на 6 и даёт номер драйвера, на котором диспетчеризация встала.

Пример: белое поле 174 строки -> 174/6 = 29 -> завис 29-й драйвер.

Идемпотентно.
"""

import os
import sys

MARK = "MsmPaintDriverCount"

HELPER = r'''
//
// Отладка без UART: номер запускаемого драйвера (fw/patches/paint_dispatcher.py)
//
STATIC UINTN  mUggDispatchCount = 0;

STATIC
VOID
MsmPaintDriverCount (
  VOID
  )
{
  UINT8  *Base = (UINT8 *)(UINTN)(0x90000000ULL - 256ULL);
  UINTN  Rows;
  UINTN  Y;
  UINTN  X;
  UINT8  *Row;

  mUggDispatchCount++;
  Rows = mUggDispatchCount * 6;
  if (Rows > 1200) {
    Rows = 1200;
  }

  for (Y = 0; Y < Rows; Y++) {
    Row = Base + Y * 2160;
    for (X = 0; X < 2160; X++) {
      Row[X] = 0xFF;
    }
  }
}

'''

ANCHOR = "        Status = CoreStartImage (DriverEntry->ImageHandle, NULL, NULL);"
CALL = "        MsmPaintDriverCount ();\n"


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

    if ANCHOR not in src:
        sys.exit("paint_dispatcher: не найден вызов CoreStartImage в CoreDispatcher")

    # helper — перед определением CoreDispatcher
    anchor_fn = "CoreDispatcher (\n"
    idx = src.find(anchor_fn)
    if idx < 0:
        sys.exit("paint_dispatcher: не найдено определение CoreDispatcher")
    src = src[:idx] + HELPER + src[idx:]

    src = src.replace(ANCHOR, CALL + ANCHOR, 1)
    with open(path, "w", encoding="utf-8") as f:
        f.write(src)
    print("paint_dispatcher: счётчик добавлен")
    return 0


if __name__ == "__main__":
    sys.exit(main())
