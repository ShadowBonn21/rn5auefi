#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
list_fv_order.py — фактический порядок драйверов в FV прошивки.

Зачем: диспетчер DXE обходит FV в порядке файлов, и «номер драйвера» на экране
соответствует именно этому порядку. Порядок INF в FDF с ним НЕ совпадает
(номера съезжают), из-за чего мы путались в диагностике.

Скрипт сам разбирает FD: внешний том, вложенный сжатый FVMAIN (Tiano/LZMA),
и печатает файлы в том порядке, в котором их увидит диспетчер.

Использование:
    python tools/list_fv_order.py <MSM8937_UEFI.fd>
"""

import sys

from uefi_firmware.efi_compressor import TianoDecompress, LzmaDecompress

FVH = b"_FVH"
TYPES = {
    0x01: "SEC", 0x02: "PEI_CORE", 0x03: "PEIM", 0x04: "PEIM_DEPEX",
    0x05: "DXE_CORE", 0x06: "DXE_DRIVER", 0x07: "DRIVER", 0x08: "DXE_DEPEX",
    0x09: "APP", 0x0A: "SMM", 0x0B: "FV_IMAGE", 0x0C: "COMBINED_PEIM",
    0xF0: "PAD", 0xFF: "ALL",
}


def u16(b, o):
    return int.from_bytes(b[o:o + 2], "little")


def u24(b, o):
    return int.from_bytes(b[o:o + 3], "little")


def u32(b, o):
    return int.from_bytes(b[o:o + 4], "little")


def u64(b, o):
    return int.from_bytes(b[o:o + 8], "little")


def guid_str(g):
    d1 = int.from_bytes(g[0:4], "little")
    d2 = int.from_bytes(g[4:6], "little")
    d3 = int.from_bytes(g[6:8], "little")
    return "%08X-%04X-%04X-%s-%s" % (d1, d2, d3, g[8:10].hex().upper(), g[10:16].hex().upper())


def fv_files(data, base, depth=0):
    """Печать файлов FV (без рекурсии в сжатые секции)."""
    out = []
    if data[base + 0x28:base + 0x2C] != FVH:
        return out
    fv_len = u64(data, base + 0x20)
    hdr_len = u16(data, base + 0x30)
    pos = base + hdr_len
    end = base + fv_len
    while pos + 24 <= end:
        ftype = data[pos + 18]
        if ftype == 0xFF:
            break
        size = u24(data, pos + 20)
        if size < 24:
            break
        guid = data[pos:pos + 16]
        ui = ""
        # ищем UI-секцию в первых 200 байтах файла
        chunk = data[pos + 24:pos + 24 + 200]
        j = chunk.find(b"\x15")
        if j >= 0 and j + 4 < len(chunk):
            slen = u24(chunk, j)
            if 4 < slen < 200:
                raw = chunk[j + 4:j + slen]
                try:
                    ui = raw.decode("utf-16-le", "ignore").split("\x00")[0]
                except Exception:
                    ui = ""
        out.append((ftype, guid, ui, pos, size, depth))
        pos += (size + 7) & ~7
    return out


def find_nested(data, pos, size):
    """В файле FV_IMAGE ищем сжатый вложенный том и возвращаем распакованные байты."""
    end = pos + size
    p = pos + 24
    while p + 4 <= end:
        ssize = u24(data, p)
        stype = data[p + 3]
        if ssize < 4:
            break
        body = data[p + 4:p + ssize]
        if stype == 0x17:              # FV_IMAGE
            inner = find_nested(data, p, ssize)
            if inner:
                return inner
        elif stype == 0x02:            # GUIDED
            guid = body[0:16]
            payload = body[20:]        # 16 guid + 2 data offset + 2 attrs
            if len(payload) > 4:
                comp = payload[4:]     # пропускаем размер распакованных данных
                for fn in (TianoDecompress, LzmaDecompress):
                    try:
                        res = fn(comp)
                        if res:
                            return res
                    except Exception:
                        pass
        elif stype == 0x01:            # COMPRESSED
            payload = body[4:]
            for fn in (TianoDecompress, LzmaDecompress):
                try:
                    res = fn(payload)
                    if res:
                        return res
                except Exception:
                    pass
        p += (ssize + 3) & ~3
    return None


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: list_fv_order.py <MSM8937_UEFI.fd>")
    data = open(sys.argv[1], "rb").read()

    # внешний том начинается там, где стоит сигнатура FVH минус 0x28
    idx = data.find(FVH)
    if idx < 0:
        sys.exit("не нашёл сигнатуру _FVH")
    base = idx - 0x28
    print("внешний FV @0x%X" % base)

    files = fv_files(data, base)
    nested = None
    for ftype, guid, ui, pos, size, _ in files:
        print("  %-10s %s %s" % (TYPES.get(ftype, ftype), guid_str(guid), ui))
        if ftype == 0x0B:
            nested = find_nested(data, pos, size)

    if not nested:
        print("\nвложенный сжатый том не распакован")
        return 1

    print("\nвложенный FV содержит %d байт; порядок файлов (как видит диспетчер):" % len(nested))
    inner = fv_files(nested, 0)
    for n, (ftype, guid, ui, pos, size, _) in enumerate(inner, 1):
        print("%2d. %-10s %s  %s" % (n, TYPES.get(ftype, ftype), guid_str(guid), ui))
    return 0


if __name__ == "__main__":
    sys.exit(main())
