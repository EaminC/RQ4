#!/usr/bin/env bash
# ============================================================================
# setup-openhands.sh — bootstrap the second RQ4 component: OpenHands
# Agent Canvas, routed through the tu-zi OpenAI-compatible API gateway.
#
# Run from the RQ4 repo root:
#     bash scripts/setup-openhands.sh
#
# What this does, in order:
#   1. Sanity-check tooling (node ≥ 22.12, npm).
#   2. Install @openhands/agent-canvas globally via npm (skip if already at
#      the pinned version).
#   3. Write ./agent/openhands-config/.env with tu-zi gateway credentials
#      and an auto-generated API key / secret key for the OpenHands
#      server. These are used by run_openhands.sh and protect the local
#      Canvas UI.
#   4. Drop a tiny smoke test that boots the canvas stack, waits for the
#      ingress /alive endpoint to return 200, then tears it down.
#   5. Run the smoke test.
#
# Note: OpenHands stores LLM settings in an encrypted server-side store
# (keyed by OH_SECRET_KEY). They CANNOT be pre-configured from the CLI.
# After this script finishes, the user must open http://localhost:8000
# once and pick the tu-zi gateway in Settings > LLM. See
# agent/openhands-config/README.md for the exact steps.
#
# Idempotent: re-running will reuse the existing global install and
# regenerate config in place.
# ============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

CONFIG_DIR="$REPO_ROOT/agent/openhands-config"
ENV_FILE="$CONFIG_DIR/.env"
ENV_EXAMPLE="$CONFIG_DIR/.env.example"
README_FILE="$CONFIG_DIR/README.md"
RUNNER="$REPO_ROOT/agent/run_openhands.sh"
SMOKE="$CONFIG_DIR/smoke_test.sh"

OH_PACKAGE="@openhands/agent-canvas"
OH_PIN_VERSION="${OH_PIN_VERSION:-1.16.0}"

# ---------------------------------------------------------------------------
# tu-zi gateway configuration (shared with component 1)
# ---------------------------------------------------------------------------
TUZI_API_KEY="${TUZI_API_KEY:-sk-52RaA81V3pImnAGLRby5kMbDWVVDcXkZkmBPXlj4D7pUxLvv}"
TUZI_BASE_URL="${TUZI_BASE_URL:-https://api.tu-zi.com/v1}"
DEFAULT_MODEL="${DEFAULT_MODEL:-openai/gpt-4o-mini}"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
log()  { printf '\033[1;34m[setup-oh]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[setup-oh][warn]\033[0m %s\n' "$*" >&2; }
err()  { printf '\033[1;31m[setup-oh][error]\033[0m %s\n' "$*" >&2; }
die()  { err "$*"; exit 1; }

# ---------------------------------------------------------------------------
# 1. Tooling checks
# ---------------------------------------------------------------------------
need_cmd() {
    command -v "$1" >/dev/null 2>&1 || die "Missing required command: $1 — install it and re-run."
}

need_cmd node
need_cmd npm

NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]')"
NODE_MINOR="$(node -p 'process.versions.node.split(".")[1]')"
if (( NODE_MAJOR < 22 || (NODE_MAJOR == 22 && NODE_MINOR < 12) )); then
    die "Node ≥ 22.12 required (found $NODE_MAJOR.$NODE_MINOR). Install via nvm or Homebrew."
fi

log "Tooling OK (node $NODE_MAJOR.$NODE_MINOR, npm $(npm --version))"

# ---------------------------------------------------------------------------
# 2. Install @openhands/agent-canvas (pinned version, skip if up to date)
# ---------------------------------------------------------------------------
INSTALLED_VERSION="$(npm ls -g --depth=0 "$OH_PACKAGE" 2>/dev/null \
    | awk -v pkg="$OH_PACKAGE" '$2==pkg {print $3}' \
    | tr -d '`' | sed 's/@$//' || true)"

if [[ "$INSTALLED_VERSION" == "$OH_PIN_VERSION" ]]; then
    log "$OH_PACKAGE@$OH_PIN_VERSION already installed (skipping)"
else
    log "Installing $OH_PACKAGE@$OH_PIN_VERSION globally"
    if [[ -n "$INSTALLED_VERSION" ]]; then
        warn "Replacing previously installed version: $INSTALLED_VERSION"
    fi
    npm install -g "${OH_PACKAGE}@${OH_PIN_VERSION}" >/dev/null
fi

