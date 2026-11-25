#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
paint_cpudxe.py — метки внутри CpuDxeInitialize (ArmPkg/Drivers/CpuDxe/CpuDxe.c).

Рисует полосу начиная со строки 900: шаг k -> высота k*20 строк.
Шаги:
    1 — до InitializeExceptions()
    2 — после InitializeExceptions()
    3 — после InitializeDma()
    4 — после InstallMultipleProtocolInterfaces() (CPU arch + MemoryAttribute)
    5 — после SyncCacheConfig()   <-- главный подозреваемый
    6 — после CreateEventEx()
    7 — перед return EFI_SUCCESS

Трактовка: если полоса остановилась на 4 -> виснет SyncCacheConfig
(перестройка атрибутов по нашей карте памяти); на 3 -> InstallMultiple;
на 2 -> InitializeDma; на 1 -> исключения.
"""

import os
import sys

MARK = "MsmPaintCpuDxeStep"

HELPER = r'''
//
// Отладка без UART: шаг CpuDxeInitialize (fw/patches/paint_cpudxe.py)
//
STATIC
VOID
MsmPaintCpuDxeStep (
  IN UINTN  Step
  )
{
  UINT8  *Base = (UINT8 *)(UINTN)(0x90000000ULL - 256ULL);
  UINTN  K;
  UINTN  Y;
  UINTN  X;
  UINT8  *Row;

  /* полоски по 30 строк с зазором 10: шаг k -> строки 900+(k-1)*40 .. +30 */
  for (K = 1; K <= Step && K <= 8; K++) {
    for (Y = 900 + (K - 1) * 12; Y < 900 + (K - 1) * 12 + 8; Y++) {
      Row = Base + Y * 2160;
      for (X = 0; X < 2160; X++) {
        Row[X] = 0xFF;
      }
    }
  }

  /*
    «Разрушающие» метки: каждый следующий шаг стирает одну видимую деталь.
    По фото сразу видно, выполнялся ли шаг, даже если полоски не различимы.

      шаг >= 4  -> стирается область штрихкода (x 36..368, y 196..844)
      шаг >= 5  -> стирается область числа      (x 0..260,  y 0..100)
      шаг >= 6  -> закрашивается белым блок внизу справа (x 400..700, y 1150..1250)
  */
  if (Step >= 4) {
    for (Y = 196; Y < 844; Y++) {
      Row = Base + Y * 2160;
      for (X = 36; X < 368; X++) {
        Row[X * 3 + 0] = 0x00;
        Row[X * 3 + 1] = 0x00;
        Row[X * 3 + 2] = 0x00;
      }
    }
  }
  if (Step >= 5) {
    for (Y = 0; Y < 100; Y++) {
      Row = Base + Y * 2160;
      for (X = 0; X < 260; X++) {
        Row[X * 3 + 0] = 0x00;
        Row[X * 3 + 1] = 0x00;
        Row[X * 3 + 2] = 0x00;
      }
    }
  }

}

'''

HOOKS = [
    ("  InitializeExceptions ();", "  MsmPaintCpuDxeStep (1);", True),
    ("  InitializeExceptions ();", "  MsmPaintCpuDxeStep (2);", False),
    ("  InitializeDma (&mCpu);", "  MsmPaintCpuDxeStep (3);", False),
    ("  if (FALSE) {", "  MsmPaintCpuDxeStep (4);", True),
    ("  CpuHandle = NULL;", "  MsmPaintCpuDxeStep (5);", True),
    ("  mIsFlushingGCD = TRUE;", "  MsmPaintCpuDxeStep (6);", True),
    ("  mIsFlushingGCD = FALSE;", "  MsmPaintCpuDxeStep (7);", False),
    ("  EfiCreateProtocolNotifyEvent (", "  MsmPaintCpuDxeStep (8);", True),
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

    anchor = "CpuDxeInitialize (\n"
    idx = src.find("EFI_STATUS\nEFIAPI\n" + anchor)
    if idx < 0:
        idx = src.find("EFI_STATUS\nCpuDxeInitialize (\n")
    if idx < 0:
        sys.exit("paint_cpudxe: не найдено определение CpuDxeInitialize")
    src = src[:idx] + HELPER + src[idx:]

    #
    # ugg: блок RemapUnusedMemoryNx() фатален на нашей карте памяти
    # (проверено метками: шаг 3 -> тишина). Отключаем его прямо здесь,
    # чтобы не править DSC (PCD не объявлен в DEC, доступных сборке).
    #
    src = src.replace(
        "if (FeaturePcdGet (PcdRemapUnusedMemoryNx)) {",
        "if (FALSE) {  /* ugg: see fw/patches/paint_cpudxe.py */",
    )

    n = 0
    for anchor, call, before in HOOKS:
        if anchor not in src:
            print("  !! не найден якорь: %s" % anchor.strip()[:50])
            continue
        repl = (call + "\n" + anchor) if before else (anchor + "\n" + call)
        src = src.replace(anchor, repl, 1)
        n += 1

    if n == 0:
        sys.exit("paint_cpudxe: ни одной точки не найдено")

    with open(path, "w", encoding="utf-8") as f:
        f.write(src)
    print("paint_cpudxe: точек %d" % n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
