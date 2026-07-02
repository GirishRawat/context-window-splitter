# Inference-Time LLM Compilation Orchestration

Optimising LLVM Intermediate Representation (IR) by routing IR functions through Large Language Models as optimisation engines, with **formal verification (Alive2/Z3) guaranteeing correctness** of every accepted transformation.

The output executable is **100% valid by construction**: every function is either a formally-proven refinement of the original, or the untouched `-O0` original itself.

> **For AI agents / future contributors:** Read this entire README before writing code. Section 2 lists inviolable architectural constraints - if a requested change conflicts with them, **stop and flag the conflict rather than silently relaxing it**. Section 9 describes exactly what exists today and what to build next.

---

## 1. What this project is

A deterministic Python state machine that:

1. Parses raw LLVM IR compiled at `-O0` (unoptimised on purpose - maximum optimisation headroom).
2. Extracts every function definition into a self-contained, independently-assemblable unit.
3. Triages functions by cyclomatic complexity and token count.
4. Routes non-trivial functions concurrently to LLMs (frontier → mid-tier → local, by complexity) as **stateless, single-turn text transformations**.
5. Formally verifies each LLM candidate against the original using `llvm-as` (syntax) then `alive-tv` / Alive2 (SMT-based refinement proof via Z3).
6. Assembles the final module: proven-correct optimisations locked in, everything else falls back to the original `-O0` function.

The scientific claim: probabilistic risk exists **only** in the LLM phase and is fully contained by deterministic guardrails around it. LLM output never reaches the final binary unverified.

---

## 2. Architectural constraints (INVIOLABLE)

These define the system's identity. Do not violate them to make a task easier.

- **MUST** be a deterministic Python state machine. Phases run in fixed order; control flow is fully deterministic.
- **MUST** use LLMs strictly as stateless, single-turn, text-in/text-out transformation functions. One IR function in, one candidate out.
- **MUST NOT** introduce agents, cross-call memory, conversational loops, retries-with-feedback, model tool-use, or autonomous behaviour. The LLM never sees its own prior outputs.
- **MUST** confine all non-determinism to Phase 3. Phases 1, 2, 4, 5, 6 are deterministic and must produce identical outputs for identical inputs.
- **MUST** chunk IR at **function granularity** - never basic-block granularity. Basic-block splitting severs use-def chains, destroys liveness information (which depends on the whole CFG), and breaks CFG integrity (branch targets), producing semantically invalid fragments no LLM can reason about.
- **MUST** keep the original parsed module in memory for the entire run. `FunctionRecord.original_ir` is **immutable after Phase 1** - it is the source of truth for the Phase 6 fallback and the reference Phase 5 verifies against.
- **MUST NOT** perform inter-procedural transformations. Each function is optimised and verified in isolation (Alive2 does not support inter-procedural reasoning and may emit spurious counterexamples).
- **MUST** treat anything other than a proven refinement (`REJECTED`, `SYNTAX_FAIL`, `UNSUPPORTED`, timeout) as a failure that routes to fallback. A timeout is **never** a pass.

---

## 3. The six-phase pipeline

| Phase | Nature | What it does |
|---|---|---|
| **1 - Parsing** | deterministic | `llvmlite` ingests `-O0` IR, verifies it, extracts every `define` into a standalone `FunctionRecord`. Module retained in memory. |
| **2 - Triage & profiling** | deterministic | Per function: cyclomatic complexity (from CFG) + token count. Below-threshold functions are `triaged_out` (skip 3–5, pass through unchanged). |
| **3 - LLM execution & routing** | **probabilistic (the only one)** | `asyncio` + LiteLLM fire all calls concurrently. Routing: high complexity / 32k–128k+ tokens → frontier (GPT-4o, Claude 3.5 Sonnet, Qwen 32B); 8k–32k → mid (Llama 3 8B, Qwen 7B); <8k → fast/local (Qwen 3B). Barrier: await slowest response. No validation here. |
| **4 - AST reconstruction** | deterministic | Mechanically substitute LLM candidates into the module; write temp file. **No validation** - that is Phase 5's job. |
| **5 - Verification gate** | deterministic | Sequential: ① `llvm-as` syntax check (cheap filter). ② `alive-tv` refinement proof - source = original, target = candidate; functions paired by name. UNSAT = `PASSED`; SAT = `REJECTED` (+counterexample); undecided/timeout = `UNSUPPORTED`. Pass requires **both** checks. |
| **6 - Fallback assembly** | deterministic | `PASSED` → optimised IR locked in. Anything else → original `-O0` function reinserted from memory. Compile final module to executable. |

