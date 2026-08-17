# Agent Handoff — 2026-08-17 (Gemini full-corpus completion session)

**To the next agent**: this replaces every prior version of this file from
today (the "Gemini frontier-arm session" and "dissertation rewrite session"
versions are both folded in below — their work is preserved, not lost, just
consolidated now that the full arc is finished). As of this writing, **every
batch launched today has completed. The entire 114-function corpus has a
Gemini attempt on record. Nothing is running.** This is a clean stopping
point — read this file, decide what's next, no processes to babysit.

## 0. Standing git rules (unchanged, still true, checked again this session)

Two rules from a pinned user memory, apply to every session/repo, indefinitely:

1. **No `Co-Authored-By: Claude` / `Claude-Session:` trailer on any commit,
   ever** — including automated ones. Verified clean on every commit made
   today, including the auto-commit loop's.
2. **Commit periodically and automatically, without being asked.**
   Implemented by `scripts/auto_commit_results.sh` — see §5 for changes.

The 3 commits (`f0bcb66`, `6e37ca5`, `c16285e`) carrying Claude attribution
trailers are still on `main`. Asked again this session (twice, across two
sub-sessions): the user chose to leave them as-is both times. **Stop asking
unless the user brings it up.**

## 1. What happened today, in order

This was a long session with a lot of ground covered. Rough chronology:

1. **Read the prior handoff** (overnight local-model chain, complete;
   Gemini arm blocked on an API key, flagged as the single highest-value
   remaining experiment).
2. **Got a Gemini API key from the user**, researched actual free-tier rate
   limits live against Google's and OpenRouter's real APIs (not blog posts —
   see §6), and launched the first Gemini batch.
3. **User asked to remove the timeout** after early runs looked
   timeout-limited. Investigation found the real cause wasn't the configured
   timeout at all — it was a genuine infrastructure bug (§2a).
4. **Found and fixed two real bugs** (§2) that had been silently discarding
   provable candidates for the project's entire history.
5. **Ran 7 sequential/parallel Gemini batches** across 7 different API
   keys/projects (verified empirically that Gemini's free-tier quota is
   per-model-per-project, not per-key — §6), covering the full 114-function
   corpus with zero overlap between batches (verified programmatically each
   time, never by eyeballing).
6. **Set up a live 10-minute status-check loop** (a cron job) so progress
   could be reported without manual polling; cancelled it once all batches
   finished since there was nothing left to watch.
7. **Wrote a full handoff mid-session**, then discovered a *second,
   concurrent* session (same user, different Claude Code session) had
   independently picked up that handoff, found a **third** real bug
   (`!tbaa` metadata), rewrote the actual dissertation LaTeX and
   `README.md`, and pushed. Rebased cleanly on top rather than clobbering it
   — see §1a for what that session did, since its content is folded into
   this file now.
8. **The remaining 2 batches finished** after that rewrite session captured
   its numbers, adding 10 more named wins and completing full-corpus
   coverage. This file is the final consolidation.

### 1a. What the concurrent "dissertation rewrite" session did (preserved)

That session did not run new evals. It consumed the Gemini-arm session's
results at the time (63 completed / 15 passed / 10 wins, batches 3-5 only)
and:

- **Found a third real bug**: Alive2 cannot translate `!tbaa` metadata,
  which Clang attaches to every `-O0` load/store. Fixed by stripping
  `!tbaa`/`!tbaa.struct`/`!range`/`!alias.scope`/`!noalias` during
  normalization (multiple scripts — `grep -rn tbaa scripts llmcompile` to
  find them all). See the `tbaa-verifier-ceiling` memory file for the
  original diagnosis (an identity-transform proof: pipe unmodified `-O0` IR
  straight through Phase 5 with no LLM in the loop at all, and it *still*
  failed to verify against itself until `!tbaa` was stripped — which proves
  the verifier was the ceiling, not the LLM).
