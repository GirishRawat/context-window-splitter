# Syntax-Failure Diagnosis: Plan & Status

**To the next agent (human or AI) picking this up**: this doc explains why
`syntax_fail` dominates the verdict distribution, why the raw diagnostic text
for it doesn't exist yet, and the plan to fix that and categorize the real
failure modes. Read this before re-deriving any of it.

## Why this exists

Across the historical 387-function routed corpus (`new_spec_results.csv`),
the verdict breakdown is:

| verdict | count | share |
|---|---|---|
| pending (call failed/timeout) | 185 | 47.8% |
| **syntax_fail** | **122** | **31.5%** |
| error | 34 | 8.8% |
| passed (all 0.0% reduction) | 26 | 6.7% |
| unsupported | 15 | 3.9% |
| rejected | 5 | 1.3% |

Only 5 functions were ever `rejected` by Alive2 — the model almost never
produces semantically-wrong-but-valid IR. It produces **unparseable** IR.
The bottleneck is IR syntax/SSA competence, not optimization reasoning. That
makes `syntax_fail` the single highest-leverage thing to understand: is it
truncation (a context/length problem, fixed by a bigger budget), hallucinated
references (undeclared globals/SSA values), or garbled syntax entirely (a
model-capability problem, pointing toward an IR-native model or
grammar-constrained decoding)?

## The blocking problem (confirmed firsthand, not theoretical)

Nobody ever persisted the diagnostic text needed to answer that question:

- `check_syntax()` (`llmcompile/verification/alive.py:19-52`) runs `llvm-as`,
  captures its stderr, and **discards it** — returns a bare `bool`.
- Ollama's response carries a `done_reason` field (`"stop"` vs `"length"` —
  a direct, zero-parsing truncation signal). It's extracted into a local var
  `finish_reason` at `p3_route.py:359` but only ever written into a scratch
  debug dump, never onto `FunctionRecord` or into any CSV.
- The one place raw LLM text hits disk, `scratch/raw_output_{name}.txt`
  (`p3_route.py:364`), is keyed by function name only (collides/overwrites
  across files and runs) and is gitignored.
- **The original 122 raw outputs are gone.** They were never persisted, and
  the full SPEC/llvm-test-suite build dir that produced them isn't on this
  host (gitignored, Mac-only) — only 20 of the 51 implicated files exist
  locally, inside `eval_subset_corpus_sanitized/`.

I confirmed the reconstruction mechanism itself works by live-replaying one
of the 7 leftover `scratch/raw_output_*.txt` files
(`raw_output_decode_rs.txt`) through the real pipeline path
(`sanitize_llm_output` → `replace_function_body` → `llvm-as`) and got a real,
informative error: `use of undefined value '@alpha_to'` — a missing global
reference, not truncation (`finish_reason` for that sample was `stop`, i.e.
the model completed normally and still produced broken IR). So the mechanism
is right; only persistence was missing. Don't re-diagnose this — it's
resolved as "add instrumentation, then regenerate a sample," not "the
approach doesn't work."

## The plan

### 1. Instrument the pipeline to persist diagnostics (small, durable fix)

- `llmcompile/models.py`: add `syntax_error: str | None = None` (populated
  only on `SYNTAX_FAIL`) and `finish_reason: str | None = None` (populated on
  every LLM call) to `FunctionRecord`.
- `llmcompile/verification/alive.py`: change `check_syntax()` to return
  `tuple[bool, str | None]` instead of a bare `bool`, capturing
  `result.stderr` (fall back to `stdout` if empty). Thread a diagnostic
  string through the `FileNotFoundError`/`TimeoutExpired`/generic-exception
  branches too so every `SYNTAX_FAIL` has *something* explaining it.
- `llmcompile/phases/p5_verify.py`: unpack the tuple, set
  `record.syntax_error = err` alongside `Verdict.SYNTAX_FAIL`.
- `llmcompile/phases/p3_route.py`: set `record.finish_reason = finish_reason`
  after it's read (Ollama path ~line 359; check the Gemini/OpenRouter path's
  analogous field too). Leave the scratch dump as-is.
- Tests: extend `llmcompile/tests/test_p5_verify.py` and
  `llmcompile/tests/test_p3_route.py`, following the existing
  `@patch("subprocess.run")` + `MagicMock(returncode=..., stdout=...,
  stderr=...)` convention already used in this repo. No `conftest.py` exists
  — keep fixtures local to each test file like every other test module does.

### 2. Regenerate a real, categorizable sample

- Pull `qwen2.5-coder:3b` and `qwen2.5-coder:7b` via Ollama (the model class
  that actually produced the historical 122 failures — **not** the `:32b`
  used for the separate A40 headroom eval in `qwen32b_subset_results.csv`).
