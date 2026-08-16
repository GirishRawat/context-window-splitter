# Agent Handoff — 2026-08-16/17 session

**To the next agent**: this replaces the previous (stale, A40-GPU-toolchain-era)
version of this file entirely. That session's toolchain work all still holds
(Ollama, Alive2, `llvm_toolchain` paths — nothing there changed). This session
built on top of it: fixed three silent-crash bugs in the eval runner, ran and
completed several diagnostic evals, found a real mechanistic result, corrected
misleading README claims, fixed two pre-existing test failures, and queued an
overnight chain of runs that should be finishing or finished by the time you
read this. **Three background processes are intentionally still running** —
see §1. Do not kill them without reading why first.

For the fast version of "what happened while I slept," read `MORNING.md`
instead — it's the wake-up checklist. This file is the full technical record.

## 0. Environment identity (unchanged from prior session, still true)

JupyterHub pod (QMUL, `jhub-qmul`), NVIDIA A40. `/home/jovyan` is a small 24GB
persistent volume — **never** put anything large there. `/tmp` (overlay,
~893GB) is large and ephemeral. Ollama binary lives under a previous session's
scratchpad path:
`/tmp/claude-1000755250/-home-jovyan/ab0ec1f0-ef52-46f1-a31d-caba1a12f3d1/scratchpad/ollama-run/bin/ollama`
— it and the server it started have survived across multiple sessions on this
pod, so `/tmp` at that base path is apparently persistent here, not
session-scoped. `llvm-as`/`opt`/`clang` are at
`~/llvm_toolchain/llvm-project/llvm/build/bin` (put on `PATH` explicitly —
`config.py` auto-resolves `llvm-as`/`alive-tv`/`opt` paths but the runner
scripts still shell out to bare `clang`, which needs `PATH`). `alive-tv` is at
`~/llvm_toolchain/alive2/build/alive-tv`.

## 1. Processes intentionally left running — DO NOT KILL without reading this

```
PID 12607  python3 -m scripts.run_openrouter_subset ... full_corpus_subset.csv ...  (32b full-corpus eval)
PID 13566  bash ./scripts/overnight_chain.sh 12607                                   (waits for 12607, then chains 3b arms)
PID 13689  bash ./scripts/auto_commit_results.sh 1800                                (checkpoints *_results.csv to git every 30 min)
```

Check them with `ps -p 12607,13566,13689 -o pid,etime,cmd`. If any are gone,
that's expected once the chain completes — see §3 for what "done" looks like.

**`scripts/auto_commit_results.sh`** is a scoped auto-commit loop (only ever
stages `*_results.csv`, never `git add .`) — leave it running for any future
long unattended eval; it already proved itself this session (commit `f0afbf2`
landed while I was mid-commit of the same file and won the race harmlessly).

## 2. TL;DR — what this session actually found