- **Fixed a real plotting bug** in `scripts/make_result_figs.py`
  (`fig3_capability_cliff`): win-label vertical stacking used a *linear*
  formula on a *log-scale* axis, which goes negative past ~6 wins and
  silently produced a PDF with a ~196,000pt-tall `MediaBox` — didn't error
  in matplotlib, errored downstream in `tectonic` (`! Dimension too large`)
  when included in the LaTeX build. Fixed with log-space-even spacing. **If
  this figure is regenerated again and the PDF is suddenly huge or
  `tectonic` fails, check this function first.**
- **Rewrote `Thesis Dissertation/Template/template.tex`** (IEEE conference
  format, compiles with `tectonic`, ~10 pages). Old draft preserved as
  `template.tex.bak-20260817-192046` in the same directory, **not
  committed** — a local safety copy, delete or keep, your call. Major
  additions: a new section "Two Defects in the Trusted Scaffolding" (the
  `!tbaa` ceiling and the SMT-timeout-never-passed-through bug, framed as a
  general lesson about proposer-verifier systems — a broken verifier and an
  incapable proposer produce the same empty results table; an identity
  transform is the cheap way to tell them apart), an SSA-bookkeeping
  failure taxonomy, the instnamer ablation with honest p=0.057 framing, a
  capability-cliff scatter plot, and a latency table showing verification
  now *dominates* inference cost for the Gemini arm — which **inverts** the
  old paper's "verification is nearly free" claim (that claim was only true
  because the SMT-timeout bug meant verification was never actually run to
  completion).
- **Caught its own number error before shipping it**: initially wrote "13
  candidates ever rejected" by pattern-matching the old handoff's "5 ever
  rejected" framing without recomputing. Actually counting gave 18 at the
  time (now 21, see §3). **This is the second time in this project's
  history the exact same lesson has been learned** (first in `MORNING.md`,
  same mistake: inferring a number from a prior session's prose instead of
  recomputing it). If you take nothing else from this file: **print the
  number, don't infer it, even when a pattern has held every time before.**
- **Updated `README.md` §9** to match its numbers at the time (888/237/14).
  **These are now stale** — see §3 for the true final numbers. Whoever picks
  this up next should regenerate `README.md` §9 and `template.tex` one more
  time against the final tally.

## 2. Three real infrastructure bugs found and fixed today

All three were silently discarding provable candidates for the project's
entire history. All three are fixed, tested, committed, pushed.

### 2a. `alive-tv`'s own internal SMT timeout/memory cap were never passed through

`llmcompile/verification/alive.py`'s `verify_refinement()` built its
`alive-tv` command with just `[binary, src_path, tgt_path]` — no `--smt-to`
or `--smt-max-mem` flag, ever, in this project's history. Alive2 silently
falls back to its own defaults (**10000ms SMT-query timeout, 1024MB memory
cap**), completely independent of whatever `alive_tv_timeout` (a
subprocess-level `subprocess.run(timeout=...)` guard) was configured to.
This is why so many `unsupported` verdicts across the project's history had
suspiciously *fast* `verification_latency_s`: the outer timeout was never
the real constraint, Alive2's own internal defaults were.

Fixed in commit `94cd7a4`: added `smt_timeout` (finishing a field that was
already declared in `config.py` but marked "Reserved" and never wired up)
and a new `smt_max_mem_mb`, both env-overridable (`SMT_TIMEOUT`,
`SMT_MAX_MEM_MB`), both now actually passed to `alive-tv`. Defaults:
`smt_timeout=120s`, `smt_max_mem_mb=4096`. Today's runs used
`SMT_TIMEOUT=1200`, `SMT_MAX_MEM_MB=16384` (this machine has 335GB RAM, 48
cores, near-zero baseline load — see §6).

**This fix alone is responsible for most of today's wins.** Verdicts that
used to resolve in under a second now genuinely get up to 20 minutes and
16GB to attempt a real proof.

### 2b. Phase 6 instruction-counting bug: blanked reduction% on some genuine wins

`scripts/run_openrouter_subset.py`'s per-file instruction counting
re-parses the *whole assembled module* with llvmlite, and this re-parse
fails on some stitched modules even though `llvm-as` and Alive2 both
accepted the candidate fine per-function. Previously this blanked every
function in that file to `reduction=None`, including genuinely `PASSED`
wins — first hit on `functionobjects.bc` in batch 4 (5 blank wins), then
again in batch 5 (1 more, launched before the fix landed) — **6
unknown-magnitude wins total, not recoverable** (re-running isn't safe to
assume gives the same candidate: this pipeline has shown non-determinism at
`temperature=0.0` twice now, see §2c).

