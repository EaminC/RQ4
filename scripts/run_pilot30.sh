#!/usr/bin/env bash
# run_pilot30.sh — orchestrate 6 combos × 5 issues × 2 skill modes = 60 rollouts.
set -u
cd "$(dirname "$0")/.."

LOG_DIR=logs/pilot30
mkdir -p "$LOG_DIR"

COMBOS=(mini-swe-agent_40 mini-swe-agent_60 mini-swe-agent_80 openhands_40 openhands_60 openhands_80)

for combo in "${COMBOS[@]}"; do
  echo "=== $(date +%H:%M:%S) START $combo ===" | tee -a "$LOG_DIR/summary.log"
  python3 -u utils/verify/solve.py rollout \
    --index "data/verify/issue_index_pilot30_${combo}.jsonl" \
    --skill-mode all \
    --max-rows 5 \
    2>&1 | tee "$LOG_DIR/${combo}.log"
  ec=$?
  echo "=== $(date +%H:%M:%S) DONE $combo exit=$ec ===" | tee -a "$LOG_DIR/summary.log"
done

echo "=== ALL DONE $(date +%H:%M:%S) ===" | tee -a "$LOG_DIR/summary.log"
