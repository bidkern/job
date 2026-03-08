# GitHub Sync

This project is not currently initialized as a Git repository, and there is no configured `origin` remote yet. The scripts below handle Git even when `git` is not on `PATH` by falling back to `C:\Program Files\Git\cmd\git.exe`.

## One-time setup

Configure the repo and attach `origin`:

```powershell
cd C:\Users\adelm\Documents\job
.\scripts\setup-github-remote.ps1 `
  -RemoteUrl "https://github.com/<owner>/<repo>.git" `
  -GitUserName "Jesse Adelman" `
  -GitUserEmail "your-email-or-github-noreply@example.com"
```

If your GitHub auth is not already configured on this machine, Git will prompt the first time a push occurs.

## Push the current workspace once

```powershell
cd C:\Users\adelm\Documents\job
.\scripts\github-sync.ps1
```

## Keep syncing automatically

This loop checks the repo every 2 minutes, commits any changed files, and pushes the current branch to `origin`.

```powershell
cd C:\Users\adelm\Documents\job
.\scripts\start-github-autosync.ps1 -IntervalSeconds 120
```

## Notes

- The auto-sync script only works after the workspace is attached to a GitHub remote.
- It creates timestamped commits automatically. That is efficient, but it also publishes intermediate work. If you want cleaner commit history, use `github-sync.ps1` manually instead of the loop.
- If you want Codex to keep pushing after each major change set, the current missing input is the GitHub repo URL for `origin`.
