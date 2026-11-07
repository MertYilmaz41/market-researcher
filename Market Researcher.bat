@echo off
title Market Researcher
rem Double-click to start the Market Researcher web UI in your browser.
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

rem Ollama (local AI) is only needed for the "Write summary" buttons
curl -s -o nul -m 2 http://localhost:11434/api/version 2>nul
if errorlevel 1 (
    echo Note: Ollama isn't running, so the AI summaries are off. Everything else works.
    echo To use them, start the Ollama app ^(install: winget install Ollama.Ollama^).
    echo.
)

echo Starting Market Researcher... your browser will open in a few seconds.
echo To stop it, close this window.
echo.
uv run mr ui %*
if errorlevel 1 pause
