#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
force_dispatch.py — запустить каждый обнаруженный драйвер РОВНО ОДИН раз,
игнорируя Depex (режим bring-up).

Зачем: на устройстве штатный диспетчер запускает не все драйверы (11 из 15),
причём ни ошибок загрузки, ни ошибок запуска нет. Среди не запущенных
оказывается BdsDxe (у него Depex = TRUE), из-за чего UEFI не доходит до BDS
и консоль не поднимается.

ВАЖНО: первая версия этого патча заменяла проверку Depex на TRUE и приводила
к бесконечному перезапуску уже запущенных драйверов (симптом: BdsInitialize
выполнялся многократно, а BdsEntry так и не наступал). Здесь условие другое —
запускаем только ещё НЕ инициализированные драйверы, поэтому цикл конечен.

Идемпотентно.
"""

import os
import sys

MARK = "ugg: запускаем каждый драйвер один раз"

OLD = """      if (DriverEntry->Dependent) {
        if (CoreIsSchedulable (DriverEntry)) {
          CoreInsertOnScheduledQueueWhileProcessingBeforeAndAfter (DriverEntry);
          ReadyToRun = TRUE;
        }
      } else {
        if (DriverEntry->Unrequested) {
          DEBUG ((DEBUG_DISPATCH, "Evaluate DXE DEPEX for FFS(%g)\\n", &DriverEntry->FileName));
          DEBUG ((DEBUG_DISPATCH, "  SOR                                             = Not Requested\\n"));
          DEBUG ((DEBUG_DISPATCH, "  RESULT = FALSE\\n"));
        }
      }"""

NEW = """      //
      // ugg: см. fw/patches/force_dispatch.py — запускаем драйвер один раз,
      // не глядя на Depex. Флаг Initialized не даёт перезапускать его снова,
      // поэтому цикл диспетчера остаётся конечным.
      //
      if (!DriverEntry->Initialized) {
        CoreInsertOnScheduledQueueWhileProcessingBeforeAndAfter (DriverEntry);
        ReadyToRun = TRUE;
      }"""

OLD_V1 = """      if (DriverEntry->Dependent) {
        if (TRUE) {  /* ugg: форсируем запуск, см. fw/patches/force_dispatch.py */"""


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: force_dispatch.py <edk2-msm-dir>")
    path = os.path.join(sys.argv[1], "Common/edk2/MdeModulePkg/Core/Dxe/Dispatcher/Dispatcher.c")
    if not os.path.isfile(path):
        sys.exit("нет файла: %s" % path)

    with open(path, "r", encoding="utf-8") as f:
        src = f.read()

    if MARK in src:
        print("force_dispatch: уже применено")
        return 0

    if OLD not in src:
        sys.exit("force_dispatch: не найден участок планировки драйверов (ожидался штатный вид)")

    src = src.replace(OLD, NEW, 1)
    with open(path, "w", encoding="utf-8") as f:
        f.write(src)
    print("force_dispatch: включён однократный запуск всех драйверов")
    return 0


if __name__ == "__main__":
    sys.exit(main())
