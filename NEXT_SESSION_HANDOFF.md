# Agent Handoff — JupyterHub A40 session, 2026-08-16

**To the next agent**: this replaces the previous (stale, Mac/Gemini-era)
version of this file entirely. Everything below happened in one continuous
session on a JupyterHub pod (QMUL, `jhub-qmul`) with an idle NVIDIA A40. Read
this fully before doing anything — several things here look like they'd need
re-diagnosing but are already resolved; re-deriving them wastes time.

## 0. Environment identity (read this first)

This Claude Code session runs **inside the JupyterHub pod itself** (confirmed
via process tree: `claude` ← `bash -l` ← `jupyterhub-singleuser` ← `tini`),
not on the user's laptop. `/home/jovyan` is a small **24GB** persistent
network volume — it was already filled with the user's other coursework/
research before this session and got driven to 100% once by putting Ollama's
model cache there by mistake (recovered, see §1). `/` (overlay, ~893GB) and
everything under `/tmp` is the large, ephemeral, non-persistent filesystem.
**Put anything large (model weights, build scratch) under `/tmp`, never
under `/home/jovyan`.**

## 1. Original task (see `JUPYTERHUB_AGENT_HANDOFF.md`)

Run the curated 40-function sample (`target_subset.csv`) through
`qwen2.5-coder:32b` on this A40 (no rate limits, unlike earlier Gemini/
OpenRouter free-tier attempts), verified by Alive2/Z3, to see whether a
bigger *local* model beats the existing 0%-reduction local (3B/7B) ceiling.

## 2. Toolchain built from scratch this session (nothing worked out of the box)

- **Ollama**: no usable root/sudo in this container (`no new privileges`
  flag blocks `sudo`). Installed user-space: the official `.tgz` URL in the
  old handoff 404s now — Ollama moved to `.tar.zst` — downloaded from GitHub
  releases directly and extracted with `zstd`. Lives under the session
  scratchpad (`/tmp/claude-*/scratchpad/ollama-run/`), **not** `~/ollama`
  (first attempt put it there + the model cache, which filled the 24GB home
  volume to 100%; deleted and relocated). Server runs via `nohup`, model
  `qwen2.5-coder:32b` pulled (19GB). GPU-confirmed working.
- **Alive2 (`alive-tv`)**: the pre-existing build dir referenced a whole
  toolchain (`cmake`, `ninja`, `git`, `ar`/`ranlib`, `z3` headers+lib,
  `cc`/`c++`) at `/opt/conda/bin/*` that no longer exists — this container
  image was evidently reset since that build directory was created (July 3).
  Fixed: `pip install ninja cmake patchelf`, a `z3-solver` PyPI wheel for Z3
  headers+`libz3.so` (had to hand-write `z3_version.h` — the wheel doesn't
  ship one, and it's only used by a CMake version-gate, not real verifier
  logic), symlinked system `git`/`ar`/`ranlib` where the cached CMake config
  expected them.
  - **Genuine version mismatch, not just missing tools**: the checked-out
    Alive2 commit (dated 2026-06) targets newer LLVM attribute APIs
    (`Attribute::Captures`/`Range`/`DeadOnReturn`/`Initializes`/
    `DenormalFPEnv`) that don't exist in the pinned LLVM 18.1.8 (2024-06)
    build. Fixed by checking out Alive2 commit `9b7d1ab5` (2024-04-06), the
    last one before any of those attributes were introduced upstream
    (confirmed via `git log -S` on each attribute name individually).
  - **`opt`/`llvm-as`/`alive-tv` all need `CXXABI_1.3.15`** from libstdc++,
    which neither system libstdc++ (GCC 11, tops at 1.3.13) nor conda's
    provided. Fixed via `conda install -c conda-forge libstdcxx-ng`.
    `opt`/`llvm-as` already had `/opt/conda/lib` in their RPATH from the
    original build; `alive-tv` didn't, so it was `patchelf --set-rpath`'d.
  - Verified for real (not just `--version`): fed `alive-tv` a hand-written
    self-equivalence `.ll`, got a correct "Transformation seems to be
    correct!" verdict.
- **Python deps**: `pip install -r requirements.txt`, but had to pin
  `llvmlite==0.43.0` — unpinned latest (0.49.0) makes `llvm.initialize()` a
  hard error instead of a no-op.
