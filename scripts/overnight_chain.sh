#!/usr/bin/env bash
#
# overnight_chain.sh — keep the GPU busy all night without contending.
#
# Ollama serializes generation across the whole GPU, so concurrent eval
# processes queue behind each other. The running 32b full-corpus job already
# shows a 712s max latency against its 900s timeout budget, so adding a
# concurrent job could push it into exactly the timeout-`pending` pollution
# that job was relaunched to avoid. Instead we WAIT for it, then run the 3b
# arms back-to-back.
#
# The two 3b arms resolve the open question from the instnamer experiment:
# on the 40-function subset the syntax_fail drop (67.6% -> 51.4%) had
# p=0.22, i.e. underpowered. Re-running BOTH arms over the full 114-function
# corpus takes each to ~100 completed attempts; pooled with the subset data
# that is ~135/arm, close to the ~150/arm needed to call a 16-point gap.
#
# Everything resumes from its CSV, so a partial run at wake-up is not wasted.
#
# Usage:  ./scripts/overnight_chain.sh <pid_to_wait_for>
set -uo pipefail
cd "$(dirname "$0")/.."

WAIT_PID="${1:-}"
LOG="overnight_chain.log"

log() { echo "[$(date -Is)] $*" | tee -a "$LOG"; }

if [ -n "$WAIT_PID" ]; then
  log "waiting for PID $WAIT_PID (32b full corpus) to finish"
  while kill -0 "$WAIT_PID" 2>/dev/null; do sleep 60; done
  log "PID $WAIT_PID finished"
fi
sleep 60   # let the 32b model unload and free VRAM

export PATH="$HOME/llvm_toolchain/llvm-project/llvm/build/bin:$PATH"
export LLM_BACKEND=local_gpu
export OLLAMA_MODEL=ollama/qwen2.5-coder:3b
export PYTHONUNBUFFERED=1
# Match the arms to each other. 3b is fast; 600s is ample and still well clear
# of its observed latencies.
export LLM_TIMEOUT_SECONDS=600
export ALIVE_TV_TIMEOUT=120

run_arm() {
  local name="$1" build_dir="$2" out_csv="$3"
  log "START ${name} -> ${out_csv}"
  python3 -m scripts.run_openrouter_subset \
    --build-dir "${build_dir}" \
    --subset full_corpus_subset.csv \
    --output-csv "${out_csv}" \
    >> "${name}.log" 2>&1
  log "END ${name} (exit $?) rows=$(($(wc -l < "${out_csv}") - 1))"
}

# Baseline first: it is the comparison everything else is measured against.
run_arm "3b_full_baseline" "eval_subset_corpus_sanitized"  "qwen3b_full_corpus_results.csv"
run_arm "3b_full_instnamed" "eval_subset_corpus_instnamed" "qwen3b_full_corpus_instnamed_results.csv"

log "ALL OVERNIGHT ARMS COMPLETE"
