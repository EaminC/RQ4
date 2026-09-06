#!/usr/bin/env bash
# run_openhands.sh — start OpenHands Agent Canvas with our env loaded.
# Usage: bash agent/run_openhands.sh [agent-canvas options...]
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
set -a
source "/Users/eamin/Desktop/RQ4/agent/openhands-config/.env"
set +a
exec agent-canvas "$@"
