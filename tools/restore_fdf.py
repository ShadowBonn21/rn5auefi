#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
restore_fdf.py — снять временные пометки «# ... # ВРЕМЕННО» с FDF.

Во время диагностики (см. fw/patches/paint_bds.py, paint_stages.py) часть
компонентов FDF временно комментировалась, чтобы на экране оставалась только
тестовая картинка. Скрипт возвращает файл в штатный вид.

Идемпотентно: если пометок нет — ничего не делает.
"""

import io
import os
import sys


def main():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "..", "fw", "Platform", "Qualcomm", "msm8937", "msm8937.fdf")
    path = os.path.normpath(path)
    if not os.path.isfile(path):
        sys.exit("нет файла: %s" % path)

    src = io.open(path, encoding="utf-8").read().splitlines()
    out, restored = [], 0
    for l in src:
        if "ВРЕМЕННО" in l and l.lstrip().startswith("#"):
            body = l.lstrip()[1:].strip()
            body = body.split("  #")[0].rstrip()
            out.append(body)
            restored += 1
        else:
            out.append(l)

    if restored == 0:
        print("restore_fdf: пометок нет, файл не изменён")
        return 0

    io.open(path, "w", encoding="utf-8", newline="\n").write("\n".join(out) + "\n")
    print("restore_fdf: восстановлено строк %d" % restored)
    return 0


if __name__ == "__main__":
    sys.exit(main())
