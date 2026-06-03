param(
    [string]$Config = "config.json",
    [string]$Title = "XAU bot test",
    [string]$Message = "Pushover alerts are connected."
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

. .\scripts\load-env.ps1

python -m xau_sniper_bot.pushover_test --config $Config --title $Title --message $Message
