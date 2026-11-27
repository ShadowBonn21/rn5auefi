#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
dtb_node.py — вывести узлы device tree по подстроке: свойства как есть.

Нужно для драйвера eMMC: адрес контроллера (reg), имена и описания клоков
(clocks/clock-names), ширина шины, настройки vmmc/vqmmc.

Запуск:
    python tools/dtb_node.py build/ugg.dtb sdhc
"""

import struct
import sys

FDT_MAGIC = 0xD00DFEED
FDT_BEGIN_NODE = 1
FDT_END_NODE = 2
FDT_PROP = 3
FDT_NOP = 4
FDT_END = 9


def parse_nodes(struct_blob, strings):
    nodes = []
    stack = []
    pos = 0
    while pos + 4 <= len(struct_blob):
        token = struct.unpack(">I", struct_blob[pos:pos + 4])[0]
        pos += 4
        if token == FDT_BEGIN_NODE:
            end = struct_blob.index(b"\x00", pos)
            name = struct_blob[pos:end].decode("utf-8", "replace")
            pos = (end + 1 + 3) & ~3
            stack.append(name)
            nodes.append(["/".join(x for x in stack if x), {}])
        elif token == FDT_END_NODE:
            if stack:
                stack.pop()
        elif token == FDT_PROP:
            length, nameoff = struct.unpack(">II", struct_blob[pos:pos + 8])
            pos += 8
            value = struct_blob[pos:pos + length]
            pos = (pos + length + 3) & ~3
            end = strings.index(b"\x00", nameoff)
            pname = strings[nameoff:end].decode("utf-8", "replace")
            if nodes:
                nodes[-1][1][pname] = value
        elif token == FDT_NOP:
            continue
        else:
            break
    return nodes


def fmt(props):
    out = []
    for name, val in props.items():
        if all(32 <= b < 127 or b == 0 for b in val) and len(val) > 1:
            try:
                s = val.rstrip(b"\x00").decode("ascii")
                if s:
                    out.append("    %-18s = \"%s\"" % (name, s))
                    continue
            except UnicodeDecodeError:
                pass
        if len(val) % 4 == 0 and len(val) <= 32:
            cells = [struct.unpack(">I", val[i:i + 4])[0] for i in range(0, len(val), 4)]
            out.append("    %-18s = %s" % (name, " ".join("0x%X" % c for c in cells)))
        else:
            out.append("    %-18s = <%d bytes> %s" % (name, len(val), val[:16].hex()))
    return out


def main():
    if len(sys.argv) < 3:
        sys.exit("usage: dtb_node.py <dtb> <substring>")
    blob = open(sys.argv[1], "rb").read()
    magic, totalsize, off_struct, off_strings, off_rsv, version, last_comp, boot_cpuid, size_strings, size_struct = \
        struct.unpack(">10I", blob[:40])
    if magic != FDT_MAGIC:
        sys.exit("не DTB")
    strings = blob[off_strings:off_strings + size_strings]
    nodes = parse_nodes(blob[off_struct:off_struct + size_struct], strings)

    key = sys.argv[2].lower()
    for path, props in nodes:
        if key not in path.lower():
            continue
        print("/%s" % path)
        for line in fmt(props):
            print(line)
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
