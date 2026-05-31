param(
    [string]$EnvPath = ".env"
)

$Root = Split-Path -Parent $PSScriptRoot
$EnvFile = Join-Path $Root $EnvPath

if (Test-Path $EnvFile) {
    Get-Content $EnvFile | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#") -or -not $line.Contains("=")) {
            return
        }
        $key, $value = $line.Split("=", 2)
        $key = $key.Trim()
        $value = $value.Trim().Trim('"').Trim("'")
        if ($key) {
            Set-Item -Path "Env:$key" -Value $value
        }
    }
}

foreach ($name in @("PUSHOVER_APP_TOKEN", "PUSHOVER_USER_KEY", "OPENAI_API_KEY")) {
    if (-not (Get-Item -Path "Env:$name" -ErrorAction SilentlyContinue).Value) {
        $userValue = [Environment]::GetEnvironmentVariable($name, "User")
        if ($userValue) {
            Set-Item -Path "Env:$name" -Value $userValue
            continue
        }
        $machineValue = [Environment]::GetEnvironmentVariable($name, "Machine")
        if ($machineValue) {
            Set-Item -Path "Env:$name" -Value $machineValue
        }
    }
}