- Reuse the existing, already-fixed runner unchanged:
  ```
  LLM_BACKEND=local_gpu OLLAMA_MODEL=ollama/qwen2.5-coder:3b \
    python3 -m scripts.run_openrouter_subset \
    --build-dir eval_subset_corpus_sanitized \
    --subset target_subset.csv \
    --output-csv syntax_diag_3b_results.csv
  ```
  (repeat with `:7b` / `syntax_diag_7b_results.csv`). `OLLAMA_MODEL` override
  already exists in `config.py` — no new plumbing needed. This reuses the
  concurrency fix and the apple-m1-stripped corpus already committed.
- This won't reproduce the literal historical 122 (different/smaller sample:
  `target_subset.csv`'s 40 functions across 25 files, 20 overlapping the
  original 51) — it's the same model family and routing logic, which is what
  matters for categorizing *why* failures happen. Say so explicitly in any
  write-up; don't imply it's the same dataset.
- Don't run this concurrently with another eval on the same Ollama instance
  without checking `OLLAMA_MAX_LOADED_MODELS` / GPU headroom.

### 3. Categorization script

New `scripts/categorize_syntax_failures.py`, following this repo's existing
analysis-script convention (`analyze.py`, `make_paper_figs.py`: plain
`csv.DictReader`, print a summary table; a plot is optional).

Bucketing, in priority order:
1. `finish_reason == "length"` → **TRUNCATED** (direct signal, no parsing).
2. Regex over `syntax_error` for the rest: `undefined value` →
   **UNDECLARED_REFERENCE**; `expected type|expected instruction
   opcode|expected '='` → **MALFORMED_SYNTAX**; `multiple definition of` →
   **SSA_REUSE**; `expected top-level entity|unterminated` →
   **STRUCTURAL**; unmatched → **OTHER** (print verbatim for manual review —
   don't force a fit).

Cross-tabulate by model (3b vs 7b) and token bucket.

### 4. Verification

- `python -m pytest llmcompile/tests/test_p5_verify.py
  llmcompile/tests/test_p3_route.py -v`
- Manually spot-check 2-3 classified `syntax_error` strings against their
  bucket to sanity-check the regexes.
- If `finish_reason == "length"` never appears despite the sample skewing
  large (6k-27k tokens), that's itself a finding: it would rule out
  truncation and point squarely at SSA/syntax competence instead.

## Status as of writing

**§1 (instrumentation) is done**, verified, and correct — not yet committed/pushed:
- `llmcompile/models.py`: `FunctionRecord` gained `finish_reason` and `syntax_error`.
- `llmcompile/verification/alive.py`: `check_syntax()` now returns
  `tuple[bool, str | None]` instead of a bare `bool`.
- `llmcompile/phases/p5_verify.py`: unpacks the tuple, sets `record.syntax_error`.
- `llmcompile/phases/p3_route.py`: sets `record.finish_reason` on every LLM call,
  including the exception path (`f"call_error: {e or type(e).__name__}"` — this
  also fixes the earlier empty-message-timeout problem for the `pending` bucket
  for free, since `str(asyncio.TimeoutError())` is `""`).
- `api.py`'s `/api/verify` endpoint call site updated too (there's a second,
  previously-missed `check_syntax()` call there besides `p5_verify.py`'s).
- Tests updated in `llmcompile/tests/test_p5_verify.py` and
  `llmcompile/tests/test_orchestrator.py` (two `@patch(..., return_value=True)`
  mocks needed to become `return_value=(True, None)`).
- Full suite run: `4 failed, 60 passed, 12 skipped`. Verified via `git stash`
  that **all 4 failures pre-exist on unmodified `main`** (2 in
  `test_orchestrator.py` — genuine pre-existing bug, not caused by the tuple
  change, see below; 1 in `test_p4_reconstruct.py`, unrelated; 1 in
  `test_p6_assemble.py::test_compile_to_binary` — environmental, `clang` isn't
  on `PATH` for a bare `pytest` invocation in this pod unless you export
  `~/llvm_toolchain/llvm-project/llvm/build/bin` first). None of these four are
  this task's concern, but they're real and someone should look at them —
  `test_end_to_end_all_pass_is_identity` (`AssertionError`) and
  `test_end_to_end_triage_mix` (`RuntimeError: LLVM IR parsing error`,
  `expected instruction opcode`) both look like a genuine bug in the M1
  identity/triage orchestrator path, not test infra.

**Not started**: §2 (pull `qwen2.5-coder:3b`/`:7b`, re-run against
`eval_subset_corpus_sanitized` with `target_subset.csv`) and §3 (the
`scripts/categorize_syntax_failures.py` bucketing script). Do §2 before §3 —
the categorizer needs real `syntax_error`/`finish_reason` data to bucket, and
none exists yet since this is the first run with the new instrumentation.

Also still uncommitted: the separate `qwen2.5-coder:32b` A40 headroom eval
(`qwen32b_subset_results.csv`) was still running in the background across this
whole session — check its progress/completion independently before touching
that file; it's unrelated to this syntax-failure-diagnosis work.