### Verification semantics (read before touching Phase 5)

- **Refinement, not symmetric equivalence.** Alive2 proves the target does everything the source does but may be *more* defined (e.g. resolving `undef`). Argument order matters: `alive-tv <original> <candidate>`. Phrase claims as "proven a sound refinement", not "proven equivalent".
- **Bounded verification.** Alive2 unrolls loops up to a bound; discrepancies beyond the bound can be missed. The honest guarantee is "correct up to Alive2's bound" - state this in any write-up.
- **What it catches:** differing return values, memory violations, introduced undefined behaviour (poison/undef), altered side effects.
- **Why `llvm-as` first:** it is a fast, cheap filter; no point running an expensive SMT proof on syntactically broken IR.

---

## 4. Repository structure

```
.
├── README.md                      <- this file
├── TECHNICAL_REQUIREMENTS.md      <- full spec (agent ground truth; keep in sync with this README)
├── llmcompile/
│   ├── __init__.py
│   ├── models.py                  ✅ IMPLEMENTED - FunctionRecord, ParsedModule, Verdict
│   ├── orchestrator.py            ⬜ not yet built - synchronous state machine, phases 1→6
│   ├── config.py                  ⬜ not yet built - thresholds, routing table, tool paths, timeouts
│   ├── phases/
│   │   ├── __init__.py
│   │   ├── p1_parse.py            ✅ IMPLEMENTED - see §9 for design details
│   │   ├── p2_triage.py           ⬜ next up - cyclomatic complexity + token count
│   │   ├── p3_route.py            ⬜ asyncio + LiteLLM dispatch (the ONLY async module)
│   │   ├── p4_reconstruct.py      ⬜ mechanical substitution, temp file
│   │   ├── p5_verify.py           ⬜ llvm-as then alive-tv via subprocess
│   │   └── p6_assemble.py         ⬜ fallback selection + final compile
│   ├── verification/
│   │   └── alive.py               ⬜ subprocess wrappers; parse UNSAT/SAT/unsupported + counterexample
│   ├── eval/
│   │   └── harness.py             ⬜ corpus runner + per-function metrics
│   └── tests/
│       └── test_p1_parse.py       ✅ IMPLEMENTED - 8 tests incl. independent-assemblability proof
```

The orchestrator stays synchronous; only `p3_route.py` is async internally (`asyncio.gather` over records). This keeps "deterministic state machine with one contained probabilistic phase" literally true at the code-structure level.

---

## 5. Data model (`llmcompile/models.py`)

One carrier object flows through every phase, accumulating state:

```python
class Verdict(Enum):
    PENDING     # not yet verified
    PASSED      # llvm-as OK AND alive-tv proved refinement
    REJECTED    # alive-tv found a counterexample (SAT)
    SYNTAX_FAIL # llvm-as rejected the candidate
    UNSUPPORTED # alive-tv undecided / timed out / unsupported construct

@dataclass
class FunctionRecord:
    name: str
    original_ir: str          # Phase 1. Standalone assemblable IR. IMMUTABLE.
    complexity: int | None    # Phase 2
    token_count: int | None   # Phase 2
    triaged_out: bool         # Phase 2
    assigned_model: str|None  # Phase 3
    llm_output: str | None    # Phase 3 (raw candidate)
    verdict: Verdict          # Phase 5
    counterexample: str|None  # Phase 5 (on REJECTED)
    final_ir: str | None      # Phase 6 (optimised if PASSED, else original)

@dataclass
class ParsedModule:           # Phase 1 output; lives for the whole run
    source_ir: str            # canonical full-module text (immutable)
    preamble: str             # shared module-level context
    functions: list[FunctionRecord]
    module_ref: Any           # live llvmlite ModuleRef, retained in memory
```

