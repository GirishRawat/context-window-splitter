"""
Milestone 0 Spike Test: Verifies that the built toolchain works correctly.
It reads toolchain_versions.lock for the binary paths and tests them on simple IR.

Run with:
    python -m pytest llmcompile/tests/test_m0_spike.py -v
"""

from __future__ import annotations
import os
import subprocess
import pytest

def get_toolchain_paths():
    lockfile = os.path.expanduser("~/llvm_toolchain/toolchain_versions.lock")
    if not os.path.exists(lockfile):
        pytest.skip(f"Toolchain lockfile not found at {lockfile}. Run build_toolchain.sh first.")
        
    paths = {}
    with open(lockfile, "r") as f:
        for line in f:
            if "=" in line and not line.startswith("#"):
                key, val = line.strip().split("=", 1)
                paths[key] = val
    
    if "alive_tv_path" not in paths or "llvm_as_path" not in paths:
        pytest.skip("Lockfile is missing alive_tv_path or llvm_as_path")
        
    return paths["llvm_as_path"], paths["alive_tv_path"]


@pytest.fixture
def tools():
    llvm_as, alive_tv = get_toolchain_paths()
    if not os.path.exists(llvm_as):
        pytest.fail(f"llvm-as not found at {llvm_as}")
    if not os.path.exists(alive_tv):
        pytest.fail(f"alive-tv not found at {alive_tv}")
    return llvm_as, alive_tv


def test_llvm_as_valid(tools, tmp_path):
    llvm_as, _ = tools
    ir = "define i32 @f(i32 %a) {\n  ret i32 %a\n}\n"
    p = tmp_path / "valid.ll"
    p.write_text(ir)
    
    result = subprocess.run([llvm_as, str(p)], capture_output=True, text=True)
    assert result.returncode == 0


def test_llvm_as_invalid(tools, tmp_path):
    llvm_as, _ = tools
    ir = "define i32 @f(i32 %a) {\n  not a real instruction\n}\n"
    p = tmp_path / "invalid.ll"
    p.write_text(ir)
    
    result = subprocess.run([llvm_as, str(p)], capture_output=True, text=True)
    assert result.returncode != 0


def test_alive_tv_accepts_valid_refinement(tools, tmp_path):
    _, alive_tv = tools
    src_ir = "define i32 @f(i32 %a) {\n  %b = add i32 %a, 0\n  ret i32 %b\n}\n"
    tgt_ir = "define i32 @f(i32 %a) {\n  ret i32 %a\n}\n"
    
    src_p = tmp_path / "src.ll"
    src_p.write_text(src_ir)
    tgt_p = tmp_path / "tgt.ll"
    tgt_p.write_text(tgt_ir)
    
    result = subprocess.run([alive_tv, str(src_p), str(tgt_p)], capture_output=True, text=True)
    assert result.returncode == 0
    assert "Transformation seems to be correct!" in result.stdout


def test_alive_tv_rejects_invalid_refinement(tools, tmp_path):
    _, alive_tv = tools
    src_ir = "define i32 @f(i32 %a) {\n  ret i32 %a\n}\n"
    tgt_ir = "define i32 @f(i32 %a) {\n  ret i32 1\n}\n"
    
    src_p = tmp_path / "src.ll"
    src_p.write_text(src_ir)
    tgt_p = tmp_path / "tgt.ll"
    tgt_p.write_text(tgt_ir)
    
    result = subprocess.run([alive_tv, str(src_p), str(tgt_p)], capture_output=True, text=True)
    assert "Transformation doesn't verify!" in result.stdout

def test_alive_tv_rejects_introduced_poison(tools, tmp_path):
    _, alive_tv = tools
    # src does regular add, overflow is well defined (wraps)
    src_ir = "define i32 @f(i32 %a) {\n  %b = add i32 %a, 1\n  ret i32 %b\n}\n"
    # tgt introduces nsw (no signed wrap), which yields poison on overflow.
    # A refinement cannot introduce poison for inputs that were previously well-defined.
    tgt_ir = "define i32 @f(i32 %a) {\n  %b = add nsw i32 %a, 1\n  ret i32 %b\n}\n"
    
    src_p = tmp_path / "src.ll"
    src_p.write_text(src_ir)
    tgt_p = tmp_path / "tgt.ll"
    tgt_p.write_text(tgt_ir)
    
    result = subprocess.run([alive_tv, str(src_p), str(tgt_p)], capture_output=True, text=True)
    assert "Transformation doesn't verify!" in result.stdout
