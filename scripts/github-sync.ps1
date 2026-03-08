param(
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$Message = "",
    [switch]$AllowEmpty
)

function Resolve-GitExecutable {
    $gitCommand = Get-Command git -ErrorAction SilentlyContinue
    if ($gitCommand) {
        return $gitCommand.Source
    }

    $candidates = @(
        "C:\Program Files\Git\cmd\git.exe",
        "C:\Program Files\Git\bin\git.exe"
    )

    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) {
            return $candidate
        }
    }

    throw "Git executable not found. Install Git or add it to PATH."
}

$git = Resolve-GitExecutable

Push-Location $RepoRoot
try {
    & $git rev-parse --is-inside-work-tree *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "Repo root is not a git repository: $RepoRoot"
    }

    $originUrl = (& $git remote get-url origin 2>$null | Select-Object -First 1)
    if (-not $originUrl) {
        throw "No git remote named 'origin' is configured for $RepoRoot"
    }
    if ($originUrl -match '<owner>' -or $originUrl -match '<repo>') {
        throw "The configured origin is still a placeholder URL. Replace it with the real GitHub repo URL first."
    }

    $userName = (& $git config --local --get user.name 2>$null | Select-Object -First 1)
    $userEmail = (& $git config --local --get user.email 2>$null | Select-Object -First 1)
    if (-not $userName -or -not $userEmail) {
        throw "Git author identity is missing. Set local user.name and user.email before syncing."
    }

    $status = (& $git status --porcelain=v1)
    if (-not $AllowEmpty -and -not $status) {
        Write-Output "No changes to sync."
        return
    }

    & $git add -A
    if ($LASTEXITCODE -ne 0) {
        throw "git add failed."
    }

    if ($status) {
        $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        $commitMessage = if ($Message) { $Message } else { "chore: codex sync $stamp" }
        & $git commit -m $commitMessage
        if ($LASTEXITCODE -ne 0) {
            throw "git commit failed."
        }
    }

    $branch = (& $git branch --show-current | Select-Object -First 1).Trim()
    if (-not $branch) {
        throw "Could not determine the current branch."
    }

    & $git push origin $branch
    if ($LASTEXITCODE -ne 0) {
        throw "git push failed."
    }

    Write-Output "Synced branch '$branch' to '$originUrl'."
}
finally {
    Pop-Location
}
