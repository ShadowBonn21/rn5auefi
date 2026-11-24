#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
test_fd_stub2.py — два вопроса одним прогоном:

  1) Включена ли MMU в момент передачи управления от LK?
     (читаем SCTLR_EL1, бит M)
  2) Выживает ли запись FDT-указателя по PcdDeviceTreeStore (0x8F2E0000)?

Стаб подменяет ветвление FD[0] и рисует полосы:
    №8  — всегда (доказательство, что FD исполняется)
    №9  — только если MMU ВКЛЮЧЕНА
    №10 — после записи в 0x8F2E0000 (если не упали)

Трактовка:
    8+9+10 -> MMU включена, запись проходит; падение дальше (bl/векторы/стек)
    9+10, без 8 -> невозможно
    8+9    -> MMU включена и запись по 0x8F2E0000 падает -> надо отобразить адрес
    8+10   -> MMU выключена, запись проходит; падение в bl-цепочке
    8      -> упали сразу после первой полосы (маловероятно)
"""

import argparse
import gzip
import os
import struct
import sys
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mksmoke as M

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

UEFI_SIZE = 0x00800000
STUB_OFF = 0x400000
DT_STORE = 0x8F2E0000       # PcdDeviceTreeStore из ugg.dsc
FB = M.FB_ADDR - 256


def decode_b(img, off):
    w = struct.unpack("<I", img[off:off + 4])[0]
    if (w >> 26) != 0x05:
        return None
    imm = w & 0x03FFFFFF
    if imm & 0x02000000:
        imm -= 0x04000000
    return off + imm * 4


def add_x_reg(rd, rn, rm):
    return 0x8B000000 | ((rm & 0x1F) << 16) | ((rn & 0x1F) << 5) | (rd & 0x1F)


class Stub:
    def __init__(self):
        self.code = []

    def emit(self, w):
        self.code.append(w & 0xFFFFFFFF)
        return len(self.code) - 1

    def mov_imm(self, rd, value, sf=1):
        self.emit(M.movz(rd, value & 0xFFFF, sf=sf, shift=0))
        if (value >> 16) & 0xFFFF:
            self.emit(M.movk(rd, (value >> 16) & 0xFFFF, sf=sf, shift=16))

    def paint(self, band):
        """Белая полоса band*100..+50, 24bpp, stride 2160."""
        self.mov_imm(11, FB)
        self.emit(M.movz(2, 0xFFFF, sf=0, shift=0))
        self.emit(M.movk(2, 0xFFFF, sf=0, shift=16))
        self.mov_imm(5, band * 100 * 2160)
        self.emit(add_x_reg(11, 11, 5))
        self.mov_imm(8, 50, sf=0)
        row = len(self.code)
        self.emit(M.mov_xd_xn(9, 11))
        self.mov_imm(7, 2160, sf=0)
        px = len(self.code)
        self.emit(M.str_wt_postinc(2, 11, 4))
        self.emit(M.subs_w_imm(7, 7, 1))
        self.emit(M.b_ne(px, len(self.code)))
        self.mov_imm(5, 2160)
        self.emit(add_x_reg(11, 9, 5))
        self.emit(M.subs_w_imm(8, 8, 1))
        self.emit(M.b_ne(row, len(self.code)))


def build_stub(target_off):
    s = Stub()
    # 8: доказательство входа
    s.paint(8)
    # сохранить FDT (x0) и прочитать SCTLR_EL1
    s.emit(M.mov_xd_xn(12, 0))            # x12 = x0 (FDT)
    s.emit(0xD5381000)                    # mrs x0, sctlr_el1
    # tbz w0, #0, skip9   (если MMU выключена — пропустить полосу 9)
    tbz_idx = s.emit(0)                   # заглушка, заполним ниже
    s.paint(9)
    skip9 = len(s.code)
    s.code[tbz_idx] = 0x36000000 | (((skip9 - tbz_idx) & 0x3FFF) << 5) | 0
    # восстановить FDT и записать его в PcdDeviceTreeStore
    s.emit(M.mov_xd_xn(0, 12))            # x0 = FDT
    s.mov_imm(10, DT_STORE)
    s.emit(0xF9000000 | (10 << 5) | 0)    # str x0, [x10]
    s.paint(10)
    # b <original entry>
    here = STUB_OFF + len(s.code) * 4
    delta = target_off - here
    s.emit(M.b_uncond(here // 4 + delta // 4, here // 4))
    return b"".join(struct.pack("<I", w) for w in s.code)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fd", default="build/ugg-art4/workspace/Build/ugg/RELEASE_GCC5/FV/MSM8937_UEFI.fd")
    ap.add_argument("--boot-img", default="build/boot-ugg.img")
    ap.add_argument("--dtblock", default="build/ugg.dtblock")
    ap.add_argument("--out", default="build/test-fd-stub2.img")
    args = ap.parse_args()

    fd = bytearray(open(args.fd, "rb").read())
    target = decode_b(fd, 0)
    print("FD[0] -> 0x%x (вход PrePi)" % target)

    stub = build_stub(target)
    print("стаб: %d байт, по FD+0x%x; полосы 8/9/10" % (len(stub), STUB_OFF))
    fd[STUB_OFF:STUB_OFF + len(stub)] = stub
    fd[0:4] = struct.pack("<I", 0x14000000 | ((STUB_OFF // 4) & 0x03FFFFFF))
    print("FD[0] перенаправлен на 0x%x" % decode_b(fd, 0))

    d = open(args.boot_img, "rb").read()
    ks = struct.unpack("<I", d[8:12])[0]
    page = struct.unpack("<I", d[36:40])[0]
    z = zlib.decompressobj(16 + zlib.MAX_WBITS)
    payload = z.decompress(d[page:page + ks])
    shim = payload[:144]

    kernel = gzip.compress(shim + bytes(fd), 9)
    if os.path.exists(args.dtblock):
        kernel += open(args.dtblock, "rb").read()
    img = M.build_bootimg(kernel, b"", 0)
    open(args.out, "wb").write(img)
    print("bootimg: %s (%d байт)" % (args.out, len(img)))
    print()
    print("ЧТО СМОТРЕТЬ (полосы сверху вниз: 8 ~800-850, 9 ~900-950, 10 ~1000-1050):")
    print("  8+9+10 -> MMU включена, запись в 0x8F2E0000 проходит")
    print("  8+9    -> MMU включена, запись по 0x8F2E0000 падает (нет страницы)")
    print("  8+10   -> MMU выключена, запись проходит")
    print("  8      -> падение сразу после первой полосы")
    return 0


if __name__ == "__main__":
    sys.exit(main())
