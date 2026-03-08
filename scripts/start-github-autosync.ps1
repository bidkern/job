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
        $message = $_.Exception.Message
        Write-Warning $message
        if (
            $message -match "placeholder URL" -or
            $message -match "No git remote" -or
            $message -match "Git author identity is missing" -or
            $message -match "not a git repository"
        ) {
            Write-Warning "Auto-sync stopped because the git configuration is incomplete."
            break
        }
    }

    Start-Sleep -Seconds $IntervalSeconds
}
