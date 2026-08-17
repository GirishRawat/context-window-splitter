# The instnamer arm: does naming SSA values fix the syntax failures?

**Updated after the full-corpus replication (114 functions, ~110/arm
completed) — see §"Full-corpus replication" below for the definitive numbers.
The subset-only result below (§"Result", n≈35/arm) is kept for the record but
superseded where the two disagree.**

**Short answer: yes, directionally and marginally significantly (p=0.057,
replicated independently across two corpora) — but the WITHIN-syntax_fail
failure-mode shift does not replicate cleanly, so "removing the counter
relocates rather than eliminates the deficit" (the subset-only conclusion
below) is not the full story. And for the first time in the project, this arm
produced two verified non-zero reductions from a LOCAL model — but on
instnamer-modified input, not raw `-O0`, which matters for how the claim is
stated.**

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

### First verified non-zero reductions from a LOCAL model — with a scope caveat

The full-corpus instnamed arm produced **two** `passed` candidates with
non-zero `reduction_pct` — the first ever from a local model in this
project's history (every prior local-model result, across 3b/7b/32b and both
corpora, was 0 wins):

| file | function | reduction | orig → final instrs |
|---|---|---|---|
| `cholesky.bc` | `init_array` | 5.06% | 257 → 244 |
| `fannkuch.bc` | `fannkuch` | 0.34% | 294 → 293 |

Both are formally proven by Alive2 (that proof is the actual correctness
guarantee — no manual verification needed), both have `finish_reason=stop`
(not truncation), and manually diffing `init_array`'s candidate against its
original confirms genuine block/loop restructuring around the
diagonal-initialization pattern in a 2000×2000 array pair, not a metrics
artifact.

**Scope caveat — state this precisely, do not overclaim**: both wins occurred
on the **instnamer-modified corpus**, not raw `-O0` input. Per README §2 this
arm is an explicit comparison, not the main pipeline. The correct claim is
"first verified non-zero reduction from a local model **on named-SSA
input**" — not "on `-O0` IR" unqualified. Whether this generalizes to raw
`-O0` input is untested; the subset baseline-vs-instnamed comparison (§ above)
had 0 wins in both arms, so this may be corpus-composition-dependent (small,
simple functions in `functionobjects.bc`) rather than a naming effect per se.
That distinction is itself worth a follow-up run if time allows.

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

1. **Does the win rate generalize to raw `-O0` input?** Both wins so far are
   on instnamer-modified input. Running the *subset* baseline arm's non-zero
   winners (there are none) vs re-checking whether any *full-corpus baseline*
   (non-instnamed) `passed` rows were misclassified as 0.00% would settle
   this cheaply — just re-check `qwen3b_full_corpus_results.csv` for any
   near-zero-but-nonzero reduction that got rounded away (none were found this
   session, but worth a second look with `--verbose` on
   `analyze_final_results.py`).
2. Reconcile *why* the bucket-composition shift didn't replicate — is it
   genuinely noisy at n≈25-40 failures per arm, or is `functionobjects.bc`'s
   C++-template-heavy composition doing something specific to
   `SSA_TYPE_MISMATCH`? Would need per-file (not just per-corpus) breakdown.
3. 7b and 32b full-corpus instnamed arms, for the same reason the 3b arm was
   run — neither has been tried.
