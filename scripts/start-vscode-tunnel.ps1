param(
    [string]$Name = "xau-mt5-home"
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command code -ErrorAction SilentlyContinue)) {
    throw "VS Code CLI 'code' was not found. Install VS Code and enable the code command in PATH."
}

code tunnel --name $Name

