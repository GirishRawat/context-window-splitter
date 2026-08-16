#!/usr/bin/env bash
#
# launch_32b_full_corpus.sh — wait for the GPU to drain, then start the
# full-corpus qwen2.5-coder:32b run.
#
# Why the wait: Ollama serializes generation across the whole GPU, so a third
# concurrent eval process queues behind the others and can burn its client-side
# timeout before generation even starts. That is exactly how the earlier 32b
# subset run ended up 26/39 `pending`. This run is the statistical backbone of
# the negative result, so it gets the GPU to itself.
#
# Usage:  ./scripts/launch_32b_full_corpus.sh [pid_to_wait_for ...]
set -uo pipefail
cd "$(dirname "$0")/.."

OUT_CSV="qwen32b_full_corpus_results.csv"
LOG="qwen32b_full_corpus.log"

echo "[$(date -Is)] waiting for PIDs: $*"
for pid in "$@"; do
  while kill -0 "$pid" 2>/dev/null; do sleep 30; done
  echo "[$(date -Is)] PID $pid finished"
done

# Small settle so the previous process's model unloads and VRAM frees.
sleep 60

export PATH="$HOME/llvm_toolchain/llvm-project/llvm/build/bin:$PATH"
export LLM_BACKEND=local_gpu
export OLLAMA_MODEL=ollama/qwen2.5-coder:32b
export PYTHONUNBUFFERED=1
# Generous budgets: this run is long and unattended, and a `pending` row is a
# wasted measurement. Both are env-overridable per config.py.
export LLM_TIMEOUT_SECONDS=900
export ALIVE_TV_TIMEOUT=120

echo "[$(date -Is)] launching full-corpus 32b run -> ${OUT_CSV}"
nohup python3 -m scripts.run_openrouter_subset \
  --build-dir eval_subset_corpus_sanitized \
  --subset full_corpus_subset.csv \
  --output-csv "${OUT_CSV}" \
  >> "${LOG}" 2>&1 &

echo "[$(date -Is)] started PID $! (log: ${LOG})"
