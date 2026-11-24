#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
quiet_debug.py — переключить DebugLib на «пустую» реализацию.

Зачем: в edk2-msm при USE_UART=0 используется

    DebugLib|MdePkg/Library/BaseDebugLibSerialPort/...   (пишет через SerialPortLib)
    SerialPortLib|.../FrameBufferSerialPortLib/...       (пишет В FRAMEBUFFER)

FrameBufferSerialPortLib рассчитан на 32bpp и на свой адрес буфера. На ugg
панель 24bpp, база сдвинута (−256 байт), поэтому первая же строка вида
DEBUG((...)) внутри BdsEntry валит загрузку (проверено: метки 1 есть, 2 нет).

Для отладки без UART отладочный вывод не нужен — выключаем его целиком,
а прогресс отслеживаем белыми полосами в framebuffer (paint_bds.py).

Идемпотентно.
"""

import os
import sys

OLD = "  DebugLib|MdePkg/Library/BaseDebugLibSerialPort/BaseDebugLibSerialPort.inf"
NEW = "  DebugLib|MdePkg/Library/BaseDebugLibNull/BaseDebugLibNull.inf"


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: quiet_debug.py <edk2-msm-dir>")
    path = os.path.join(sys.argv[1], "Silicon/Qualcomm/QcomPkg/QcomCommonDsc.inc")
    if not os.path.isfile(path):
        sys.exit("нет файла: %s" % path)

    with open(path, "r", encoding="utf-8") as f:
        src = f.read()

    if NEW in src:
        print("quiet_debug: уже включено")
        return 0
    if OLD not in src:
        sys.exit("quiet_debug: не нашёл строку DebugLib|BaseDebugLibSerialPort")

    src = src.replace(OLD, NEW + "  # fw/patches/quiet_debug.py: без вывода в FB (24bpp)", 1)
    with open(path, "w", encoding="utf-8") as f:
        f.write(src)
    print("quiet_debug: DebugLib -> BaseDebugLibNull")
    return 0


if __name__ == "__main__":
    sys.exit(main())
