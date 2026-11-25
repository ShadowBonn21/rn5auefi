#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
null_serial.py — заменить SerialPortLib на пустую реализацию.

Зачем: при USE_UART=0 edk2-msm подставляет

    SerialPortLib|Silicon/Qualcomm/QcomPkg/Library/FrameBufferSerialPortLib/...

Эта библиотека «печатает» символы прямо в framebuffer, предполагая 32bpp и
свой размер экрана. На ugg панель 24bpp (stride 2160, база −256 байт), поэтому
её вывод превращается в искажённые глифы, заливающие весь экран.

Кто её использует даже без консольных драйверов:
  * DXE-ядро — печать дампа при исключении;
  * любые ASSERT/DEBUG-пути, которым нужен SerialPortLib напрямую.

Заменяем путь во ВСЕХ секциях DSC (в файле их несколько: common, AARCH64 и т.п.),
чтобы не осталось ни одного «печатающего» варианта.

Идемпотентно.
"""

import os
import sys

OLD = "Silicon/Qualcomm/QcomPkg/Library/FrameBufferSerialPortLib/FrameBufferSerialPortLib.inf"
NEW = "Common/edk2/MdePkg/Library/BaseSerialPortLibNull/BaseSerialPortLibNull.inf"


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: null_serial.py <edk2-msm-dir>")
    path = os.path.join(sys.argv[1], "Silicon/Qualcomm/QcomPkg/QcomCommonDsc.inc")
    if not os.path.isfile(path):
        sys.exit("нет файла: %s" % path)

    with open(path, "r", encoding="utf-8") as f:
        src = f.read()

    if NEW in src and OLD not in src:
        print("null_serial: уже заменено")
        return 0

    n = src.count(OLD)
    if n == 0:
        sys.exit("null_serial: не нашёл FrameBufferSerialPortLib")

    src = src.replace(OLD, NEW)
    with open(path, "w", encoding="utf-8") as f:
        f.write(src)
    print("null_serial: заменено вхождений %d" % n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
