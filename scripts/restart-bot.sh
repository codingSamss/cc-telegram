#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"

pkill -f "cli-tg" >/dev/null 2>&1 || true

# Start in foreground; run inside tmux/screen if you want it detached
exec poetry run claude-telegram-bot
