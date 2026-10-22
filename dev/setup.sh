#!/bin/sh
# Developer setup on macOS / Linux: installs uv (if needed), Python and the dependencies into .venv.
set -e
cd "$(dirname "$0")/.."
if ! command -v uv >/dev/null 2>&1; then
    echo "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    PATH="$HOME/.local/bin:$PATH"
fi
uv sync --frozen || uv sync
echo
echo "Setup complete. Run dev/run-debug.sh, or build the app with: uv run python tools/build.py"
