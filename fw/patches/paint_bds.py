#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
paint_bds.py — два независимых сигнала о состоянии BDS.

1. ЦИФРЫ (работают даже при сломанной консоли), верхняя строка, y=10:
       x=360 — 1, если BdsInitialize (точка входа драйвера) начал работу
       x=410 — 1, если BdsDxe установил gEfiBdsArchProtocolGuid
       x=260/310 — шаг BdsEntry (0..8)

2. ТЕКСТ в консоль (виден только если ConOut реально подключён к нашему GOP):
       при входе в BdsInitialize печатается "UGG-BDS-INIT"
       при входе в BdsEntry      печатается "UGG-BDS-ENTRY"

Это разом отвечает на вопрос: BDS не запускается (нет цифры) или запускается,
но консоль никуда не выводит (цифра есть, текста нет).

Идемпотентно.
"""

import os
import sys

MARK = "MsmPaintBdsState"

HELPER = r'''
//
// Отладка без UART: цифры состояния BDS (fw/patches/paint_bds.py)
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
MsmPaintBdsStep (
  IN UINTN  Step
  )
{
  MsmPaintBdsDigit (260, (Step / 10) % 10);
  MsmPaintBdsDigit (310, Step % 10);
}

'''

HOOKS = [
    # цифровые маркеры (видны всегда)
    ("  EFI_HANDLE  Handle;", "  MsmPaintBdsDigit (360, 1);\n", True),
    ("  Status = gBS->InstallMultipleProtocolInterfaces (", "  MsmPaintBdsDigit (410, 1);\n", True),
    ("  HotkeyTriggered = NULL;", "  MsmPaintBdsStep (0);\n", True),
    ('  DEBUG ((DEBUG_INFO, "[Bds] Entry...\\n"));', "  MsmPaintBdsStep (1);\n", False),
    ("  Status = gBS->LocateProtocol (&gEdkiiVariablePolicyProtocolGuid, NULL, (VOID **)&VariablePolicy);", "  MsmPaintBdsStep (2);\n", True),
    ("  InitializeHwErrRecSupport ();", "  MsmPaintBdsStep (3);\n", True),
    ("  BootOptionSupport = EFI_BOOT_OPTION_SUPPORT_APP | EFI_BOOT_OPTION_SUPPORT_SYSPREP;", "  MsmPaintBdsStep (4);\n", True),
    ('  // Cache the "BootNext" NV variable before calling any PlatformBootManagerLib APIs', "  MsmPaintBdsStep (5);\n", True),
    ("  PlatformBootManagerBeforeConsole ();", "  MsmPaintBdsStep (6);\n", True),
    ('  PERF_INMODULE_END ("PlatformBootManagerBeforeConsole");', "  MsmPaintBdsStep (7);\n", False),
    ('  PERF_INMODULE_END ("PlatformBootManagerAfterConsole");', "  MsmPaintBdsStep (8);\n", False),
    # текстовые метки (видны только при рабочем ConOut)
    ("  EFI_HANDLE  Handle;",
     '  if (gST->ConOut != NULL) {\n'
     '    gST->ConOut->OutputString (gST->ConOut, L"UGG-BDS-INIT\\r\\n");\n'
     '  }\n', True),
    ("  HotkeyTriggered = NULL;",
     '  if (gST->ConOut != NULL) {\n'
     '    gST->ConOut->OutputString (gST->ConOut, L"UGG-BDS-ENTRY\\r\\n");\n'
     '  }\n', True),
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
    print("paint_bds: меток %d (цифры + текстовые)" % added)
    return 0


if __name__ == "__main__":
    sys.exit(main())
