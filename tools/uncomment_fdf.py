#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
uncomment_fdf.py — вернуть в FDF все закомментированные INF-строки.

Во время bring-up часть компонентов FDF временно комментировалась
(«# INF ... # ВРЕМЕННО: ...»). Скрипт снимает такие пометки и проверяет,
что в каждой строке остался корректный путь INF-файла.

Идемпотентно: если пометок нет — ничего не меняет.
"""

import io
import os
import re
import sys

FDF = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "..", "fw", "Platform", "Qualcomm", "msm8937", "msm8937.fdf"))

LINE_RE = re.compile(r'^\s*#\s*INF\s+(\S+)(\s*#.*)?$')


def main():
    if not os.path.isfile(FDF):
        sys.exit("нет файла: %s" % FDF)

    with io.open(FDF, encoding="utf-8") as f:
        lines = f.read().splitlines()

    out, restored, bad = [], 0, []
    for l in lines:
        m = LINE_RE.match(l)
        if m and "ВРЕМЕННО" in l:
            inf = m.group(1)
            if not inf or inf == "INF" or not re.search(r"\.inf$", inf, re.I):
                bad.append(l)
                out.append(l)
                continue
            out.append("  INF %s" % inf)
            restored += 1
        else:
            out.append(l)

    io.open(FDF, "w", encoding="utf-8", newline="\n").write("\n".join(out) + "\n")
    print("восстановлено: %d" % restored)
    if bad:
        print("НЕ РАСПОЗНАНО (оставлено как есть): %d" % len(bad))
        for l in bad[:10]:
            print("   %s" % l.strip())

    # отчёт: активные INF
    print("\nактивные INF:")
    i = 0
    for l in out:
        m = re.match(r"^\s*INF\s+(\S+)$", l)
        if m:
            i += 1
            print("%3d. %s" % (i, m.group(1)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