---

## 6. Toolchain setup

Two independent toolchains - do not conflate them:

**(a) `llvmlite`** (Phase 1/4) - `pip install llvmlite`. Ships its own LLVM used purely for parsing/re-emission. No relation to (b).

**(b) The verification toolchain** (Phase 5) - Z3 + LLVM-from-source + Alive2. This is the project's highest-risk dependency; build and prove it **before** pipeline work (Milestone 0, §8).

```bash
# 1) Z3 with dev headers (e.g. Debian/Ubuntu)
sudo apt install libz3-dev

# 2) LLVM from source - RTTI and EH ON are NON-NEGOTIABLE for Alive2 to link
cd llvm-project/llvm && mkdir build && cd build
cmake -GNinja \
  -DLLVM_ENABLE_RTTI=ON -DLLVM_ENABLE_EH=ON -DBUILD_SHARED_LIBS=ON \
  -DCMAKE_BUILD_TYPE=Release -DLLVM_TARGETS_TO_BUILD=X86 \
  -DLLVM_ENABLE_ASSERTIONS=ON -DLLVM_ENABLE_PROJECTS="llvm;clang" ../llvm
ninja   # slow + RAM-heavy; use a well-resourced machine; RECORD THE COMMIT HASH

# 3) Alive2 against that LLVM
git clone https://github.com/AliveToolkit/alive2.git
cd alive2 && mkdir build && cd build
cmake -GNinja -DCMAKE_BUILD_TYPE=Release \
  -DLLVM_DIR=/path/to/llvm-project/llvm/build/lib/cmake/llvm ..
ninja   # if Z3 not found: -DZ3_INCLUDE_DIR=... -DZ3_LIBRARIES=...
# target binary: build/alive-tv - RECORD THE COMMIT HASH
```

**Version pinning is mandatory.** LLVM (source build), Alive2, Z3, `llvmlite`, and pinned LLM model identifiers all go in a lockfile. Toolchain version mismatch is the single most common failure mode of this kind of project.

A hosted Alive2 exists at `alive2.llvm.org/ce/` for quick concept checks, but with hard restrictions (no function inputs, no memory, no UB dependence, small loops only) - not a substitute for the local build.

**Dev environment note:** development is happening on a university JupyterHub. Engine code stays in `.py` modules (deterministic, testable, agent-editable, diffable); notebooks are thin drivers that import the engine - for exploration, experiments, and dissertation figures only. Never put pipeline state in notebook cells.

---

## 7. Running the tests

```bash
pip install llvmlite pytest
python -m pytest llmcompile/tests/ -v
```

In JupyterHub: `%pip install llvmlite pytest` then `!python -m pytest llmcompile/tests/test_p1_parse.py -v`.

The load-bearing Phase 1 test is `test_each_function_is_independently_assemblable`: every extracted `original_ir` must re-parse and re-verify **on its own**. If that holds, the extraction is sound for Phase 5's needs.

---

## 8. Build order (do NOT build in runtime order 1→6)

De-risk the hard parts first:

