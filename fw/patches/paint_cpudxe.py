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
  UINTN  Rows = Step * 20;
  UINTN  Y;
  UINTN  X;
  UINT8  *Row;

  for (Y = 900; Y < 900 + Rows && Y < 1270; Y++) {
    Row = Base + Y * 2160;
    for (X = 0; X < 2160; X++) {
      Row[X] = 0xFF;
    }
  }
}

'''

HOOKS = [
    ("  ArmDisableInterrupts ();", "  MsmPaintCpuDxeStep (1);", True),
    ("  InitializeExceptions ();", "  MsmPaintCpuDxeStep (2);", False),
    ("  InitializeDma (&mCpu);", "  MsmPaintCpuDxeStep (3);", False),
    ("  if (FeaturePcdGet (PcdRemapUnusedMemoryNx)) {", "  MsmPaintCpuDxeStep (4);", True),
    ("  mIsFlushingGCD = FALSE;", "  MsmPaintCpuDxeStep (5);", False),
    ("  EfiCreateProtocolNotifyEvent (", "  MsmPaintCpuDxeStep (6);", True),
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
