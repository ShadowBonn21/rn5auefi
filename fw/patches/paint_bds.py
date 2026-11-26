#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
paint_bds.py — состояние BDS как ЦИФРЫ в верхней строке экрана.

Полоски убраны: теперь на экране одна строка цифр (y=10):

    x=360, 410 — шаг BdsEntry (0..8), две цифры
    x=500      — 1, если точка входа BdsDxe (BdsInitialize) начала работу
    x=560      — 1, если BdsDxe установил gEfiBdsArchProtocolGuid

Шаги BdsEntry:
    0 — BdsEntry начался
    1 — отладочная строка пройдена
    2 — перед LocateProtocol(VariablePolicy)
    3 — перед InitializeHwErrRecSupport
    4 — перед инициализацией BootOptionSupport
    5 — перед кэшированием BootNext
    6 — перед PlatformBootManagerBeforeConsole
    7 — после PlatformBootManagerBeforeConsole
    8 — после PlatformBootManagerAfterConsole

Идемпотентно.
"""

import os
import sys

MARK = "MsmPaintBdsStep"

HELPER = r'''
//
// Отладка без UART: цифры состояния BDS (fw/patches/paint_bds.py)
//
STATIC
VOID
MsmPaintBdsDigits (
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
MsmPaintBdsStep (
  IN UINTN  Step
  )
{
  MsmPaintBdsDigits (260, (Step / 10) % 10);
  MsmPaintBdsDigits (310, Step % 10);
}

'''

# (якорь, шаг: int для BdsEntry или ("flag", x) для флагов, ставить ДО якоря?)
HOOKS = [
    ("  EFI_HANDLE  Handle;", ("flag", 360), True),
    ("  Status = gBS->InstallMultipleProtocolInterfaces (", ("flag", 410), True),
    ("  HotkeyTriggered = NULL;", 0, True),
    ('  DEBUG ((DEBUG_INFO, "[Bds] Entry...\\n"));', 1, False),
    ("  Status = gBS->LocateProtocol (&gEdkiiVariablePolicyProtocolGuid, NULL, (VOID **)&VariablePolicy);", 2, True),
    ("  InitializeHwErrRecSupport ();", 3, True),
    ("  BootOptionSupport = EFI_BOOT_OPTION_SUPPORT_APP | EFI_BOOT_OPTION_SUPPORT_SYSPREP;", 4, True),
    ('  // Cache the "BootNext" NV variable before calling any PlatformBootManagerLib APIs', 5, True),
    ("  PlatformBootManagerBeforeConsole ();", 6, True),
    ('  PERF_INMODULE_END ("PlatformBootManagerBeforeConsole");', 7, False),
    ('  PERF_INMODULE_END ("PlatformBootManagerAfterConsole");', 8, False),
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
    for anchor, step, before in HOOKS:
        if anchor not in src:
            print("  !! не найден якорь: %s" % anchor.strip()[:55])
            continue
        if isinstance(step, tuple):
            call = "  MsmPaintBdsDigits (%d, 1);" % step[1]
        else:
            call = "  MsmPaintBdsStep (%d);" % step
        repl = (call + "\n" + anchor) if before else (anchor + "\n" + call)
        src = src.replace(anchor, repl, 1)
        added += 1

    if added == 0:
        sys.exit("paint_bds: ни одной точки не найдено")

    with open(path, "w", encoding="utf-8") as f:
        f.write(src)
    print("paint_bds: цифровых меток %d" % added)
    return 0


if __name__ == "__main__":
    sys.exit(main())
