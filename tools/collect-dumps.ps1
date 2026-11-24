<#
.SYNOPSIS
    Сбор дампов с Redmi Note 5A Prime (ugg) через adb — всё, что нужно для порта UEFI.

.DESCRIPTION
    Работает БЕЗ root: читает /proc, /sys и свойства. Что не читается без root
    (iomem, dmesg, разделы устройства) — помечается в отчёте как "нужен root/EDL",
    см. docs\03-dumps.md.

    Результат: dump\<серийник>\*.txt + dump\<серийник>\manifest.txt

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools\collect-dumps.ps1
#>
[CmdletBinding()]
param([string]$OutDir = "")

$ErrorActionPreference = "Continue"
# Windows PowerShell 5.1: вывод python (UTF-8) не должен превращаться в кракозябры
    try {
        [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
        $OutputEncoding = [System.Text.UTF8Encoding]::new()
    } catch { }

. (Join-Path $PSScriptRoot "_native.ps1")

function Say($m, $c = "Gray") { Write-Host "[dump] $m" -ForegroundColor $c }

if (-not (Get-Command adb -ErrorAction SilentlyContinue)) {
    Say "adb не найден в PATH" "Red"; exit 2
}

$devs = @((Invoke-Native adb devices).Lines | Where-Object { $_ -match "\S+\s+device$" })
if ($devs.Count -eq 0) {
    Say "нет устройства в режиме adb. Включите USB-отладку и подтвердите запрос на телефоне." "Red"
    Say "проверка: adb devices" "Red"
    exit 3
}

$serial = ($devs[0] -split "\s+")[0]
Say "устройство: $serial" "Green"

$root = Split-Path -Parent $PSScriptRoot
if (-not $OutDir) { $OutDir = Join-Path $root ("dump\" + $serial) }
New-Item -ItemType Directory -Force $OutDir | Out-Null
Say "каталог: $OutDir" "Green"

$manifest = New-Object System.Collections.Generic.List[string]
function Grab([string]$name, [string]$cmd, [string]$note = "") {
    $safe = ($name -replace '[^\w\.\-]', '_')
    $file = Join-Path $OutDir ($safe + ".txt")
    Say "  $name"
    $r = Invoke-Native adb -s $serial shell $cmd
    $out = $r.Text
    $text = "# cmd: adb shell $cmd`r`n# note: $note`r`n# exit: $($r.ExitCode)`r`n`r`n$out"
    [System.IO.File]::WriteAllText($file, $text, (New-Object System.Text.UTF8Encoding($false)))
    $ok = ($out.Trim().Length -gt 0) -and ($out -notmatch "Permission denied|No such file|inaccessible")
    $manifest.Add(("{0,-28} {1,-8} {2}" -f $name, $(if ($ok) { "ok" } else { "EMPTY" }), $note))
}

Say "собираю (2-4 минуты)..." "Cyan"

# ── идентификация устройства и платформы
Grab "getprop"        "getprop"                                     "все свойства; ключевые: ro.product.device, ro.board.platform, ro.boot.*"
Grab "board_platform" "getprop ro.board.platform"                   "ожидается msm8937/msm8940"
Grab "device_name"    "getprop ro.product.device"                   "ожидается ugg (Prime) или ugglite"
Grab "soc_model"      "getprop ro.soc.model"                        "SoC как его видит Android"
Grab "boot_cmdline"   "cat /proc/cmdline"                           "cmdline от LK: адреса памяти, mem=, androidboot.*"
Grab "dt_compatible"  "cat /proc/device-tree/compatible"            "реальный compatible DTB — какой dtsi использовать"
Grab "dt_model"       "cat /proc/device-tree/model"                 "модель из DTB"
Grab "dt_qcom_msm_id" "cat /proc/device-tree/qcom,msm-id"           "msm-id (hex) — для совместимости dtb"

# ── память и разделы
Grab "meminfo"        "cat /proc/meminfo"                           "MemTotal => сколько RAM реально"
Grab "partitions"     "cat /proc/partitions"                        "блочные устройства и размеры"
Grab "block_byname"   "ls -l /dev/block/bootdevice/by-name"         "имена разделов -> /dev/block/mmcblk0pN"
Grab "block_sizes"    "for f in /sys/class/block/mmcblk0p*; do echo -n `$f `; cat `$f/size; done" "размеры в 512b-секторах"
Grab "mmcblk0"        "cat /sys/class/block/mmcblk0/size"           "весь eMMC, сектора"
Grab "mounts"         "mount"                                       "что смонтировано"
Grab "df"             "df -h"                                       "свободное место"

# ── дисплей (для SimpleFbDxe) и железо
Grab "display"        "dumpsys display"                             "разрешение панели, плотность"
Grab "surfaceflinger" "dumpsys SurfaceFlinger --display-id"         "панель/refresh"
Grab "lcd_density"    "getprop ro.sf.lcd_density"                   "плотность"
Grab "cpuinfo"        "cat /proc/cpuinfo"                           "ядра/частота (big.LITTLE?)"
Grab "clocks"         "cat /sys/kernel/debug/clk/clk_summary"       "без root обычно пусто"
Grab "i2c_devices"    "ls /sys/bus/i2c/devices"                     "тач/сенсоры (модели)"
Grab "input_devices"  "cat /proc/bus/input/devices"                 "кнопки/тач — какие evdev есть"
Grab "thermal"        "cat /sys/class/thermal/thermal_zone*/type"   "зоны"

# ── загрузчик / верификация
Grab "verifiedboot"   "getprop ro.boot.verifiedbootstate"           "green/orange — разблокирован ли BL"
Grab "bootloader"     "getprop ro.bootloader"                       "версия LK"
Grab "slot_suffix"    "getprop ro.boot.slot_suffix"                 "_a/_b => A/B (для ugg ожидается пусто)"
Grab "dtbo_prop"      "getprop ro.boot.dtbo_idx"                    "есть ли dtbo"

# ── только root / EDL (помечаем, если пусто)
Grab "iomem_root"     "cat /proc/iomem"                             "НУЖЕН ROOT: карта памяти как её видит ядро"
Grab "dmesg_root"     "dmesg"                                       "НУЖЕН ROOT: инициализация SDCC/USB/панели"
Grab "fb_root"        "cat /sys/class/graphics/fb0/virtual_size"     "НУЖЕН ROOT: размер framebuffer"

# ── fastboot-переменные (если телефон уйдёт в bootloader — отдельный шаг)
$fbFile = Join-Path $OutDir "fastboot_getvar_all.txt"
$fb = (Invoke-Native fastboot devices).Lines | Where-Object { $_ -match '^\S+\s+fastboot' }
if ($fb) {
    Say "  fastboot getvar all"
    $gv = Invoke-Native fastboot getvar all
    [System.IO.File]::WriteAllText($fbFile, ($gv.Text + "`r`n`r`nexit=$($gv.ExitCode)`r`n"), (New-Object System.Text.UTF8Encoding($false)))
    $manifest.Add(("{0,-28} {1,-8} {2}" -f "fastboot_getvar_all", "ok", "product, partition-size:*, unlocked"))
} else {
    $manifest.Add(("{0,-28} {1,-8} {2}" -f "fastboot_getvar_all", "SKIP", "телефон не в fastboot: adb reboot bootloader"))
}

$manifest | Out-File -Encoding utf8 (Join-Path $OutDir "manifest.txt")
Say "" 
Say "готово: $OutDir" "Green"
Write-Host ""
$manifest | ForEach-Object { Write-Host "  $_" -ForegroundColor DarkGray }
Write-Host ""
Say "EMPTY/SKIP в конце — не страшно; см. docs\03-dumps.md (что даёт EDL/root)." "Yellow"
