#!/usr/bin/env bash
# setup.sh — bootstrap mini-swe-agent for RQ4 against the tu-zi API gateway.
#
# mini-swe-agent is treated as a READ-ONLY EXTERNAL MODULE:
#   - cloned into ./upstream/ (gitignored, never committed)
#   - installed editable via `uv pip install -e ./upstream`
#   - we never edit files inside ./upstream/
# All RQ4-side configuration lives in this directory (mini.yaml, secrets.env,
# smoke_test.py), one level above upstream/.
#
# What this script does, in order:
#   1. Sanity-check tooling (git, python3, uv, curl).
#   2. Resolve the upstream version: query GitHub for the current main SHA
#      (so we always pin to "latest released" rather than a stale local copy).
#      `--no-update` skips this and reuses the existing upstream/ as-is.
#   3. Sync ./upstream/ to that SHA (init+fetch+checkout on first run;
#      fetch+reset on subsequent runs).
#   4. Load or create ./secrets.env (API key, base URL, default model).
#   5. Create an isolated `uv` venv in ./.venv and pip install -e the agent.
#   6. Drop a mini.yaml that points litellm at the tu-zi OpenAI-compatible
#      endpoint, plus a tiny smoke-test script.
#   7. Run the smoke test (single chat call through mini-swe-agent).
#
# Re-running is safe: existing files are reused, nothing is wiped.
#
# Usage:
#   ./setup.sh           # fetch latest main + install + smoke test
#   ./setup.sh --no-update   # skip GitHub lookup; use existing upstream/

set -euo pipefail

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

UPSTREAM_DIR="$SCRIPT_DIR/upstream"
VENV_DIR="$SCRIPT_DIR/.venv"
SECRETS_FILE="$SCRIPT_DIR/secrets.env"
CONFIG_FILE="$SCRIPT_DIR/mini.yaml"
SMOKE_SCRIPT="$SCRIPT_DIR/smoke_test.py"

UPSTREAM_REPO="https://github.com/SWE-agent/mini-swe-agent.git"

# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------
log()  { printf '\033[1;34m[setup]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[setup]\033[0m %s\n' "$*" >&2; }
err()  { printf '\033[1;31m[setup]\033[0m %s\n' "$*" >&2; }

# ---------------------------------------------------------------------------
# 1. Tooling checks
# ---------------------------------------------------------------------------
need_cmd() {
    if ! command -v "$1" >/dev/null 2>&1; then
        err "Missing required command: $1"
        return 1
    fi
}

need_cmd git
need_cmd python3

if ! command -v uv >/dev/null 2>&1; then
    warn "uv not found — installing via pipx/pip"
    python3 -m pip install --user uv || {
        err "Failed to install uv. Install it manually: https://docs.astral.sh/uv/"
        exit 1
    }
fi

PYTHON_BIN="$VENV_DIR/bin/python"
UV_PIP="$VENV_DIR/bin/pip"

# ---------------------------------------------------------------------------
# 2. Secrets
# ---------------------------------------------------------------------------
if [[ ! -f "$SECRETS_FILE" ]]; then
    log "Creating placeholder $SECRETS_FILE (edit it with your real key, then re-run)."
    cat > "$SECRETS_FILE" <<EOF
# tu-zi API credentials (OpenAI-compatible gateway)
TUZI_API_KEY=sk-52RaA81V3pImnAGLRby5kMbDWVVDcXkZkmBPXlj4D7pUxLvv
TUZI_BASE_URL=https://api.tu-zi.com/v1

# Default model. Format: openai/<model-id> (litellm routes through
# OPENAI_API_BASE / OPENAI_API_KEY set below).
DEFAULT_MODEL=openai/gpt-4o-mini

# Per-run cost limit in USD (mini.yaml reads this).
COST_LIMIT=3.0
EOF
    log "Wrote placeholder secrets. If you need a different key, edit $SECRETS_FILE now."
fi

# shellcheck disable=SC1090
source "$SECRETS_FILE"

: "${TUZI_API_KEY:?TUZI_API_KEY must be set in $SECRETS_FILE}"
: "${TUZI_BASE_URL:?TUZI_BASE_URL must be set in $SECRETS_FILE}"
: "${DEFAULT_MODEL:?DEFAULT_MODEL must be set in $SECRETS_FILE}"
COST_LIMIT="${COST_LIMIT:-3.0}"

