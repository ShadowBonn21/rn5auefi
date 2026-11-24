#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
extract_dtb.py — вытащить device tree из Android boot.img (или из .img целиком).

Зачем: LK на msm8937 может отказаться грузить образ без DTB, а проба G0
(tools/mksmoke.py --dtb) и LinuxLoader нуждаются в реальном DTB этого телефона.

Использование:
    python tools/extract_dtb.py build\stock_boot.img -o build\stock.dtb
    python tools/extract_dtb.py --scan dump\aboot.img     # просто найти все FDT
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


def fdt_size(buf, off):
    """Валидный FDT? Возвращает totalsize или None."""
    if off < 0 or off + 8 > len(buf):
        return None
    if struct.unpack(">I", buf[off:off + 4])[0] != FDT_MAGIC:
        return None
    total = struct.unpack(">I", buf[off + 4:off + 8])[0]
    if 64 <= total <= 4 * 1024 * 1024 and off + total <= len(buf):
        return total
    return None


def find_fdts(buf):
    out, i = [], 0
    while True:
        i = buf.find(b"\xd0\x0d\xfe\xed", i)
        if i < 0:
            return out
        sz = fdt_size(buf, i)
        if sz:
            out.append((i, sz))
            i += sz
        else:
            i += 4


def parse_bootimg(buf):
    """Возвращает (kernel_bytes, dt_size_field, header_version)."""
    if buf[:8] != b"ANDROID!":
        return None
    page = struct.unpack("<I", buf[36:40])[0] or 2048
    kernel_size = struct.unpack("<I", buf[8:12])[0]
    field40 = struct.unpack("<I", buf[40:44])[0]          # dt_size (v0) / header_version (v1+)
    kernel = buf[page:page + kernel_size]
    # v1/v2: там header_version; dtb лежит отдельным блоком после ramdisk/second
    hdr_ver = field40 if 0 <= field40 <= 4 else 0
    return kernel, (field40 if hdr_ver == 0 else 0), hdr_ver, page, kernel_size


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("-o", "--out", default="build/stock.dtb")
    ap.add_argument("--scan", action="store_true", help="только перечислить FDT в файле")
    ap.add_argument("--pick", type=int, default=0, help="индекс кандидата (см. --scan)")
    ap.add_argument("--model", default=None, help="подстрока model= для выбора кандидата")
    ap.add_argument("--dtblock", action="store_true",
                    help="выгрузить весь хвост kernel от первого DTB (как в стоковом boot.img)")
    args = ap.parse_args()

    buf = open(args.image, "rb").read()
    print("файл: %s (%d байт)" % (args.image, len(buf)))

    info = parse_bootimg(buf)

    if args.dtblock:
        if not info:
            sys.exit("--dtblock требует boot.img")
        kernel, _dts, _hv, _pg, _ksize = info
        found = find_fdts(kernel)
        if not found:
            sys.exit("в kernel нет FDT")
        off, _sz = found[0]
        block = kernel[off:]
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        with open(args.out, "wb") as f:
            f.write(block)
        print("DT-блок: %d байт (DTB внутри: %d) -> %s"
              % (len(block), block.count(b"\xd0\x0d\xfe\xed"), args.out))
        return 0
    candidates = []

    if info:
        kernel, dt_size, hdr_ver, page, ksize = info
        print("boot.img: header_version=%d page=%d kernel=%d dt_size_field=%d"
              % (hdr_ver, page, ksize, dt_size))
        # 1) dtb в конце kernel (старый LK: dt_size от конца kernel)
        if dt_size and dt_size <= ksize:
            off = ksize - dt_size
            if fdt_size(kernel, off):
                candidates.append(("kernel tail (dt_size)", kernel[off:off + fdt_size(kernel, off)]))
        # 2) просто ищем в kernel
        for off, sz in find_fdts(kernel):
            candidates.append(("kernel+0x%x" % off, kernel[off:off + sz]))
        # 3) v1/v2: dtb отдельным блоком в файле
        for off, sz in find_fdts(buf[page:]):
            candidates.append(("image+0x%x" % (page + off), buf[page + off:page + off + sz]))
    else:
        for off, sz in find_fdts(buf):
            candidates.append(("file+0x%x" % off, buf[off:off + sz]))

    if args.scan or not candidates:
        if not candidates:
            print("FDT не найден. Возможно, у этого образа DTB в отдельном разделе (dtbo/dt).")
            return 1
        for name, blob in candidates:
            print("  %-24s %6d байт, model=%r" % (name, len(blob), _model(blob)))
        return 0

    name, blob = candidates[0]
    if args.model:
        hit = [(n, b) for (n, b) in candidates if args.model.lower() in _model(b).lower()]
        if not hit:
            print("ни один кандидат не содержит %r в model=" % args.model)
            for n, b in candidates:
                print("  %-24s %s" % (n, _model(b)))
            return 2
        name, blob = hit[0]
    elif args.pick:
        if args.pick >= len(candidates):
            sys.exit("--pick %d вне диапазона (кандидатов: %d)" % (args.pick, len(candidates)))
        name, blob = candidates[args.pick]
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    open(args.out, "wb").write(blob)
    print("найден FDT: %s, %d байт, model=%r" % (name, len(blob), _model(blob)))
    print("сохранено: %s" % args.out)
    print("проверка: python tools\\mksmoke.py --dtb %s --out build\\smoke_dtb.img" % args.out)
    return 0


def _model(blob):
    """Прочитать /model из настоящего FDT (а не угадывать по подстроке)."""
    try:
        _magic, _total, off_struct, off_strings, _rsv, _ver, _last, _cpu, \
            size_strings, _size_struct = struct.unpack(">10I", blob[:40])
        if _magic != FDT_MAGIC:
            return "?"
        strings = blob[off_strings:off_strings + size_strings]
        pos = off_struct
        model = None
        while pos + 4 <= len(blob):
            tok = struct.unpack(">I", blob[pos:pos + 4])[0]
            pos += 4
            if tok == 1:                                  # FDT_BEGIN_NODE
                end = blob.find(b"\0", pos)
                pos = (end + 1 + 3) & ~3                  # имя узла выровнено на 4 байта
            elif tok == 3:                                # FDT_PROP
                ln, nameoff = struct.unpack(">II", blob[pos:pos + 8])
                pos += 8
                name_end = strings.find(b"\0", nameoff)
                pname = strings[nameoff:name_end].decode("ascii", "replace")
                val = blob[pos:pos + ln]
                pos += (ln + 3) & ~3
                if pname == "model" and model is None:
                    model = val.rstrip(b"\0").decode("utf-8", "replace")
            elif tok in (2, 4):                           # END_NODE / NOP
                continue
            elif tok == 9:                                # FDT_END
                break
            else:
                break
        return model or "?"
    except Exception:
        return "?"


if __name__ == "__main__":
    sys.exit(main())
