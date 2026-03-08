param(
    [Parameter(Mandatory = $true)]
    [string]$RemoteUrl,
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$DefaultBranch = "main",
    [string]$GitUserName = "",
    [string]$GitUserEmail = ""
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

if ($RemoteUrl -match '<owner>' -or $RemoteUrl -match '<repo>') {
    throw "RemoteUrl still contains the placeholder values. Use the real GitHub repo URL."
}

Push-Location $RepoRoot
try {
    & $git rev-parse --is-inside-work-tree *> $null
    if ($LASTEXITCODE -ne 0) {
        & $git init -b $DefaultBranch
        if ($LASTEXITCODE -ne 0) {
            throw "git init failed."
        }
    }

    $existingOrigin = (& $git remote get-url origin 2>$null | Select-Object -First 1)
    if ($existingOrigin) {
        & $git remote set-url origin $RemoteUrl
    }
    else {
        & $git remote add origin $RemoteUrl
    }

    if ($LASTEXITCODE -ne 0) {
        throw "Configuring git remote failed."
    }

    $existingName = (& $git config --local --get user.name 2>$null | Select-Object -First 1)
    $existingEmail = (& $git config --local --get user.email 2>$null | Select-Object -First 1)

    if (-not $existingName -and $GitUserName) {
        & $git config --local user.name $GitUserName
    }
    if (-not $existingEmail -and $GitUserEmail) {
        & $git config --local user.email $GitUserEmail
    }

    $currentBranch = (& $git branch --show-current | Select-Object -First 1).Trim()
    if (-not $currentBranch) {
        & $git checkout -b $DefaultBranch
        if ($LASTEXITCODE -ne 0) {
            throw "Creating default branch failed."
        }
        $currentBranch = $DefaultBranch
    }

    Write-Output "Git remote configured."
    Write-Output "Repo root: $RepoRoot"
    Write-Output "Branch: $currentBranch"
    Write-Output "Origin: $RemoteUrl"
    Write-Output "Next: run scripts\\github-sync.ps1 to push current changes."
}
finally {
    Pop-Location
}