log "Using endpoint: $TUZI_BASE_URL"
log "Using model:    $DEFAULT_MODEL"

# ---------------------------------------------------------------------------
# 3. Sync upstream/ to the current main of SWE-agent/mini-swe-agent
#
#   Strategy:
#     a) Query GitHub for the SHA of the upstream default branch (main).
#        No auth required (60 req/h/IP, plenty for setup scripts).
#     b) If ./upstream/ doesn't exist yet, init it, add the official remote,
#        fetch just that SHA, and check it out into a detached HEAD.
#     c) If ./upstream/ already exists with the official remote, fetch the
#        new SHA and `git reset --hard` to it so we always track "latest".
#     d) If --no-update was passed, reuse the existing checkout as-is.
#
#   This means ./upstream/ is always a pristine copy of upstream at a known
#   SHA — no untracked local edits can survive a re-run.
# ---------------------------------------------------------------------------
OFFICIAL_REMOTE="https://github.com/SWE-agent/mini-swe-agent.git"
UPSTREAM_BRANCH="main"

fetch_upstream_sha() {
    # Returns the SHA of the upstream default branch.
    # Uses curl + jq if available, else falls back to a python one-liner.
    local sha
    if command -v jq >/dev/null 2>&1; then
        sha="$(curl -fsSL "https://api.github.com/repos/SWE-agent/mini-swe-agent/branches/$UPSTREAM_BRANCH" \
              | jq -r '.commit.sha')"
    else
        sha="$(curl -fsSL "https://api.github.com/repos/SWE-agent/mini-swe-agent/branches/$UPSTREAM_BRANCH" \
              | python3 -c 'import json,sys; print(json.load(sys.stdin)["commit"]["sha"])')"
    fi
    if [[ -z "$sha" || "$sha" == "null" ]]; then
        err "Failed to resolve upstream SHA from GitHub."
        err "Check network access to api.github.com or re-run with --no-update."
        return 1
    fi
    printf '%s' "$sha"
}

if [[ "${1:-}" == "--no-update" ]]; then
    if [[ ! -d "$UPSTREAM_DIR/.git" ]]; then
        err "--no-update passed but $UPSTREAM_DIR has no git checkout yet."
        exit 1
    fi
    log "Skipping upstream sync (--no-update); using existing $UPSTREAM_DIR"
else
    log "Resolving upstream SHA from GitHub ($UPSTREAM_BRANCH)..."
    TARGET_SHA="$(fetch_upstream_sha)"
    log "Upstream main @ ${TARGET_SHA:0:12}"

    if [[ -d "$UPSTREAM_DIR/.git" ]]; then
        existing_remote="$(git -C "$UPSTREAM_DIR" config --get remote.origin.url 2>/dev/null || echo "")"
        if [[ "$existing_remote" != "$OFFICIAL_REMOTE" ]]; then
            err "upstream/ already exists but its remote is '$existing_remote',"
            err "expected '$OFFICIAL_REMOTE'. Refusing to clobber. Move it aside first."
            exit 1
        fi
        current_sha="$(git -C "$UPSTREAM_DIR" rev-parse HEAD 2>/dev/null || echo "")"
        if [[ "$current_sha" == "$TARGET_SHA" ]]; then
            log "upstream/ already at $TARGET_SHA (skipping fetch)"
        else
            log "Updating upstream/ $current_sha → $TARGET_SHA"
            git -C "$UPSTREAM_DIR" fetch --depth 1 origin "$TARGET_SHA"
            git -C "$UPSTREAM_DIR" reset --hard "$TARGET_SHA"
        fi
    else
        if [[ -d "$UPSTREAM_DIR" ]] && [[ -n "$(ls -A "$UPSTREAM_DIR" 2>/dev/null)" ]]; then
            err "$UPSTREAM_DIR exists and is non-empty but is not a git checkout."
            err "Move it aside before re-running setup.sh."
            exit 1
        fi
        log "Initializing upstream/ and fetching $TARGET_SHA"
        mkdir -p "$UPSTREAM_DIR"
        git -C "$UPSTREAM_DIR" init -q
        git -C "$UPSTREAM_DIR" remote add origin "$OFFICIAL_REMOTE"
        git -C "$UPSTREAM_DIR" fetch --depth 1 origin "$TARGET_SHA"
        git -C "$UPSTREAM_DIR" checkout -q --detach "$TARGET_SHA"
    fi
    # Make git status / future fetches behave nicely.
    git -C "$UPSTREAM_DIR" config advice.detachedHead false