Fixed in commit `59daf0a`: on whole-module count failure, fall back to
counting each function standalone via its own `original_ir`/`candidate_ir`
(both independently assemblable by Phase 1 design). Batches 6 and 7,
launched after this fix landed, both hit `functionobjects.bc` again and got
**real numbers** this time (`_Z9quicksortIPdXadL_...` 58.54%,
`_Z9quicksortIPdNSt3__14lessIdEEE...` 57.65%) — direct proof the fix works.

### 2c. `!tbaa` metadata (found by the concurrent session, §1a)

Alive2 cannot translate `!tbaa`/`!tbaa.struct`/`!range`/`!alias.scope`/
`!noalias` metadata, which Clang attaches to every `-O0` load/store by
default. Fixed by stripping it during corpus normalization. See §1a for the
full writeup and the `tbaa-verifier-ceiling` memory file for the original
identity-transform diagnosis.

### 2d. Confirmed non-determinism at `temperature=0.0` (second instance today)

`fpcmp.bc::diff_file` — the project's original historic 60.67% win from a
prior session — was re-attempted in today's batch 7 (same model, same
prompt, `temperature=0.0`) and came back **`unsupported`, not reproducing**.
This is the second confirmed instance (`ludcmp.bc::init_array` did the same
thing in an earlier session: 4.10% once, 0.00% on rerun). **State this as an
explicit limitation wherever the 60.67% figure or the "deterministic
pipeline" framing is cited** — Phases 1/2/4/5/6 are deterministic by
architecture (README §2), but Phase 3's LLM calls are not bit-reproducible
even at nominal `temperature=0.0`, and that's an LLM-API-level fact this
project cannot control from its own code.

## 3. Final numbers (regenerate first, always: `python3 -m scripts.analyze_final_results`)

As of this handoff, **all Gemini batches are complete, nothing is running**:

- **931 completed attempts** across all real-corpus CSVs (up from 822 at the
  start of today)
- **247 `verdict=passed`** (up from 222)
- **24 verified non-zero reductions** (up from 5) — full list, run the
  script for the current authoritative version, but as of now:

| function | reduction | model |
|---|---|---|
| `fpcmp.bc::diff_file` | 60.67% | gemini (prior session; did NOT reproduce on rerun, §2d) |
| `nussinov.bc::kernel_nussinov` | 81.23% | gemini |
| `nussinov.bc::kernel_nussinov_StrictFP` | 81.23% | gemini |
| `ffbench.bc::fourn` | 67.11% | gemini |
| `nussinov.bc::check_FP` | 67.68% | gemini |
| `linpack-pc.bc::ddot` | 64.44% | gemini |
| `linpack-pc.bc::daxpy` | 63.57% | gemini |
| `linpack-pc.bc::idamax` | 62.22% | gemini |
| `linpack-pc.bc::matgen` | 62.00% | gemini |
| `cholesky.bc::kernel_cholesky` | 62.59% | gemini |
| `lu.bc::init_array` | 65.92% | gemini |
| `cholesky.bc::check_FP` | 72.16% | gemini |
| `cholesky.bc::kernel_cholesky_StrictFP` | 57.82% | gemini |
| `ludcmp.bc::kernel_ludcmp_StrictFP` | 55.76% | gemini |
| `himenobmtxpa.bc::set_param` | 57.14% | gemini |
| `fannkuch.bc::fannkuch` | 58.16% | gemini |
| `functionobjects.bc::_Z9quicksortIPdXadL_Z19less_than_function2ddEEEvT_S1_` | 58.54% | gemini |
| `functionobjects.bc::_Z9quicksortIPdNSt3__14lessIdEEEvT_S4_T0_` | 57.65% | gemini |
| `Puzzle.bc::Trial` | 53.23% | gemini |
| `exptree.bc::doSearch` | 33.33% | gemini |
| `cholesky.bc::init_array` | 5.06% | qwen3b instnamed |
| `ludcmp.bc::init_array` | 4.10% | qwen3b instnamed |
| `fannkuch.bc::fannkuch` | 0.34% | qwen3b instnamed ×2 (same result, two runs — cross-validates determinism, not two independent points) |

