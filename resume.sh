#!/usr/bin/env bash
#
# resume.sh — safely resume the spec_runner evaluation after a crash/power-off.
#
# spec_runner.py resumes at FILE granularity: on startup it skips every
# file_name already present in the results CSV. The catch is the ONE file that
# was mid-processing when the machine died — it has some (not all) of its
# function rows written, so a plain resume would skip it and silently drop its
# remaining functions. This script removes that last (possibly partial) file's
# rows before relaunching, so it is re-processed cleanly and completely.
#
# Usage:  ./resume.sh
#
set -euo pipefail

cd "$(dirname "$0")"

CSV="new_spec_results.csv"
BUILD_DIR="build"
COMPLEXITY=5
OLLAMA_URL="http://localhost:11434"
# Prefer anaconda's python (has llvmlite); fall back to whatever `python` is.
PYTHON="/opt/anaconda3/bin/python"
[ -x "$PYTHON" ] || PYTHON="python"

# 1. Guard: never touch the CSV while an eval is still running.
if pgrep -f "llmcompile.eval.spec_runner" > /dev/null; then
  echo "ERROR: a spec_runner process is already running."
  echo "       Check it with:  ps aux | grep spec_runner | grep -v grep"
  echo "       If you are certain it is dead, kill it first:"
  echo "         pkill -f llmcompile.eval.spec_runner"
  exit 1
fi

# 2. Make sure Ollama is up (it does not auto-start after a hard shutdown).
if curl -sf "${OLLAMA_URL}/api/tags" > /dev/null 2>&1; then
  echo "Ollama is up."
else
  echo "Ollama not reachable — starting 'ollama serve'..."
  nohup ollama serve > ollama.log 2>&1 &
  disown
  for _ in $(seq 1 30); do
    sleep 1
    curl -sf "${OLLAMA_URL}/api/tags" > /dev/null 2>&1 && break
  done
  if ! curl -sf "${OLLAMA_URL}/api/tags" > /dev/null 2>&1; then
    echo "ERROR: Ollama did not come up within 30s."
    echo "       Start it manually ('ollama serve') and re-run ./resume.sh"
    exit 1
  fi
  echo "Ollama is up."
fi

# 3. Strip the last (possibly partial) file's rows so it re-runs from scratch.
#    Exact first-field match (file_name) — .bc names never contain commas.
if [ -f "$CSV" ] && [ "$(tail -n +2 "$CSV" | wc -l | tr -d ' ')" -gt 0 ]; then
  LAST=$(tail -n +2 "$CSV" | tail -1 | cut -d, -f1)
  echo "Last file in results was '${LAST}' (may be partial) — removing its rows so it re-runs cleanly."
  awk -F, -v last="$LAST" 'NR==1 || $1 != last' "$CSV" > "${CSV}.tmp" && mv "${CSV}.tmp" "$CSV"
  DONE=$(tail -n +2 "$CSV" | cut -d, -f1 | sort -u | wc -l | tr -d ' ')
  echo "Fully-completed files that will be skipped on resume: ${DONE}"
else
  echo "No existing results found — this will be a fresh run."
fi

# 4. Relaunch the evaluation (detached) and pin the Mac awake until it finishes.
echo "Launching spec_runner..."
nohup "$PYTHON" -m llmcompile.eval.spec_runner \
  --build-dir "$BUILD_DIR" \
  --output-csv "$CSV" \
  --complexity-threshold "$COMPLEXITY" > eval_run.log 2>&1 &
disown
PID=$!
echo "spec_runner PID: ${PID}   (log: eval_run.log)"

# -i idle, -m disk, -s system sleep (system-sleep hold requires AC power);
# -w waits for PID then releases the assertion automatically on completion.
nohup caffeinate -ims -w "$PID" > /dev/null 2>&1 &
disown
echo "caffeinate tied to PID ${PID} — Mac stays awake (on AC) until the run completes."
echo
echo "Track progress with:"
echo "  tail -n +2 ${CSV} | cut -d, -f1 | sort -u | wc -l    # files done (of 147)"
echo "  tail -f eval_run.log                                 # live log"
