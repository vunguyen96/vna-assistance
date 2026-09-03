<#
.SYNOPSIS
    Remove vna-assistance integration from this machine.

.DESCRIPTION
    Removes the installed skills, the session hook, and the Desktop shortcut.
    Your notes (the data folder) are kept unless you pass -PurgeData.

.PARAMETER CopilotConfig
    Copilot CLI config directory. Default: %USERPROFILE%\.copilot

.PARAMETER PurgeData
    Also delete the data folder (default: VNA_HOME or %USERPROFILE%\vna-assistance).
#>
[CmdletBinding()]
param(
    [string]$CopilotConfig = (Join-Path $HOME ".copilot"),
    [switch]$PurgeData
)

$ErrorActionPreference = "SilentlyContinue"

"vna-assistance-note", "vna-assistance-done", "vna-assistance-review" | ForEach-Object {
    $p = Join-Path (Join-Path $CopilotConfig "skills") $_
    if (Test-Path $p) { Remove-Item $p -Recurse -Force; Write-Host "removed skill: $_" }
}

$hook = Join-Path (Join-Path $CopilotConfig "hooks") "vna-assistance-reminder.json"
if (Test-Path $hook) { Remove-Item $hook -Force; Write-Host "removed hook" }

$lnk = Join-Path ([Environment]::GetFolderPath("Desktop")) "vna-assistance.lnk"
if (Test-Path $lnk) { Remove-Item $lnk -Force; Write-Host "removed desktop shortcut" }

if ($PurgeData) {
    $data = $(if ($env:VNA_HOME) { $env:VNA_HOME } else { Join-Path $HOME "vna-assistance" })
    if (Test-Path $data) { Remove-Item $data -Recurse -Force; Write-Host "purged data folder: $data" }
} else {
    Write-Host "data folder kept (pass -PurgeData to delete notes)."
}

Write-Host "Uninstall complete."
