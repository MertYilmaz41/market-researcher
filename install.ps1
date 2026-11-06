# Steam Researcher installer for Windows. Run it with:
#   powershell -ExecutionPolicy ByPass -c "irm https://raw.githubusercontent.com/MertYilmaz41/steam-researcher/main/install.ps1 | iex"
# It installs uv if it's missing, installs the app as a uv tool (uv fetches Python 3.13 itself)
# and puts a "Steam Researcher" shortcut on the desktop. Run it again to update.
# Settings (environment variables): SR_SOURCE = what to install (default: the main branch on GitHub),
# SR_NO_SHORTCUT = 1 to skip the shortcut.

$ErrorActionPreference = "Stop"

$source = $env:SR_SOURCE
if (-not $source) { $source = "https://github.com/MertYilmaz41/steam-researcher/archive/refs/heads/main.zip" }

# 1. uv
$env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "Installing uv..."
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}

# 2. The app
Write-Host "Installing Steam Researcher..."
uv tool install --force --refresh --python 3.13 $source
if ($LASTEXITCODE -ne 0) { throw "uv tool install failed." }
# Put the tool folder on PATH for new terminals (unless you chose your own with UV_TOOL_BIN_DIR)
if (-not $env:UV_TOOL_BIN_DIR) { uv tool update-shell 2>$null | Out-Null }

$bin = (uv tool dir --bin).Trim()
$exe = Join-Path $bin "steam-researcher.exe"
if (-not (Test-Path $exe)) { throw "Installed, but $exe is missing." }

# 3. Desktop shortcut
if ($env:SR_NO_SHORTCUT -ne "1") {
    $desktop = [Environment]::GetFolderPath("Desktop")
    $shell = New-Object -ComObject WScript.Shell
    $link = $shell.CreateShortcut((Join-Path $desktop "Steam Researcher.lnk"))
    $link.TargetPath = $exe
    $link.WorkingDirectory = $env:USERPROFILE
    $link.Description = "Find underserved Steam audiences (opens in your browser; close the window to stop)"
    $link.Save()
    Write-Host "Added a 'Steam Researcher' shortcut to your desktop."
}

Write-Host ""
if ($env:SR_NO_SHORTCUT -ne "1") { Write-Host "Done. Start it with the desktop shortcut, or type: steam-researcher" }
else { Write-Host "Done. Start it by typing: steam-researcher" }
Write-Host "(The command works in new terminal windows. For the AI summaries, also install Ollama: winget install Ollama.Ollama)"
