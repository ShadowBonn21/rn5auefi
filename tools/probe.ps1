<#
.SYNOPSIS
    Проба №0 для Redmi Note 5A Prime (ugg / MSM8940): запускает дымовой образ и
    проверяет, умеет ли загрузчик (LK/aboot) входить в AArch64 и где framebuffer.

.DESCRIPTION
    Использует только `fastboot boot` — на флеш ничего не пишется.
    Образ: build\smoke.img (собирается tools\mksmoke.py, нужен только Python 3).

    Ожидаемый результат (PASS): экран мигает КРАСНЫЙ <-> ЦИАН ~3 раза в секунду.
    Если этого нет — см. docs\02-bringup-plan.md, шаг G0.

    Замечания по Windows:
      * fastboot/adb пишут вывод в stderr — здесь все вызовы идут через
        Invoke-Native (tools\_native.ps1), поэтому это не считается ошибкой;
      * `getvar version-bootloader` поддерживают не все LK — используется getvar all
        с толерантным разбором.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools\probe.ps1
    powershell -ExecutionPolicy Bypass -File tools\probe.ps1 -Dtb build\stock.dtb
#>
[CmdletBinding()]
param(
    [string]$Image = "build\smoke.img",
    [string]$Dtb = "",
    [int]$TimeoutSec = 60
)

$ErrorActionPreference = "Stop"

