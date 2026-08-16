# Agent Handoff: Local-GPU Frontier Model Eval on JupyterHub

**To the agent picking this up**: you are starting fresh on a JupyterHub instance
with an idle NVIDIA A40 (46GB VRAM). Read this fully before doing anything —
it explains why you're here and exactly what to run.

## 1. Project in one paragraph

This is Girish's MSc dissertation project: a deterministic 6-phase pipeline
(`llmcompile/`) that uses an LLM as an untrusted oracle to optimize LLVM IR,
gated by the Alive2/Z3 formal verifier (`alive-tv`). A function is only kept
if Alive2 *proves* the LLM's rewrite is a semantics-preserving refinement of
the `-O0` original; otherwise it falls back to the untouched original. Read
`README.md` for the full architecture (`parse -> triage -> route ->
reconstruct -> verify -> assemble`).

## 2. What's already been established (don't re-derive these)

- **Local small models produce nothing.** Qwen2.5-Coder 3B/7B via Ollama, run
  over the full 387-function routed corpus: 0 real optimizations. The ~26
  "passed" verdicts were all 0.0% reduction (the model just echoed the input
  under the signature-prefill prompting scheme).
- **The verifier itself was fixed already.** Alive2 couldn't originally
  translate `!tbaa` metadata that Clang attaches even at `-O0`, causing a
  false 0% ceiling from verifier rejection, not model failure. This is fixed
  in `spec_runner.py`'s normalization step (strips `!tbaa`/`!range`/etc
  before parsing). Do not re-diagnose this if you see it mentioned in logs —
  it's resolved.
- **One frontier model has already broken the 0% ceiling.** Google
  Gemini 3.5 Flash, on `fpcmp.bc`'s `diff_file` function: 328 -> 129
  instructions, **60.67% reduction, verdict `passed`** (formally verified,
  confirmed by manually inspecting the candidate IR in
  `scratch/raw_output_diff_file.txt` — it's a real algorithmic rewrite, not
  an artifact). This is the one existence proof that a stronger model *can*
  do this; the open question is whether it's repeatable at any real rate.
- **Cloud free tiers are impractical for volume.** Gemini's free tier is
  capped at 20 requests/DAY (not just per-minute) and the eval died mid-run
  after exhausting it. OpenRouter's free tier (50 req/day, 20 req/min) was
  tried next with two models
  (`nvidia/nemotron-3-ultra-550b-a55b:free`, `cohere/north-mini-code:free`);
  both were technically working but took **10-20+ minutes per single
  request** even for OpenRouter's own configured timeout of 120s (never
  fired — litellm/httpx doesn't seem to enforce it against OpenRouter's
  connection-holding behavior). At that rate a 40-function sample would take
  many hours. Both had 0% reduction on every function that returned so far
  (through `decode_rs`, `Puzzle`, `main`, `execute_target_process`,
  `monitor_child_process`, `compdecomp` on Nemotron; `decode_rs` on
  north-mini-code) — inconclusive due to tiny sample, not a negative result.

**This is why you're on the A40**: no rate limits, no queueing, and a much
larger model (32B vs the local 3B/7B) than what's already been ruled out.

## 3. Your task

Run the same curated 40-function sample against a real local model on the
GPU, to see whether a bigger *local* model can reproduce (or beat) the
Gemini `diff_file` result at a rate that's actually usable for the
dissertation's eval numbers.

The repo already has everything wired up:

- `llmcompile/config.py` has an `LLM_BACKEND=local_gpu` option (routes to
  `ollama/qwen2.5-coder:32b` by default via the existing raw-HTTP Ollama
  path in `p3_route.py` — same code path already proven on the 3B/7B runs,
  just pointed at a bigger model). Override the model with `OLLAMA_MODEL` if
  you want to try something else that fits in 46GB (e.g. a 4-bit quant of a
  larger model).
- `target_subset.csv` — the 40 selected functions (complexity 10-59,
  deduplicated against near-identical C++ template instantiations, spread
  across 25 distinct files so no single file dominates).
- `eval_subset_corpus/` — just the 25 `.bc` files those 40 functions live in
  (620KB), so you do NOT need to rebuild the full llvm-test-suite corpus.
  Point `--build-dir` at this folder, not `build/`.
- `scripts/run_openrouter_subset.py` — despite the name, this is backend
  agnostic (it just runs the standard pipeline phases with everything
  outside the target list forced to `triaged_out=True` so API/compute is
  only spent on the 40 selected functions). Reuse it as-is.

## 4. Exact commands

```bash
git pull

# Install Ollama if not already present. If this container has no root/sudo
# and the install script fails, stop and report back rather than trying to
# work around it -- there's a vLLM fallback path to wire up instead, but it
# needs different config.py plumbing (OpenAI-compatible endpoint, not the
# ollama/ raw-HTTP path).
curl -fsSL https://ollama.com/install.sh | sh
ollama serve &

ollama pull qwen2.5-coder:32b   # ~20GB download, fits the A40's 46GB easily

# Sanity check before spending the real run:
nvidia-smi   # confirm VRAM actually gets used
ollama run qwen2.5-coder:32b "say hi"

export LLM_BACKEND=local_gpu
python -m scripts.run_openrouter_subset \
    --build-dir eval_subset_corpus \
    --subset target_subset.csv \
    --output-csv qwen32b_subset_results.csv
```

Also confirm the verification toolchain resolves correctly before the run —
`config.py`'s `VerificationConfig.__post_init__` auto-detects
`llvm_as`/`alive-tv`/`opt` under `/home/jovyan/llvm_toolchain/...` if it
exists on this host. If it's missing, `llvm-as`/`alive-tv` calls will fail
closed (every function falls back to original, verdict stays `pending` —
not a crash, but useless results) — check `README.md`'s toolchain build
instructions if so.

## 5. What "done" looks like

Report back (to Girish, not by editing this handoff file):
- How many of the 40 functions got a `passed` verdict with `reduction_pct >
  0` (the actual thing we're testing for — the local Ollama runs and
  cloud-free-tier runs both got a 0.0% rate here so far, one exception:
  Gemini's `diff_file` at 60.67%, outside this specific 40-function sample).
- Wall-clock time for the whole 40-function run, so we know if local-GPU
  throughput is actually viable for scaling this up to the full 387-function
  corpus afterward.
- Anything that looks like a real regression from the pipeline itself (vs. a
  genuine model limitation) — e.g. if verification keeps returning
  `unsupported` in a way that smells like another verifier gap rather than
  the model failing.

Do not modify `openrouter_subset_results.csv` or `northminicode_subset_results.csv`
(the parallel OpenRouter runs, possibly still finishing on a different
machine) — write only to `qwen32b_subset_results.csv`.
