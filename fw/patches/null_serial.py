#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
null_serial.py — заменить SerialPortLib на пустую реализацию.

Зачем: в edk2-msm при USE_UART=0 стоит

    SerialPortLib|.../FrameBufferSerialPortLib/FrameBufferSerialPortLib.inf

Эта библиотека «печатает» символы прямо в framebuffer, предполагая 32bpp и
свой размер экрана. На ugg панель 24bpp (stride 2160), поэтому её вывод
превращается в искажённые глифы, заливающие экран.

Кто её использует даже без консольных драйверов:
  * DXE-ядро (MdeModulePkg/Core/Dxe) — печать дампа при исключении;
  * любые ASSERT/DEBUG-пути, которым нужен SerialPortLib напрямую.

Ставим BaseSerialPortLibNull: текст больше физически некуда печатать,
и экран остаётся под нашим контролем.

Идемпотентно.
"""

import os
import sys

NEW = "  SerialPortLib|MdePkg/Library/BaseSerialPortLibNull/BaseSerialPortLibNull.inf"


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: null_serial.py <edk2-msm-dir>")
    path = os.path.join(sys.argv[1], "Silicon/Qualcomm/QcomPkg/QcomCommonDsc.inc")
    if not os.path.isfile(path):
        sys.exit("нет файла: %s" % path)

    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    if any("BaseSerialPortLibNull" in l for l in lines):
        print("null_serial: уже включено")
        return 0

    changed = 0
    out = []
    for l in lines:
        if l.strip().startswith("SerialPortLib|") and "FrameBufferSerialPortLib" in l:
            indent = l[: len(l) - len(l.lstrip())]
            out.append(indent + "# " + l.strip() + "  # fw/patches/null_serial.py: печатает в FB как 32bpp\n")
            out.append(indent + NEW.strip() + "\n")
            changed += 1
        else:
            out.append(l)

    if changed == 0:
        sys.exit("null_serial: не нашёл SerialPortLib|FrameBufferSerialPortLib")

    with open(path, "w", encoding="utf-8") as f:
        f.writelines(out)
    print("null_serial: заменено вхождений %d" % changed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