Plus **6 more Gemini wins with unknown magnitude** (§2b) not in this table.

**By-model**: `gemini-3.5-flash`: 116 completed, 26 passed, **20 wins, 17.2%
win rate**. Every local model is still ≤0.9%
(`qwen2.5-coder:3b` 0.9%, `7b`/`32b` 0.0%). This gap — not the syntax-vs-
optimization threshold framing from before today — is now the project's
central empirical finding.

**Safety gate**: 684 candidates rejected (syntax_fail + rejected +
unsupported), **0** invalid candidates ever reached a final module. Held
perfectly across every model, every session, the entire project's history.
Still the load-bearing claim.

**`README.md` §9 and `Thesis Dissertation/Template/template.tex` reflect an
earlier snapshot (888/237/14) and have not been regenerated against this
final tally (931/247/24).** This is the most concrete immediate task for
whoever picks this up: re-run `analyze_final_results` and
`make_result_figs`, then update both documents one more time.

## 4. Provider/model research (verified empirically, not from blog posts)

Full detail in
`/home/jovyan/.claude/plans/please-research-if-we-curious-peacock.md` (a
plan-mode research doc; the user redirected mid-review to ask live status
questions instead of formally approving/rejecting it, but its findings are
correct and citable). Key facts, confirmed by live API calls:

- **Gemini free-tier quota is per-model-per-project, not per-API-key.**
  Confirmed empirically: a key exhausted (`429`, `limit: 20`) on
  `gemini-3.5-flash` **immediately succeeded** on `gemini-3.6-flash` with the
  same key. The 429 body's `quotaId` literally says
  `GenerateRequestsPerDayPerProjectPerModel-FreeTier`. Extra keys *inside the
  same Google Cloud project* would NOT add capacity — the reason today's 7
  different keys all worked is they're on distinct projects/accounts.
- **No free-tier Pro-model upgrade exists.** `gemini-3.1-pro-preview` and
  `gemini-pro-latest` both returned `limit: 0` on every key tested — a hard
  block, not a low quota.
- **Available free-tier flash models** (tested live): `gemini-3.5-flash`
  (today's model, all wins), `gemini-3.6-flash`, `gemini-3.7-flash` (newer,
  intermittent 503s), `gemini-3.5-flash-lite`, `gemini-3.1-flash-lite`,
  `gemini-3-flash-preview`. `gemini-2.5-flash`/`-pro` are 404 "no longer
  available to new users."
- **Decision made this session, asked directly of the user: stay on
  `gemini-3.5-flash` for the whole corpus**, to keep the win-rate denominator
  uncontaminated by a model-choice confound. Do not silently switch
  `GEMINI_MODEL` without asking — that decision stands, the corpus is now
  complete on this one model, which is exactly what was asked for.
- **OpenRouter** (from their own docs): free models (`:free` suffix) get
  **20 req/min, 50/day unfunded, 1000/day after a one-time ≥$10 lifetime
  credit purchase**. No `OPENROUTER_API_KEY` configured on this machine.
  Notable free model: `nvidia/nemotron-3-ultra-550b-a55b:free` (550B
  params, 1M context). **Switching provider/model needs zero code
  changes** — `LLM_BACKEND`/`GEMINI_MODEL`/`OPENROUTER_MODEL` env vars,
  `p3_route.py` already shares one LiteLLM dispatch path for both. This was
  explicitly deferred as a **separate arm, after** the Gemini corpus —
  not decided against, just sequenced later. Now that the Gemini corpus is
  done, this is a reasonable next thing to raise with the user.

## 5. Operational changes made this session

