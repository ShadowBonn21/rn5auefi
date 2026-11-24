#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
mkfdt_from_tree.py — собрать бинарный DTB из дерева /proc/device-tree.

Зачем: LK на ugg отказывается грузить boot.img без DTB ("dtb not found"), а
качать 2-ГБ fastboot-ROM ради одного файла не хочется. Зато живой Android
отдаёт своё дерево в /proc/device-tree — из него можно собрать эквивалентный
DTB (с теми же qcom,msm-id / qcom,board-id, по которым LK выбирает образ).

Использование:
    adb pull /proc/device-tree build/device-tree
    python tools/mkfdt_from_tree.py build/device-tree -o build/stock.dtb
"""

import argparse
import os
import struct
import sys

try:  # Windows: не ломать кириллицу при выводе в пайп
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

FDT_MAGIC = 0xD00DFEED
FDT_BEGIN_NODE = 1
FDT_END_NODE = 2
FDT_PROP = 3
FDT_NOP = 4
FDT_END = 9


def _pad4(b):
    return b + b"\x00" * ((4 - len(b) % 4) % 4)


class Strings:
    def __init__(self):
        self.blob = b""
        self.offsets = {}

    def add(self, name):
        if name in self.offsets:
            return self.offsets[name]
        off = len(self.blob)
        self.offsets[name] = off
        self.blob += name.encode("ascii", "replace") + b"\x00"
        return off


def build_node(path, node_name, strings, out, depth):
    """Рекурсивно превращает каталог в FDT-структуру (props, затем подузлы)."""
    out.append(struct.pack(">I", FDT_BEGIN_NODE) + _pad4(node_name.encode("utf-8") + b"\x00"))

    try:
        entries = sorted(os.listdir(path))
    except OSError as e:
        print("  ! не читается %s: %s" % (path, e), file=sys.stderr)
        entries = []

    props, children = [], []
    for e in entries:
        p = os.path.join(path, e)
        if os.path.isdir(p):
            children.append((e, p))
        elif e == "name":
            continue                      # избыточно: имя узла уже есть
        else:
            props.append((e, p))

    for name, p in props:
        try:
            with open(p, "rb") as f:
                val = f.read()
        except OSError as ex:
            print("  ! пропуск свойства %s: %s" % (name, ex), file=sys.stderr)
            continue
        out.append(struct.pack(">III", FDT_PROP, len(val), strings.add(name)) + _pad4(val))

    for cname, cpath in children:
        build_node(cpath, cname, strings, out, depth + 1)

    out.append(struct.pack(">I", FDT_END_NODE))


def build_fdt(tree_dir, boot_cpuid=0):
    strings = Strings()
    chunks = []
    build_node(tree_dir, "", strings, chunks, 0)
    chunks.append(struct.pack(">I", FDT_END))
    struct_blob = b"".join(chunks)

    rsvmap = struct.pack(">QQ", 0, 0)     # только терминатор
    off_rsv = 40
    off_struct = off_rsv + len(rsvmap)
    off_strings = off_struct + len(struct_blob)
    total = off_strings + len(strings.blob)

    header = struct.pack(
        ">10I",
        FDT_MAGIC, total,
        off_struct, off_strings, off_rsv,
        17, 16,                          # version / last_comp_version
        boot_cpuid,
        len(strings.blob), len(struct_blob),
    )
    return header + rsvmap + struct_blob + strings.blob


def dump_tree(tree_dir, depth=0):
    """Человекочитаемая сводка: модель, compatible, msm-id/board-id, размер."""
    def prop(name):
        p = os.path.join(tree_dir, name)
        if os.path.isfile(p):
            with open(p, "rb") as f:
                return f.read()
        return None

    model = prop("model")
    comp = prop("compatible")
    for label, name in (("model", "model"), ("compatible", "compatible")):
        v = prop(name)
        if v is not None:
            print("  %-12s %s" % (label + ":", v.replace(b"\x00", b" ").decode("utf-8", "replace").strip()))
    for label, name in (("qcom,msm-id", "qcom,msm-id"), ("qcom,board-id", "qcom,board-id")):
        v = prop(name)
        if v is not None and len(v) % 4 == 0:
            cells = struct.unpack(">%dI" % (len(v) // 4), v)
            print("  %-12s %s" % (label + ":", " ".join("0x%x" % c for c in cells)))
    if model is None and comp is None:
        print("  (это не корень дерева? нет model/compatible)")
    return True


def main():
    ap = argparse.ArgumentParser(description="собрать DTB из /proc/device-tree")
    ap.add_argument("tree_dir", help="каталог, скопированный из /proc/device-tree")
    ap.add_argument("-o", "--out", default="build/stock.dtb")
    ap.add_argument("--info", action="store_true", help="только показать сводку")
    args = ap.parse_args()

    if not os.path.isdir(args.tree_dir):
        sys.exit("нет каталога: %s" % args.tree_dir)

    print("дерево: %s" % args.tree_dir)
    dump_tree(args.tree_dir)

    if args.info:
        return 0

    blob = build_fdt(args.tree_dir)
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "wb") as f:
        f.write(blob)

    print("DTB    : %d байт -> %s" % (len(blob), args.out))
    # самопроверка: читаем обратно тем же парсером, что и extract_dtb
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        import extract_dtb
        print("проверка: model=%r" % extract_dtb._model(blob))
    except Exception as e:
        print("проверка не удалась: %s" % e)
    print("дальше : powershell -ExecutionPolicy Bypass -File tools\\probe.ps1 -Dtb %s" % args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
