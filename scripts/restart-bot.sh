#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"

# Stop existing bot processes with precise patterns to avoid broad self-kill.
pkill -f "virtualenvs/cli-tg-.*bin/(cli-tg-bot|claude-telegram-bot)" >/dev/null 2>&1 || true
pkill -f "python -m src.main" >/dev/null 2>&1 || true

# Start in foreground; run inside tmux/screen if you want it detached
if poetry run which cli-tg-bot >/dev/null 2>&1; then
  exec poetry run cli-tg-bot
fi

exec poetry run claude-telegram-bot