- **`scripts/auto_commit_results.sh`**: per explicit user request, interval
  changed from 1800s (30min) to **2700s (45min)**, commit message changed
  from `"Auto-checkpoint eval results: <ISO8601>"` to
  `"Checkpoint eval results: <YYYY-MM-DD HH:MM>"` (dropped "Auto", simpler
  timestamp). Commit `9232970`. **Still running** as this is written
  (`ps aux | grep auto_commit` to check) — leave it running for future
  unattended work, or restart with `nohup
  ./scripts/auto_commit_results.sh >> scratch/auto_commit.log 2>&1 &` if
  it's died (new default 2700 applies automatically, no arg needed).
- **`scripts/analyze_final_results.py`**: registered
  `gemini_batch4/5/6/7_results.csv` (commit `b654fd2`). This is the *third*
  time this exact class of bug has bitten the project (hardcoded file list,
  new CSVs silently uncounted) — **if you add a 8th batch or any new result
  CSV, register it here immediately.**

## 6. Operational recipe for running more Gemini batches, if needed

```bash
export PATH="$HOME/llvm_toolchain/llvm-project/llvm/build/bin:$PATH"   # clang/llvm-as, NOT on default PATH
export GEMINI_API_KEY=<key>       # NEVER write a raw key into a committed file
export ALIVE_TV_TIMEOUT=3600      # outer subprocess kill-switch (hard cap)
export LLM_TIMEOUT_SECONDS=300    # per Gemini API call
export SMT_TIMEOUT=1200           # alive-tv's own SMT-query timeout (§2a)
export SMT_MAX_MEM_MB=16384       # alive-tv's own SMT memory cap (§2a)
LLM_BACKEND=gemini PYTHONUNBUFFERED=1 nohup python3 -m scripts.run_openrouter_subset \
  --build-dir eval_subset_corpus_sanitized \
  --subset <subset.csv> --max-functions 20 \
  --output-csv <output.csv> > <log> 2>&1 &
```

`alive-tv` is auto-detected at `~/llvm_toolchain/alive2/build/alive-tv` by
`config.py` if it exists there (no PATH export needed for it specifically).

**Building a non-overlapping subset** (the pattern used for all 4 new
batches today — the whole corpus is now covered, but if new corpus files
are ever added, reuse this):
```python
import csv, random
def load(path): return {(r['file_name'], r['function_name']) for r in csv.DictReader(open(path))}
touched = load('target_subset.csv') | load('gemini_batch4_subset.csv') | ...  # every prior subset
full = list(csv.DictReader(open('full_corpus_subset.csv')))
remaining = [r for r in full if (r['file_name'], r['function_name']) not in touched and r['file_name'] != 'lists.bc']
# random.shuffle(remaining); pick N; write to a new subset CSV
```
Always verify zero-overlap programmatically before launching, never by
inspection — `functionobjects.bc` alone has 20+ functions and it's easy to
eyeball wrong (this bit the session once before the check was added).

**Rate-limit retry behavior, expected and not a bug**: LiteLLM retries
429/503 up to 5 times with exponential backoff (4s, 8s, 16s, 32s, 60s). A
function that exhausts all 5 falls back to `verdict=pending` gracefully.
The runner's resume logic treats any row already in the CSV — including
`pending` — as "done," so to retry specifically-pending rows, delete just
those rows from the CSV first (done between batches today).

**A genuinely hard proof can run 45-60+ minutes and still resolve, not
hang** — confirmed repeatedly today, up to ~57 minutes on some
`functionobjects.bc` candidates. `ALIVE_TV_TIMEOUT=3600` (1 hour) is the
hard ceiling; below that, elapsed time alone is not evidence of a stall —
check `ps -o pid,etime,%cpu,args -C alive-tv`, sustained ~99% CPU means
it's genuinely computing.

**`lists.bc` is permanently unparseable** (Phase 1 parse failure, a newer-
LLVM attribute llvmlite's LLVM-14-based parser rejects, documented since a
much earlier session). Exclude it from every subset; the runner already
skips it gracefully if it slips through, but don't waste a slot on it.

## 7. Files worth knowing about (touched today)

- `llmcompile/verification/alive.py`, `llmcompile/config.py` — the
  `--smt-to`/`--smt-max-mem` fix (§2a). New fields: `VerificationConfig.
  smt_timeout`, `.smt_max_mem_mb`, env: `SMT_TIMEOUT`, `SMT_MAX_MEM_MB`.
