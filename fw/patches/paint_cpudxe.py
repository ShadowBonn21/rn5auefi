#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
paint_cpudxe.py — метки внутри CpuDxeInitialize.

ВАЖНО: сборка использует ЗАКРЕПЛЁННУЮ версию edk2 из сабмодуля edk2-msm,
а не master. В ней функция выглядит так (ArmPkg/Drivers/CpuDxe/CpuDxe.c):

    InitializeExceptions (&mCpu);
    InitializeDma (&mCpu);
    Status = gBS->InstallMultipleProtocolInterfaces (   <-- CPU arch protocol
                 &mCpuHandle, &gEfiCpuArchProtocolGuid, &mCpu, NULL);
    mIsFlushingGCD = TRUE;
    SyncCacheConfig (&mCpu);                            <-- перестройка атрибутов
    mIsFlushingGCD = FALSE;
    Status = gBS->CreateEventEx (...);
    return Status;

Метки: полоса-шаг (по 8 строк, шаг 12 строк, начиная со строки 900 экрана).

    1 — перед InitializeExceptions
    2 — после InitializeExceptions
    3 — после InitializeDma
    4 — перед InstallMultipleProtocolInterfaces
    5 — после установки (перед mIsFlushingGCD = TRUE)
    6 — после SyncCacheConfig
    7 — перед CreateEventEx
    8 — перед return

Плюс диагностика без экрана: перед return вызывается холодная перезагрузка.
Если телефон перезагрузился — значит весь CpuDxe отработал (и «зависание»
на экране было замороженным кадром); если нет — код стоит на месте.
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

  /* полоски по 8 строк, шаг 12 строк: шаг k -> 900+(k-1)*12 .. +8 */
  for (K = 1; K <= Step && K <= 8; K++) {
    for (Y = 900 + (K - 1) * 12; Y < 900 + (K - 1) * 12 + 8; Y++) {
      Row = Base + Y * 2160;
      for (X = 0; X < 2160; X++) {
        Row[X] = 0xFF;
      }
    }
  }

  /* «разрушающие» метки: шаг >= 4 стирает штрихкод, шаг >= 5 — число */
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

# (якорь, номер шага, ставить ДО якоря?)
HOOKS = [
    ("  InitializeExceptions (&mCpu);", 1, True),
    ("  InitializeExceptions (&mCpu);", 2, False),
    ("  InitializeDma (&mCpu);", 3, False),
    ("  Status = gBS->InstallMultipleProtocolInterfaces (", 4, True),
    ("  mIsFlushingGCD = TRUE;", 5, True),
    ("  SyncCacheConfig (&mCpu);", 6, False),
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

    anchor = "CpuDxeInitialize (\n"
    idx = src.find("EFI_STATUS\n" + anchor)
    if idx < 0:
        sys.exit("paint_cpudxe: не найдено определение CpuDxeInitialize")
    src = src[:idx] + HELPER + src[idx:]

    #
    # ugg: SyncCacheConfig() обходит страничные таблицы и на нашей карте
    # памяти уходит в бесконечный цикл (проверено метками: шаг 5 -> тишина).
    # На время bring-up не синхронизируем GCD с MMU: защиты памяти всё равно
    # отключены PCD'ами, так что атрибуты GCD не влияют на работу драйверов.
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
        call = "  MsmPaintCpuDxeStep (%d);" % step
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
