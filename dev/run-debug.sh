#!/bin/sh
# Runs from source with debug logging and the window open (macOS / Linux).
cd "$(dirname "$0")/.."
exec uv run python -m rotary --show --debug "$@"
