#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
set_fdf_profile.py — состав компонентов FDF по профилям и группам.

Профиль min — проверенный на устройстве набор: ядро, память/переменные,
консоль, GIC/таймер, наш драйвер дисплея, BdsDxe. В нём консоль UEFI работает
и BDS печатает текст.

Группы добавляются к min по одной, чтобы сразу видеть, после какой группы
BdsDxe перестаёт запускаться (тогда на экране остаётся только наша строка).

Запуск:
    python tools/set_fdf_profile.py min
    python tools/set_fdf_profile.py min disk
    python tools/set_fdf_profile.py min disk apps
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

GROUPS = {
    "disk": [
        "MdeModulePkg/Universal/Disk/DiskIoDxe/DiskIoDxe.inf",
        "MdeModulePkg/Universal/Disk/PartitionDxe/PartitionDxe.inf",
        "FatPkg/EnhancedFatDxe/Fat.inf",
        "MdeModulePkg/Universal/Disk/UnicodeCollation/EnglishDxe/EnglishDxe.inf",
    ],
    "smbios": [
        "EmbeddedPkg/Drivers/DtPlatformDxe/DtPlatformDxe.inf",
        "Platform/RenegadePkg/Drivers/PlatformSmbiosDxe/PlatformSmbiosDxe.inf",
        "MdeModulePkg/Universal/SmbiosDxe/SmbiosDxe.inf",
    ],
    "hii": [
        "MdeModulePkg/Universal/HiiDatabaseDxe/HiiDatabaseDxe.inf",
        "MdeModulePkg/Universal/PrintDxe/PrintDxe.inf",
        "MdeModulePkg/Universal/DisplayEngineDxe/DisplayEngineDxe.inf",
        "MdeModulePkg/Universal/SetupBrowserDxe/SetupBrowserDxe.inf",
        "MdeModulePkg/Universal/DriverHealthManagerDxe/DriverHealthManagerDxe.inf",
    ],
    "usb": [
        "MdeModulePkg/Bus/Usb/UsbBusDxe/UsbBusDxe.inf",
        "MdeModulePkg/Bus/Usb/UsbMassStorageDxe/UsbMassStorageDxe.inf",
        "MdeModulePkg/Bus/Usb/UsbKbDxe/UsbKbDxe.inf",
    ],
    "testapp": [
        "Platform/Xiaomi/msm8937/Apps/UggTestApp/UggTestApp.inf",
    ],
    "logo": [
        "Platform/RenegadePkg/Drivers/LogoDxe/LogoDxe.inf",
    ],
    "shellonly": [
        "ShellPkg/Application/Shell/Shell.inf",
    ],
    "shell": [
        "ShellPkg/Application/Shell/Shell.inf",
        "MdeModulePkg/Application/UiApp/UiApp.inf",
    ],
    "simpleinit": [
        "src/main/SimpleInitMain.inf",
    ],
    "apps": [
        "Platform/RenegadePkg/Drivers/LogoDxe/LogoDxe.inf",
        "ShellPkg/Application/Shell/Shell.inf",
        "src/main/SimpleInitMain.inf",
        "MdeModulePkg/Application/UiApp/UiApp.inf",
    ],
    "services": [
        "MdeModulePkg/Universal/CapsuleRuntimeDxe/CapsuleRuntimeDxe.inf",
        "EmbeddedPkg/EmbeddedMonotonicCounter/EmbeddedMonotonicCounter.inf",
        "MdeModulePkg/Universal/ResetSystemRuntimeDxe/ResetSystemRuntimeDxe.inf",
        "EmbeddedPkg/MetronomeDxe/MetronomeDxe.inf",
        "MdeModulePkg/Universal/ReportStatusCodeRouter/RuntimeDxe/ReportStatusCodeRouterRuntimeDxe.inf",
        "MdeModulePkg/Universal/StatusCodeHandler/RuntimeDxe/StatusCodeHandlerRuntimeDxe.inf",
    ],
}

INF_RE = re.compile(r'^(\s*)(#\s*)?INF\s+(\S+)(\s*#.*)?$')


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: set_fdf_profile.py [min|full] [%s]" % "|".join(GROUPS))

    profile = "min"
    wanted = set()
    for a in sys.argv[1:]:
        if a in ("min", "full"):
            profile = a
        elif a in GROUPS:
            wanted.add(a)
        else:
            sys.exit("неизвестный аргумент: %s (группы: %s)" % (a, ", ".join(GROUPS)))

    keep = set()
    if profile == "full":
        for g in GROUPS.values():
            keep.update(g)
        keep.update(MIN_KEEP)
    else:
        keep.update(MIN_KEEP)
        for g in wanted:
            keep.update(GROUPS[g])

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
        if inf in keep:
            out.append("  INF %s" % inf)
            enabled += 1
        else:
            out.append("  # INF %s   # выключено профилем" % inf)
            disabled += 1

    io.open(FDF, "w", encoding="utf-8", newline="\n").write("\n".join(out) + "\n")
    print("профиль %s%s: включено %d, выключено %d"
          % (profile, ("+" + ",".join(sorted(wanted))) if wanted else "", enabled, disabled))
    return 0


if __name__ == "__main__":
    sys.exit(main())
