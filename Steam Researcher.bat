@echo off
title Steam Researcher
rem Double-click to start the Steam Researcher web UI in your browser.
cd /d "%~dp0"

rem uv's default install folder, in case it isn't on PATH yet
set "PATH=%USERPROFILE%\.local\bin;%PATH%"

where uv >nul 2>nul
if errorlevel 1 (
    echo uv is not installed. Install it once with this command, then run this file again:
    echo.
    echo   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    echo.
    pause
    exit /b 1
)

echo Starting Steam Researcher... your browser will open in a few seconds.
echo To stop it, close this window.
echo.
uv run sr ui %*
if errorlevel 1 pause
