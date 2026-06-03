param(
    [string]$StatusPath = "runtime\status.json",
    [int]$StaleSeconds = 180,
    [int]$RefreshSeconds = 5
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Show-Status {
    if (-not (Test-Path $StatusPath)) {
        Write-Host "UNKNOWN  status file not found: $StatusPath" -ForegroundColor Yellow
        return
    }

    try {
        $raw = Get-Content -Raw -Path $StatusPath
        $status = $raw | ConvertFrom-Json
        $heartbeat = [DateTimeOffset]::Parse($status.last_heartbeat)
        $age = ([DateTimeOffset]::UtcNow - $heartbeat.ToUniversalTime()).TotalSeconds
        $mode = if ($status.dry_run) { "DRY-RUN" } else { "LIVE" }
        $line = "{0:u}  {1,-8}  age={2,4:n0}s  mode={3}  {4}" -f `
            [DateTimeOffset]::Now, $status.status.ToUpper(), $age, $mode, $status.message

        if ($age -gt $StaleSeconds -and $status.status -eq "running") {
            Write-Host ("{0:u}  OFFLINE   age={1,4:n0}s  last={2}" -f `
                [DateTimeOffset]::Now, $age, $status.message) -ForegroundColor Red
        } elseif ($status.status -eq "running") {
            Write-Host $line -ForegroundColor Green
        } elseif ($status.status -eq "stopped") {
            Write-Host $line -ForegroundColor Yellow
        } elseif ($status.status -eq "error") {
            Write-Host $line -ForegroundColor Red
        } else {
            Write-Host $line
        }
    } catch {
        Write-Host "ERROR    could not read status: $_" -ForegroundColor Red
    }
}

while ($true) {
    Show-Status
    Start-Sleep -Seconds $RefreshSeconds
}

