import os
import csv
from pathlib import Path

import llvmlite.binding as llvm
from llmcompile.eval.harness import get_instruction_counts

def test_get_instruction_counts():
    llvm.initialize()
    llvm.initialize_native_target()
    llvm.initialize_native_asmprinter()
    llvm.set_option("llvmlite", "-opaque-pointers")
    
    """Verify that llvmlite correctly extracts instruction counts, ignoring labels and braces."""
    ir_text = """
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-f80:128-n8:16:32:64-S128"
target triple = "x86_64-unknown-linux-gnu"

define i32 @test_func(i32 %a) {
entry:
  %x = add i32 %a, 1
  %y = mul i32 %x, 2
  ret i32 %y
}

declare i32 @printf(i8*, ...)
"""
    counts = get_instruction_counts(ir_text)
    
    # test_func has exactly 3 instructions: add, mul, ret
    assert "test_func" in counts
    assert counts["test_func"] == 3
    
    # declarations should be ignored
    assert "printf" not in counts
