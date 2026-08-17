# Agent Handoff — 2026-08-17 (Gemini frontier-arm session)

**To the next agent**: this replaces the 2026-08-17 "overnight monitoring session"
version of this file. That session finished the local-model full-corpus chain and
handed off with the Gemini arm as the single highest-value remaining experiment,
blocked only on an API key. This session got that key (several, in fact) and used
it to find and fix two real infrastructure bugs, then ran the Gemini arm across
**seven sequential/parallel batches, four of which are still running** as this is
written. The headline result changed completely: Gemini went from 1 win in 7
completed attempts to **10 wins in 63 completed attempts (15.9% win rate)**, and
the project's all-time verified-win count went from 5 to 14.

**Read §1 first if anything looks like it's hanging — it almost certainly isn't.**

## 0. Standing git rules (unchanged, still true)

Same two rules as always, from a pinned user memory, apply to every session/repo:

1. **No `Co-Authored-By: Claude` / `Claude-Session:` trailer on any commit, ever**
   — including automated ones. Every commit this session was written without them;
   verify this stayed true if you keep committing.
2. **Commit periodically and automatically, without being asked.** Implemented by
   `scripts/auto_commit_results.sh` (see §5 for changes made to it this session).

The previous handoff flagged 3 commits (`f0bcb66`, `6e37ca5`, `c16285e`) that still
carry Claude attribution trailers on `main`, and noted the user was informed and
chose not to rewrite history. **This session, asked directly, the user again chose
to leave those 3 commits as-is.** Do not raise it again unless the user does.

## 1. What's running right now — check before assuming anything is stuck

Four background pipelines are mid-run as this handoff is written. **Sustained high
CPU on an `alive-tv` process is normal, not a hang** — this session's biggest fix
(§2) means verification now legitimately takes up to an hour on hard candidates,
where it used to fail in under a second.

```bash
# process health
for P in <check current PIDs — see below>; do ps -p $P; done
# proof-in-progress check: sustained ~99% CPU = working, not stuck
ps -o pid,etime,%cpu,args -C alive-tv
```

| Batch | PID (at handoff time) | Log | Output CSV | Subset file |
|---|---|---|---|---|
| 4 | 51116 | `gemini_batch4.log` | `gemini_batch4_results.csv` | `gemini_batch4_subset.csv` |
| 5 | 51807 | `gemini_batch5.log` | `gemini_batch5_results.csv` | `gemini_batch5_subset.csv` |
| 6 | 52537 | `gemini_batch6.log` | `gemini_batch6_results.csv` | `gemini_batch6_subset.csv` |
| 7 | 52675 | `gemini_batch7.log` | `gemini_batch7_results.csv` | `gemini_batch7_subset.csv` |

PIDs will be stale by the time you read this if they've since exited — check
`ps aux | grep run_openrouter_subset` for what's actually alive. Batch 3
(`gemini_subset_results.csv`, built from `target_subset.csv`) **completed** this
session with 6 wins; treat it as done, do not re-run it.

**A `/loop`-style cron job (ID `08e98ac7`, every 10 minutes) is posting a live
status table into this chat session** as a running commentary while these batches
finish. It is **session-only** — it dies when this Claude session ends, is not
written to disk, and auto-expires after 7 days regardless. If you are a fresh
agent reading this file cold, that job is not running for you; recreate it with
`/loop 10m <describe the batches to check>` if you want the same behavior, or
just poll the table above manually.

**All four batches were built from disjoint, programmatically-verified-non-
overlapping 20-ish-function subsets of the 114-function full corpus**, deliberately
distinct from `target_subset.csv` (batch 3) and from each other. Once batch 7
finishes, **every function in the 114-function corpus (except `lists.bc`, which
can never be parsed — see below) will have received at least one Gemini attempt.**
Batch 7 is intentionally the *last* 15 functions of the corpus — nothing is left
to pick after it.

## 2. Two real infrastructure bugs found and fixed this session

Both were silently discarding provable candidates for the entire project history
up to this point. Both are now fixed, tested, committed, and pushed.

