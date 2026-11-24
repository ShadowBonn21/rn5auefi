#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
paint_stages.py — «покраска стадий» для отладки UEFI без UART.

Патчит PrePi (Silicon/Qualcomm/QcomPkg/PrePi/Pi.c), добавляя вызовы
MsmPaintBand(N) в контрольных точках. Каждая полоса — 100 строк (из 1280)
белым по framebuffer'у ugg (24bpp, stride 2160, база 0x90000000-256).

На экране видно, до какой стадии дошло:

    1 полоса  -> PrePiMain начался (код исполняется)
    2 полосы  -> посчитаны StackBase / UefiMemory (PCD читаются)
    3 полосы  -> MemoryPeim: карта памяти построена, MMU включён
    4 полосы  -> PlatformPeim: HOB'ы платформы созданы
    5 полос  -> DecompressFirstFv: сжатый FV распакован
    (дальше должен загрузиться DXE Core и наш UggFbDxe)

Идемпотентно: повторный запуск ничего не меняет.
"""

import os
import sys

MARK = "MsmPaintBand"

HELPER = r'''
//
// Отладка без UART: белая полоса N в framebuffer (см. fw/patches/paint_stages.py)
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

  for (Y = Band * 100; Y < Band * 100 + 100; Y++) {
    Row = Base + Y * 2160;
    for (X = 0; X < 2160; X++) {
      Row[X] = 0xFF;
    }
  }
}

'''

# (что искать, что вставить ПОСЛЕ найденного, номер полосы)
HOOKS = [
    ("  // Architecture-specific initialization",
     "  MsmPaintBand (1);", None),
    ("  StackBase      = (VOID *)(UefiMemoryBase + UefiMemorySize - StackSize);",
     "  MsmPaintBand (2);", None),
    ("  Status = MemoryPeim(UefiMemoryBase, UefiMemorySize);\n  ASSERT_EFI_ERROR (Status);",
     "  MsmPaintBand (3);", None),
    ("  Status = PlatformPeim();\n  ASSERT_EFI_ERROR (Status);",
     "  MsmPaintBand (4);", None),
    ("  Status = DecompressFirstFv();\n  ASSERT_EFI_ERROR (Status);",
     "  MsmPaintBand (5);", None),
]


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: paint_stages.py <edk2-msm-dir>")
    root = sys.argv[1]
    path = os.path.join(root, "Silicon/Qualcomm/QcomPkg/PrePi/Pi.c")
    if not os.path.isfile(path):
        sys.exit("нет файла: %s" % path)

    with open(path, "r", encoding="utf-8") as f:
        src = f.read()

    if MARK in src:
        print("paint_stages: уже пропатчено")
        return 0

    # 1) helper перед определением PrePiMain
    anchor = "VOID\nPrePiMain("
    if anchor not in src:
        sys.exit("paint_stages: не найден PrePiMain")
    src = src.replace(anchor, HELPER + anchor, 1)

    # 2) вызовы полос
    added = 0
    for anchor, call, _ in HOOKS:
        if anchor not in src:
            print("  !! не найден якорь: %s" % anchor.splitlines()[0][:60])
            continue
        src = src.replace(anchor, anchor + "\n" + call, 1)
        added += 1

    if added == 0:
        sys.exit("paint_stages: ни одна точка не найдена — патч не применён")

    with open(path, "w", encoding="utf-8") as f:
        f.write(src)
    print("paint_stages: добавлено полос: %d" % added)
    return 0


if __name__ == "__main__":
    sys.exit(main())
