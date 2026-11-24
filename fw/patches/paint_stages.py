#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
paint_stages.py — «покраска стадий» для отладки UEFI без UART.

Патчит два файла edk2-msm, добавляя вызовы MsmPaintBand(N): белая полоса
высотой 50 строк в framebuffer'e ugg (24bpp, stride 2160, база 0x90000000-256).

Silicon/Qualcomm/QcomPkg/PrePi/Pi.c:
    1 — PrePiMain начался
    2 — посчитаны StackBase/UefiMemory
    3 — MemoryPeim: карта памяти и MMU
    4 — PlatformPeim: HOB'ы платформы
    5 — DecompressFirstFv: сжатый FV распакован

Platform/RenegadePkg/Library/PlatformBootManagerLib/PlatformBm.c (BDS):
    6 — PlatformBootManagerBeforeConsole
    7 — PlatformBootManagerAfterConsole
    8 — BootLogoEnableLogo вернулся

Плюс сам драйвер UggFbDxe рисует полосу на 1150-й строке (PcdDebugStageBands),
когда GOP уже установлен.

Идемпотентно.
"""

import os
import sys

MARK = "MsmPaintBand"

HELPER = r'''
//
// Отладка без UART: белая полоса N (fw/patches/paint_stages.py)
//
STATIC
VOID
MsmPaintBand (
  IN UINTN  Band
  )
{
  UINT8  *Base = (UINT8 *)(UINTN)(0x90000000ULL - 256ULL);
  UINTN  Y;
  UINTN  X;
  UINT8  *Row;

  for (Y = Band * 100; Y < Band * 100 + 50; Y++) {
    Row = Base + Y * 2160;
    for (X = 0; X < 2160; X++) {
      Row[X] = 0xFF;
    }
  }
}

'''

PIPEI_HOOKS = [
    ("  // Architecture-specific initialization", "  MsmPaintBand (1);"),
    ("  StackBase      = (VOID *)(UefiMemoryBase + UefiMemorySize - StackSize);", "  MsmPaintBand (2);"),
    ("  Status = MemoryPeim(UefiMemoryBase, UefiMemorySize);\n  ASSERT_EFI_ERROR (Status);", "  MsmPaintBand (3);"),
    ("  Status = PlatformPeim();\n  ASSERT_EFI_ERROR (Status);", "  MsmPaintBand (4);"),
    ("  Status = DecompressFirstFv();\n  ASSERT_EFI_ERROR (Status);", "  MsmPaintBand (5);"),
]

BDS_HOOKS = [
    ("VOID EFIAPI PlatformBootManagerBeforeConsole(VOID)\n{", "  MsmPaintBand (6);"),
    ("VOID EFIAPI PlatformBootManagerAfterConsole(VOID)\n{", "  MsmPaintBand (7);"),
    ("  Status = BootLogoEnableLogo();", "  MsmPaintBand (8);"),
]


def patch_pi(root):
    path = os.path.join(root, "Silicon/Qualcomm/QcomPkg/PrePi/Pi.c")
    if not os.path.isfile(path):
        print("  нет %s" % path)
        return 0
    with open(path, "r", encoding="utf-8") as f:
        src = f.read()
    if MARK in src:
        print("  Pi.c: уже пропатчен")
        return 0
    anchor = "VOID\nPrePiMain("
    if anchor not in src:
        print("  Pi.c: не найден PrePiMain")
        return 0
    src = src.replace(anchor, HELPER + anchor, 1)
    n = 0
    for anchor, call in PIPEI_HOOKS:
        if anchor in src:
            src = src.replace(anchor, anchor + "\n" + call, 1)
            n += 1
    with open(path, "w", encoding="utf-8") as f:
        f.write(src)
    print("  Pi.c: полос %d" % n)
    return n


def patch_bds(root):
    path = os.path.join(root, "Platform/RenegadePkg/Library/PlatformBootManagerLib/PlatformBm.c")
    if not os.path.isfile(path):
        print("  нет %s" % path)
        return 0
    with open(path, "r", encoding="utf-8") as f:
        src = f.read()
    if MARK in src:
        print("  PlatformBm.c: уже пропатчен")
        return 0
    first = "VOID EFIAPI PlatformBootManagerBeforeConsole(VOID)"
    if first not in src:
        print("  PlatformBm.c: не найден BeforeConsole")
        return 0
    src = src.replace(first, HELPER + first, 1)
    n = 0
    for anchor, call in BDS_HOOKS:
        if anchor in src:
            src = src.replace(anchor, anchor + "\n" + call, 1)
            n += 1
    with open(path, "w", encoding="utf-8") as f:
        f.write(src)
    print("  PlatformBm.c: полос %d" % n)
    return n


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: paint_stages.py <edk2-msm-dir>")
    root = sys.argv[1]
    print("paint_stages:")
    total = patch_pi(root) + patch_bds(root)
    if total == 0:
        print("  (ничего не изменено)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
