import logging
from llmcompile.orchestrator import compile_module, summarize_run

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

sample_ir = """
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-f80:128-n8:16:32:64-S128"
target triple = "x86_64-pc-linux-gnu"

define i32 @add_trivial(i32 %a, i32 %b) {
entry:
  %res = add i32 %a, %b
  ret i32 %res
}

define i32 @complex_logic(i32 %x) {
entry:
  %cmp = icmp sgt i32 %x, 0
  br i1 %cmp, label %if.then, label %if.else

if.then:
  %v1 = mul i32 %x, 2
  br label %return

if.else:
  %v2 = sub i32 0, %x
  br label %return

return:
  %res = phi i32 [ %v1, %if.then ], [ %v2, %if.else ]
  ret i32 %res
}
"""

if __name__ == "__main__":
    print("========================================")
    print(" Running M1: Orchestrator Spine Demo ")
    print("========================================")
    
    parsed = compile_module(sample_ir)
    
    print("\n--- Pipeline Summary ---")
    print(summarize_run(parsed))
    print("\n--- Final IR for @add_trivial ---")
    
    trivial_fn = next(f for f in parsed.functions if f.name == "add_trivial")
    print(trivial_fn.final_ir)
