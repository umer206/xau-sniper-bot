param(
    [string]$Config = "config.json"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host "LIVE MODE: approved setups can be sent to MT5." -ForegroundColor Yellow
Write-Host "Press Ctrl+C now if this is not intentional." -ForegroundColor Yellow
Start-Sleep -Seconds 5

New-Item -ItemType Directory -Force -Path "logs" | Out-Null
python -m xau_sniper_bot.bot --config $Config --live

