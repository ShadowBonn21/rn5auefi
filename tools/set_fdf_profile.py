#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
set_fdf_profile.py — переключать состав компонентов FDF между профилями.

Профили:
    min   — то, что проверено на устройстве: ядро, память/переменные,
            консоль, GIC/таймер, наш драйвер дисплея, BdsDxe.
            В этом наборе консоль UEFI работает и BDS печатает текст.
    full  — весь набор (диск, USB, логотип, Shell, SimpleInit, HII/UI, SMBIOS).

Зачем: при полном наборе BdsDxe перестаёт запускаться, и мы теряем консоль.
Скрипт позволяет добавлять драйверы по одному и сразу видеть результат.

Запуск:
    python tools/set_fdf_profile.py min
    python tools/set_fdf_profile.py full
"""

import io
import os
import re
import sys

FDF = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "..", "fw", "Platform", "Qualcomm", "msm8937", "msm8937.fdf"))

MIN_KEEP = [
    "MdeModulePkg/Core/Dxe/DxeMain.inf",
    "MdeModulePkg/Universal/PCD/Dxe/Pcd.inf",
    "ArmPkg/Drivers/CpuDxe/CpuDxe.inf",
    "MdeModulePkg/Core/RuntimeDxe/RuntimeDxe.inf",
    "MdeModulePkg/Universal/Variable/RuntimeDxe/VariableRuntimeDxe.inf",
    "MdeModulePkg/Universal/DevicePathDxe/DevicePathDxe.inf",
    "MdeModulePkg/Universal/SecurityStubDxe/SecurityStubDxe.inf",
    "EmbeddedPkg/RealTimeClockRuntimeDxe/RealTimeClockRuntimeDxe.inf",
    "MdeModulePkg/Universal/Console/ConPlatformDxe/ConPlatformDxe.inf",
    "MdeModulePkg/Universal/Console/ConSplitterDxe/ConSplitterDxe.inf",
    "MdeModulePkg/Universal/Console/GraphicsConsoleDxe/GraphicsConsoleDxe.inf",
    "ArmPkg/Drivers/ArmGic/ArmGicDxe.inf",
    "ArmPkg/Drivers/TimerDxe/TimerDxe.inf",
    "MdeModulePkg/Universal/WatchdogTimerDxe/WatchdogTimer.inf",
    "Silicon/Qualcomm/msm8937/Drivers/UggFbDxe/UggFbDxe.inf",
    "MdeModulePkg/Universal/BdsDxe/BdsDxe.inf",
    "Silicon/Qualcomm/QcomPkg/PrePi/PrePi.inf",
]

INF_RE = re.compile(r'^(\s*)(#\s*)?INF\s+(\S+)(\s*#.*)?$')


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("min", "full"):
        sys.exit("usage: set_fdf_profile.py min|full")
    profile = sys.argv[1]

    if not os.path.isfile(FDF):
        sys.exit("нет файла: %s" % FDF)

    with io.open(FDF, encoding="utf-8") as f:
        lines = f.read().splitlines()

    out, enabled, disabled = [], 0, 0
    for l in lines:
        m = INF_RE.match(l)
        if not m:
            out.append(l)
            continue
        inf = m.group(3)
        keep = (profile == "full") or (inf in MIN_KEEP)
        if keep:
            out.append("  INF %s" % inf)
            enabled += 1
        else:
            out.append("  # INF %s   # профиль min" % inf)
            disabled += 1

    io.open(FDF, "w", encoding="utf-8", newline="\n").write("\n".join(out) + "\n")
    print("профиль %s: включено %d, выключено %d" % (profile, enabled, disabled))
    return 0


if __name__ == "__main__":
    sys.exit(main())
