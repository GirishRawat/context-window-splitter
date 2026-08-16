# Morning briefing — 2026-08-17

## One command to see everything

```bash
cd ~/context-window-splitter
export PATH="$HOME/llvm_toolchain/llvm-project/llvm/build/bin:$PATH"

tail -20 overnight_chain.log                     # what ran, in order
python3 -m scripts.analyze_final_results         # all headline numbers
python3 -m scripts.make_result_figs --out-dir figures   # refresh figures
```

## What was queued overnight, in order

The GPU runs one job at a time (Ollama serializes generation across the whole
device), so these are **chained, not parallel** — the running 32b job already
showed a 712s max latency against its 900s timeout, and a concurrent job could
have pushed it into the timeout-`pending` pollution that job exists to avoid.

| # | job | output CSV | est. |
|---|---|---|---|
| 1 | 32b full corpus (was already running) | `qwen32b_full_corpus_results.csv` | ~7h, 114 fns |
| 2 | 3b full corpus, **baseline** | `qwen3b_full_corpus_results.csv` | ~2-3h |
| 3 | 3b full corpus, **instnamed** | `qwen3b_full_corpus_instnamed_results.csv` | ~2-3h |

Every job **resumes from its CSV**, so a partial run is not wasted — just
re-run the same command to continue it.

## What each job is for

**Job 1 — the statistical backbone.** "A 32B model doesn't break the 0%
ceiling" currently rests on n=13 completed attempts. This takes it to ~114.
Check: does `WINS` stay 0? If a 32B local model produces even one verified
non-zero reduction, that changes the thesis.

**Jobs 2+3 — resolving the instnamer question.** Last night's instnamer
experiment (`INSTNAMER_EXPERIMENT.md`) found syntax failures dropping
67.6% → 51.4%, but at **p=0.22** — underpowered at ~35 completed per arm.
Detecting a 16-point gap needs ~150/arm. These two runs take each arm to ~100;
pooled with the subset data that is ~135/arm, which is close enough to call it.

To test it when both finish:

```bash
python3 -m scripts.categorize_syntax_failures \
  qwen3b_full_corpus_results.csv qwen3b_full_corpus_instnamed_results.csv
```

## The three things to actually look at

1. **`pending` rate on job 1.** Should be near 0%. It was 0% at 14/114 when I
   left. If it climbed above ~10%, the timeout needs raising again
   (`LLM_TIMEOUT_SECONDS`) and the run is worth redoing — a third-`pending` run
   is not a usable result, which is what the earlier 26/39 subset run taught us.
2. **`WINS` column** in `analyze_final_results`. Still the single most important
   number in the project: across 436 completed attempts before tonight, exactly
   **one** verified non-zero reduction has ever occurred on real code
   (`fpcmp.bc::diff_file`, 60.67%, gemini-3.5-flash).
3. **instnamer verdict.** Does the 67.6% → 51.4% gap survive at n≈100/arm?

## Still blocked on you: the Gemini arm

This is the highest-value remaining experiment and it needs your API key. The
tooling is built and validated — `--max-functions` was tested end-to-end so it
cannot waste quota. Two batches, one per day (free tier caps at 20/day):

```bash
export GEMINI_API_KEY=...        # your key
cd ~/context-window-splitter
LLM_BACKEND=gemini PYTHONUNBUFFERED=1 \
  python3 -m scripts.run_openrouter_subset \
  --build-dir eval_subset_corpus_sanitized \
  --subset target_subset.csv \
  --max-functions 20 \
  --output-csv gemini_subset_results.csv
```

Run it again tomorrow for the second 20 — resume skips the first batch
automatically. Before launching, check `GEMINI_MODEL` (default
`gemini/gemini-3.5-flash`) is what your key can actually reach; the quality of
this arm is the entire point, so don't leave it on a default by accident.

Why it matters: Gemini is the only model that has ever produced a verified real
optimisation, at **1 win in 8 completed attempts**. Local models: 0 wins in
~430. Turning that n=8 into n=40 is what upgrades "one lucky function" into a
measured frontier hit-rate.

## State when I left

- All work committed and pushed through `bf9cd9f`. Working tree clean.
- Test suite: **64 passed, 0 failed** (was 3 failing on clean `main` — they were
  stale mocks, not a pipeline bug; see `bf9cd9f`).
- 32b full corpus at 14/114, 0% pending, 0 wins.