- **M0 - Toolchain spike** (no pipeline code). Hand-written IR: `llvm-as` validates; `alive-tv src.ll tgt_good.ll` accepts a legitimate optimisation; `alive-tv src.ll tgt_bad.ll` returns a counterexample. Include the poison case: removing `nsw` = valid refinement, **adding** `nsw` = counterexample (introduces poison on overflow). Exit criterion: good accepted, bad rejected. Pin versions now.
- **M1 - Walking skeleton.** Full deterministic spine with Phase 3 replaced by an **identity transform**. Everything trivially passes Phase 5; proves all plumbing with zero API calls.
- **M2 - Verification gate for real** (build **before** real Phase 3). Hand-written good and bad transforms (dropped side effect, introduced poison, changed return value); assert correct accept/reject. The gate must be trusted before the LLM is connected.
- **M3 - Phases 1 & 2 hardening.** Extraction edge cases (exotic signatures, `-g` debug metadata); real complexity + token metrics. *(Phase 1 core: done - see §9.)*
- **M4 - Phase 3 LLM integration.** One model, fixed prompt, one function first (nail "emit only valid IR, no markdown fences"); then asyncio+LiteLLM concurrency; then routing tiers last.
- **M5 - Evaluation harness.** Per function: instruction count before/after, verdict, model, latency → dissertation results tables.
- **M6 - Hardening.** Concurrency limits, alive-tv timeouts, error handling, reproducibility logging.

---

## 9. Current status & handoff context (read this, future agent)

### What exists and is working

**`llmcompile/models.py`** - `Verdict`, `FunctionRecord`, `ParsedModule` exactly as specified in §5.

**`llmcompile/phases/p1_parse.py`** - Phase 1 complete. Public API:
- `parse_module(ir_text) -> ParsedModule` - parse, `verify()`, extract.
- `parse_module_file(path) -> ParsedModule` - convenience wrapper.
- `summarize(parsed) -> str` - human-readable listing.

Design decisions already made (do not re-litigate without cause):

1. **Canonical-text strategy.** After `llvm.parse_assembly` + `verify()`, extraction works from the *canonical re-emitted text* (`str(mod)`), not the raw input - guarantees the preamble and function bodies are mutually consistent. Definition blocks are `define ...` down to the `}` in column zero (canonical emission guarantees this).
2. **Standalone extraction with sibling declarations.** Each `original_ir` = shared preamble (datalayout, triple, named types, globals, attribute groups, metadata, foreign `declare`s) + a one-line `declare` for every **sibling** definition + this function's full body. So `@use` calling `@add` carries a *declaration* of `@add`, never its body: references resolve, token count stays lean (token budget drives Phase 3 routing), and the LLM can't mangle neighbouring code. Sibling `declare` lines are derived from `define` signatures by stripping the trailing `{`, function-level metadata attachments (`!dbg !N` etc.), and definition-only clauses (`personality`, `prologue`, `prefix`, `gc`, `section`, `comdat`).
3. **Loud failure on mismatch.** The text split is cross-checked against llvmlite's own function enumeration (`mod.functions`, `is_declaration`); any symmetric difference raises rather than silently mis-extracting.
4. **Only `define` becomes a record.** `declare` lines are shared context in the preamble; they are never optimised.
5. **Input validation at the door.** Malformed input IR raises `RuntimeError` in Phase 1 - invalid *input* is caught here; validating *LLM output* is exclusively Phase 5's job.

**`llmcompile/tests/test_p1_parse.py`** - 8 tests over a representative module (global + foreign declare + two definitions with a sibling call). Key assertions: only definitions become records; sibling calls are declared not inlined; every extracted function independently re-parses and re-verifies; invalid IR raises.

### Known limitations (deliberate, deferred to M3)

- `_signature_to_declaration` is best-effort; exotic function signatures may mishandle. The lossless `module_ref` in `ParsedModule` is the fallback source of truth if the text approach hits a wall.
- **Debug metadata (`-g`) is the main edge case**: it creates module-level nodes referencing functions by name, complicating standalone extraction. Current guidance: compile the corpus at `-O0` **without** `-g`. Handle `-g` properly in M3 if needed.
- Complexity/token fields exist on `FunctionRecord` but nothing populates them yet (that is Phase 2).

### What to build next (in order)

