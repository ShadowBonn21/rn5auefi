#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
force_dispatch.py — форсировать запуск всех обнаруженных драйверов.

Проблема: на устройстве диспетчер DXE запускает только часть драйверов
(например, 11 из 15), причём ошибок ни при загрузке, ни при запуске нет.
Драйверы с Depex = TRUE (в частности BdsDxe) при этом тоже не запускаются,
что для штатного алгоритма ненормально.

Для bring-up это лечится принудительной планировкой: в CoreDispatcher
условие «Depex выполнен» заменяется на истину, и все обнаруженные драйверы
получают попытку запуска. Если какой-то драйвер действительно требует
отсутствующий протокол, он вернёт ошибку — но остальные запустятся.

Идемпотентно.
"""

import os
import sys

MARK = "ugg: форсируем запуск"

OLD = """      if (DriverEntry->Dependent) {
        if (CoreIsSchedulable (DriverEntry)) {"""
NEW = """      if (DriverEntry->Dependent) {
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
        sys.exit("force_dispatch: не найден участок проверки Depex")

    src = src.replace(OLD, NEW, 1)
    with open(path, "w", encoding="utf-8") as f:
        f.write(src)
    print("force_dispatch: условие Depex заменено на TRUE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
