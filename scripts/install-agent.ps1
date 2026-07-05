#Requires -Version 5.1
<#
.SYNOPSIS
    Установка mobpc агента с автозапуском через Планировщик заданий Windows.

.PARAMETER AgentDir
    Путь к папке agent (по умолчанию — родитель scripts).

.PARAMETER PythonExe
    Путь к python.exe (по умолчанию .venv\Scripts\python.exe в AgentDir).
#>
param(
    [string]$AgentDir = (Join-Path $PSScriptRoot "..\agent" | Resolve-Path),
    [string]$PythonExe = ""
)

$ErrorActionPreference = "Stop"

if (-not $PythonExe) {
    $PythonExe = Join-Path $AgentDir ".venv\Scripts\python.exe"
}

$MainPy = Join-Path $AgentDir "main.py"
$TaskName = "mobpc-agent"

if (-not (Test-Path $MainPy)) {
    Write-Error "Не найден $MainPy"
}

Write-Host "==> Создание виртуального окружения..." -ForegroundColor Cyan
if (-not (Test-Path $PythonExe)) {
    $systemPython = Get-Command python -ErrorAction SilentlyContinue
    if (-not $systemPython) {
        Write-Error "Python не найден. Установите Python 3.11+"
    }
    Push-Location $AgentDir
    & python -m venv .venv
    & .\.venv\Scripts\pip install -r requirements.txt
    Pop-Location
}

Write-Host "==> Регистрация задачи '$TaskName'..." -ForegroundColor Cyan
$Action = New-ScheduledTaskAction -Execute $PythonExe -Argument "`"$MainPy`"" -WorkingDirectory $AgentDir
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Principal $Principal -Force

Write-Host ""
Write-Host "Агент mobpc будет запускаться при входе в систему." -ForegroundColor Green
Write-Host "Ручной запуск: $PythonExe `"$MainPy`""
Write-Host "Удалить автозапуск: Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false"