fi

# Record what we synced so smoke_test / debugging can reference it.
log "Upstream HEAD: $(git -C "$UPSTREAM_DIR" rev-parse --short HEAD)"

# ---------------------------------------------------------------------------
# 4. venv + install
# ---------------------------------------------------------------------------
if [[ ! -d "$VENV_DIR" ]]; then
    log "Creating uv venv at $VENV_DIR"
    uv venv --python 3.11 "$VENV_DIR"
else
    log "Reusing venv at $VENV_DIR"
fi

log "Installing mini-swe-agent (editable) into venv"
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
uv pip install -e "$UPSTREAM_DIR"

# ---------------------------------------------------------------------------
# 5. mini.yaml — route litellm at tu-zi
# ---------------------------------------------------------------------------
# mini-swe-agent reads mini.yaml and recursively merges it with builtin defaults.
# We override model.model_kwargs so litellm treats the call as an OpenAI call
# but talks to tu-zi's base URL via env vars.
cat > "$CONFIG_FILE" <<EOF
# Generated by setup.sh — routes mini-swe-agent at the tu-zi gateway.
# Loaded via: mini -c $CONFIG_FILE ...
model:
  model_name: "$DEFAULT_MODEL"
  model_class: litellm
  model_kwargs:
    api_base: "$TUZI_BASE_URL"
    api_key: "$TUZI_API_KEY"
    drop_params: true
agent:
  cost_limit: $COST_LIMIT
  mode: yolo
  confirm_exit: true
EOF
log "Wrote $CONFIG_FILE"

# ---------------------------------------------------------------------------
# 6. Smoke test — single round-trip through mini-swe-agent
# ---------------------------------------------------------------------------
cat > "$SMOKE_SCRIPT" <<'PY'
"""Smoke test: verify mini-swe-agent can drive a tool-calling round trip
through the tu-zi gateway.

Bypasses the full agent loop (which needs a TTY for `interactive` mode)
and instead drives LitellmModel directly — that's the part that actually
talks to the gateway.
"""
import os
import sys

# Belt-and-suspenders: also set OPENAI_API_BASE so any litellm internals
# that bypass model_kwargs still find the right endpoint.
os.environ.setdefault("OPENAI_API_BASE",  os.environ["TUZI_BASE_URL"])
os.environ.setdefault("OPENAI_API_KEY",   os.environ["TUZI_API_KEY"])

from minisweagent.models.litellm_model import LitellmModel

model = LitellmModel(
    model_name=os.environ.get("DEFAULT_MODEL", "openai/gpt-4o-mini"),
    model_kwargs={
        "api_base": os.environ["TUZI_BASE_URL"],
        "api_key":  os.environ["TUZI_API_KEY"],
        "drop_params": True,
    },
)

result = model.query(
    [{"role": "user", "content": "Run `echo PONG` and report the output."}]
)

extra = result.get("extra", {})
actions = extra.get("actions", [])
response = extra.get("response", {})

if not actions:
    print("FAIL: model returned no tool call", file=sys.stderr)
    print(json.dumps(response, indent=2, default=str)[:2000], file=sys.stderr)
    sys.exit(1)

cmd = actions[0].get("command", "")
print(f"OK: model returned bash tool call -> {cmd!r}", file=sys.stderr)
print("SMOKE_OK", file=sys.stderr)
PY

log "Running smoke test (this will hit the tu-zi API once)"
TUZI_BASE_URL="$TUZI_BASE_URL" \
TUZI_API_KEY="$TUZI_API_KEY" \
DEFAULT_MODEL="$DEFAULT_MODEL" \
"$PYTHON_BIN" "$SMOKE_SCRIPT"

log "✅ Setup complete."
log "Next:"
log "  source $VENV_DIR/bin/activate"
log "  mini -c $CONFIG_FILE -m $DEFAULT_MODEL -t \"your task here\""