- **`clang`** needed adding to `PATH` from
  `~/llvm_toolchain/llvm-project/llvm/build/bin` (built alongside
  `llvm-as`/`opt` per `build_toolchain.sh`, just wasn't on `PATH`).

## 3. Two real pipeline bugs found and fixed (not environment issues)

### 3a. Corpus compiled on Apple Silicon crashes clang on x86_64

`eval_subset_corpus/*.bc` (all 25 files) carries embedded per-function
`target-cpu="apple-m1"`/ARM64 `target-features` attributes. The pipeline's
`clang -S -emit-llvm` overrides the *module*-level target triple to x86_64
but never strips these *function*-level attributes, so clang's backend
segfaults on at least one file (`timeit.bc`). Confirmed zero actual
`@llvm.aarch64.*` intrinsic calls anywhere in the corpus (just tuning
metadata), so stripping is semantically safe. Fix: sanitized copies of all
25 files written to `eval_subset_corpus_sanitized/` (committed, originals
untouched), plus `scripts/run_openrouter_subset.py` now wraps the
`clang -emit-llvm` call in try/except so one bad file can't kill a
multi-hour run. **Always point `--build-dir` at `eval_subset_corpus_sanitized/`, not the original.**

### 3b. False timeouts from concurrent dispatch to a single-GPU Ollama server

`p3_route.py` gave each routing tier (`fast`/`mid`/`frontier`) its own
`asyncio.Semaphore`. For the `local_gpu` backend all three tiers point at
the *same* Ollama model, but Ollama serializes generation
(`OLLAMA_NUM_PARALLEL=1`, one GPU). Two functions landing in different tiers
fired concurrently; the one Ollama queued behind the other could exhaust its
client-side 300s timeout before generation even started — surfacing as a
bare `asyncio.TimeoutError` (empty message, since `str(TimeoutError())` is
`""`) that looked like a model failure but was harness-induced. **Caught
this live**: watched `main`'s call fail with the empty-message signature
*while* `execute_target_process` (same file, dispatched concurrently) was
still generating. Fix: tiers bound to the same `ollama/` model now share one
semaphore (`p3_route.py`, `_route_module_async`), so calls serialize
client-side — no real throughput cost, since the server was serializing
anyway. Cloud backends (`gemini/`, `openrouter/`) unaffected — verified they
still get independent per-tier semaphores. Note `global_max_concurrent` in
`config.py` is **dead config**, defined but never read anywhere — don't
reach for it as the fix.

**My own mistake worth flagging**: mid-session I deleted the results CSV
believing it held 2 rows when it actually held 19 (a stale, buffered log
read misled me). A `cp` backup ran first so nothing was lost, but don't
trust a lagging log over the CSV itself — the CSV is flushed per-row, the
log was block-buffered. Fixed by adding `PYTHONUNBUFFERED=1` to the launch
command going forward.

## 4. Git / GitHub push

No `gh` CLI, no SSH key, no credential helper existed in this pod. Set up
`git config --global credential.helper store` + `git credential approve`
with a user-supplied fine-grained PAT (their first token lacked the
`Contents: Read and write` permission — 403'd; second token worked). The
credential is **stored persistently** in `~/.git-credentials` (mode 600) —
future pushes in this pod should just work without re-prompting for a token,
unless the token expires/is revoked.

Local git identity is set (`user.name`/`user.email`, repo-local not
`--global`) to match the existing commit author convention in this repo.

**Commit `62be838`** ("Fix Ollama concurrency false-timeouts and sanitize
corpus for x86_64") is pushed to `origin/main`. It contains: the concurrency
fix, the sanitized corpus, the try/except resiliency patch, and a mid-run
checkpoint of `qwen32b_subset_results.csv`.

**Not yet committed** (git status shows these modified/untracked as of this
handoff): `api.py`, `llmcompile/models.py`, `llmcompile/phases/p3_route.py`,
`llmcompile/phases/p5_verify.py`, `llmcompile/tests/test_orchestrator.py`,
`llmcompile/tests/test_p5_verify.py`, `llmcompile/verification/alive.py`,
`qwen32b_subset_results.csv` (further progress), and the new
`SYNTAX_FAILURE_DIAGNOSIS.md` — **this session pushed these before ending,
see the final commit on `origin/main` for the actual state; if you don't see
it there, something went wrong and you should commit+push them yourself
following the pattern of commit `62be838`.**

## 5. Strategy discussion — where the project actually stands

Mined all historical result CSVs before writing new code. Key findings, in
case anyone re-litigates:

- The README's headline "78% verified reduction" claim
  (`eval_results.csv`) is from **7 hand-written toy functions**
  (complexity 1-3, ~600 tokens) — not representative of the real corpus
  (complexity 10-59, 6k-27k tokens). Don't cite it as a corpus result.
- Across the 387-function routed corpus (`new_spec_results.csv`): only 5
  functions were ever Alive2-`rejected` (semantically wrong but syntactically
  valid). **122 (31.5%) were `syntax_fail`** — the model produces unparseable
  IR far more often than it produces wrong-but-valid IR. This is *the*
  bottleneck to understand (see §6).
- Per-function `-O2` **increases** instruction count for 156/244 measured
  functions (aggregate **+22%**, because `-O2` inlines/unrolls
  inter-procedurally, which this project's architecture forbids). The
  `pct_of_o2_gap_closed` column in some CSVs is currently measuring the
  wrong thing — comparing against inter-procedural `-O2` per isolated
  function is apples-to-oranges. The real, available intra-procedural
  headroom (measured directly against a handful of corpus files) is
  **~30-69%**, dominated by `mem2reg` (SSA promotion) — exactly what `-O0`
  code is bloated with, and exactly what the models keep failing at.
- Full list of 8 strategies discussed (ordered by leverage): (1) switch to
  an IR-native model, e.g. Meta's LLM Compiler, already cited in the README
  but never tried; (2) sample k=5-10 times per function instead of one
  greedy draw, keep the best verified one — stays within the architecture's
  "stateless, single-turn" constraint; (3) grammar-constrained decoding
  (GBNF) to eliminate a whole class of syntax failures deterministically;
  (4) a `mem2reg`-canonicalized second arm as an ablation (flagged: this
  deviates from raw `-O0` input, run as an explicit comparison arm, not a
  silent swap); (5) fix the `-O2` baseline metric; (6) raise
  `alive_tv_timeout` from 30s; (7) a stratified complexity sweep across the
  unexplored middle band; (8) **categorize the 122 syntax failures** — this
  is what the rest of this session did, see §6.
- Reframe worth keeping in mind: the dissertation's load-bearing claim
  (100% of invalid/hallucinated output safely caught and fell back) is
  already proven. "Off-the-shelf LLMs can't optimize real `-O0` IR, precisely
  characterized" is a solid result on its own — don't let the thesis depend
  on breaking the 0% ceiling.

## 6. Syntax-failure diagnosis — IN PROGRESS, read `SYNTAX_FAILURE_DIAGNOSIS.md`

Full context, plan, and detailed status live in
**`SYNTAX_FAILURE_DIAGNOSIS.md`** at the repo root — read it before touching
any of `llmcompile/verification/alive.py`, `p5_verify.py`, `p3_route.py`,
or `models.py`. Short version:

- **§1 (instrumentation) is done and tested.** `check_syntax()` now returns
  `(bool, diagnostic_text)` instead of discarding `llvm-as`'s stderr;
  `FunctionRecord` gained `syntax_error` and `finish_reason` fields (the
  latter captures Ollama's `done_reason`/`"length"` — a direct truncation
  signal that was being computed and thrown away before). Full test suite
  run: `4 failed, 60 passed, 12 skipped` — **verified via `git stash` that
  all 4 pre-exist on unmodified `main`**, not caused by this work. Two of
  them (`test_orchestrator.py::test_end_to_end_all_pass_is_identity` and
  `::test_end_to_end_triage_mix`) look like a genuine bug in the M1
  identity/triage path worth someone's attention separately.
- **§2 (not started)**: pull `qwen2.5-coder:3b`/`:7b` (the model class that
  actually produced the historical 122 failures — not the `:32b` used for
  the separate headroom eval) and re-run
  `scripts/run_openrouter_subset.py` with `LLM_BACKEND=local_gpu
  OLLAMA_MODEL=ollama/qwen2.5-coder:3b` against
  `eval_subset_corpus_sanitized`/`target_subset.csv`, to generate real
  `syntax_error`/`finish_reason` data (none exists yet anywhere — the
  original 122 failures' raw output was never persisted and is
  unrecoverable; the full SPEC/llvm-test-suite corpus that produced them
  isn't on this host either, only 20/51 of the implicated files are, inside
  `eval_subset_corpus_sanitized/`).
- **§3 (not started)**: write `scripts/categorize_syntax_failures.py` to
  bucket that data (TRUNCATED via `finish_reason`, UNDECLARED_REFERENCE,
  MALFORMED_SYNTAX, SSA_REUSE, STRUCTURAL, OTHER) — the actual deliverable.

**Do §2 before §3** — there's nothing to categorize yet.

## 7. Separate, still-running background eval — do not confuse with §6

`qwen32b_subset_results.csv` — the *original* task from §1 of this doc, run
via `LLM_BACKEND=local_gpu` against `qwen2.5-coder:32b`. Was still running in
the background (PID 3904 as of this handoff — check if it's still alive,
it's very likely finished or dead by the time you read this) when this
session ended. Check progress with:
```bash
wc -l qwen32b_subset_results.csv   # rows so far, out of 40
tail -n +2 qwen32b_subset_results.csv | awk -F, '{print $8}' | sort | uniq -c
```
As of handoff: 15/40 done (9 pending, 4 unsupported, 2 passed — both passes
at 0.0% reduction, consistent with the existing 3B/7B ceiling, but the
sample is far too small to conclude anything). If it finished, report per
the original handoff's "done" criteria: `passed` count with
`reduction_pct > 0`, total wall-clock time, and whether the `unsupported`
rate (3 of 4 real verdicts were `unsupported` earlier in the run) points at
another verifier gap like the `!tbaa` one already fixed historically.

## 8. If you need to push again

Credentials are already stored (`~/.git-credentials`, mode 600) — `git push`
should just work. If it 403s, the PAT likely expired or lacks `Contents:
Read and write` permission; ask the user for a new one, don't try to work
around it.
