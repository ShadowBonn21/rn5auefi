#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
gen_font.py — сгенерировать C-массив шрифта 8x12 для нашего драйвера.

Берём моноширинный шрифт из Windows (Consolas / Lucida Console / Courier New),
рендерим символы ASCII 32..126 в битмапы 8x12 (1 бит = 1 пиксель, строка —
один байт, старший бит — левый пиксель) и пишем C-файл со структурой:

    STATIC CONST UINT8  mUggFont[95][12] = { ... };

Драйвер UggFbDxe рисует этим шрифтом текст напрямую в framebuffer,
не полагаясь на консольный стек UEFI (ConSplitter/GraphicsConsole).

Запуск:
    python tools/gen_font.py            # создаёт fw/.../UggFont.c
"""

import os
import sys

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    sys.exit("нужен Pillow:  python -m pip install pillow")

W, H = 8, 12
FIRST, LAST = 32, 126

FONT_CANDIDATES = [
    r"C:\Windows\Fonts\consola.ttf",
    r"C:\Windows\Fonts\lucon.ttf",
    r"C:\Windows\Fonts\cour.ttf",
    r"C:\Windows\Fonts\DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
]

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "fw", "Silicon",
                   "Qualcomm", "msm8937", "Drivers", "UggFbDxe", "UggFont.c")


def pick_font(size):
    for path in FONT_CANDIDATES:
        if os.path.isfile(path):
            return ImageFont.truetype(path, size), path
    return ImageFont.load_default(), "default"


def main():
    font, path = pick_font(11)
    print("шрифт: %s" % path)

    glyphs = []
    for code in range(FIRST, LAST + 1):
        img = Image.new("L", (W, H), 0)
        d = ImageDraw.Draw(img)
        ch = chr(code)
        # подбираем положение так, чтобы символ попал в кадр
        d.text((0, -1), ch, fill=255, font=font)
        rows = []
        for y in range(H):
            byte = 0
            for x in range(W):
                if img.getpixel((x, y)) > 96:
                    byte |= 0x80 >> x
            rows.append(byte)
        glyphs.append(rows)

    lines = []
    lines.append("// SPDX-License-Identifier: BSD-2-Clause-Patent")
    lines.append("//")
    lines.append("// Шрифт 8x12 для собственного вывода текста (сгенерирован tools/gen_font.py).")
    lines.append("// Символы ASCII 32..126; каждый глиф — 12 байт, по байту на строку,")
    lines.append("// старший бит — левый пиксель.")
    lines.append("//")
    lines.append("#include <Uefi.h>")
    lines.append("")
    lines.append("CONST UINT8  mUggFontData[%d][%d] = {" % (LAST - FIRST + 1, H))
    for i, rows in enumerate(glyphs):
        body = ", ".join("0x%02X" % b for b in rows)
        lines.append("  { %s },  /* '%s' */" % (body, chr(FIRST + i) if 32 <= FIRST + i < 127 else "?"))
    lines.append("};")
    lines.append("")
    lines.append("CONST UINTN  mUggFontFirst = %d;" % FIRST)
    lines.append("CONST UINTN  mUggFontCount = %d;" % (LAST - FIRST + 1))
    lines.append("")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines))
    print("записано: %s (%d глифов %dx%d)" % (OUT, len(glyphs), W, H))
    return 0


if __name__ == "__main__":
    sys.exit(main())
