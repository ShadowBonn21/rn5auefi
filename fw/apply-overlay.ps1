<#
.SYNOPSIS
    Накладывает порт msm8937/ugg на клон edk2-msm.

.DESCRIPTION
    edk2-msm не поддерживает MSM8937/8940, поэтому порт живёт отдельным слоем:
      1) берём из апстрима всё, что SoC-независимо;
      2) копируем библиотеки sdm660 -> msm8937 и переименовываем;
      3) поверх кладём наши файлы (memory map, UART, DSC/FDF, configs).

.EXAMPLE
    git clone --recurse-submodules https://github.com/edk2-porting/edk2-msm
    powershell -ExecutionPolicy Bypass -File fw\apply-overlay.ps1 -Edk2Msm ..\edk2-msm
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Edk2Msm,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
# Windows PowerShell 5.1: вывод python (UTF-8) не должен превращаться в кракозябры
    try {
        [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
        $OutputEncoding = [System.Text.UTF8Encoding]::new()
    } catch { }

    function Say($m, $c = "Gray") { Write-Host "[overlay] $m" -ForegroundColor $c }

$repo = (Resolve-Path $Edk2Msm).Path
$fw   = Split-Path -Parent $MyInvocation.MyCommand.Path

# --- проверки, что это действительно edk2-msm
foreach ($p in @("build.sh", "Silicon\Qualcomm\sdm660", "Silicon\Qualcomm\QcomPkg\PrePi")) {
    if (-not (Test-Path (Join-Path $repo $p))) {
        Say "не похоже на edk2-msm: нет $p" "Red"; exit 2
    }
}
if (-not (Test-Path (Join-Path $repo "Common\edk2\edksetup.sh"))) {
    Say "сабмодули не инициализированы: git submodule update --init --depth 1" "Red"
    if (-not $Force) { exit 3 }
}

# --- 1. копируем SoC-библиотеки с sdm660 и переименовываем
$libs = @("PlatformPeiLib", "PlatformPrePiLib", "MsPlatformDevicesLib", "SOCSmbiosInfoLib")
$srcRoot = Join-Path $repo "Silicon\Qualcomm\sdm660"
$dstRoot = Join-Path $repo "Silicon\Qualcomm\msm8937"
New-Item -ItemType Directory -Force $dstRoot | Out-Null

foreach ($lib in $libs) {
    $src = Join-Path $srcRoot "Library\$lib"
    $dst = Join-Path $dstRoot "Library\$lib"
    if (-not (Test-Path $src)) { Say "нет $src — пропускаю" "Yellow"; continue }
    if ((Test-Path $dst) -and -not $Force) { Say "$lib уже есть (используйте -Force)" "Yellow"; continue }
    Copy-Item $src $dst -Recurse -Force
    Get-ChildItem $dst -Recurse -File | ForEach-Object {
        $t = Get-Content $_.FullName -Raw
        $t = $t -replace 'sdm660', 'msm8937' -replace 'SDM660', 'MSM8937' -replace 'sdm660Pkg', 'Msm8937Pkg'
        Set-Content -Path $_.FullName -Value $t -Encoding utf8 -NoNewline
    }
    Say "скопировано $lib -> msm8937 (имена заменены)" "Green"
}

# platform.sh.inc
Copy-Item (Join-Path $srcRoot "platform.sh.inc") (Join-Path $dstRoot "platform.sh.inc.sdm660-ref") -Force -ErrorAction SilentlyContinue

# --- 2. наш слой поверх
$items = @(
    @{ From = "Silicon\Qualcomm\msm8937";              To = "Silicon\Qualcomm\msm8937" },
    @{ From = "Silicon\Qualcomm\QcomPkg\Library";      To = "Silicon\Qualcomm\QcomPkg\Library" },
    @{ From = "Platform\Qualcomm\msm8937";             To = "Platform\Qualcomm\msm8937" },
    @{ From = "Platform\Xiaomi\msm8937";               To = "Platform\Xiaomi\msm8937" },
    @{ From = "configs\msm8937.conf";                  To = "configs\msm8937.conf" },
    @{ From = "configs\devices\ugg.conf";              To = "configs\devices\ugg.conf" }
)
foreach ($it in $items) {
    $from = Join-Path $fw $it.From
    $to   = Join-Path $repo $it.To
    if (-not (Test-Path $from)) { Say "нет $from" "Red"; continue }
    New-Item -ItemType Directory -Force (Split-Path $to -Parent) | Out-Null
    if ((Get-Item $from) -is [System.IO.DirectoryInfo]) {
        Copy-Item (Join-Path $from "*") $to -Recurse -Force
    } else {
        Copy-Item $from $to -Force
    }
    Say "наложено $($it.From)" "Green"
}

# --- 2b. патч SimpleFbDxe: stride 2944 вместо width*4
$patcher = Join-Path $fw "patches\apply_simplefb_stride.py"
if (Test-Path $patcher) {
    $out = & python $patcher $repo 2>&1
    $out | ForEach-Object { Say "  $_" "Green" }
    if ($LASTEXITCODE -ne 0) { Say "патч SimpleFbDxe не применён — консоль UEFI поедет полосами" "Red" }
}
# --- 3. чек-лист правок, которые скрипт НЕ делает
Say ""
Say "ЧТО ПРОВЕРИТЬ РУКАМИ (адреса были под sdm660):" "Cyan"
Say "  Silicon/Qualcomm/msm8937/Library/PlatformPeiLib/PlatformPeiLib.c" "White"
Say "    - 'Info Blk' 0x9FFFF000  -> у нас 0x8E0D0000" "DarkGray"
Say "  Silicon/Qualcomm/msm8937/Library/PlatformPrePiLib/PlatformUtils.c" "White"
Say "    - адреса регистров/фреймбуфера -> см. PlatformMemoryMapLib.c" "DarkGray"
Say "  Silicon/Qualcomm/msm8937/Library/MsPlatformDevicesLib/MsPlatformDevicesLib.c" "White"
Say "    - список устройств (тач/кнопки/USB) -> переписать под ugg" "DarkGray"
Say "  configs/msm8937.conf: FD_BASE/FD_SIZE должны совпадать с картой памяти" "White"
Say ""
Say "ДАЛЬШЕ: bash build.sh --device ugg -t GCC5 -u   (см. docs/05-build.md)" "Cyan"
