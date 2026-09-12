#!/usr/bin/env bash
# run_pilot30_no1351.sh — like run_pilot30 but excludes issue-1351.
set -u
cd "$(dirname "$0")/.."

LOG_DIR=logs/pilot30
mkdir -p "$LOG_DIR"

COMBOS=(mini-swe-agent_40 mini-swe-agent_60 mini-swe-agent_80 openhands_40 openhands_60 openhands_80)

for combo in "${COMBOS[@]}"; do
  echo "=== $(date +%H:%M:%S) START $combo ===" | tee -a "$LOG_DIR/summary_no1351.log"
  python3 -u utils/verify/solve.py rollout \
    --index "data/verify/issue_index_pilot30_${combo}_no1351.jsonl" \
    --skill-mode all \
    --max-rows 4 \
    2>&1 | tee "$LOG_DIR/${combo}_no1351.log"
  ec=$?
  echo "=== $(date +%H:%M:%S) DONE $combo exit=$ec ===" | tee -a "$LOG_DIR/summary_no1351.log"
done

echo "=== ALL DONE $(date +%H:%M:%S) ===" | tee -a "$LOG_DIR/summary_no1351.log"
