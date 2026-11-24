# tools/_native.ps1 — надёжный запуск внешних программ в Windows PowerShell 5.1.
#
# Проблема, которую это лечит: fastboot и adb пишут обычный вывод в STDERR
# (например, "fastboot: error: ...", "adb: * daemon not running"), из-за чего
# PowerShell 5.1 при $ErrorActionPreference='Stop' считает это фатальной ошибкой
# и обрывает скрипт. Здесь stderr/stdout сливаются в один массив строк, а код
# возврата отдаётся явно.
#
# Использование:
#   . "$PSScriptRoot\_native.ps1"
#   $r = Invoke-Native fastboot devices
#   $r.ExitCode; $r.Lines; $r.Text

function Invoke-Native {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true, Position = 0)][string]$File,
        [Parameter(Position = 1, ValueFromRemainingArguments = $true)][string[]]$Arguments = @()
    )

    $g = [guid]::NewGuid().ToString('N')
    $outF = Join-Path $env:TEMP ("dsh_native_out_$g.txt")
    $errF = Join-Path $env:TEMP ("dsh_native_err_$g.txt")
    $lines = New-Object 'System.Collections.Generic.List[string]'
    $code = -1

    try {
        $exe = $File
        $cmd = Get-Command $File -ErrorAction SilentlyContinue
        if ($cmd -and $cmd.Source) { $exe = $cmd.Source }

        $args2 = @()
        foreach ($a in $Arguments) { $args2 += [string]$a }

        $p = Start-Process -FilePath $exe -ArgumentList $args2 -NoNewWindow -Wait -PassThru `
            -RedirectStandardOutput $outF -RedirectStandardError $errF
        $code = $p.ExitCode

        foreach ($f in @($outF, $errF)) {
            if (Test-Path -LiteralPath $f) {
                $content = Get-Content -LiteralPath $f -Encoding UTF8 -ErrorAction SilentlyContinue
                if ($null -ne $content) {
                    foreach ($l in $content) { if ($null -ne $l) { $lines.Add([string]$l) } }
                }
            }
        }
    }
    catch {
        $lines.Add("[Invoke-Native] $File не запущен: $($_.Exception.Message)")
    }
    finally {
        Remove-Item -LiteralPath $outF, $errF -Force -ErrorAction SilentlyContinue
    }

    [pscustomobject]@{
        ExitCode = $code
        Lines    = $lines.ToArray()
        Text     = ($lines -join "`r`n")
    }
}

<#
.SYNOPSIS
    Запуск внешней программы с сохранением stdout в файл БЕЗ перекодирования.

.DESCRIPTION
    Нужен для двоичного вывода (например, `adb exec-out tar -cf -`). В PowerShell
    оператор `>` пишет текст и портит байты, поэтому здесь используется
    System.Diagnostics.Process и копирование BaseStream.

    Аргументы передаются простым списком: пути с пробелами не поддерживаются —
    для наших вызовов (adb/tar с путями /proc, /sdcard, build\...) это не нужно.
#>
function Invoke-NativeBinary {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true, Position = 0)][string]$File,
        [Parameter(Mandatory = $true, Position = 1)][string[]]$Arguments,
        [Parameter(Mandatory = $true, Position = 2)][string]$OutFile
    )

    $cmd = Get-Command $File -ErrorAction SilentlyContinue
    if (-not $cmd) { return [pscustomobject]@{ ExitCode = -1; Error = "не найден $File" } }

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $cmd.Source
    $psi.Arguments = ($Arguments -join ' ')
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = $true

    $errText = ""
    try {
        $p = [System.Diagnostics.Process]::Start($psi)
        $fs = [System.IO.File]::Create($OutFile)
        try {
            $p.StandardOutput.BaseStream.CopyTo($fs)
        } finally {
            $fs.Dispose()
        }
        $errText = $p.StandardError.ReadToEnd()
        $p.WaitForExit()
        return [pscustomobject]@{ ExitCode = $p.ExitCode; Error = $errText }
    } catch {
        return [pscustomobject]@{ ExitCode = -1; Error = $_.Exception.Message }
    }
}
