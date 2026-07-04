#!/usr/bin/env python3
import os
import subprocess
import re
from pathlib import Path

def main():
    base_dir = Path(__file__).parent.parent
    src_dir = base_dir / "sbase_src"
    out_dir = base_dir / "sbase_corpus"
    
    out_dir.mkdir(exist_ok=True)
    
    # Locate all C files in the root of sbase_src
    c_files = list(src_dir.glob("*.c"))
    print(f"Found {len(c_files)} C files in sbase_src root.")
    
    # We use the build toolchain's clang if available, otherwise system clang
    clang_path = os.path.expanduser("~/llvm_toolchain/llvm-project/llvm/build/bin/clang")
    if not os.path.exists(clang_path):
        clang_path = "clang"
        
    # On macOS, custom clang needs the SDK path passed via -isysroot
    isysroot = None
    try:
        isysroot = subprocess.check_output(["xcrun", "--show-sdk-path"], text=True).strip()
    except Exception:
        pass
        
    print(f"Using clang: {clang_path}")
    if isysroot:
        print(f"Using sysroot: {isysroot}")
    
    compiled_count = 0
    failed_count = 0
    
    for c_file in c_files:
        # Exclude libutf and libutil sources if they are ever moved/symlinked to root
        if c_file.name in ["libutf", "libutil"]:
            continue
            
        out_file = out_dir / c_file.name.replace(".c", ".ll")
        
        cmd = [
            clang_path,
            "-S", "-emit-llvm",
            "-O0",
            "-Xclang", "-disable-O0-optnone",
            "-I", str(src_dir),
            "-I", str(src_dir / "libutf"),
            "-I", str(src_dir / "libutil"),
        ]
        if isysroot:
            cmd.extend(["-isysroot", isysroot])
        cmd.extend([str(c_file), "-o", str(out_file)])
        
        try:
            subprocess.run(cmd, check=True, capture_output=True)
            
            # Post-process IR: strip LLVM 18 incompatibilities for llvmlite
            with open(out_file, "r") as f:
                ll_text = f.read()
                
            ll_text = ll_text.replace("uwtable(sync)", "uwtable")
            ll_text = re.sub(r"!llvm\.module\.flags = .*?\n", "", ll_text)
            ll_text = re.sub(r"\bmemory\([^)]*\)", "", ll_text)
            
            with open(out_file, "w") as f:
                f.write(ll_text)
                
            compiled_count += 1
        except Exception as e:
            # Some files might require additional headers or definitions, log and skip
            print(f"Failed to compile {c_file.name}: {e}")
            failed_count += 1
            if out_file.exists():
                out_file.unlink()
                
    print(f"\nCompleted: Compiled {compiled_count} files, failed {failed_count}.")
    print(f"LLVM IR files saved in {out_dir}")

if __name__ == "__main__":
    main()