# ---------------------------------------------------------------------------
# 3. Write .env — tu-zi credentials + auto-generated API / secret keys
# ---------------------------------------------------------------------------
mkdir -p "$CONFIG_DIR"

# Generate keys if .env is missing; otherwise reuse what's there so the
# server doesn't reject previously issued auth tokens.
if [[ ! -f "$ENV_FILE" ]]; then
    API_KEY="$(openssl rand -hex 24 2>/dev/null || python3 -c 'import secrets; print(secrets.token_hex(24))')"
    SECRET_KEY="$(openssl rand -hex 32 2>/dev/null || python3 -c 'import secrets; print(secrets.token_hex(32))')"
    GENERATED_KEYS=1
    log "Generated fresh API_KEY and OH_SECRET_KEY"
else
    API_KEY=""
    SECRET_KEY=""
    GENERATED_KEYS=0
    log "Reusing existing $ENV_FILE"
fi

cat > "$ENV_FILE" <<EOF
# Generated by RQ4 scripts/setup-openhands.sh — configures OpenHands Canvas
# to authenticate with the local stack and points its LLM store at the
# tu-zi gateway credentials below.
#
# These first two lines are consumed by run_openhands.sh — DO NOT delete them.
LOCAL_BACKEND_API_KEY=${API_KEY:-REPLACE_ME_FROM_RUN_LOG}
OH_SECRET_KEY=${SECRET_KEY:-REPLACE_ME_FROM_RUN_LOG}

# tu-zi gateway credentials (OpenAI-compatible).
# Note: OpenHands stores LLM settings server-side (encrypted with OH_SECRET_KEY).
# These env vars are documentation only — use them when filling in Settings > LLM
# in the web UI on first launch.
TUZI_API_KEY=$TUZI_API_KEY
TUZI_BASE_URL=$TUZI_BASE_URL

# Default model (used in Settings > LLM > Custom Model field).
DEFAULT_MODEL=$DEFAULT_MODEL
EOF
chmod 600 "$ENV_FILE"
log "Wrote $ENV_FILE (mode 600, generated=$GENERATED_KEYS)"

cat > "$ENV_EXAMPLE" <<'EOF'
# OpenHands Canvas config — copy to .env and re-run setup-openhands.sh.
# The first two keys are auto-generated on first run; leave placeholders here.
LOCAL_BACKEND_API_KEY=
OH_SECRET_KEY=

# tu-zi gateway (OpenAI-compatible).
TUZI_API_KEY=sk-replace-me
TUZI_BASE_URL=https://api.tu-zi.com/v1

# Default model string (provider prefix required, e.g. openai/gpt-4o-mini).
DEFAULT_MODEL=openai/gpt-4o-mini
EOF
log "Wrote $ENV_EXAMPLE"

# ---------------------------------------------------------------------------
# 4. README — how to point OpenHands at the tu-zi gateway via the web UI
# ---------------------------------------------------------------------------
cat > "$README_FILE" <<EOF
# Component 2 — OpenHands Agent Canvas

