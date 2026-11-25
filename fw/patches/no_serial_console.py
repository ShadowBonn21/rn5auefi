#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
no_serial_console.py — убрать последовательную консоль из ConIn/ConOut/ErrOut.

Проблема: Platform/RenegadePkg/Library/PlatformBootManagerLib/PlatformBm.c
в PlatformBootManagerBeforeConsole() жёстко добавляет терминал поверх
последовательного порта:

    EfiBootManagerUpdateConsoleVariable(
      ConOut, (EFI_DEVICE_PATH_PROTOCOL *)&mSerialConsole, NULL);

На ugg UART нет (а SerialPortLib у нас заглушён), поэтому ConOut указывает на
несуществующее устройство, BDS печатает «в никуда», а графическая консоль
(GraphicsConsoleDxe на нашем GOP) молчит — экран остаётся чёрным.

Скрипт комментирует вызовы целиком (две строки каждый). Идемпотентно.
"""

import os
import sys


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: no_serial_console.py <edk2-msm-dir>")
    path = os.path.join(sys.argv[1],
                        "Platform/RenegadePkg/Library/PlatformBootManagerLib/PlatformBm.c")
    if not os.path.isfile(path):
        sys.exit("нет файла: %s" % path)

    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    if any("no_serial_console.py" in l for l in lines):
        print("no_serial_console: уже применено")
        return 0

    out, n, i = [], 0, 0
    while i < len(lines):
        l = lines[i]
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        if (l.strip().startswith("EfiBootManagerUpdateConsoleVariable")
                and "mSerialConsole" in nxt):
            out.append("#if 0  /* no_serial_console.py: UART не используется */\n")
            out.append(l)
            out.append(nxt)
            out.append("#endif\n")
            n += 1
            i += 2
            continue
        out.append(l)
        i += 1

    if n == 0:
        sys.exit("no_serial_console: не нашёл вызовы с mSerialConsole")

    with open(path, "w", encoding="utf-8") as f:
        f.writelines(out)
    print("no_serial_console: обёрнуто в #if 0 вызовов %d" % n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
