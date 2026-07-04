#!/usr/bin/env python3
import os
import subprocess
from pathlib import Path

# A few simple C programs that offer good optimization opportunities
# (e.g. loops, arithmetic that can be simplified, dead code)
C_SOURCES = {
    "math_ops.c": """
int compute_sum(int a, int b) {
    int x = a + b;
    int y = x + 0; // dead addition
    int z = y * 4; // can be strength-reduced to shl z, 2
    return z;
}

int complex_condition(int a) {
    if (a > 10) {
        if (a > 5) {
            return 1; // The second check is redundant
        }
    }
    return 0;
}
""",
    "array_sum.c": """
int sum_array(int* arr, int n) {
    int sum = 0;
    for (int i = 0; i < n; i++) {
        sum += arr[i];
    }
    return sum;
}
""",
    "bitwise.c": """
int bit_tricks(int x) {
    int a = x ^ x; // Always 0
    int b = a | x; // Just x
    return b;
}

int redundant_arithmetic(int x) {
    int a = x + 0;
    int b = a * 1;
    int c = b / 1;
    return c;
}

int redundant_logic(int x) {
    if (x > 10) {
        if (x > 5) {
            return x + 1;
        }
    }
    return x;
}
"""
}

# Hand-crafted IR files that don't need compilation from C, but are great for Alive2 PASSED tests.
HAND_CRAFTED_IR = {
    "accumulate.ll": """
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
}

def main():
    base_dir = Path(__file__).parent.parent
    src_dir = base_dir / "corpus_src"
    out_dir = base_dir / "corpus"
    
    src_dir.mkdir(exist_ok=True)
    out_dir.mkdir(exist_ok=True)
    
    print("Generating C sources...")
    for filename, content in C_SOURCES.items():
        with open(src_dir / filename, "w") as f:
            f.write(content.strip())
            
    # We assume clang is available in PATH or from the LLVM toolchain dir
    # Note: we use -Xclang -disable-O0-optnone so Alive2 and LLVM passes aren't blocked by the optnone attribute.
    clang_path = os.path.expanduser("~/llvm_toolchain/llvm-project/llvm/build/bin/clang")
    if not os.path.exists(clang_path):
        clang_path = "clang" # fallback to system clang
        
    print(f"Using clang: {clang_path}")
    
    for filename in C_SOURCES.keys():
        src_file = src_dir / filename
        out_file = out_dir / filename.replace(".c", ".ll")
        
        cmd = [
            clang_path,
            "-S", "-emit-llvm",
            "-O0",
            "-Xclang", "-disable-O0-optnone",
            str(src_file),
            "-o", str(out_file)
        ]
        
        print(f"Compiling {filename} to {out_file.name}...")
        subprocess.run(cmd, check=True)
        # llvmlite 0.42.0 uses LLVM 14, which does not support uwtable(sync), only uwtable.
        # It also does not support LLVM 18 module flags (behavior operand 8).
        import re
        with open(out_file, "r") as f:
            ll_text = f.read()
        ll_text = ll_text.replace("uwtable(sync)", "uwtable")
        ll_text = re.sub(r"!llvm\.module\.flags = .*?\n", "", ll_text)
        with open(out_file, "w") as f:
            f.write(ll_text)
            
    print("Generating hand-crafted IR files...")
    for filename, content in HAND_CRAFTED_IR.items():
        out_file = out_dir / filename
        with open(out_file, "w") as f:
            f.write(content.strip() + "\n")
        
    print(f"\nCorpus generation complete! {len(C_SOURCES) + len(HAND_CRAFTED_IR)} .ll files are ready in the 'corpus/' directory.")

if __name__ == "__main__":
    main()