The single most important number in the whole project, verified this session:
**across 436 completed real-code attempts (before tonight's runs), exactly ONE
verified non-zero instruction reduction has ever occurred** —
`fpcmp.bc::diff_file`, 60.67%, `gemini-3.5-flash`. Every other proven-correct
candidate, across every local model at every scale, is a 0.00% no-op.

But scale is not *useless* — it fixes IR syntactic competence even though it
never fixes optimisation:

| model | syntax_fail rate (of completed) | wins |
|---|---|---|
| qwen2.5-coder:3b | 67.6% | 0 |
| qwen2.5-coder:7b | 36.1% | 0 |
| qwen2.5-coder:32b | 15% (n=13, low-powered — tonight's run fixes this) | 0 |
| gemini-3.5-flash | 0% (n=7) | **1 (14.3%)** |

**Syntactic competence and optimisation ability are separate thresholds.**
Local models cross the first and not the second; Gemini crosses both. That's
the thesis framing this session settled on (see `/home/jovyan/.claude/plans/based-on-what-we-cached-yao.md`
for the full 2-month plan and rationale).

**Why the syntax failures happen**: 91% of `qwen2.5-coder:3b`'s syntax failures
are SSA value-numbering incoherence — the model can't track its own implicit
unnamed-value counter (`%1, %2, …`) across a long body, producing e.g.
`%190 = getelementptr ..., i64 %190` (using its own not-yet-defined number as
an operand). See `scripts/categorize_syntax_failures.py` and
`SYNTAX_FAILURE_DIAGNOSIS.md`.

**Causal test of that (the instnamer experiment, `INSTNAMER_EXPERIMENT.md`)**:
naming every SSA value (`opt -passes=instnamer`, count-neutral, verified)
dropped the syntax-failure rate 67.6% → 51.4%, but at **p=0.22** — not
significant at n≈35/arm. More interesting than the headline number: the
*failure mode relocated* rather than disappearing. `SSA_REUSE` (name
collisions) went 0 → 2 and `UNDECLARED_REFERENCE` rose 13% → 22%. Removing the
numeric counter didn't stop the model losing track of identifiers; it changed
*how* it loses track. That argues the deficit is identifier bookkeeping in
general, not the counter specifically — rules out the cheap fix, motivates
grammar-constrained decoding or an IR-native model instead. **Tonight's
overnight chain runs both arms over the full 114-function corpus specifically
to get this to statistical significance** (~150/arm needed; full corpus gets
each arm to ~100, ~135 pooled with the subset data).

## 3. What the overnight chain is doing and how to tell if it's done

`scripts/overnight_chain.sh` (started ~22:52 UTC) runs, **in order**, waiting
for each to finish before starting the next (GPU is single-tenant — Ollama
serializes generation, so concurrent jobs queue and can timeout each other;
this bit us twice this session before the fix):

1. **32b full-corpus** (PID 12607, already running when I set this up) →
   `qwen32b_full_corpus_results.csv`, 114 functions, ~7-8h estimated.
2. **3b full-corpus baseline** → `qwen3b_full_corpus_results.csv`.
3. **3b full-corpus instnamed** → `qwen3b_full_corpus_instnamed_results.csv`.

Check `overnight_chain.log` for `START`/`END` markers per arm and a final
`ALL OVERNIGHT ARMS COMPLETE` line. Every arm resumes from its own CSV via the
runner's built-in `(file_name, function_name)` completed-set logic, so if you
find it partway through any arm, just re-run the same command (see the script)
to continue — nothing is lost.

**First thing to check**: the `pending` rate on the 32b run. It was 0% through
17/114 when I left. If it's climbed above ~10% by the time you read this, the
timeout needs raising further and that arm should be considered unreliable
until redone — a run that's a third `pending` is not a usable result (this is
exactly what killed the *original* 32b subset run's credibility, fixed this
session, see §5).

## 4. Bugs found and fixed this session (all committed, `bf9cd9f` and earlier)

Three distinct silent-crash bugs in `scripts/run_openrouter_subset.py`, all
now guarded with try/except so one bad file/function can't kill a multi-hour
run (matching the pre-existing clang-emit-llvm guard):

1. **Phase 6 module-reassembly numbering bug** (commit `0be3e3a`) — a `PASSED`
   candidate's body, once stitched into the full multi-function module, can
   fail llvmlite's re-parse (`label expected to be numbered 'N'`) even though
   `llvm-as` accepted it standalone. Reproduced on `queens.bc::main`.
   **Contained but not root-caused** — it's a metrics-harness bug (breaks
   instruction counting), not a correctness-gate bug (Alive2 already proved
   the refinement independently in Phase 5). Someone should eventually look at
   how `p6_assemble.py` substitutes `record.llm_output` into the full module.
2. **Timeout clipping** (commit `db4a7f8`) — `local_gpu` LLM-call timeout was
   300s while real latencies average 234s with a 297s max; raised to 600s
   (900s for the full-corpus arm). `alive_tv_timeout` raised 30s→120s since the
   local-model runs had never actually given Alive2 real proof work (every
   pass was a no-op) so the tight timeout was never exercised — a model that
   returns *genuinely different* IR needs real SMT budget. Both are now
   env-overridable (`LLM_TIMEOUT_SECONDS`, `ALIVE_TV_TIMEOUT`,
   `LLVM_AS_TIMEOUT`).
