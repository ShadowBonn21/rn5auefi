<#
.SYNOPSIS
    Собрать DTB устройства ugg из живого Android (adb), без скачивания прошивки.

.DESCRIPTION
    LK на ugg требует DTB ("dtb not found"), поэтому и проба, и UEFI-образ
    собираются с приложенным DTB. Скрипт:
      1) забирает /proc/device-tree с телефона (adb pull; если не выйдет — tar);
      2) собирает бинарный DTB (tools/mkfdt_from_tree.py);
      3) печатает model / compatible / qcom,msm-id / qcom,board-id.

    Если телефон в fastboot — скрипт скажет, что нужно вернуться в Android.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools\pull_devicetree.ps1
#>
[CmdletBinding()]
param(
    [string]$Out = "build\stock.dtb"
)

$ErrorActionPreference = "Stop"

try {
    [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
    $OutputEncoding = [System.Text.UTF8Encoding]::new()
} catch { }

. (Join-Path $PSScriptRoot "_native.ps1")

function Say($m, $c = "Gray") { Write-Host "[dt] $m" -ForegroundColor $c }

$root = Split-Path -Parent $PSScriptRoot
$outPath = if ([System.IO.Path]::IsPathRooted($Out)) { $Out } else { Join-Path $root $Out }
$stage = Join-Path $root "build\_dt_stage"
$work = Join-Path $root "build\device-tree"

foreach ($t in @("adb", "python")) {
    if (-not (Get-Command $t -ErrorAction SilentlyContinue)) { Say "не найден $t в PATH" "Red"; exit 2 }
}

# ── 1. устройство должно быть в adb (Android)
$adbDev = @((Invoke-Native adb devices).Lines | Where-Object { $_ -match '^\S+\s+device$' })
if ($adbDev.Count -eq 0) {
    $fb = @((Invoke-Native fastboot devices).Lines | Where-Object { $_ -match '^\S+\s+fastboot' })
    if ($fb.Count -gt 0) {
        Say "телефон в fastboot — для этого шага нужен Android:" "Yellow"
        Say "    fastboot reboot" "White"
        Say "затем запустите скрипт снова." "Yellow"
    } else {
        Say "нет устройства. Включите USB-отладку и подключите кабель." "Red"
    }
    Say ""
    Say "Обходной путь без телефона: boot.img из официального fastboot-ROM ugg" "DarkGray"
    Say "    python tools\extract_dtb.py <boot.img> -o build\stock.dtb" "DarkGray"
    exit 3
}
$serial = (($adbDev[0]) -split '\s+')[0]
Say "устройство: $serial" "Green"

# ── 2. забрать дерево
Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force (Split-Path $stage) | Out-Null

Say "adb pull /proc/device-tree ..."
$pull = Invoke-Native adb -s $serial pull /proc/device-tree $stage
$pull.Lines | Where-Object { $_.Trim() } | Select-Object -Last 3 | ForEach-Object { Say "    $_" }

function Find-Root([string]$dir) {
    # adb может создать вложенный каталог device-tree/
    if (Test-Path -LiteralPath (Join-Path $dir "model")) { return $dir }
    if (Test-Path -LiteralPath (Join-Path $dir "compatible")) { return $dir }
    $nested = Join-Path $dir "device-tree"
    if ((Test-Path -LiteralPath (Join-Path $nested "model")) -or (Test-Path -LiteralPath (Join-Path $nested "compatible"))) { return $nested }
    return $null
}

$srcRoot = Find-Root $stage
if (-not $srcRoot) {
    Say "adb pull не дал дерево, пробую tar (двоичный вывод)" "Yellow"
    $tar = Join-Path $root "build\_dt_stage.tar"
    $r = Invoke-NativeBinary adb @('-s', $serial, 'exec-out', 'tar', '-C', '/proc', '-cf', '-', 'device-tree') $tar
    if ($r.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $tar) -or (Get-Item -LiteralPath $tar).Length -lt 1024) {
        Say "не удалось: $($r.Error)" "Red"
        Say "проверьте вручную: adb shell ls -l /proc/device-tree" "Red"
        exit 4
    }
    Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force $stage | Out-Null
    & tar.exe -xf $tar -C $stage 2>$null
    Remove-Item -LiteralPath $tar -Force -ErrorAction SilentlyContinue
    $srcRoot = Find-Root $stage
}
if (-not $srcRoot) { Say "дерево не получено" "Red"; exit 5 }

# ── 3. нормализуем расположение: build\device-tree
if ($srcRoot -ne $work) {
    Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
    Move-Item -LiteralPath $srcRoot -Destination $work -Force
}
$count = @(Get-ChildItem -LiteralPath $work -Recurse -File -ErrorAction SilentlyContinue).Count
Say "получено файлов: $count" "Green"
if ($count -lt 50) { Say "подозрительно мало файлов — дерево могло приехать частично" "Yellow" }

# ── 4. собрать DTB
Say "собираю DTB ..."
$gen = Invoke-Native python (Join-Path $PSScriptRoot "mkfdt_from_tree.py") $work -o $outPath
$gen.Lines | ForEach-Object { Say "    $_" }
if ($gen.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $outPath)) { Say "сборка DTB не удалась" "Red"; exit 6 }

Say ""
Say ("готово: {0} ({1} байт)" -f $outPath, (Get-Item -LiteralPath $outPath).Length) "Green"
Say ""
Say "СЛЕДУЮЩИЙ ШАГ — проба с DTB:" "Cyan"
Say ("    powershell -ExecutionPolicy Bypass -File tools\probe.ps1 -Dtb " + $Out) "White"
Say ""
Say "Если LK опять скажет 'dtb not found' — нужен именно стоковый DTB из boot.img:" "DarkGray"
Say "    python tools\extract_dtb.py <boot.img> -o build\stock.dtb   (docs\03-dumps.md)" "DarkGray"
exit 0
