#!/bin/sh
# Steam Researcher installer for macOS and Linux. Run it with:
#   curl -LsSf https://raw.githubusercontent.com/MertYilmaz41/steam-researcher/main/install.sh | sh
# It installs uv if it's missing and installs the app as a uv tool (uv fetches Python 3.13 itself).
# Run it again to update. SR_SOURCE = what to install (default: the main branch on GitHub).
set -eu

source="${SR_SOURCE:-https://github.com/MertYilmaz41/steam-researcher/archive/refs/heads/main.zip}"

# 1. uv
PATH="$HOME/.local/bin:$PATH"
if ! command -v uv >/dev/null 2>&1; then
    echo "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    PATH="$HOME/.local/bin:$PATH"
fi

# 2. The app
echo "Installing Steam Researcher..."
uv tool install --force --refresh --python 3.13 "$source"
# Put the tool folder on PATH for new terminals (unless you chose your own with UV_TOOL_BIN_DIR)
[ -n "${UV_TOOL_BIN_DIR:-}" ] || uv tool update-shell >/dev/null 2>&1 || true

bin="$(uv tool dir --bin)"
[ -x "$bin/steam-researcher" ] || { echo "Installed, but $bin/steam-researcher is missing." >&2; exit 1; }

echo
echo "Done. Start it with: steam-researcher"
echo "(It opens in your browser. Open a new terminal first if the command isn't found."
echo " For the AI summaries, also install Ollama: https://ollama.com)"
