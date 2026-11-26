#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
paint_cpudxe.py — шаг инициализации CpuDxe как ЦИФРА на экране.

Никаких полосок: в верхней строке (y=10, x=300) рисуется одна семисегментная
цифра — номер шага CpuDxeInitialize. Так и человеку, и мне видно однозначно.

Шаги:
    1 — перед InitializeExceptions
    2 — после InitializeExceptions
    3 — после InitializeDma
    4 — перед InstallMultipleProtocolInterfaces (CPU arch protocol)
    5 — после установки протокола
    6 — после SyncCacheConfig (в текущей сборке отключён)
    7 — перед CreateEventEx
    8 — перед return

ВАЖНО: файл берётся из ЗАКРЕПЛЁННОЙ версии edk2 (сабмодуль edk2-msm),
там другая сигнатура и нет блока RemapUnusedMemoryNx — якоря проверены
скриптом tools/audit_patches.py.
"""

import os
import sys

MARK = "MsmPaintStepDigit"

HELPER = r'''
//
// Отладка без UART: цифра шага в верхней строке (fw/patches/paint_cpudxe.py)
//
STATIC
VOID
MsmPaintStepDigits (
  IN UINTN  X,
  IN UINTN  Digit
  )
{
  STATIC CONST UINT8  Seg[10] = {
    0x3F, 0x06, 0x5B, 0x4F, 0x66, 0x6D, 0x7D, 0x07, 0x7F, 0x6F
  };
  UINT8  *Base = (UINT8 *)(UINTN)(0x90000000ULL - 256ULL);
  UINTN  W = 36;
  UINTN  H = 72;
  UINTN  T = 7;
  UINTN  Y0 = 10;
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

  /* стереть цифру (область 46x100) */
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

'''

# (якорь, номер шага, ставить ДО якоря?)
HOOKS = [
    ("  InitializeExceptions (&mCpu);", 1, True),
    ("  InitializeExceptions (&mCpu);", 2, False),
    ("  InitializeDma (&mCpu);", 3, False),
    ("  Status = gBS->InstallMultipleProtocolInterfaces (", 4, True),
    ("  mIsFlushingGCD = TRUE;", 5, True),
    ("  Status = gBS->CreateEventEx (", 7, True),
    ("  return Status;", 8, True),
]


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: paint_cpudxe.py <edk2-msm-dir>")
    path = os.path.join(sys.argv[1], "Common/edk2/ArmPkg/Drivers/CpuDxe/CpuDxe.c")
    if not os.path.isfile(path):
        sys.exit("нет файла: %s" % path)

    with open(path, "r", encoding="utf-8") as f:
        src = f.read()

    if MARK in src:
        print("paint_cpudxe: уже пропатчено")
        return 0

    anchor_fn = "CpuDxeInitialize (\n"
    idx = src.find("EFI_STATUS\n" + anchor_fn)
    if idx < 0:
        sys.exit("paint_cpudxe: не найдено определение CpuDxeInitialize")
    src = src[:idx] + HELPER + src[idx:]

    #
    # SyncCacheConfig на нашей карте памяти уходит в бесконечный цикл
    # (обход страничных таблиц). На время bring-up не вызываем.
    #
    src = src.replace(
        "  SyncCacheConfig (&mCpu);",
        "  /* ugg: SyncCacheConfig отключён, см. fw/patches/paint_cpudxe.py */",
        1,
    )

    n = 0
    for anchor, step, before in HOOKS:
        if anchor not in src:
            print("  !! не найден якорь для шага %d: %s" % (step, anchor.strip()[:50]))
            continue
        call = "  MsmPaintStepDigits (300, %d);" % step
        repl = (call + "\n" + anchor) if before else (anchor + "\n" + call)
        src = src.replace(anchor, repl, 1)
        n += 1

    if n == 0:
        sys.exit("paint_cpudxe: ни одной точки не найдено")

    with open(path, "w", encoding="utf-8") as f:
        f.write(src)
    print("paint_cpudxe: цифровых меток %d" % n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
