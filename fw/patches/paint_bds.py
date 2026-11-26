#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
paint_bds.py — дискретные метки в BdsDxe.

Все метки — отдельные горизонтальные полоски на своих строках, поэтому по фото
однозначно видно, какие шаги выполнены (полосы не сливаются).

Строки экрана (24bpp, stride 2160, база 0x90000000-256):

    1150..1167 — BdsInitialize: точка входа (драйвер BdsDxe начал работу)
    1175..1192 — BdsInitialize: установка gEfiBdsArchProtocolGuid выполнена
    --- далее шаги BdsEntry, шаг 100 строк ---
    60..89   — BdsEntry начался
    160..189 — строка DEBUG пройдена
    260..289 — перед LocateProtocol(VariablePolicy)
    360..389 — перед InitializeHwErrRecSupport
    460..489 — перед инициализацией BootOptionSupport
    560..589 — перед кэшированием BootNext
    660..689 — перед PlatformBootManagerBeforeConsole
    760..789 — после PlatformBootManagerBeforeConsole
    860..889 — после PlatformBootManagerAfterConsole

Идемпотентно.
"""

import os
import sys

MARK = "MsmPaintBdsStep"

HELPER = r'''
//
// Отладка без UART: шаг BDS (fw/patches/paint_bds.py)
//
STATIC
VOID
MsmPaintBdsStep (
  IN UINTN  Step
  )
{
  UINT8  *Base = (UINT8 *)(UINTN)(0x90000000ULL - 256ULL);
  UINTN  Y;
  UINTN  X;
  UINT8  *Row;

  /* полоска шага: строки 60 + Step*100 .. +30 */
  for (Y = 60 + Step * 100; Y < 60 + Step * 100 + 30; Y++) {
    Row = Base + Y * 2160;
    for (X = 0; X < 2160; X++) {
      Row[X] = 0xFF;
    }
  }
}

//
// Метка точки входа BdsDxe: строки 20 + Idx*20 .. +15
//
STATIC
VOID
MsmPaintInitMark (
  IN UINTN  Idx
  )
{
  UINT8  *Base = (UINT8 *)(UINTN)(0x90000000ULL - 256ULL);
  UINTN  Y;
  UINTN  X;
  UINT8  *Row;

  for (Y = 1150 + Idx * 25; Y < 1150 + Idx * 25 + 18; Y++) {
    Row = Base + Y * 2160;
    for (X = 0; X < 2160; X++) {
      Row[X] = 0xFF;
    }
  }
}

'''

# (якорь, шаг: int для BdsEntry или "initN" для точки входа, ставить ДО якоря?)
HOOKS = [
    ("  EFI_HANDLE  Handle;", "init0", True),
    ("  Status = gBS->InstallMultipleProtocolInterfaces (", "init1", True),
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

    # helper вставляем перед определением BdsInitialize (первая из функций)
    anchor_fn = "EFI_STATUS\nEFIAPI\nBdsInitialize ("
    if anchor_fn in src:
        src = src.replace(anchor_fn, HELPER + anchor_fn, 1)
    else:
        anchor_fn = "VOID\nEFIAPI\nBdsEntry ("
        if anchor_fn not in src:
            sys.exit("paint_bds: не найдены ни BdsInitialize, ни BdsEntry")
        src = src.replace(anchor_fn, HELPER + anchor_fn, 1)

    added = 0
    for anchor, step, before in HOOKS:
        if anchor not in src:
            print("  !! не найден якорь: %s" % anchor.strip()[:55])
            continue
        if isinstance(step, str) and step.startswith("init"):
            call = "  MsmPaintInitMark (%s);" % step[4:]
        else:
            call = "  MsmPaintBdsStep (%d);" % step
        repl = (call + "\n" + anchor) if before else (anchor + "\n" + call)
        src = src.replace(anchor, repl, 1)
        added += 1

    if added == 0:
        sys.exit("paint_bds: ни одной точки не найдено")

    with open(path, "w", encoding="utf-8") as f:
        f.write(src)
    print("paint_bds: точек %d" % added)
    return 0


if __name__ == "__main__":
    sys.exit(main())
