#!/usr/bin/env bash
#
# resume_gemini.sh — launch / safely resume the Gemini eval.
#
# Mirrors resume.sh but targets the Gemini output CSV and requires a Gemini API
# key instead of a local Ollama server. spec_runner.py resumes at FILE
# granularity (skips file_names already in the CSV); this script strips the last
# (possibly partial) file's rows before relaunching so it re-runs completely.
#
# Usage:  export GEMINI_API_KEY=...   then   ./resume_gemini.sh
#
set -euo pipefail

cd "$(dirname "$0")"

CSV="spec_results_gemini.csv"
BUILD_DIR="build"
COMPLEXITY=5
LOG="gemini_run.log"
PYTHON="/opt/anaconda3/bin/python"
[ -x "$PYTHON" ] || PYTHON="python"

# 1. Guard: never touch the CSV while an eval is still running.
if pgrep -f "llmcompile.eval.spec_runner.*${CSV}" > /dev/null; then
  echo "ERROR: a Gemini spec_runner process is already running for ${CSV}."
  echo "       Kill it first if you are sure it is dead:"
  echo "         pkill -f 'llmcompile.eval.spec_runner.*${CSV}'"
  exit 1
fi

# 2. Require the API key (litellm reads GEMINI_API_KEY / GOOGLE_API_KEY).
if [ -z "${GEMINI_API_KEY:-}" ] && [ -z "${GOOGLE_API_KEY:-}" ]; then
  echo "ERROR: neither GEMINI_API_KEY nor GOOGLE_API_KEY is set."
  echo "       export GEMINI_API_KEY=...   and re-run ./resume_gemini.sh"
  exit 1
fi

# 3. Strip the last (possibly partial) file's rows so it re-runs from scratch.
if [ -f "$CSV" ] && [ "$(tail -n +2 "$CSV" | wc -l | tr -d ' ')" -gt 0 ]; then
  LAST=$(tail -n +2 "$CSV" | tail -1 | cut -d, -f1)
  echo "Last file in results was '${LAST}' (may be partial) — removing its rows so it re-runs cleanly."
  awk -F, -v last="$LAST" 'NR==1 || $1 != last' "$CSV" > "${CSV}.tmp" && mv "${CSV}.tmp" "$CSV"
  DONE=$(tail -n +2 "$CSV" | cut -d, -f1 | sort -u | wc -l | tr -d ' ')
  echo "Fully-completed files that will be skipped on resume: ${DONE}"
else
  echo "No existing results found — this will be a fresh run."
fi

# 4. Relaunch detached and pin the Mac awake until it finishes.
echo "Launching Gemini spec_runner..."
nohup "$PYTHON" -m llmcompile.eval.spec_runner \
  --build-dir "$BUILD_DIR" \
  --output-csv "$CSV" \
  --complexity-threshold "$COMPLEXITY" > "$LOG" 2>&1 &
disown
PID=$!
echo "spec_runner PID: ${PID}   (log: ${LOG})"

nohup caffeinate -ims -w "$PID" > /dev/null 2>&1 &
disown
echo "caffeinate tied to PID ${PID} — Mac stays awake (on AC) until the run completes."
echo
echo "Track progress with:"
echo "  tail -n +2 ${CSV} | cut -d, -f1 | sort -u | wc -l    # files done (of 147)"
echo "  tail -f ${LOG}"
