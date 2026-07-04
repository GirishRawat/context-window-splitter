"""End-to-end demo of the FULL local pipeline — no API costs.

Exercises every phase for real:
  P1 parse -> P2 triage -> P3 route to LOCAL Ollama (qwen2.5-coder)
  -> P4 reconstruct -> P5 verify with Alive2/Z3 -> P6 assemble.

Unlike demo_m1.py (whose sample functions are trivial and get triaged out),
this uses a control-flow-heavy function and a low complexity threshold so the
function actually routes to the local LLM and is then formally verified.

Correctness is guaranteed regardless of what the local model emits: any
candidate that Alive2 cannot prove a sound refinement of the original falls
back to the untouched -O0 function (README §2, §6).
"""

import logging

from llmcompile.orchestrator import compile_module, summarize_run
from llmcompile.config import PipelineConfig, TriageConfig

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

# A function with a loop + inner branch: enough cyclomatic complexity to route,
# and enough optimisation headroom (redundant identity ops) for the model to
# have something legal to simplify.
sample_ir = """
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-f80:128-n8:16:32:64-S128"
target triple = "x86_64-pc-linux-gnu"

define i32 @accumulate(i32 %n) {
entry:
  br label %loop.head

loop.head:
  %i = phi i32 [ 0, %entry ], [ %i.next, %loop.cont ]
  %acc = phi i32 [ 0, %entry ], [ %acc.next, %loop.cont ]
  %cond = icmp slt i32 %i, %n
  br i1 %cond, label %loop.body, label %exit

loop.body:
  %isodd = and i32 %i, 1
  %oddcmp = icmp eq i32 %isodd, 1
  br i1 %oddcmp, label %add.odd, label %add.even

add.odd:
  %a1 = add i32 %acc, %i
  br label %loop.cont

add.even:
  %tmp = add i32 %acc, 0
  %a2 = mul i32 %tmp, 1
  br label %loop.cont

loop.cont:
  %acc.next = phi i32 [ %a1, %add.odd ], [ %a2, %add.even ]
  %i.next = add i32 %i, 1
  br label %loop.head

exit:
  ret i32 %acc
}
"""

if __name__ == "__main__":
    print("=" * 48)
    print(" Full LOCAL pipeline demo (Ollama + Alive2) ")
    print("=" * 48)

    # Low threshold so the function routes to the local LLM instead of being
    # triaged out. Everything else uses the default local Ollama config.
    config = PipelineConfig(triage=TriageConfig(complexity_threshold=1))

    parsed = compile_module(sample_ir, config)

    print("\n--- Pipeline Summary ---")
    print(summarize_run(parsed))

    fn = next(f for f in parsed.functions if f.name == "accumulate")
    print("\n--- LLM candidate (raw Phase 3 output) ---")
    print(fn.llm_output if fn.llm_output else "(none — model failed or output unparseable)")
    print("\n--- Final IR locked into the module ---")
    print(fn.final_ir)
