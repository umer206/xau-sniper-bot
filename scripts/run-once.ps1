param(
    [string]$Config = "config.json",
    [switch]$Live
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

. .\scripts\load-env.ps1

New-Item -ItemType Directory -Force -Path "logs" | Out-Null
if ($Live) {
    python -m xau_sniper_bot.bot --config $Config --once --live
} else {
    python -m xau_sniper_bot.bot --config $Config --once
}
