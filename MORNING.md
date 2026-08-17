# Status — overnight chain complete (2026-08-17, ~08:15 UTC)

All three queued arms finished cleanly. This replaces the earlier
mid-run version of this file. For the full technical record see
`NEXT_SESSION_HANDOFF.md` (last written before the chain finished — the
process/PID details there are now stale, but the bug-fix history is not)
and `INSTNAMER_EXPERIMENT.md` (fully updated with final numbers).

## What ran

| arm | result |
|---|---|
| 32b full corpus (114 fn) | 21.6% syntax_fail (n=111), 0 wins, 6 rejections |
| 3b full corpus baseline | 37.3% syntax_fail (n=110), 0 wins |
| 3b full corpus instnamed | 24.8% syntax_fail (n=109), **2 wins** |

Run `python3 -m scripts.analyze_final_results` for the always-current
aggregate, and `python3 -m scripts.make_result_figs --out-dir figures` to
refresh figures after any new data lands.

## The headline result, corrected and verified

**Verified non-zero reductions from local models have so far only occurred
on instnamer-modified input, never on raw `-O0`.** Full count across every
result CSV in the project: **0 wins on either baseline arm** (subset and
full corpus), **2 wins on each instnamed arm** — 4 total, all Alive2-proven,
none truncated. (One of those, `fannkuch.bc::fannkuch`, appears identically
in both instnamed runs — same corpus, same function, same 0.34% — which
cross-validates determinism rather than being two independent data points.)

Note this correction happened live: the original write-up claimed the
subset instnamed arm had 0 wins, stated by pattern-matching against every
prior local-model result rather than actually checking. The systematic
aggregator caught it. Worth remembering for any future session: **print the
number, don't infer it from the pattern**, even when the pattern has held
every time before.

The instnamer syntax-failure-rate effect itself replicated independently
across two populations (subset 67.6%→51.4%, full corpus 37.3%→24.8%,
p=0.057 on the full-corpus arm alone) — real, if not conventionally
significant on either arm in isolation. The more specific claim from the
subset run ("removing the counter relocates the deficit onto names") did
**not** replicate on the full corpus — corrected in
`INSTNAMER_EXPERIMENT.md` rather than left standing.

## Still blocked on you: the Gemini arm

Unchanged from before — still the highest-value remaining experiment, still
needs `GEMINI_API_KEY`. Command:

```bash
export GEMINI_API_KEY=...
cd ~/context-window-splitter
LLM_BACKEND=gemini PYTHONUNBUFFERED=1 \
  python3 -m scripts.run_openrouter_subset \
  --build-dir eval_subset_corpus_sanitized \
  --subset target_subset.csv \
  --max-functions 20 \
  --output-csv gemini_subset_results.csv
```

Two batches (20/day free-tier cap), resume picks up the second automatically.

## Repo state

Clean, fully pushed. Last commits: `INSTNAMER_EXPERIMENT.md` correction and
fig3 fix. `scripts/auto_commit_results.sh` (PID may have changed by the time
you read this — check `ps aux | grep auto_commit`) is still running and will
keep checkpointing any new `*_results.csv` changes every 30 min.
