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
