#Requires -Version 5.1
<#
.SYNOPSIS
    Настройка интернет-доступа к mobpc агенту через Tailscale или Cloudflare Tunnel.

.DESCRIPTION
    По умолчанию использует Tailscale. С флагом -UseCloudflare запускает cloudflared.

.PARAMETER UseCloudflare
    Использовать Cloudflare Tunnel вместо Tailscale.

.PARAMETER AgentPort
    Порт агента mobpc (по умолчанию 8765).
#>
param(
    [switch]$UseCloudflare,
    [int]$AgentPort = 8765
)

$ErrorActionPreference = "Stop"

function Write-Step($msg) {
    Write-Host "==> $msg" -ForegroundColor Cyan
}

function Test-Command($name) {
    return [bool](Get-Command $name -ErrorAction SilentlyContinue)
}

if ($UseCloudflare) {
    Write-Step "Режим: Cloudflare Tunnel"

    if (-not (Test-Command "cloudflared")) {
        Write-Host "cloudflared не найден. Установите:" -ForegroundColor Yellow
        Write-Host "  winget install Cloudflare.cloudflared"
        exit 1
    }

    Write-Step "Запуск туннеля на http://127.0.0.1:$AgentPort"
    Write-Host "Скопируйте HTTPS URL из вывода cloudflared и используйте как host в приложении."
    Write-Host "Включите TLS (WSS) в настройках подключения."
    cloudflared tunnel --url "http://127.0.0.1:$AgentPort"
    exit 0
}

Write-Step "Режим: Tailscale"

if (-not (Test-Command "tailscale")) {
    Write-Host "Tailscale не найден. Установите:" -ForegroundColor Yellow
    Write-Host "  winget install Tailscale.Tailscale"
    Write-Host ""
    Write-Host "После установки:"
    Write-Host "  1. Войдите в аккаунт Tailscale на ПК"
    Write-Host "  2. Установите Tailscale на телефон (Play Store / App Store)"
    Write-Host "  3. Запустите этот скрипт снова"
    exit 1
}

Write-Step "Проверка статуса Tailscale..."
$status = tailscale status --json 2>$null | ConvertFrom-Json
if (-not $status) {
    Write-Host "Tailscale не подключён. Запустите Tailscale и войдите в аккаунт." -ForegroundColor Red
    exit 1
}

Write-Step "Получение Tailscale IP..."
$ip = tailscale ip -4 2>$null
if (-not $ip) {
    Write-Host "Не удалось получить Tailscale IPv4." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  mobpc доступен через интернет!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Tailscale IP:  $ip"
Write-Host "  Порт агента:   $AgentPort"
Write-Host ""
Write-Host "  В приложении mobpc укажите:"
Write-Host "    Host: $ip"
Write-Host "    Port: $AgentPort"
Write-Host "    TLS:  выкл (для Tailscale mesh)"
Write-Host ""
Write-Host "  Убедитесь что агент запущен:"
Write-Host "    cd agent"
Write-Host "    .venv\Scripts\activate"
Write-Host "    python main.py"
Write-Host ""

# Проверка что порт слушается
$listening = Get-NetTCPConnection -LocalPort $AgentPort -State Listen -ErrorAction SilentlyContinue
if ($listening) {
    Write-Host "  [OK] Порт $AgentPort слушается" -ForegroundColor Green
} else {
    Write-Host "  [!] Порт $AgentPort не слушается — запустите агент" -ForegroundColor Yellow
}

Write-Step "Готово"
