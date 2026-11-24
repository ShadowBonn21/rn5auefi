#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mksmoke.py — сборка "дымового" boot.img для Redmi Note 5A Prime (ugg / MSM8940).

Зачем: до того как писать UEFI, нужно проверить ДВА факта про загрузчик (LK/aboot):
  1) LK умеет передать управление AArch64-ядру (Image с магией "ARM\\x64"), а не только arm32;
  2) континьюс-сплэш (framebuffer) лежит по адресу 0x90000000 и в него можно писать.

Payload —  120 байт машинного кода AArch64, который заливает экран красным и
зелёным, синим и белым (~6 Гц), т.е. заметно мигает и крутится в вечном цикле.
Ничего не пишет на флеш, ничего не портит: только RAM (framebuffer).

Инструментов сборки не требуется — только Python 3. Кодогенерация и сборка
Android boot image (header v0) целиком внутри.

Запуск:
    python tools/mksmoke.py --out smoke.img
"""

import argparse
import hashlib
import os
import struct
import sys

# ---------------------------------------------------------------- параметры
BASE_ADDR = 0x80000000          # стандарт Qualcomm msm8937 (arm64 Image)
KERNEL_OFFSET = 0x00008000      # -> 0x80008000
RAMDISK_OFFSET = 0x01000000     # -> 0x81000000 (нам не нужен, но LK ждёт поле)
TAGS_OFFSET = 0x00000100        # -> 0x80000100
PAGE_SIZE = 2048

FB_ADDR = 0x90000000            # cont_splash_mem из msm8937.dtsi
SCREEN_W, SCREEN_H = 720, 1280  # Redmi Note 5A Prime
BYTES_PER_PX = 4

CMDLINE = (
    "console=ttyMSM0,115200n8 earlycon androidboot.hardware=qcom "
    "androidboot.console=ttyMSM0 msm_rtb.filter=0x237 lpm_levels.sleep_disabled=1"
)

# ------------------------------------------------------------ AArch64 кодирование
def movz(rd, imm16, sf=1, shift=0):
    base = 0xD2800000 if sf else 0x52800000
    hw = 1 if shift == 16 else 0
    return base | (hw << 21) | ((imm16 & 0xFFFF) << 5) | (rd & 0x1F)

def movk(rd, imm16, sf=1, shift=0):
    base = 0xF2800000 if sf else 0x72800000
    hw = 1 if shift == 16 else 0
    return base | (hw << 21) | ((imm16 & 0xFFFF) << 5) | (rd & 0x1F)

def mov_xd_xn(rd, rn):
    # MOV Xd, Xn == ORR Xd, XZR, Xn
    return 0xAA0003E0 | ((rn & 0x1F) << 16) | (rd & 0x1F)

def str_wt_postinc(rt, rn, imm9):
    # STR (immediate), 32-bit, post-indexed, unsigned imm9
    return 0xB8000400 | ((imm9 & 0x1FF) << 12) | ((rn & 0x1F) << 5) | (rt & 0x1F)

def subs_w_imm(rd, rn, imm12):
    return 0x71000000 | ((imm12 & 0xFFF) << 10) | ((rn & 0x1F) << 5) | (rd & 0x1F)

def subs_x_imm(rd, rn, imm12):
    return 0xF1000000 | ((imm12 & 0xFFF) << 10) | ((rn & 0x1F) << 5) | (rd & 0x1F)

def b_ne(target_index, here_index):
    off = target_index - here_index
    return 0x54000000 | ((off & 0x7FFFF) << 5) | 0b0001

def b_uncond(target_index, here_index):
    off = target_index - here_index
    return 0x14000000 | (off & 0x3FFFFFF)

NOP = 0xD503201F

# ------------------------------------------------------------ payload
# палитра: яркие цвета, RGBA8888 в little-endian (0xAARRGGBB)
PALETTE = (0xFFFF0000, 0xFF00FF00, 0xFF0000FF, 0xFFFFFFFF)


def build_payload():
    """Возвращает байты валидного arm64 Image: 64-байтный заголовок + код."""
    code = []

    def emit(w):
        code.append(w & 0xFFFFFFFF)
        return len(code) - 1            # индекс только что добавленной инструкции

    # заголовок: code0 = b start, code1 = nop
    # образ: [0]=code0, [1]=code1, ..., [15]=последняя инструкция заголовка,
    #        [16]=первая инструкция тела (смещение 64 байта)
    code0 = b_uncond(16, 0)
    code1 = NOP

    # ---- тело (начинается с образа + 64)
    # x0 = framebuffer base
    emit(movz(0, FB_ADDR >> 16, sf=1, shift=16))          # movz x0, #0x9000, lsl #16
    words = (SCREEN_W * SCREEN_H * BYTES_PER_PX) // 4     # 720*1280 = 921600
    cnt_hi, cnt_lo = (words >> 16) & 0xFFFF, words & 0xFFFF

    phase_starts = []
    for color in PALETTE:
        phase_starts.append(len(code))
        # w2 = цвет
        emit(movz(2, color & 0xFFFF, sf=0, shift=0))
        emit(movk(2, (color >> 16) & 0xFFFF, sf=0, shift=16))
        # w1 = число слов
        emit(movz(1, cnt_hi, sf=0, shift=16))
        if cnt_lo:
            emit(movk(1, cnt_lo, sf=0, shift=0))
        emit(mov_xd_xn(4, 0))                             # x4 = x0
        fill = len(code)                                  # << FILL
        emit(str_wt_postinc(2, 4, 4))                     # str w2, [x4], #4
        emit(subs_w_imm(1, 1, 1))                         # subs w1, w1, #1
        emit(b_ne(fill, len(code)))                       # b.ne FILL
        # задержка ~0.15 c
        emit(movz(3, 0x0800, sf=1, shift=16))
        dloop = len(code)                                 # << DLOOP
        emit(subs_x_imm(3, 3, 1))
        emit(b_ne(dloop, len(code)))

    emit(b_uncond(phase_starts[0], len(code)))            # по кругу
    body = b"".join(struct.pack("<I", w) for w in code)

    total = 64 + len(body)
    header = struct.pack(
        "<IIQQQQQQII",
        code0,                       # code0 : b start
        code1,                       # code1 : nop
        0,                           # text_offset
        total,                       # image_size
        0,                           # flags (LE, 4K pages)
        0, 0, 0,                     # res2..res4
        0x644D5241,                  # "ARM\x64" magic
        0,                           # res5
    )
    assert len(header) == 64, len(header)
    return header + body


# ------------------------------------------------------------ boot image v0
def build_bootimg(kernel, dtb=b"", dt_size=None):
    kernel_addr = BASE_ADDR + KERNEL_OFFSET
    ramdisk_addr = BASE_ADDR + RAMDISK_OFFSET
    tags_addr = BASE_ADDR + TAGS_OFFSET

    ramdisk = b""
    hdr = struct.pack(
        "<8s10I16s512s32s1024s",
        b"ANDROID!",
        len(kernel), kernel_addr,
        len(ramdisk), ramdisk_addr,
        0, 0,                        # second size/addr
        tags_addr,
        PAGE_SIZE,
        (len(dtb) if dt_size is None else dt_size),   # поле 40: dt_size (v0)
        0x00000000,                  # os_version
        b"uefi-probe".ljust(16, b"\0"),
        CMDLINE.encode()[:511].ljust(512, b"\0"),
        b"\0" * 32,
        b"\0" * 1024,
    )
    assert len(hdr) == 1632, len(hdr)

    def pad(b):
        rem = len(b) % PAGE_SIZE
        return b + b"\0" * ((PAGE_SIZE - rem) % PAGE_SIZE) if rem else b

    return pad(hdr) + pad(kernel) + pad(ramdisk) + pad(dtb)


def main():
    ap = argparse.ArgumentParser(description="AArch64 framebuffer probe for ugg (MSM8940)")
    ap.add_argument("--out", default="smoke.img", help="куда писать boot image")
    ap.add_argument("--payload-out", default=None, help="сохранить только Image")
    ap.add_argument("--dtb", default=None, help="приложить device tree из стокового boot.img")
    ap.add_argument("--append", default=None, help="приложить произвольный блок как есть (например, весь DT-блок стока)")
    ap.add_argument("--gzip", action="store_true", help="сжать payload gzip (как делает стоковый kernel)")
    args = ap.parse_args()

    payload = build_payload()
    if args.gzip:
        import gzip as _gz
        payload = _gz.compress(payload, 9)
        print("payload : gzip -> %d bytes" % len(payload))
    dtb = b""
    if args.dtb:
        with open(args.dtb, "rb") as f:
            dtb = f.read()
        if len(dtb) < 4 or struct.unpack(">I", dtb[:4])[0] != 0xD00DFEED:
            sys.exit("!! %s не похож на DTB (нет магии 0xD00DFEED)" % args.dtb)
        dtb = dtb + b"\0" * ((4096 - len(dtb) % 4096) % 4096)
    dt_size = None
    if args.append:
        with open(args.append, "rb") as f:
            payload += f.read()
        dt_size = 0
        print("append  : %s -> kernel %d bytes" % (args.append, len(payload)))
    img = build_bootimg(payload, dtb, dt_size)

    with open(args.out, "wb") as f:
        f.write(img)
    if args.payload_out:
        with open(args.payload_out, "wb") as f:
            f.write(payload)

    print("payload : %d bytes (Image header 64 + code %d)" % (len(payload), len(payload) - 64))
    print("dtb     : %d bytes" % len(dtb))
    print("bootimg : %d bytes -> %s" % (len(img), os.path.abspath(args.out)))
    print("sha256  : %s" % hashlib.sha256(img).hexdigest())
    print("kernel_addr=0x%08x tags=0x%08x page=%d fb=0x%08x %dx%d" % (
        BASE_ADDR + KERNEL_OFFSET, BASE_ADDR + TAGS_OFFSET, PAGE_SIZE,
        FB_ADDR, SCREEN_W, SCREEN_H))
    return 0


if __name__ == "__main__":
    sys.exit(main())
