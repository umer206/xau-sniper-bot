param(
    [string]$LogPath = "logs\bot.log",
    [int]$Tail = 120
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not (Test-Path $LogPath)) {
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $LogPath) | Out-Null
    New-Item -ItemType File -Force -Path $LogPath | Out-Null
}

Get-Content $LogPath -Wait -Tail $Tail