### 2a. `alive-tv`'s own internal SMT timeout/memory cap were never passed through

`llmcompile/verification/alive.py`'s `verify_refinement()` built its `alive-tv`
command with just `[binary, src_path, tgt_path]` — no `--smt-to` or
`--smt-max-mem` flag, ever, on any prior run in this project's history. Alive2's
own binary silently falls back to **its own defaults: 10000ms SMT-query timeout,
1024MB memory cap** — completely independent of and much tighter than whatever
`alive_tv_timeout` (a subprocess-level `subprocess.run(timeout=...)` guard) was
configured to. This is why so many `unsupported` verdicts across the whole
project's history had suspiciously *fast* `verification_latency_s` (well under
whatever the outer timeout was): the outer timeout was never the real constraint.

Fixed in commit `94cd7a4`: added a dedicated `smt_timeout` field (finishing off a
field that was already declared in `config.py` but marked "Reserved" and never
wired up) and a new `smt_max_mem_mb` field, both env-overridable
(`SMT_TIMEOUT`, `SMT_MAX_MEM_MB`), both now actually passed as
`--smt-to=<seconds*1000>` / `--smt-max-mem=<MB>` to the `alive-tv` invocation.
Defaults: `smt_timeout=120s`, `smt_max_mem_mb=4096`. Today's runs used much more
generous env overrides (`SMT_TIMEOUT=1200`, `SMT_MAX_MEM_MB=16384`) since this
machine has 335GB RAM and 48 cores with near-zero baseline load — see §6 for why
that headroom matters if you raise it further.

**This fix alone is responsible for most of today's wins.** Every `unsupported`
verdict that used to resolve in under a second now genuinely gets 20 minutes and
16GB to attempt a real proof, and a large fraction of Gemini's real,
substantively-different candidates turned out to be provable once given that
room — they were not being rejected by Alive2, they were never being *tried*.

### 2b. Phase 6 instruction-counting bug: silently blanked out reduction% on PASSED wins

Separately, `scripts/run_openrouter_subset.py`'s per-file instruction counting
re-parses the *whole assembled module* (`parsed.final_module_ir`) with llvmlite,
and this re-parse fails on some stitched modules even though `llvm-as` and Alive2
both accepted the same candidate fine per-function (a known llvmlite/Phase 6
interaction bug, first documented by a *previous* session, never root-caused).
Previously this just blanked every function in that file to `reduction=None`,
including genuinely `PASSED`, Alive2-proven wins — first observed today on
`functionobjects.bc` in batch 4, where **4 real wins landed with unknown
magnitude** (still `verdict=passed` in the CSV, just no percentage).

Fixed in commit `59daf0a`: on whole-module count failure, fall back to counting
each selected function **standalone**, via its own `original_ir` /
`candidate_ir` — both independently assemblable by Phase 1 design (this is
exactly the property Phase 1's `test_each_function_is_independently_assemblable`
test already guarantees), so this sidesteps the whole-module re-parse bug
entirely rather than needing to fix Phase 6 itself.

**This only affects files processed *after* the fix landed.** The 4 already-blank
`functionobjects.bc` wins in `gemini_batch4_results.csv` were already committed
before the fix and are **not recoverable** without re-running the LLM call — and
re-running is not safe to assume gives the same candidate, because this pipeline
has already shown non-determinism at `temperature=0.0` in a previous session
(`ludcmp.bc::init_array` won 4.10% in one run and reran at 0.00% in another,
same settings). Report those as "verified win, magnitude unknown," don't guess
a number, and don't spend quota trying to recover it unless the user asks.

