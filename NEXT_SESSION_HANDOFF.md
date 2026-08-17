# Agent Handoff — 2026-08-17 (dissertation rewrite session)

**To the next agent**: this replaces the prior "Gemini frontier-arm session"
version of this file. That session got the Gemini arm from n=7 to n=63 and
fixed two infrastructure bugs (§2 of the old handoff, still true, summarized
below). This session did not run new evals — it consumed that session's
results, regenerated the figures, fixed a plotting bug that broke the LaTeX
build, and rewrote the dissertation and README to match the current numbers
instead of the stale "zero verified optimizations on real code" framing.

## 0. Standing git rules (unchanged, still true)

1. **No `Co-Authored-By: Claude` / `Claude-Session:` trailer on any commit,
   ever** — confirmed again by reading the last 3 commits' full messages
   before writing this session's commits.
2. **Commit periodically and automatically, without being asked**, per
   `scripts/auto_commit_results.sh` (45min interval, still the convention —
   check `ps aux | grep auto_commit` for whether it's still running).

The 3 commits (`f0bcb66`, `6e37ca5`, `c16285e`) that carry Claude attribution
trailers are still on `main` by the user's explicit choice, unchanged. Do not
raise it again unless the user does.

## 1. What this session actually did

1. **Installed a plugin**: `avoid-ai-writing` from
   `conorbronsdon/avoid-ai-writing` via `/plugin marketplace add` +
   `/plugin install`. Unrelated to the eval pipeline, just infrastructure —
   mentioned here only because it's now in `.claude/` and it's what triggered
   loading the writing-style skill before drafting the dissertation prose.
2. **Regenerated figures** (`python3 -m scripts.make_result_figs --out-dir
   figures`) against the current, complete result set — the fig3
   "capability cliff" scatter plot had never been rendered since the
   Gemini-arm session added ~15 new win points.
3. **Found and fixed a real bug in `scripts/make_result_figs.py`
   (`fig3_capability_cliff`)**: the win-label vertical stacking used a
   *linear* formula (`ymax * (1.9 - 0.32*i)`) on a *log-scale* y-axis. Past
   ~6 wins this goes negative, and matplotlib silently produces a PDF with a
   `MediaBox` height of ~196,000 points (should be ~280). This didn't error
   in matplotlib — it errored downstream, in `tectonic`, with `! Dimension
   too large` when the figure was included in the LaTeX build. Fixed by
   switching to log-space-even spacing (`top * (bot/top)**(i/(n-1))`) and
   widening the figure slightly (3.4in → 4.4in tall) to fit 14 labels
   legibly. **If you regenerate this figure again and the PDF is suddenly
   huge or `tectonic` fails on it, check this function first** — it's an
   easy trap to reintroduce if the label-stacking logic gets touched again
   without re-deriving why it's log-space.
4. **Rewrote `Thesis Dissertation/Template/template.tex`** (the paper
   compiles with `tectonic`, IEEE conference format, now 10 pages). The old
   draft is preserved as `template.tex.bak-20260817-192046` in the same
   directory — **not committed**, it's a local safety copy, delete it
   whenever or leave it, your call, but don't assume it's tracked in git.
   Major content changes, all cross-checked against
   `scripts/analyze_final_results.py` output and hand-written verification
   queries against the registered CSVs (see §3 for the exact numbers and
   how they were derived):
   - New Section V, "Two Defects in the Trusted Scaffolding" — the `!tbaa`
     verifier ceiling and the SMT-timeout-never-passed-through bug, framed
     as a general lesson about proposer-verifier systems (a broken verifier
     and an incapable proposer produce the same empty results table; an
     identity transform is the cheap way to tell them apart).
   - Results section rewritten around **888 completed attempts**, 237
     proven refinements, **14 verified wins** (10 Gemini, mean 64.8%
     reduction; 4 Qwen 3B, all on the instnamer ablation arm, none on raw
     `-O0`), with the pass≠win distinction stated prominently (223/237
     passes are 0% no-op echoes — reporting pass count as win count
     overstates by 17x).
   - New subsections: SSA-bookkeeping failure taxonomy (§ "Why Candidates
     Fail to Parse"), the instnamer ablation with the honest p=0.057
     framing and the corrected (non-replicating) within-bucket claim, the
     capability-cliff scatter (complexity/tokens, not context length,
     predicts failure), and a latency table showing verification now
     *dominates* inference cost for the Gemini arm (346s mean vs 96s) —
     this **inverts** the old paper's "verification is nearly free" claim,
     which was true only because the SMT-timeout bug meant verification
     was never actually run to completion.
   - Limitations section expanded: the 6 unknown-magnitude wins, the
     `temperature=0.0` non-determinism (`ludcmp.bc::init_array` won 4.10%
     once and reran at 0.00%), the discarded `pct_of_o2_gap_closed` metric.
5. **Caught and fixed a number I got wrong on first pass**: I initially
   wrote "13 candidates were ever refuted (rejected) by Alive2" by
   pattern-matching against the old handoff's "5 functions ever rejected"
   framing without recomputing it. Actually counting `rejected` verdicts
   across every CSV `scripts/analyze_final_results.py` registers gives
   **18**, not 13 and not 5 (the old number was stale even before this
   session — the Gemini batches added more rejections). Fixed in the two
   places it appeared (Results section and Conclusion). **Lesson repeated
   from `MORNING.md`, now a second time in this project's history: print
   the number, don't infer it from a prior session's framing, even when the
   framing has held before.**
6. **Updated `README.md` §9 "Evaluation Findings"** to match — it still said
   "Verified optimisation on real code has happened exactly once" and used
   436 as the completed-attempt denominator (both true of an earlier
   session, neither true now). Rewrote with the current 888/237/14 numbers,
   the two scaffolding-bug writeups, the pass≠win caveat, the per-model
   table, the instnamer ablation summary, and the inverted latency finding.
   Added a pointer to the dissertation file at the end of the section.

## 2. The two infrastructure bugs (carried forward from the prior session,
   now also documented in the paper itself — read `template.tex` §V for the
   full writeup, this is just the pointer)

1. `alive-tv`'s own `--smt-to`/`--smt-max-mem` were never passed through —
   fixed in `llmcompile/verification/alive.py` + `config.py`
   (`smt_timeout`, `smt_max_mem_mb`, env: `SMT_TIMEOUT`, `SMT_MAX_MEM_MB`).
2. Alive2 cannot translate `!tbaa` metadata, which Clang attaches to every
   `-O0` load/store — fixed by stripping `!tbaa`/`!tbaa.struct`/`!range`/
   `!alias.scope`/`!noalias` in normalization (multiple scripts, see
   `grep -rn tbaa scripts llmcompile`). See the `tbaa-verifier-ceiling`
   memory file for the original diagnosis (identity-transform proof).

Neither needs further work right now; both are load-bearing facts for the
results, not open threads.

## 3. Numbers this session verified by hand (don't re-derive, just trust
   these, they were computed directly from the CSVs `analyze_final_results.py`
   registers, not inferred from prose)

