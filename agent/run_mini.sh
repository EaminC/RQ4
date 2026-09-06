#!/usr/bin/env bash
# run_mini.sh — invoke mini-swe-agent with the tu-zi gateway configured.
# Usage: bash agent/run_mini.sh -t "<task>" [-m <model>]
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
set -a
source "/Users/eamin/Desktop/RQ4/agent/config/.env"
set +a
source "/Users/eamin/Desktop/RQ4/agent/.venv/bin/activate"
cd "/Users/eamin/Desktop/RQ4/agent/mini-swe-agent"
exec mini -c "/Users/eamin/Desktop/RQ4/agent/config/mini.yaml" "$@"
