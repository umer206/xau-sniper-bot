param(
    [string]$Name = "xau-mt5-host"
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command code -ErrorAction SilentlyContinue)) {
    throw "VS Code CLI 'code' was not found. Install VS Code and enable the code command in PATH."
}

Write-Host "Installing VS Code Tunnel as a background service named '$Name'."
Write-Host "You may be prompted to sign in with GitHub or Microsoft."
code tunnel service install --name $Name