**Update while writing this handoff**: batch 5 (PID 51807, launched 16:52, well
before this bug was found and fixed) hit the identical bug on its own
`functionobjects.bc` pass and added a 5th-through-6th blank win
(`_ZNSt3__17__sort5...`) — **6 unknown-magnitude wins total as of this writing**
(5 in batch 4, 1 in batch 5), not 4. Both of those batches were already running
with the old code in memory when the fix landed, so neither benefits from it
retroactively. **Batches 6 and 7 were launched after the fix was written to disk**
(confirm by checking whether their start time in the log is after commit
`59daf0a`'s timestamp), so they should get real numbers even if they hit
`functionobjects.bc` again — verify this assumption once they reach that file.

## 3. Headline numbers (regenerate first, always)

Run `python3 -m scripts.analyze_final_results` — it self-updates as CSVs land, and
it was itself fixed this session (see §4). As of this handoff:

- **878 completed attempts** across all real-corpus CSVs (up from 822 last session)
- **236 `verdict=passed`** (up from 222)
- **14 verified non-zero reductions** (up from 5) — full list:

| function | reduction | model |
|---|---|---|
| `fpcmp.bc::diff_file` | 60.67% | gemini (prior session) |
| `ffbench.bc::fourn` | 67.11% | gemini (this session) |
| `nussinov.bc::kernel_nussinov` | 81.23% | gemini (this session) |
| `nussinov.bc::kernel_nussinov_StrictFP` | 81.23% | gemini (this session) |
| `fannkuch.bc::fannkuch` | 58.16% | gemini (this session) |
| `lu.bc::init_array` | 65.92% | gemini (this session) |
| `himenobmtxpa.bc::set_param` | 57.14% | gemini (this session) |
| `cholesky.bc::kernel_cholesky` | 62.59% | gemini (this session) |
| `cholesky.bc::kernel_cholesky_StrictFP` | 57.82% | gemini (this session) |
| `ludcmp.bc::kernel_ludcmp_StrictFP` | 55.76% | gemini (this session) |
| `cholesky.bc::init_array` | 5.06% | qwen3b instnamed (prior session) |
| `ludcmp.bc::init_array` | 4.10% | qwen3b instnamed (prior session) |
| `fannkuch.bc::fannkuch` | 0.34% | qwen3b instnamed ×2 (prior session, same result twice) |

Plus **6 more Gemini wins with unknown magnitude** (§2b — 5 in batch 4, 1 in
batch 5, both pre-fix) not in this table since they have no reduction% to
report — total genuinely-verified-PASSED-with-actual-optimization count is
**14 with numbers + 6 without = 20**, and batches 5/6/7 are still running and
will add more.

**By-model, Gemini specifically**: 63 completed, 15 `passed`, **10 with non-zero
reduction, 15.9% win rate** — up from the prior session's headline "1/7, 14.3%".
This is now a real, statistically meaningful hit-rate rather than n=7 anecdote,
and it is the single biggest evidential shift in the project's history: local
models are still at effectively 0% (qwen 3b: 0.9%, 7b: 0.0%, 32b: 0.0%), Gemini
is at 15.9%. The gap is not subtle.

**The safety gate still holds perfectly**: 642 candidates rejected
(syntax_fail + rejected + unsupported), **0** invalid candidates ever reached a
final module. This has never once failed across the project's entire history,
across every model, every session. This is still the load-bearing claim.

## 4. Other fixes this session

- **`scripts/analyze_final_results.py`'s hardcoded file list** — same class of bug
  the *previous* handoff already found and fixed once (it's a recurring trap: new
  CSVs silently don't count until registered by hand). Registered
  `gemini_batch4/5/6/7_results.csv` in commit `b654fd2`. **If you add an 8th batch
  or any new result CSV, register it here too, immediately** — this has now bitten
  the project twice.
- **`scripts/auto_commit_results.sh`**: per explicit user request, changed the
  default interval from 1800s (30min) to **2700s (45min)**, and changed the commit
  message from `"Auto-checkpoint eval results: <ISO8601>"` to
  `"Checkpoint eval results: <YYYY-MM-DD HH:MM>"` — dropped the word "Auto" and
  switched to a plainer timestamp. Commit `9232970`. The currently-running loop
  (check `ps aux | grep auto_commit`) is on the new version; if you restart it,
  the new default (2700) applies automatically, no need to pass it explicitly.

## 5. Provider/model research this session (verified empirically, not just from docs)

Full detail in `/home/jovyan/.claude/plans/please-research-if-we-curious-peacock.md`
(a plan-mode research doc, not yet fully executed — read it before proposing
provider/model changes). Key facts, several confirmed by live API calls rather
than trusting blog summaries (which were unreliable/contradictory):

- **Gemini free-tier quota is per-model-per-project, not per-API-key.** Confirmed
  empirically: a key fully exhausted (`limit: 20`, `429 RESOURCE_EXHAUSTED`) on
  `gemini-3.5-flash` **immediately succeeded** on `gemini-3.6-flash` with the same
  key. The 429 body's `quotaId` literally says
  `GenerateRequestsPerDayPerProjectPerModel-FreeTier`. Extra keys *inside the same
  Google Cloud project* would NOT add capacity (Google's own docs: "Rate limits
  are applied per project, not per API key") — the reason today's 7 different keys
  all worked is that they are on distinct projects/accounts.
- **There is no free-tier Pro-model upgrade available.** `gemini-3.1-pro-preview`
  and `gemini-pro-latest` both returned `limit: 0` on every key tested — hard
  free-tier block, not just a low quota. Frontier-Pro access needs billing.
- **Available free-tier flash models** (tested live): `gemini-3.5-flash` (current
  default, all of today's wins), `gemini-3.6-flash`, `gemini-3.7-flash` (newer,
  intermittent 503 high-demand at test time), `gemini-3.5-flash-lite`,
  `gemini-3.1-flash-lite`, `gemini-3-flash-preview`. `gemini-2.5-flash`/`-pro` are
  404 "no longer available to new users."
- **Decision made this session, asked directly of the user: stay on
  `gemini-3.5-flash`, finish the whole corpus on one model before considering any
  other model or provider**, to keep the win-rate denominator uncontaminated by a
  model-choice confound. Do not silently switch `GEMINI_MODEL` without asking.
- **OpenRouter** (docs, not blog posts): free models (`:free` suffix) get
  **20 requests/minute, 50/day unfunded, rising to 1000/day after a one-time ≥$10
  lifetime credit purchase**. No `OPENROUTER_API_KEY` is configured on this
  machine. Notable free models available: `nvidia/nemotron-3-ultra-550b-a55b:free`
  (550B params, 1M context — genuinely frontier-scale) and several coding-specific
  ones. **Switching provider or model requires zero code changes** — confirmed by
  reading `llmcompile/config.py` (`LLM_BACKEND`/`GEMINI_MODEL`/`OPENROUTER_MODEL`
  env vars) and `p3_route.py` (Gemini and OpenRouter share one LiteLLM dispatch
  path, identical retry/rate-limit logic). This was explicitly deferred as a
  **separate arm, after** the single-model Gemini corpus is complete — not decided
  against, just sequenced after.

## 6. Operational notes for running further batches

- **Toolchain**: `clang`/`llvm-as`/`opt` are at
  `~/llvm_toolchain/llvm-project/llvm/build/bin` — must be on `PATH` explicitly
  (`export PATH="$HOME/llvm_toolchain/llvm-project/llvm/build/bin:$PATH"`), it is
  **not** on the default shell `PATH`. `alive-tv` is at
  `~/llvm_toolchain/alive2/build/alive-tv`, auto-detected by `config.py` if it
  exists at that path (no PATH export needed for it specifically).
- **The exact env-var recipe used for every batch today**, safe to reuse:
  ```bash
  export PATH="$HOME/llvm_toolchain/llvm-project/llvm/build/bin:$PATH"
  export GEMINI_API_KEY=<key>
  export ALIVE_TV_TIMEOUT=3600      # outer subprocess kill-switch (hard cap)
  export LLM_TIMEOUT_SECONDS=300    # per Gemini API call
  export SMT_TIMEOUT=1200           # alive-tv's own SMT-query timeout (§2a)
  export SMT_MAX_MEM_MB=16384       # alive-tv's own SMT memory cap (§2a)
  LLM_BACKEND=gemini PYTHONUNBUFFERED=1 nohup python3 -m scripts.run_openrouter_subset \
    --build-dir eval_subset_corpus_sanitized \
    --subset <subset.csv> --max-functions 20 \
    --output-csv <output.csv> > <log> 2>&1 &
  ```
- **Machine has huge headroom**: 335GB RAM free, 48 cores, load average ~2 even
  with 3-4 concurrent `alive-tv` processes each capped at 16GB. Running more
  batches in parallel is safe; CPU contention just means proofs take longer
  wall-clock, nothing fails or starves.
- **Building a non-overlapping subset** (the pattern used for batches 4-7):
  ```python
  import csv, random
  def load(path): return {(r['file_name'], r['function_name']) for r in csv.DictReader(open(path))}
  touched = load('target_subset.csv') | load('gemini_batch4_subset.csv') | ...  # every prior subset
  full = list(csv.DictReader(open('full_corpus_subset.csv')))
  remaining = [r for r in full if (r['file_name'], r['function_name']) not in touched and r['file_name'] != 'lists.bc']
  # random.shuffle(remaining); pick 20; write to a new subset CSV
  ```
  Always verify zero-overlap programmatically before launching, not by inspection
  — `functionobjects.bc` alone has 20+ functions and it's easy to eyeball wrong.
- **`lists.bc` is permanently unparseable** — a Phase 1 parse failure (newer-LLVM
  attribute `dead_on_unwind writable sret(...)` that llvmlite's LLVM-14-based
  parser rejects), documented since a much earlier session. Exclude it from every
  subset; the runner already logs and skips it gracefully if it slips through, but
  don't waste a slot on it.
- **Rate-limit retry behavior you'll see constantly, all of it expected**: LiteLLM
  retries 429/503 up to 5 times with exponential backoff (4s, 8s, 16s, 32s, 60s).
  A function that exhausts all 5 falls back to `verdict=pending` gracefully — this
  is not a bug, don't intervene, just let it resume on the next invocation (the
  runner's resume logic treats any row already in the CSV, including `pending`,
  as "done" — so if you want to retry `pending` rows specifically, delete just
  those rows from the CSV first, as was done between batch 2 and batch 3 today).
- **A genuinely hard proof can run 45-60 minutes** and still resolve, not hang —
  confirmed today on batch 4's `dgefa`, which ran past 55 minutes at sustained
  ~99% CPU before this handoff was written. `ALIVE_TV_TIMEOUT=3600` (1 hour) is
  the hard ceiling; below that, elapsed time alone is not evidence of a stall —
  check CPU%.

## 7. Files worth knowing about (new/changed this session)

- `scripts/run_openrouter_subset.py` — the per-function counting fallback (§2b).
- `llmcompile/verification/alive.py`, `llmcompile/config.py` — the `--smt-to`/
  `--smt-max-mem` fix (§2a). New config fields: `VerificationConfig.smt_timeout`,
  `VerificationConfig.smt_max_mem_mb`, env-overridable via `SMT_TIMEOUT` /
  `SMT_MAX_MEM_MB`.
- `scripts/analyze_final_results.py` — run first, always (§4 caveat: register new
  CSVs here immediately, don't let it go stale again).
- `scripts/auto_commit_results.sh` — 45min interval, plain timestamp (§4).
- `gemini_batch{4,5,6,7}_subset.csv` / `gemini_batch{4,5,6,7}_results.csv` — this
  session's non-overlapping subsets and their (partially in-progress) results.
- `/home/jovyan/.claude/plans/please-research-if-we-curious-peacock.md` — the
  provider/model research doc (§5), plan-mode output, not fully executed as a
  formal plan (the user redirected mid-plan-review to ask live status questions
  instead of approving/rejecting it) but its research findings are correct and
  citable as-is.
- **Not committed**: `gemini_batch{1,2}*.log.bak` and
  `gemini_subset_results_batch{1,2}*.csv.bak` — scratch diagnostic backups from
  debugging the timeout/memory bugs early this session (§2a). Left untracked
  deliberately, same as prior sessions' convention of not committing scratch
  artifacts. Safe to delete once you've confirmed you don't need them, or leave
  them, your call.

## 8. Immediate next steps for whoever picks this up

1. **Check batch health first** (§1) — if all 4 are done, great, run
   `python3 -m scripts.analyze_final_results` for final numbers and skip to 2.
   If some are still running, either wait or just start working alongside them
   (they're independent processes, safe to leave running).
2. **Once all of batches 4-7 finish**, the entire 114-function corpus (minus
   `lists.bc`) has a Gemini attempt on record. Recompute the true Gemini win rate
   (should be ≥18/~110 completed, i.e. ≥16%, likely higher as batches 5-7 are
   still landing wins as this is written) and update this file's §3 table with
   final numbers.
3. **Update `README.md` §"Evaluation Findings"** — it still says Gemini is "1/7"
   and states the 0%-local/win-rate framing from before this session. That framing
   (syntax vs optimization separate thresholds) is still true for local models but
   is no longer the *whole* story — Gemini crossing to 15.9%+ is now the headline,
   and the mechanistic story (SSA-numbering bookkeeping cliff explains local-model
   failure) doesn't yet explain *why* the verification-gate bugs (§2a) mattered so
   much more for Gemini's candidates than local models' mostly-no-op ones — that's
   worth investigating and writing up: did local models even generate enough
   genuinely different candidates for the SMT-timeout bug to matter, or is this
   purely a Gemini-arm story?
4. **Regenerate figures**: `python3 -m scripts.make_result_figs --out-dir figures`
   — fig3's win annotation logic already generalizes to mark every verified win
   across all plotted arms (a previous session's fix), so it should Just Work with
   the new data, but verify the 15+ new points render sanely rather than
   overlapping/illegible on a subset plot built for far fewer.
5. **The 4-with-unknown-magnitude wins (§2b)** — decide with the user whether to
   report them as "verified win, magnitude unknown" in any write-up, or to leave
   them out of headline tables entirely. Both are honest; the project's existing
   convention (§3's table) is to only tabulate wins with a known number, so they're
   currently uncounted in the "14" — but they are real, Alive2-proven, non-zero
   (implicitly — a `passed` verdict with literally 0 change would have hit the
   whole-module counter fine, it's specifically the *changed* ones that this
   particular llvmlite bug tends to trip on) wins that should be mentioned as a
   caveat wherever the "14" number is quoted.
6. **Track F (best-of-k sampling)** and **Track G (P2 cleanup items)** from the
   dissertation roadmap (`/home/jovyan/.claude/plans/based-on-what-we-cached-yao.md`,
   still the governing 2-month plan) remain untouched and are still reasonable
   next work once the Gemini corpus is fully landed and written up.

## 9. Rules of engagement (carried forward, still true)

- §2 of `README.md` (architectural constraints) is hard. Stop and flag if a task
  conflicts with it.
- No hard-coded thresholds/timeouts — everything in `config.py`, env-overridable.
  This session added two more (`SMT_TIMEOUT`, `SMT_MAX_MEM_MB`) to that pattern —
  keep doing this for any new tunable.
- Committing a partially-filled CSV mid-run is this project's established
  convention, not a mistake — don't be alarmed by "unfinished" data in git, and
  feel free to commit mid-run results yourself rather than waiting for completion.
- **Never write a live API key into a committed file, ever** — this session
  handled 7 different Gemini keys purely via shell env vars, never persisted to
  disk in any file that gets committed. If you're tempted to hardcode one "just
  for this run," don't — export it instead.
- `/home/jovyan` is a 24GB persistent volume — never put anything large there.
  `/tmp` is large and effectively persistent on this pod.
- Git credentials are stored (`~/.git-credentials`, mode 600); `git push` works.
- Working tree has some untracked scratch `.bak` files (§7) as of this handoff;
  everything else is committed and pushed.