- Completed attempts: **888** (of 7,999 rows across real-corpus CSVs, 88.9%
  pending/error).
- Verdict totals across the 18 registered result CSVs: `passed=237`,
  `unsupported=185`, `syntax_fail=448`, `rejected=18`, `pending=7043`,
  `error=68`. Gate-rejected total (`syntax_fail+rejected+unsupported`) =
  **651**.
- `finish_reason` over the 521 completed attempts that have it recorded:
  501 `stop`, 0 `length` (zero truncation, at any sample size collected so
  far).
- Syntax-failure taxonomy over the 5 arms `make_result_figs.py`'s fig1
  plots (`syntax_diag_3b/7b_results.csv`, `qwen32b_subset_results.csv`,
  `syntax_diag_3b_instnamed_results.csv`, `gemini_subset_results.csv`): 195
  rows loaded, 67 `syntax_fail`, 65 with captured diagnostics (2 pre-date
  the `syntax_error` instrumentation). Local-only failures (54 of the 67)
  are ~70% SSA-bookkeeping by the categorizer's bucketing.
- `sbase_results.csv` tokens: n=311, mean 4,627, **median 3,883** (the old
  README quoted the mean as if it were representative; the paper's table
  now uses the median for consistency with the other corpus rows, which
  are also medians).
- By-model win rates (Table in both README and paper): qwen3b 431 compl./
  0.9% win, qwen7b 217/0.0%, qwen32b 124/0.0% (lowest syntax_fail of any
  arm at 21%, still zero wins), gemini 73/13.7%.

If you add new result CSVs, **register them in
`scripts/analyze_final_results.py`'s file list first** (this has bitten the
project twice already per the prior handoff) and then re-derive any number
above that's affected before quoting it in either doc.

## 4. Repo state as this is written

Working tree before this session's commit:
- Modified: `figures/fig{1,2,3}_*.{pdf,png}` (regenerated), `northminicode_subset_results.csv`
  (1-line change, pre-existing from before this session, not touched by
  this session's work — leave as-is, not this session's concern), plus
  `scripts/make_result_figs.py` (the log-space fix), `README.md`, and
  `Thesis Dissertation/Template/template.tex` + the 3 figure PDFs copied
  into that directory + a new `template.pdf` build output.
- Untracked: `.claude/` (the plugin install from earlier in the session —
  check whether the user wants this committed or gitignored; it wasn't
  addressed this session, just noting it's there).
- Not committed as of this handoff being written — the next action is to
  commit and push everything above except deciding on `.claude/`.

## 5. Immediate next steps for whoever picks this up

1. Decide on `.claude/` — commit, gitignore, or leave untracked. Not
   resolved this session.
2. If the auto-commit loop isn't running, consider restarting it
   (`scripts/auto_commit_results.sh`) if more eval runs are planned.
3. The Gemini-arm session's remaining open threads (best-of-k sampling,
   preserving alias metadata through a matched toolchain instead of
   stripping it, wider frontier-model coverage) are all still open and are
   now also listed in the paper's "Future Work" section — that's the
   canonical place to check what's next, not this file, going forward.
4. If `poppler` (`brew install poppler`) gets installed, worth re-rendering
   `template.pdf` page-by-page to visually confirm table/figure placement
   past page 1 — this session could only visually verify page 1 via `sips`
   and trusted `tectonic`'s clean compile (0 errors, only underfull-hbox
   warnings) for the rest.