3. **`lists.bc` Phase 1 parse failure** (commit `a59b5ad`) — clang emits a
   newer-LLVM-only attribute (`dead_on_unwind writable sret(...)`) via a
   libc++ call that llvmlite 0.43/LLVM-14 can't parse. Now skipped and logged
   rather than crashing. `lists.bc::test_lists` is therefore permanently
   unreachable on this host; 39/40 (subset) or 114/115 (full corpus, effectively;
   see below) is the ceiling, not 40 or 115.

Also added `--max-functions N` (commit `db4a7f8`) for rate-limited-backend
batching, validated end-to-end (exact row counts, no duplicate resume, budget
trimmed *before* routing so a rate-limited backend never spends quota on
discarded candidates).

## 5. Two pre-existing test failures fixed (commit `bf9cd9f`)

Both handoffs (this one's predecessor included) flagged
`test_end_to_end_all_pass_is_identity` and `test_end_to_end_triage_mix` as
"looks like a genuine bug, needs attention" and left them alone. **Not a
pipeline bug.** All four identity-transform mocks in the test suite read
`messages[1]` to recover "the user's prompt" — correct when written, but
`p3_route.py`'s prompt gained a one-shot example since (`messages` is now
`[system, example_user, example_assistant, user, (assistant_prefill)]`), so
index 1 was the hardcoded `@max` example, not the function under test. Every
"identity" mock was silently echoing `@max` back for every function — which is
exactly the double-`define` garbage that showed up in the parse error. Fixed
to read the last `role=="user"` message and correctly account for the chat
path's assistant-prefill contract. **Full suite: 64 passed, 0 failed**,
verified deterministic across repeated runs.

## 6. What's still blocked on the user: the Gemini arm

Highest-value remaining experiment, needs `GEMINI_API_KEY`. Tooling is built
and tested (`--max-functions`, validated this session). Command is in
`MORNING.md` — two batches of 20 (free tier's daily cap), one per day. Why it
matters: Gemini is the only model that's ever produced a verified win (1/8
completed attempts); this turns that into a real hit-rate with n=40.

## 7. Files worth knowing about (created/rewritten this session)

- `scripts/analyze_final_results.py` — the aggregate numbers script. Run this
  first in any future session; it self-updates as new CSVs land.
- `scripts/categorize_syntax_failures.py` — syntax-failure taxonomy, refined
  this session from guessed patterns (87% OTHER) to observed ones (0% OTHER).
- `scripts/make_result_figs.py` — 3 dissertation figures, portable paths
  (replaces the Mac-hardcoded `make_paper_figs.py`). Regenerate after any new
  eval data lands.
- `scripts/prep_instnamer_corpus.py`, `INSTNAMER_EXPERIMENT.md` — the causal
  experiment and its write-up.
- `scripts/make_full_corpus_subset.py` — generates `full_corpus_subset.csv`
  (114 routed functions across 24 usable files).
- `scripts/launch_32b_full_corpus.sh`, `scripts/overnight_chain.sh` — the
  gated/chained launchers described in §3.
- `scripts/auto_commit_results.sh` — the checkpoint loop, §1.
- `MORNING.md` — wake-up briefing (may be stale by the time you read this if
  the user already read it; feel free to overwrite with a fresh status).
- `/home/jovyan/.claude/plans/based-on-what-we-cached-yao.md` — the full
  2-month dissertation strategy (Tracks A–G), written in plan mode with the
  user's explicit sign-off. Track A (Gemini) and Track E (32b full corpus,
  in progress) are P0. Read this before proposing new work — it's the agreed
  roadmap, not just notes.
- `README.md` §"Evaluation Findings" — corrected this session (was citing a
  7-function toy result as if it were a corpus result; now separates them and
  states the real numbers, regenerable via `analyze_final_results.py`).

## 8. Rules of engagement (carried forward, still true)

- §2 of `README.md` (architectural constraints) is hard. Stop and flag if a
  task conflicts with it.
- No hard-coded thresholds/timeouts — everything in `config.py`,
  env-overridable.
- Every CSV committed as a checkpoint mid-run is intentional and matches this
  project's established convention (see commit history) — don't be alarmed by
  "unfinished" data in a committed CSV; that's normal here.
- Git credentials are stored (`~/.git-credentials`, mode 600) — `git push`
  should just work.
