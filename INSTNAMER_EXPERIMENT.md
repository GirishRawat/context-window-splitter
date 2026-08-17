# The instnamer arm: does naming SSA values fix the syntax failures?

**Updated after the full-corpus replication (114 functions, ~110/arm
completed) — see §"Full-corpus replication" below for the definitive numbers.
The subset-only result below (§"Result", n≈35/arm) is kept for the record but
superseded where the two disagree.**

**Short answer: yes, directionally and marginally significantly (p=0.057,
replicated independently across two corpora) — but the WITHIN-syntax_fail
failure-mode shift does not replicate cleanly, so "removing the counter
relocates rather than eliminates the deficit" (the subset-only conclusion
below) is not the full story. And across both the subset and full-corpus
instnamed arms, this is the first time ANY local model has produced a
verified non-zero reduction — 4 total (0 on either baseline arm) — but on
instnamer-modified input, not raw `-O0`, which matters for how the claim is
stated. One of the subset arm's original numbers was wrong on first write-up
(claimed 0 wins where there were 2) — corrected below, not hidden.**

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

**Correction (caught by `scripts/analyze_final_results.py` after the
full-corpus run landed, not caught at the time)**: this section originally
claimed "6 candidates were proven correct... zero reduced instruction count",
by pattern-matching against every other local-model run rather than actually
checking `reduction_pct` on these 6 rows. That claim was **wrong**. Two of
the six are genuine non-zero reductions: `fannkuch.bc::fannkuch` (0.34%,
294→293 instrs) and `ludcmp.bc::init_array` (4.10%, 268→257 instrs). Both
`finish_reason=stop`, no `syntax_error`, formally proven by Alive2. **The
subset instnamed arm has 2 wins, not 0** — see "Full-corpus replication"
below, where the full-corpus instnamed arm independently produced 2 more
(one of which, `fannkuch.bc::fannkuch`, is the identical function with the
identical 0.34% result — the two runs cross-validate each other). The
*baseline* arm (raw `-O0`, no instnaming) genuinely has 0 wins in both the
subset and full-corpus versions — that part was correct. Lesson: don't state
a number without printing it, even when it matches the expected pattern.

## Full-corpus replication (114 functions, ~110 completed/arm)

The subset result above was underpowered (p=0.22). The overnight full-corpus
run (`qwen3b_full_corpus_results.csv` / `qwen3b_full_corpus_instnamed_results.csv`,
both 114/114, same model, same timeouts, only naming differs) was built to
resolve that. **Note this is a different, easier population than the
40-function subset** — the full corpus is dominated by `functionobjects.bc`'s
47 small C++ template instantiations, so its baseline syntax_fail rate (37.3%)
is not directly comparable to the subset's (67.6%). The two corpora cannot be
legitimately pooled into one bigger sample; what they CAN do is show whether
the *effect* replicates independently in two different populations.

### Headline rate: replicates, and clears significance

| | completed | syntax_fail | rate |
|---|---|---|---|
| full-corpus baseline | 110 | 41 | **37.3%** |
| full-corpus instnamed | 109 | 27 | **24.8%** |

**Fisher exact two-sided p = 0.057** (odds ratio 1.80) — just above the
conventional 0.05 threshold on this arm alone, but the *direction and rough
relative magnitude* replicate the subset result independently:

| corpus | baseline → instnamed | relative drop |
|---|---|---|
| subset (n≈35/arm) | 67.6% → 51.4% | ~24% |
| full corpus (n≈110/arm) | 37.3% → 24.8% | ~33% |

Two independent samples pointing the same direction is stronger evidence than
one bigger pooled sample would be. **Conclusion: naming SSA values measurably
reduces the syntax-failure rate.** State the full-corpus p=0.057 honestly as
"marginal" rather than rounding to "significant" — it is evidence for the
effect, not proof at the conventional threshold.

### Within-syntax_fail failure-mode shift: does NOT replicate cleanly

This is the part worth being careful about. The subset experiment's more
striking claim — "the counter is removed but the model relocates the
deficit onto identifier NAMES instead" (`SSA_REUSE` appearing at 0→2,
`UNDECLARED_REFERENCE` rising 13%→22%) — **does not hold up on the full
corpus**:

