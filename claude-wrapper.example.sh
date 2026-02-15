#!/bin/bash
# Claude CLI wrapper template for subprocess mode.
# 1) Copy to local file:
#    cp claude-wrapper.example.sh claude-wrapper.sh
# 2) Adjust paths/proxy for your machine.
# 3) Make executable:
#    chmod +x claude-wrapper.sh

# Optional proxy example (uncomment if needed):
# export http_proxy="http://127.0.0.1:7897"
# export https_proxy="http://127.0.0.1:7897"
# export HTTP_PROXY="$http_proxy"
# export HTTPS_PROXY="$https_proxy"
# export no_proxy="localhost,127.0.0.1"
# export NO_PROXY="$no_proxy"

# Example using Claude Code via npx:
exec /opt/homebrew/bin/npx -y @anthropic-ai/claude-code@latest "$@"