- `scripts/run_openrouter_subset.py` — the per-function counting fallback
  (§2b).
- `scripts/analyze_final_results.py` — run first, always; register new
  CSVs here immediately (§5).
- `scripts/auto_commit_results.sh` — 45min interval, plain timestamp (§5).
- `scripts/make_result_figs.py` — log-space label fix (§1a).
- `gemini_batch{4,5,6,7}_subset.csv` / `gemini_batch{4,5,6,7}_results.csv`
  — this session's non-overlapping subsets and their final results, all
  complete.
- `README.md` §9, `Thesis Dissertation/Template/template.tex` — rewritten
  once already (§1a), need one more regeneration pass against final
  numbers (§3).
- `/home/jovyan/.claude/plans/please-research-if-we-curious-peacock.md` —
  provider/model research (§4).
- **Not committed**: `gemini_batch{1,2}*.log.bak` and
  `gemini_subset_results_batch{1,2}*.csv.bak` — scratch diagnostic backups
  from debugging the timeout/memory bugs. Safe to delete or leave, your
  call.

## 8. Immediate next steps

1. **Regenerate `README.md` §9 and `template.tex`** against the true final
   numbers in §3 (931/247/24, Gemini 116/26/20/17.2%). This is the single
   most concrete unfinished task.
2. **Regenerate figures**: `python3 -m scripts.make_result_figs --out-dir
   figures` — verify the log-space label fix (§1a) still looks right with
   24 wins now (up from 14 when it was last checked).
3. **Decide on OpenRouter** (§4) — the Gemini corpus is done, so the
   deferred "separate arm" decision is now live. Ask the user.
4. **Consider best-of-k sampling (Track F)** and the other items in
   `/home/jovyan/.claude/plans/based-on-what-we-cached-yao.md` — still the
   governing 2-month dissertation roadmap, largely untouched since Track A
   (Gemini) is now genuinely done rather than just started.
5. **The 6 unknown-magnitude wins (§2b)** — decide with the user whether to
   report them as "verified win, magnitude unknown" in any write-up, or
   leave them out of headline tables. They're real, Alive2-proven,
   non-zero-change wins; the project's convention so far is to only
   tabulate wins with a known number, so they're not in the "24."
6. **The `!tbaa` fix and non-determinism finding (§2c, §2d)** are both
   already written into `template.tex` per the concurrent session — verify
   they're still accurate after step 1's regeneration, since the numbers
   around them will shift.

## 9. Rules of engagement (carried forward, still true)

- §2 of `README.md` (architectural constraints) is hard. Stop and flag if a
  task conflicts with it.
- No hard-coded thresholds/timeouts — everything in `config.py`,
  env-overridable. This session added `SMT_TIMEOUT`/`SMT_MAX_MEM_MB` to
  that pattern (§2a) — keep doing this for any new tunable.
- Committing a partially-filled CSV mid-run is this project's established
  convention, not a mistake.
- **Never write a live API key into a committed file, ever.** This session
  handled 7 different Gemini keys purely via shell env vars, never
  persisted to disk in anything that gets committed.
- **If you find yourself pattern-matching a number from a prior session's
  prose instead of recomputing it from the CSVs — stop and recompute.**
  This exact mistake has now happened twice in this project's history
  (`MORNING.md`, and again in §1a above). It will happen a third time to
  someone who doesn't read this line.
- `/home/jovyan` is a 24GB persistent volume — never put anything large
  there. `/tmp` is large and effectively persistent on this pod.
- Git credentials are stored (`~/.git-credentials`, mode 600); `git push`
  works. Expect concurrent-session push conflicts if another Claude Code
  session is active on this same repo at the same time (happened today) —
  `git fetch` + inspect the diverging commit + `git rebase origin/main` is
  the right response, not force-push. Check *who* authored the conflicting
  commit before assuming it's noise to discard.
- Working tree has some untracked scratch `.bak` files (§7) as of this
  handoff; everything else is committed and pushed. `git status` should
  show a clean, up-to-date `main` otherwise.
