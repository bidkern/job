param(
    [int]$IntervalSeconds = 120,
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$MessagePrefix = "chore: codex auto-sync"
)

if ($IntervalSeconds -lt 30) {
    throw "IntervalSeconds must be at least 30 seconds."
}

$syncScript = Join-Path $PSScriptRoot "github-sync.ps1"
if (-not (Test-Path $syncScript)) {
    throw "Sync script not found: $syncScript"
}

Write-Output "Starting GitHub auto-sync loop for $RepoRoot"
Write-Output "Interval: $IntervalSeconds seconds"
Write-Output "Press Ctrl+C to stop."

while ($true) {
    $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    try {
        & $syncScript -RepoRoot $RepoRoot -Message "$MessagePrefix $stamp"
    }
    catch {
        Write-Warning $_.Exception.Message
    }

    Start-Sleep -Seconds $IntervalSeconds
}
