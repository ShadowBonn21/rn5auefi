#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
dtb_keys.py — вытащить из device tree описание кнопок (gpio-keys).

Печатает для каждого узла-кнопки: имя, linux,code, gpios (контроллер + номер +
флаги) и key/прерывание. Нужно для драйвера ввода на TLMM.

Запуск:
    python tools/dtb_keys.py build/ugg.dtb
"""

import struct
import sys

FDT_MAGIC = 0xD00DFEED
FDT_BEGIN_NODE = 1
FDT_END_NODE = 2
FDT_PROP = 3
FDT_NOP = 4
FDT_END = 9


def parse_strings(blob, off):
    out = []
    while off < len(blob) and blob[off] != 0:
        end = blob.index(b"\x00", off)
        out.append(blob[off:end].decode("utf-8", "replace"))
        off = end + 1
    return out


def parse_props(struct_blob, strings):
    """Возвращает список (path, {prop: bytes})."""
    result = []
    stack = []
    pos = 0
    while pos + 4 <= len(struct_blob):
        token = struct.unpack(">I", struct_blob[pos:pos + 4])[0]
        pos += 4
        if token == FDT_BEGIN_NODE:
            end = struct_blob.index(b"\x00", pos)
            name = struct_blob[pos:end].decode("utf-8", "replace")
            pos = end + 1
            pos = (pos + 3) & ~3
            stack.append(name)
            result.append(["/".join(x for x in stack if x), {}])
        elif token == FDT_END_NODE:
            if stack:
                stack.pop()
        elif token == FDT_PROP:
            length, nameoff = struct.unpack(">II", struct_blob[pos:pos + 8])
            pos += 8
            value = struct_blob[pos:pos + length]
            pos = (pos + length + 3) & ~3
            end = strings.index(b"\x00", nameoff)
            name = strings[nameoff:end].decode("utf-8", "replace")
            if result:
                result[-1][1][name] = value
        elif token == FDT_NOP:
            continue
        elif token == FDT_END:
            break
        else:
            break
    return result


def u32(b):
    return struct.unpack(">I", b[:4])[0]


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: dtb_keys.py <dtb>")
    blob = open(sys.argv[1], "rb").read()
    magic, totalsize, off_struct, off_strings, off_rsv, version, last_comp, boot_cpuid, size_strings, size_struct = \
        struct.unpack(">10I", blob[:40])
    if magic != FDT_MAGIC:
        sys.exit("не DTB (magic=0x%08X)" % magic)

    strings = blob[off_strings:off_strings + size_strings]
    nodes = parse_props(blob[off_struct:off_struct + size_struct], strings)

    keys = []
    for path, props in nodes:
        if not path:
            continue
        name = path.rsplit("/", 1)[-1]
        interesting = (
            "gpio-keys" in path or "gpio_keys" in path or
            name in ("vol_up", "vol_down", "power", "key_vol_up", "key_vol_down",
                     "key_power", "volume_up", "volume_down")
            or "linux,code" in props
        )
        if not interesting:
            continue
        info = {"path": path}
        if "linux,code" in props and len(props["linux,code"]) >= 4:
            info["linux,code"] = u32(props["linux,code"])
        for key in ("gpios", "gpio"):
            if key in props:
                raw = props[key]
                cells = [u32(raw[i:i + 4]) for i in range(0, len(raw) - 3, 4)]
                info[key] = cells
        if "label" in props:
            info["label"] = props["label"].rstrip(b"\x00").decode("utf-8", "replace")
        if "wakeup-source" in props:
            info["wakeup"] = True
        keys.append(info)

    KEYS = {116: "POWER", 114: "VOL-", 115: "VOL+", 102: "HOME", 158: "BACK"}
    print("кнопки из device tree (%d):" % len(keys))
    for k in keys:
        code = k.get("linux,code")
        code_txt = ""
        if code is not None:
            code_txt = " linux,code=%d (%s)" % (code, KEYS.get(code, "?"))
        gp = ""
        if "gpios" in k:
            gp = " gpios=%s" % [hex(c) for c in k["gpios"]]
        elif "gpio" in k:
            gp = " gpio=%s" % [hex(c) for c in k["gpio"]]
        print("  %-40s%s%s" % (k["path"], code_txt, gp))
    return 0


if __name__ == "__main__":
    sys.exit(main())
