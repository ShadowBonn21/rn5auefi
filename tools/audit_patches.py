#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
audit_patches.py — аудит всех патчей проекта против ЗАКРЕПЛЁННОЙ версии edk2.

Зачем: скрипты-патчи ищут текстовые якоря. Если якорь не найден, патч МОЛЧА
ничего не делает, и потом мы полдня ищем «почему метка не появилась».
Сборка использует не master edk2, а коммит из сабмодуля edk2-msm, и файлы
там отличаются (это уже дважды стоило нам времени).

Скрипт:
  1) скачивает файлы закреплённой версии во временное дерево;
  2) по очереди применяет каждый патч;
  3) печатает, изменился ли файл (OK) или патч ничего не сделал (NO-OP).

Запуск: python tools/audit_patches.py
"""

import os
import shutil
import subprocess
import sys
import urllib.request

EDK2_SHA = "e7aac7fc137e247edad22f7ee53b9a1fba227397"

EDK2_FILES = [
    "ArmPkg/Drivers/CpuDxe/CpuDxe.c",
    "MdeModulePkg/Universal/BdsDxe/BdsEntry.c",
    "MdeModulePkg/Core/Dxe/DxeMain/DxeMain.c",
    "MdeModulePkg/Core/Dxe/Dispatcher/Dispatcher.c",
]

MSM_FILES = [
    "Silicon/Qualcomm/QcomPkg/PrePi/ModuleEntryPoint.S",
    "Silicon/Qualcomm/QcomPkg/QcomCommonDsc.inc",
    "Platform/RenegadePkg/Library/PlatformBootManagerLib/PlatformBm.c",
]

# (скрипт, файл, который он должен изменить)
PATCHES = [
    ("minimal_prepi_entry.py", "Silicon/Qualcomm/QcomPkg/PrePi/ModuleEntryPoint.S"),
    ("null_serial.py", "Silicon/Qualcomm/QcomPkg/QcomCommonDsc.inc"),
    ("no_serial_console.py", "Platform/RenegadePkg/Library/PlatformBootManagerLib/PlatformBm.c"),
    ("paint_dispatcher.py", "Common/edk2/MdeModulePkg/Core/Dxe/Dispatcher/Dispatcher.c"),
    ("paint_bds.py", "Common/edk2/MdeModulePkg/Universal/BdsDxe/BdsEntry.c"),
    ("force_dispatch.py", "Common/edk2/MdeModulePkg/Core/Dxe/Dispatcher/Dispatcher.c"),
    ("cpudxe_fix.py", "Common/edk2/ArmPkg/Drivers/CpuDxe/CpuDxe.c"),
]

ROOT = "build/_audit"
EDK2_BASE = "https://raw.githubusercontent.com/tianocore/edk2/%s/" % EDK2_SHA
MSM_BASE = "https://raw.githubusercontent.com/edk2-porting/edk2-msm/master/"


def fetch(url, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "dsh"})
    with urllib.request.urlopen(req, timeout=60) as r, open(dst, "wb") as f:
        f.write(r.read())


def main():
    if os.path.isdir(ROOT):
        shutil.rmtree(ROOT)

    print("Скачиваю закреплённые файлы:")
    for rel in EDK2_FILES:
        fetch(EDK2_BASE + rel, os.path.join(ROOT, "Common/edk2", rel))
        print("  edk2  %s" % rel)
    for rel in MSM_FILES:
        fetch(MSM_BASE + rel, os.path.join(ROOT, rel))
        print("  msm   %s" % rel)

    # эталонные копии для сравнения
    snap = {}
    for _, rel in PATCHES:
        p = os.path.join(ROOT, rel)
        if rel not in snap and os.path.isfile(p):
            snap[rel] = open(p, "rb").read()

    print("\nПрименяю патчи:")
    bad = []
    for script, rel in PATCHES:
        path = os.path.join("fw", "patches", script)
        if not os.path.isfile(path):
            print("  %-26s НЕТ ФАЙЛА ПАТЧА" % script)
            bad.append(script)
            continue
        before = os.path.getsize(os.path.join(ROOT, rel)) if os.path.isfile(os.path.join(ROOT, rel)) else 0
        r = subprocess.run(
            [sys.executable, path, ROOT],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        after = os.path.getsize(os.path.join(ROOT, rel)) if os.path.isfile(os.path.join(ROOT, rel)) else 0
        out = (r.stdout or "").strip().replace("\n", " | ")
        status = "OK" if after != before else "NO-OP"
        if status == "NO-OP":
            bad.append(script)
        print("  %-26s %-6s %s" % (script, status, out[:120]))

    print("\nЦелевые файлы, изменённые хотя бы раз:")
    for rel, orig in snap.items():
        cur = os.path.join(ROOT, rel)
        if os.path.isfile(cur):
            changed = open(cur, "rb").read() != orig
            print("  %-70s %s" % (rel, "изменён" if changed else "НЕ изменён"))

    if bad:
        print("\nПРОБЛЕМЫ (патч не сработал): %s" % ", ".join(bad))
        return 1

    print("\nВсе патчи применились.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