# Windows PowerShell 5.1: вывод python (UTF-8) не должен превращаться в кракозябры
try {
    [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
    $OutputEncoding = [System.Text.UTF8Encoding]::new()
} catch { }

. (Join-Path $PSScriptRoot "_native.ps1")

function Say($m, $c = "Gray") { Write-Host "[probe] $m" -ForegroundColor $c }

$root = Split-Path -Parent $PSScriptRoot
$imgPath = if ([System.IO.Path]::IsPathRooted($Image)) { $Image } else { Join-Path $root $Image }

# ── 1. инструменты
foreach ($t in @("fastboot", "adb")) {
    if (-not (Get-Command $t -ErrorAction SilentlyContinue)) {
        Say "не найден $t. Установите platform-tools и добавьте в PATH." "Red"
        exit 2
    }
}

# ── 2. образ: пересобрать с DTB или собрать, если отсутствует
New-Item -ItemType Directory -Force (Split-Path $imgPath) | Out-Null
# Схема сборки (проверено на устройстве): LK не смотрит на dt_size в заголовке,
# ему нужен ТОТ ЖЕ хвост, что у стокового boot.img: gzip(kernel) + весь DT-блок.
$dtblock = Join-Path $root "build\ugg.dtblock"
if ($Dtb) {
    $dtbPath = if ([System.IO.Path]::IsPathRooted($Dtb)) { $Dtb } else { Join-Path $root $Dtb }
    Say "пересборка образа с DTB: $dtbPath"
    $gen = Invoke-Native python (Join-Path $PSScriptRoot "mksmoke.py") --out $imgPath --dtb $dtbPath
}
elseif (Test-Path -LiteralPath $dtblock) {
    Say "собираю по стоковой схеме (gzip + DT-блок)"
    $gen = Invoke-Native python (Join-Path $PSScriptRoot "mksmoke.py") --out $imgPath --gzip --append $dtblock
}
else {
    Say "нет build\ugg.dtblock — собираю простой вариант (может не пройти проверку DT)" "Yellow"
    $gen = Invoke-Native python (Join-Path $PSScriptRoot "mksmoke.py") --out $imgPath
}
$gen.Lines | ForEach-Object { Say "    $_" }
if ($gen.ExitCode -ne 0) { Say "сборка образа не удалась (код $($gen.ExitCode))" "Red"; exit 3 }

# ── 3. найти устройство в fastboot; если оно в Android — перезагрузить
function Get-FastbootSerial {
    (Invoke-Native fastboot devices).Lines | Where-Object { $_ -match '^\S+\s+fastboot' } | ForEach-Object {
        ($_ -split '\s+')[0]
    }
}

$fbSerial = @(Get-FastbootSerial)
if (-not $fbSerial) {
    $adbDev = (Invoke-Native adb devices).Lines | Where-Object { $_ -match '^\S+\s+device$' }
    if ($adbDev) {
        Say "устройство в Android — перезагружаю в bootloader" "Yellow"
        (Invoke-Native adb reboot bootloader) | Out-Null
        $deadline = (Get-Date).AddSeconds($TimeoutSec)
        do {
            Start-Sleep -Milliseconds 800
            $fbSerial = @(Get-FastbootSerial)
        } while (-not $fbSerial -and (Get-Date) -lt $deadline)
    }
}
if (-not $fbSerial) {
    Say "устройство не в fastboot." "Red"
    Say "1) включите USB-отладку и проверьте: adb devices" "Red"
    Say "2) затем: adb reboot bootloader   (или выключенный: Vol- + Power)" "Red"
    exit 4
}
$serial = $fbSerial[0]
Say "устройство в fastboot: $serial" "Green"

# ── 4. картина по загрузчику (толерантно: не все LK знают version-bootloader)
$gv = Invoke-Native fastboot getvar all
$dumpDir = Join-Path $root "dump"
New-Item -ItemType Directory -Force $dumpDir | Out-Null
$gvFile = Join-Path $dumpDir "probe-getvar-$serial.txt"
if ($gv.Lines.Count -gt 0) {
    [System.IO.File]::WriteAllText($gvFile, ($gv.Text + "`r`n`r`nexit=$($gv.ExitCode)`r`n"), (New-Object System.Text.UTF8Encoding($false)))
    Say "getvar all -> $gvFile" "DarkGray"
}
$interesting = 'unlocked|secure|device-state|version-bootloader|^\(bootloader\)|product|partition-size:boot|partition-type:boot|slot-count|max-download-size|current-slot'
$shown = @($gv.Lines | Where-Object { $_ -match $interesting })
if ($shown.Count -gt 0) {
    Say "ключевые параметры:" 
    $shown | ForEach-Object { Say "    $_" }
} else {
    Say "getvar all ничего полезного не вернул (LK с урезанным fastboot) — продолжаю" "Yellow"
}

# ── 5. запуск образа
$size = (Get-Item -LiteralPath $imgPath).Length
Say ("fastboot boot {0} ({1} байт)" -f (Split-Path -Leaf $imgPath), $size) "Cyan"
$boot = Invoke-Native fastboot boot $imgPath
$boot.Lines | Where-Object { $_.Trim() } | ForEach-Object { Say "    $_" }

if ($boot.Text -match 'FAILED|error:|unknown command|not allowed|too large|too many') {
    Say "" 
    Say "образ НЕ запущен:" "Red"
    if ($boot.Text -match 'dtb not found') {
        Say "  LK требует DTB (так и есть на ugg). Сделайте:" "Red"
        Say "    1) вернуться в Android: fastboot reboot" "White"
        Say "    2) powershell -ExecutionPolicy Bypass -File tools\pull_devicetree.ps1" "White"
        Say "    3) powershell -ExecutionPolicy Bypass -File tools\probe.ps1 -Dtb build\stock.dtb" "White"
    }
    if ($boot.Text -match 'unknown command') {
        Say "  LK не поддерживает 'fastboot boot' — нужна запись в раздел (docs\04-flash-recovery.md)" "Red"
    }
    if ($boot.Text -match 'not allowed|unlock') {
        Say "  скорее всего загрузчик заблокирован (нужен Mi Unlock)" "Red"
    }
    if ($boot.Text -match 'too large|too many') {
        Say "  образ больше лимита загрузки (max-download-size) — должен быть < 64 МиБ" "Red"
    }
    Say "  полный вывод: $gvFile (рядом fastboot_boot.txt при следующем запуске)" "DarkGray"
    [System.IO.File]::WriteAllText((Join-Path $dumpDir "fastboot_boot.txt"), $boot.Text, (New-Object System.Text.UTF8Encoding($false)))
    exit 5
}

# ── 6. устройство должно уйти из fastboot, если payload начал исполняться
Start-Sleep -Seconds 3
$stillInFastboot = @(Get-FastbootSerial).Count -gt 0

Write-Host ""
Write-Host "  ─────────────────────────────────────────────────────────────" -ForegroundColor DarkGray
if ($stillInFastboot) {
    Write-Host "  Устройство ОСТАЛОСЬ в fastboot — образ, вероятно, не стартовал." -ForegroundColor Yellow
} else {
    Write-Host "  Устройство ушло из fastboot — передача управления произошла." -ForegroundColor Green
}
Write-Host "  СМОТРИТЕ НА ЭКРАН (10 секунд):" -ForegroundColor White
Write-Host "   PASS: экран мигает: красный -> зелёный -> синий -> белый (~6 Гц)" -ForegroundColor Green
Write-Host "         => LK входит в AArch64, framebuffer @0x90000000 верен" -ForegroundColor DarkGray
Write-Host "   FAIL: чёрный экран / логотип / мусор без смены цвета" -ForegroundColor Yellow
Write-Host "         => docs\02-bringup-plan.md, G0: нужен DTB или arm32-ветка" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  ВЫХОД: зажмите Power 10-15 с (hard reset). Флеш не тронут." -ForegroundColor White
Write-Host "  ─────────────────────────────────────────────────────────────" -ForegroundColor DarkGray
exit 0