1. **`phases/p2_triage.py`** - cyclomatic complexity from the CFG via `module_ref` (per function: sum over blocks of (successor edges) − blocks + 2, or equivalently decision points + 1) and token counting with the tokenizer Phase 3 routing will key on. Populate `complexity`, `token_count`, `triaged_out` (threshold from `config.py` - build a minimal `config.py` alongside).
2. **`verification/alive.py` + `phases/p5_verify.py`** - before Phase 3, per M2. Subprocess wrappers with configurable timeout; parse alive-tv stdout into `PASSED` / `REJECTED` (+counterexample text) / `UNSUPPORTED`. Timeout maps to `UNSUPPORTED`, never `PASSED`.
3. **`orchestrator.py` + identity-transform walking skeleton** (M1) - synchronous, phases in order, Phase 3 stubbed as identity.
4. **`phases/p3_route.py`** - last. Stateless single-turn prompts; deterministic output sanitisation (strip markdown fences/prose) is allowed, semantic "repair" is not; bounded concurrency.

### Rules of engagement for agents

- §2 constraints are hard. If a task conflicts, stop and flag.
- Keep phases in separate modules; keep the orchestrator synchronous; only `p3_route.py` may contain async code.
- Every new phase ships with pytest tests, including determinism tests (identical input → identical output) for deterministic phases.
- No hard-coded thresholds, model names, tool paths, or timeouts - everything configurable via `config.py`; credentials via environment, never committed.
- Do not mutate `original_ir` or `ParsedModule.source_ir` anywhere, ever.

---

## 10. Testing requirements (accumulate as phases land)

- **Toolchain regression** (M0): good transform → accepted; bad transform → counterexample; broken syntax → rejected by `llvm-as`.
- **Phase 5 unit tests**: known-good/known-bad transforms incl. poison-introduction and side-effect-removal cases.
- **Determinism tests**: Phases 1, 2, 4, 5, 6 produce identical output across runs.
- **Fallback test**: a function with deliberately wrong `llm_output` ends with `final_ir == original_ir`.
- **Identity end-to-end** (M1): every function passes; final executable behaves identically to an unoptimised build.

---

## 11. Key literature (positioning)

- **Lopes, Lee, Hur, Liu, Regehr - "Alive2: Bounded Translation Validation for LLVM" (PLDI 2021).** The tool behind Phase 5. "Bounded" is the honest limitation to carry into any claims.
- **Cummins et al. - "Large Language Models for Compiler Optimization" (arXiv:2309.07062).** Closest prior art; fine-tuned 7B model for LLVM pass ordering. Useful datum: ~2 chars/token when encoding LLVM-IR.
- **Cummins et al. - "Meta LLM Compiler" (arXiv:2407.02524).** Foundation models trained on 546B tokens of IR/assembly; candidate Phase 3 models and a natural baseline.
- **Grubisic et al. - "Compiler-generated feedback for LLMs" (arXiv:2403.14714).** The feedback-loop *contrast* to this project's deliberate single-turn design (their measured gain from feedback was small; sampling did better).
- **Sun et al. - "Clover: Closed-loop Verifiable Code Generation" (2024)** and **Councilman et al. (arXiv:2507.13290)** - the "LLM proposes, formal checker disposes" pattern in other domains (Dafny/DSLs).
- **Positioning:** the combination here - inference-time orchestration across multiple off-the-shelf models routed by complexity, with Alive2 as the correctness gate on raw LLVM IR - is not occupied by any single work above. That gap is the contribution.

## 12. Glossary

| Term | Meaning |
|---|---|
| IR | LLVM Intermediate Representation |
| `-O0` | Unoptimised compilation; the system's input |
| Refinement | Target does everything source does, possibly more-defined; the property Alive2 proves |
| Poison / undef | Forms of LLVM undefined behaviour; *introducing* them violates refinement |
| Translation validation | Verifying one specific translation instance, not the optimiser in general |
| Use-def chain | Link between a value's definition and its uses; severed by sub-function chunking |
| Bounded verification | Alive2 unrolls loops to a bound; misses divergence beyond it |
| Walking skeleton | Minimal end-to-end system with the risky part stubbed (identity transform) |