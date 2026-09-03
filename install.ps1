<#
.SYNOPSIS
    Install vna-assistance on this machine.

.DESCRIPTION
    Wires the repository into GitHub Copilot CLI and prepares the local store:
      1. Creates the data folder (default: %USERPROFILE%\vna-assistance).
      2. Installs the three skills into the Copilot config (skills\<name>\SKILL.md).
      3. Installs the sessionStart hook, patched to point at this repo.
      4. Installs the optional Python dependency (dateparser), best effort.
      5. Creates Desktop and Start Menu shortcuts that launch the HTA viewer.
      6. Attempts to pin the viewer shortcut to the taskbar.
      7. Adds the viewer to the current user's Windows Startup folder.

    The app itself hard-codes no paths: the CLI and HTA resolve the data folder
    from %USERPROFILE% (or VNA_HOME) and the HTA finds the CLI from its own
    location at runtime.

.PARAMETER CopilotConfig
    Copilot CLI config directory. Default: %USERPROFILE%\.copilot

.PARAMETER DataDir
    Where notes are stored. Default: VNA_HOME, else %USERPROFILE%\vna-assistance

.PARAMETER NoHook
    Skip installing the sessionStart hook.

.PARAMETER NoShortcut
    Skip creating the Desktop shortcut.

.PARAMETER NoDeps
    Skip the optional "pip install dateparser" step.

.PARAMETER NoStartup
    Skip creating the Windows Startup shortcut.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\install.ps1
#>
[CmdletBinding()]
param(
    [string]$CopilotConfig = (Join-Path $HOME ".copilot"),
    [string]$DataDir = $(if ($env:VNA_HOME) { $env:VNA_HOME } else { Join-Path $HOME "vna-assistance" }),
    [switch]$NoHook,
    [switch]$NoShortcut,
    [switch]$NoDeps,
    [switch]$NoStartup
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot

function Info($m) { Write-Host "  $m" }

function Pin-ShortcutToTaskbar($shortcutPath) {
    $shell = New-Object -ComObject Shell.Application
    $folder = $shell.Namespace((Split-Path $shortcutPath))
    $item = $folder.ParseName((Split-Path $shortcutPath -Leaf))
    if (-not $item) { return $false }

    $pinVerb = $item.Verbs() | Where-Object {
        $_.Name -match "pin" -and $_.Name -match "task.?bar"
    } | Select-Object -First 1
    if (-not $pinVerb) { return $false }

    $pinVerb.DoIt()
    return $true
}

Write-Host ""
Write-Host "vna-assistance installer"
Write-Host "========================"
Info "repo folder    : $Root"
Info "copilot config : $CopilotConfig"
Info "data folder    : $DataDir"
Write-Host ""

# 1. Data folder ------------------------------------------------------------
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
Write-Host "[1/7] Data folder ready."

# 2. Skills -----------------------------------------------------------------
$skillsSrc = Join-Path $Root "copilot\skills"
$skillsDst = Join-Path $CopilotConfig "skills"
New-Item -ItemType Directory -Force -Path $skillsDst | Out-Null
Get-ChildItem $skillsSrc -Directory | ForEach-Object {
    $dst = Join-Path $skillsDst $_.Name
    New-Item -ItemType Directory -Force -Path $dst | Out-Null
    Copy-Item (Join-Path $_.FullName "SKILL.md") $dst -Force
    Info "installed skill: $($_.Name)"
}
Write-Host "[2/7] Skills installed."

# 3. Hook (patched to this repo) -------------------------------------------
if (-not $NoHook) {
    $hookDst = Join-Path $CopilotConfig "hooks"
    New-Item -ItemType Directory -Force -Path $hookDst | Out-Null
    $hookText = Get-Content (Join-Path $Root "copilot\hooks\vna-assistance-reminder.json") -Raw
    $hookText = $hookText.Replace("__VNA_PROJECT__", $Root.Replace("\", "\\"))
    Set-Content -Path (Join-Path $hookDst "vna-assistance-reminder.json") -Value $hookText -Encoding UTF8
    Write-Host "[3/7] Session hook installed."
} else {
    Write-Host "[3/7] Session hook skipped (-NoHook)."
}

# 4. Optional Python dependency --------------------------------------------
if (-not $NoDeps) {
    try {
        python -m pip install --quiet --user dateparser
        Write-Host "[4/7] dateparser installed (better date parsing)."
    } catch {
        Write-Host "[4/7] dateparser not installed (optional). Run 'pip install dateparser' later."
    }
} else {
    Write-Host "[4/7] Python deps skipped (-NoDeps)."
}

# 5. Shortcuts --------------------------------------------------------------
if (-not $NoShortcut) {
    $hta = Join-Path $Root "web\vna-assistance.hta"
    $ico = Join-Path $Root "web\vna-assistance.ico"
    $ws = New-Object -ComObject WScript.Shell
    $lnkPath = Join-Path ([Environment]::GetFolderPath("Desktop")) "VNA Assistance.lnk"
    $startMenuDir = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
    $startMenuLnkPath = Join-Path $startMenuDir "VNA Assistance.lnk"
    New-Item -ItemType Directory -Force -Path $startMenuDir | Out-Null

    $lnk = $ws.CreateShortcut($lnkPath)
    $lnk.TargetPath = "mshta.exe"
    $lnk.Arguments = '"' + $hta + '"'
    if (Test-Path $ico) { $lnk.IconLocation = $ico }
    $lnk.WorkingDirectory = (Join-Path $Root "web")
    $lnk.Description = "vna-assistance task viewer"
    $lnk.Save()

    Copy-Item $lnkPath $startMenuLnkPath -Force
    Write-Host "[5/7] Shortcuts created:"
    Info $lnkPath
    Info $startMenuLnkPath

    # Windows may hide this shell verb on some versions or managed machines.
    try {
        if (Pin-ShortcutToTaskbar $lnkPath) {
            Write-Host "[6/7] Pinned to the taskbar."
        } else {
            Write-Warning "Windows did not expose 'Pin to taskbar'. Open the shortcut, then right-click its running taskbar icon and choose 'Pin to taskbar'."
        }
    } catch {
        Write-Warning "Could not pin to the taskbar automatically. Open the shortcut, then right-click its running taskbar icon and choose 'Pin to taskbar'."
    }
} else {
    Write-Host "[5/7] Shortcuts and taskbar pin skipped (-NoShortcut)."
}

# 6. Windows Startup shortcut -----------------------------------------------
if (-not $NoStartup -and -not $NoShortcut) {
    $startupDir = [Environment]::GetFolderPath("Startup")
    $startupLnkPath = Join-Path $startupDir "vna-assistance.lnk"
    Copy-Item $lnkPath $startupLnkPath -Force
    Write-Host "[7/7] Startup shortcut created: $startupLnkPath"
} elseif ($NoStartup) {
    $startupLnkPath = Join-Path ([Environment]::GetFolderPath("Startup")) "vna-assistance.lnk"
    if (Test-Path $startupLnkPath) { Remove-Item $startupLnkPath -Force }
    Write-Host "[7/7] Startup shortcut skipped (-NoStartup)."
} else {
    Write-Host "[7/7] Startup shortcut skipped (-NoShortcut)."
}

Write-Host ""
Write-Host "Done. Quick start:"
Write-Host "  python `"$Root\vna-assistance-cli.py`" note `"remember to email the team tomorrow 9am`""
Write-Host "  Double-click the Desktop shortcut (or run: mshta `"$Root\web\vna-assistance.hta`")"
Write-Host ""