Upstream: <https://github.com/OpenHands/OpenHands>
Installed via: \`npm install -g $OH_PACKAGE\`
API gateway: <https://api.tu-zi.com> (OpenAI-compatible, configured via the web UI)

## Boundary

| Layer | Owner | Tracked? |
| --- | --- | --- |
| \`$OH_PACKAGE\` (global npm install) | npm registry | **No** (system-level) |
| \`config/\` (our tracked config) | **RQ4** | Yes |

## First-time LLM setup

OpenHands stores LLM settings in an encrypted server-side store. They
cannot be set via environment variables. After \`bash agent/run_openhands.sh\`:

1. Open <http://localhost:8000> in a browser.
2. Go to **Settings → LLM**.
3. Toggle **Advanced**.
4. Fill in:
   - **Custom Model**: \`$DEFAULT_MODEL\`
   - **Base URL**: \`$TUZI_BASE_URL\`
   - **API Key**: \`$TUZI_API_KEY\`
5. Click **Save Changes**.

Subsequent conversations use the saved profile until you delete it.

## Files

- \`run_openhands.sh\` (parent dir) — wrapper that sources this \`.env\`,
  then \`exec\`s \`agent-canvas\`.
- \`.env\` — auto-generated API key (\`LOCAL_BACKEND_API_KEY\`) and secret
  key (\`OH_SECRET_KEY\`). Gitignored, \`chmod 600\`.
- \`.env.example\` — template.
- \`smoke_test.sh\` — boots the stack, hits \`/alive\`, tears it down.
EOF
log "Wrote $README_FILE"

# ---------------------------------------------------------------------------
# 5. Wrapper script — single command to start the canvas
# ---------------------------------------------------------------------------
cat > "$RUNNER" <<EOF
#!/usr/bin/env bash
# run_openhands.sh — start OpenHands Agent Canvas with our env loaded.
# Usage: bash agent/run_openhands.sh [agent-canvas options...]
set -euo pipefail
REPO_ROOT="\$(cd "\$(dirname "\${BASH_SOURCE[0]}")/.." && pwd)"
set -a
source "$ENV_FILE"
set +a
exec agent-canvas "\$@"
EOF
chmod +x "$RUNNER"
log "Wrote $RUNNER"

# ---------------------------------------------------------------------------
# 6. Smoke test — boot, hit /alive, tear down
# ---------------------------------------------------------------------------
cat > "$SMOKE" <<'BASH'
#!/usr/bin/env bash
# Smoke test: boot OpenHands Agent Canvas, wait for the ingress /alive
# endpoint to return 200, then tear it down.
#
# We deliberately do NOT exercise the LLM here — that requires the user
# to first save LLM settings via the web UI (see ../README.md).
set -euo pipefail

INGRESS_PORT="${INGRESS_PORT:-8000}"
LOG_FILE="${LOG_FILE:-/tmp/openhands-smoke.log}"
PID_FILE="${PID_FILE:-/tmp/openhands-smoke.pid}"

echo "[smoke] starting agent-canvas (logs: $LOG_FILE)"
agent-canvas >"$LOG_FILE" 2>&1 &
PID=$!
echo "$PID" >"$PID_FILE"

cleanup() {
    if kill -0 "$PID" 2>/dev/null; then
        echo "[smoke] killing agent-canvas (pid $PID)"
        kill "$PID" 2>/dev/null || true
        # give it a few seconds, then SIGKILL
        for _ in 1 2 3 4 5; do
            kill -0 "$PID" 2>/dev/null || break
            sleep 1
        done
        if kill -0 "$PID" 2>/dev/null; then
            kill -9 "$PID" 2>/dev/null || true
        fi
    fi
    rm -f "$PID_FILE"
}
trap cleanup EXIT

echo "[smoke] waiting for http://localhost:$INGRESS_PORT/alive (max 90s)"
for i in $(seq 1 45); do
    if curl -fsS -o /dev/null --max-time 2 "http://localhost:$INGRESS_PORT/alive"; then
        echo "[smoke] OK: /alive returned 200 (after ${i}*2s)"
        echo "SMOKE_OK"
        exit 0
    fi
    if ! kill -0 "$PID" 2>/dev/null; then
        echo "[smoke] FAIL: agent-canvas exited unexpectedly. Tail of log:" >&2
        tail -n 50 "$LOG_FILE" >&2 || true
        exit 1
    fi
    sleep 2
done

echo "[smoke] FAIL: /alive did not return 200 within 90s. Tail of log:" >&2
tail -n 80 "$LOG_FILE" >&2 || true
exit 1
BASH
chmod +x "$SMOKE"
log "Wrote $SMOKE"

# ---------------------------------------------------------------------------
# 7. Run smoke test
# ---------------------------------------------------------------------------
log "Running smoke test (boots agent-canvas, hits /alive)"
set +e
SMOKE_OUTPUT="$(bash "$SMOKE" 2>&1)"
SMOKE_RC=$?
set -e

echo "$SMOKE_OUTPUT"
if (( SMOKE_RC != 0 )) || ! grep -q '^SMOKE_OK$' <<<"$SMOKE_OUTPUT"; then
    die "Smoke test failed — see output above."
fi

log "✅ Setup complete."
log ""
log "Next steps:"
log "  1. bash agent/run_openhands.sh           # starts the canvas at http://localhost:8000"
log "  2. open http://localhost:8000 in a browser"
log "  3. Settings → LLM → Advanced → fill Custom Model / Base URL / API Key (see $README_FILE)"
log ""
log "Files of interest:"
log "  • env loader   $ENV_FILE  (source it for custom runs)"
log "  • config docs  $README_FILE"
log "  • wrapper      $RUNNER"
log "  • smoke test   $SMOKE"
log "  • upstream     $OH_PACKAGE@$OH_PIN_VERSION  (global npm install)"