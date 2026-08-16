# Agent Handoff Context (Phase 3: Evaluation Execution)

**To the next AI Agent**: The user has asked me to record the exact state of the workspace and our strategic context so you can pick up flawlessly where we left off. Please read this carefully before taking action.

## 1. Project Background
This project evaluates the ability of LLMs to perform zero-shot LLVM IR optimizations, strictly gated by the `alive-tv` formal verifier. We have a robust multi-phase pipeline (Parse ➡️ Triage ➡️ Route ➡️ Reconstruct ➡️ Verify). The core problem we faced was models failing basic `llvm-as` syntax checks. We fixed this by providing a rigid signature prefill and constraining outputs.

## 2. Completed Local Baseline Eval (The "0% Optimization" Discovery)
* The original local evaluation run using `qwen2.5-coder:3b` and `7b` has completely finished (`new_spec_results.csv`). 
* **The Breakthrough**: Out of 387 routed functions, the local models achieved **26 formally verified `passed` verdicts**. This empirically proves that our pipeline successfully repairs and verifies generated IR!
* **The Bottleneck**: Every single one of those 26 passes resulted in exactly a **0.0% reduction**. The models produced mathematically correct code, but failed to optimize it at all (they just echoed the input or made trivial non-reducing changes). This validates the user's thesis: *local sub-10B models simply lack the reasoning capacity to optimize LLVM IR.*

## 3. The Pivot to Gemini (What We Built Today)
To test if a frontier model can breach the 0.0% reduction barrier, we updated the pipeline to use the Google Gemini free tier.
* We updated `llmcompile/config.py` and `llmcompile/phases/p3_route.py`.
* We added a robust global module-level rate limiter (`_rate_limit_acquire`) utilizing `asyncio.Lock`.
* **Smoke Testing Discovery**: We found that `gemini-2.5-flash` hits brutal 429 quota limits (20 RPM/RPD). We discovered that the only viable models on this specific endpoint/key are the 3.5/2.5 families. We explicitly settled on **`gemini/gemini-3.5-flash`** with a highly restricted `requests_per_minute = 5` and `max_concurrent = 1`.

## 4. CURRENT ACTIVE STATE (CRITICAL! DO NOT KILL!)
We have launched the **Full Gemini Evaluation Run** and it is currently running in the background. 
* **Command**: `./resume_gemini.sh` (Detached via `nohup`)
* **PID**: `12130`
* **Output CSV**: `spec_results_gemini.csv`
* **Pacing**: It is intentionally running at 1 request every 12 seconds (5 RPM) to avoid Google's API bans. It will take ~11+ hours to complete.
* **Mac State**: `caffeinate` is hooked to the PID to keep the Mac awake. **DO NOT KILL THIS PROCESS.** 

## 5. Next Steps for You (The Next Agent)
1. **Check Progress**: When you start, run `wc -l spec_results_gemini.csv` to see how many of the 3,420 functions have finished.
2. **Analyze Results**: If the Gemini run is finished, analyze `spec_results_gemini.csv`. We are desperately looking for any `passed` verdict with a `reduction_pct > 0.0`!
3. **Generate Plots**: Update `scratch/generate_plots.py` (or write a new script) to graph the results comparing the local LLMs vs Gemini, and generate the final figures.
4. **Dissertation**: Help the user integrate these findings into their `dissertation.tex` file.

Good luck!
