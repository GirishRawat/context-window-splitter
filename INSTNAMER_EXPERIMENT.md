# The instnamer arm: does naming SSA values fix the syntax failures?

**Short answer: partially, and not significantly. The deficit is identifier
tracking in general, not the numeric counter specifically.**

## Why this experiment exists

Categorizing the first real syntax-failure sample showed that ~91% of
`qwen2.5-coder:3b`'s syntax failures were SSA value-numbering incoherence,
dominated by `SSA_FORWARD_REF` (52%) — the model using its own not-yet-defined
number as an operand, e.g.

    %190 = getelementptr inbounds [2500 x i32], ptr %186, i64 %190

The natural hypothesis: the model cannot maintain LLVM's *implicit unnamed-value
counter* (`%1, %2, …`) across a long body. If so, removing the counter should
remove the failures. `opt -passes=instnamer` does exactly that — it gives every
anonymous instruction and block an explicit name (`%i`, `%i1`, `bb`), so there is
no counter left to lose track of.

## Design

Identical pipeline, identical model (`qwen2.5-coder:3b`), identical 40-function
subset, **identical timeouts** (`LLM_TIMEOUT_SECONDS=300`, `ALIVE_TV_TIMEOUT=30`
— pinned to the baseline's values rather than the raised defaults, so naming is
the only variable that changed). Corpus built by
`scripts/prep_instnamer_corpus.py`, which verifies the transform is
**instruction-count-neutral**: all 24 parseable files have byte-identical
per-function instruction counts, so the arm is uncounfounded.

## Result: headline rate

| | completed | syntax_fail | rate | passed | unsupported | pending |
|---|---|---|---|---|---|---|
| baseline (raw `-O0`) | 34 | 23 | **67.6%** | 7 | 4 | 5 |
| instnamed | 35 | 18 | **51.4%** | 6 | 11 | 4 |

Directionally better — 16 points — but **Fisher exact two-sided p = 0.22**
(odds ratio 1.97). At this sample size that is **indistinguishable from noise**.
Detecting a gap this size near p≈0.6 needs roughly **150 completed attempts per
arm**; we have ~35. Do not report this as "instnamer reduces syntax failures"
without the larger sample.

## Result: where the failures went (the interesting part)

| bucket | baseline | instnamed |
|---|---|---|
| `SSA_FORWARD_REF` | 12 (52%) | 7 (39%) |
| `SSA_TYPE_MISMATCH` | 5 (22%) | 3 (17%) |
| `SSA_SELF_REFERENCE` | 1 (4%) | 1 (6%) |
| **`SSA_REUSE`** (name collision) | **0 (0%)** | **2 (11%)** |
| `UNDECLARED_REFERENCE` | 3 (13%) | 4 (22%) |
| `INVALID_LABEL_REF` | 1 (4%) | 0 |
| `MALFORMED_SYNTAX` | 1 (4%) | 0 |
| `OTHER` | 0 | 1 (6%) |
| **total** | **23** | **18** |

Two things worth putting in the write-up:

1. **SSA-numbering failures fell from 78% to 61% of all syntax failures** — the
   targeted mechanism did move in the predicted direction.

2. **A failure mode appeared that did not exist in the baseline.** `SSA_REUSE`
   ("multiple definition of") went 0 → 2. With numbers removed, the model
   started *colliding on names* instead of forward-referencing numbers. It did
   not stop losing track of identifiers; it changed **how** it loses track.
   `UNDECLARED_REFERENCE` likewise rose (13% → 22%).

That is the substantive finding: the deficit is **identifier bookkeeping in
general**, not the numeric counter specifically. Removing the counter relocates
the error rather than eliminating it. This rules out the cheap fix and argues
that the real remedies are the structural ones — grammar-constrained decoding
that makes an invalid reference *unrepresentable*, or an IR-native model.

3. **`unsupported` rose 4 → 11.** More candidates now survive the syntax gate and
   reach Alive2 at all — consistent with the mechanism working — but they then
   fail to be proven. Passing the parser is not the same as being provable.

**The optimisation ceiling did not move:** 6 candidates were proven correct, and
as in every other local-model run, **zero reduced instruction count**.

## Reproducing

```bash
python3 -m scripts.prep_instnamer_corpus \
    --src eval_subset_corpus_sanitized --dst eval_subset_corpus_instnamed

LLM_BACKEND=local_gpu OLLAMA_MODEL=ollama/qwen2.5-coder:3b \
LLM_TIMEOUT_SECONDS=300 ALIVE_TV_TIMEOUT=30 PYTHONUNBUFFERED=1 \
  python3 -m scripts.run_openrouter_subset \
  --build-dir eval_subset_corpus_instnamed \
  --subset target_subset.csv \
  --output-csv syntax_diag_3b_instnamed_results.csv

python3 -m scripts.categorize_syntax_failures \
  syntax_diag_3b_results.csv syntax_diag_3b_instnamed_results.csv
```

## Caveat to carry into the write-up

Per README §2, name-annotated input deviates from raw `-O0`, so this is an
**explicit comparison arm** and never a silent swap of the main pipeline — the
same caveat that applies to a `mem2reg`-canonicalised arm. The headline pipeline
still consumes unmodified `-O0` IR.

## Next step if this is worth resolving

Run both arms over the full 114-function corpus (`full_corpus_subset.csv`)
rather than the 40-function subset. That gets each arm to ~100+ completed
attempts, which is close to the ~150 needed to call the 16-point gap either way.
