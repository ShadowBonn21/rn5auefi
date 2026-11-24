#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
minimal_prepi_entry.py — замена пролога PrePi на минимальный (фикс для ugg).

Проблема (проверено на устройстве):
  апстримовый `_ModuleEntryPoint` в Silicon/Qualcomm/QcomPkg/PrePi/ModuleEntryPoint.S
  делает до вызова CEntryPoint: выключение прерываний/кешей/MMU, `msr sctlr_el1`
  с битом SPAN, заполнение 2 КБ векторов, обнуление 256 КБ стека SIMD-инструкцией
  `st4`, инвалидацию кеша и включение кешей. На ugg (LK внутри, состояние CPU
  не совпадает с тем, что ожидает апстрим) это валится — на экране остаётся
  только наша отладочная полоса, PrePiMain не стартует.

  Обход пролога (стаб, вызывающий CEntryPoint напрямую) — PrePiMain проходит
  все стадии вплоть до распаковки FV. Значит достаточно оставить от пролога
  только: сохранить FDT, выставить стек и позвать CEntryPoint. Настройку MMU
  и кешей делает MemoryPeim уже по нашей карте памяти.

Идемпотентно (по маркеру "ugg minimal prologue").
"""

import os
import sys

MARK = "ugg minimal prologue"

NEW_BODY = r"""_ModuleEntryPoint:
  //
  // ugg minimal prologue (see fw/patches/minimal_prepi_entry.py):
  // no cache/MMU/SPAN/vector/SIMD-stack-clear steps, they crash before
  // CEntryPoint on this device. MMU is configured later by MemoryPeim
  // from our own memory map.
  //
  mov x10, FixedPcdGet64 (PcdDeviceTreeStore)
  str x0, [x10]              // keep FDT passed by LK

  ldr x0, _StackBase
  ldr x1, _StackSize
  add sp, x0, x1             // PrePi stack top

  bl CEntryPoint

"""


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: minimal_prepi_entry.py <edk2-msm-dir>")
    path = os.path.join(sys.argv[1], "Silicon/Qualcomm/QcomPkg/PrePi/ModuleEntryPoint.S")
    if not os.path.isfile(path):
        sys.exit("нет файла: %s" % path)

    with open(path, "r", encoding="utf-8") as f:
        src = f.read()

    if MARK in src:
        print("minimal_prepi_entry: уже применено")
        return 0

    start = src.find("_ModuleEntryPoint:")
    end = src.find(".align 3\ndead:")
    if start < 0 or end < 0 or end <= start:
        # попробуем найти dead: в другом написании
        end = src.find("\ndead:")
        if start < 0 or end <= start:
            sys.exit("не нашёл границы пролога (_ModuleEntryPoint .. dead:)")

    old = src[start:end]
    print("старый пролог: %d байт, %d строк" % (len(old), old.count("\n")))
    src = src[:start] + NEW_BODY + src[end:]

    with open(path, "w", encoding="utf-8") as f:
        f.write(src)
    print("пролог заменён на минимальный (стек + CEntryPoint)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