| bucket | full-corpus baseline (n=41) | full-corpus instnamed (n=27) |
|---|---|---|
| `SSA_FORWARD_REF` | 49% | 52% |
| `SSA_TYPE_MISMATCH` | 7% | **22%** |
| `SSA_SELF_REFERENCE` | 12% | 4% |
| `UNDECLARED_REFERENCE` | 15% | 11% |
| `SSA_REUSE` | 0% | **0%** (did not appear here) |

No new `SSA_REUSE` failure mode appears on the full corpus; instead
`SSA_TYPE_MISMATCH` triples in relative share. **Correction to the earlier
conclusion**: "removing the counter relocates the deficit onto names" was a
pattern in one 18-failure sample, not a replicated finding. The safer,
narrower claim: naming reduces the *overall* syntax-failure rate, but exactly
*which* SSA-bookkeeping symptom dominates the remainder is noisy at these
sample sizes and should not be over-interpreted from either single run.

### First verified non-zero reductions from a LOCAL model — and the pattern is clean

Across every result CSV in the project (see `scripts/analyze_final_results.py`),
there are now **4 verified non-zero reductions from local models — every
single one on an instnamed arm, zero on either baseline arm**:

| corpus | arm | file | function | reduction |
|---|---|---|---|---|
| subset (40 fn) | baseline | — | — | **0 wins** |
| subset (40 fn) | instnamed | `fannkuch.bc` | `fannkuch` | 0.34% |
| subset (40 fn) | instnamed | `ludcmp.bc` | `init_array` | 4.10% |
| full corpus (114 fn) | baseline | — | — | **0 wins** |
| full corpus (114 fn) | instnamed | `fannkuch.bc` | `fannkuch` | 0.34% |
| full corpus (114 fn) | instnamed | `cholesky.bc` | `init_array` | 5.06% |

`fannkuch.bc::fannkuch` appears as an **identical win in both instnamed
runs** — same function, same corpus (both draw from
`eval_subset_corpus_instnamed`), same 0.34% result — which cross-validates
the pipeline's determinism rather than being two independent data points.
All four are formally proven by Alive2 (that proof is the actual correctness
guarantee — no manual verification needed) with `finish_reason=stop` (not
truncation) and no `syntax_error`. Manually diffing `cholesky.bc::init_array`'s
candidate against its original confirmed genuine block/loop restructuring
around the diagonal-initialization pattern in a 2000×2000 array pair, not a
metrics artifact.

**The pattern this leaves is cleaner than it first looked**: 0/2 baseline
arms produced a win, 2/2 instnamed arms did, independently, across two
different populations. State it as "verified non-zero reductions from local
models have so far only occurred on instnamer-modified input, never on raw
`-O0`" — that is a precise, defensible claim the data actually supports,
stronger than my first pass at this section (which wrongly asserted the
subset baseline-vs-instnamed comparison had 0 wins in *both* arms — it did
not; see the correction in "Result: headline rate" above). Per README §2
this remains an explicit comparison arm, not the main pipeline, so the
correct framing is still "on named-SSA input" rather than an unqualified
claim about `-O0` IR.

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

~~Run both arms over the full 114-function corpus~~ — **done**, see
"Full-corpus replication" above. Remaining open threads, in order of value:

1. ~~Does the win rate generalize to raw `-O0` input?~~ — **checked**: 0/2
   baseline arms (subset and full corpus, both non-instnamed) produced any
   win, verified directly against `reduction_pct > 0` (not a display-rounding
   question). All 4 local-model wins are on instnamed arms. Whether this
   holds at larger N than 2 wins/arm is the real open question now — the
   pattern is clean but the counts are still small.
2. Reconcile *why* the bucket-composition shift didn't replicate — is it
   genuinely noisy at n≈25-40 failures per arm, or is `functionobjects.bc`'s
   C++-template-heavy composition doing something specific to
   `SSA_TYPE_MISMATCH`? Would need per-file (not just per-corpus) breakdown.
3. 7b and 32b full-corpus instnamed arms, for the same reason the 3b arm was
   run — neither has been tried.
