"""
Milestone 2: Trust the Gate for Real.
Integration tests for Phase 5 (verification) using the real Alive2 toolchain.

Run with:
    python -m pytest llmcompile/tests/test_m2_gate.py -v
"""

from __future__ import annotations
import os
import pytest
from unittest.mock import patch

from llmcompile.models import FunctionRecord, Verdict
from llmcompile.phases.p5_verify import verify_module, check_syntax, verify_refinement
from llmcompile.config import PipelineConfig, VerificationConfig


def _get_toolchain_paths():
    lockfile = os.path.expanduser("~/llvm_toolchain/toolchain_versions.lock")
    if not os.path.exists(lockfile):
        return None, None
        
    paths = {}
    with open(lockfile, "r") as f:
        for line in f:
            if "=" in line and not line.startswith("#"):
                key, val = line.strip().split("=", 1)
                paths[key] = val
    
    return paths.get("llvm_as_path"), paths.get("alive_tv_path")


# Get paths once for the module
LLVM_AS_PATH, ALIVE_TV_PATH = _get_toolchain_paths()
HAS_TOOLCHAIN = LLVM_AS_PATH and os.path.exists(LLVM_AS_PATH) and ALIVE_TV_PATH and os.path.exists(ALIVE_TV_PATH)


@pytest.fixture
def config():
    if not HAS_TOOLCHAIN:
        pytest.skip("Alive2 toolchain not found. Run build_toolchain.sh first.")
        
    return PipelineConfig(
        verification=VerificationConfig(
            llvm_as_path=LLVM_AS_PATH,
            alive_tv_path=ALIVE_TV_PATH,
            llvm_as_timeout=5,
            smt_timeout=30,
        )
    )


def test_m2_syntax_fail(config):
    ir = "define i32 @f(i32 %a) {\n  not a real instruction\n}\n"
    assert check_syntax(ir, config.verification) is False


def test_m2_syntax_pass(config):
    ir = "define i32 @f(i32 %a) {\n  ret i32 %a\n}\n"
    assert check_syntax(ir, config.verification) is True


def test_m2_good_dead_code_elimination(config):
    src = "define i32 @f(i32 %a) {\n  %x = add i32 0, %a\n  ret i32 %x\n}\n"
    tgt = "define i32 @f(i32 %a) {\n  ret i32 %a\n}\n"
    
    verdict, cex = verify_refinement(src, tgt, config.verification)
    assert verdict == Verdict.PASSED
    assert cex is None


def test_m2_good_strength_reduction(config):
    src = "define i32 @f(i32 %a) {\n  %x = mul i32 %a, 4\n  ret i32 %x\n}\n"
    tgt = "define i32 @f(i32 %a) {\n  %x = shl i32 %a, 2\n  ret i32 %x\n}\n"
    
    verdict, cex = verify_refinement(src, tgt, config.verification)
    assert verdict == Verdict.PASSED
    assert cex is None


def test_m2_bad_changed_return_value(config):
    src = "define i32 @f(i32 %a) {\n  ret i32 %a\n}\n"
    tgt = "define i32 @f(i32 %a) {\n  ret i32 1\n}\n"
    
    verdict, cex = verify_refinement(src, tgt, config.verification)
    assert verdict == Verdict.REJECTED
    assert cex is not None
    assert "Transformation doesn't verify" in cex


def test_m2_bad_introduced_poison(config):
    # original does add, well-defined overflow behaviour
    src = "define i32 @f(i32 %a) {\n  %b = add i32 %a, 1\n  ret i32 %b\n}\n"
    # target introduces nsw (no signed wrap) -> poison on overflow
    tgt = "define i32 @f(i32 %a) {\n  %b = add nsw i32 %a, 1\n  ret i32 %b\n}\n"
    
    verdict, cex = verify_refinement(src, tgt, config.verification)
    assert verdict == Verdict.REJECTED
    assert cex is not None


def test_m2_bad_dropped_side_effect(config):
    # Note: globals must be declared in both IR snippets since they are standalone
    src = "@g = global i32 0\n\ndefine i32 @f() {\n  store i32 1, ptr @g\n  ret i32 0\n}\n"
    tgt = "@g = global i32 0\n\ndefine i32 @f() {\n  ret i32 0\n}\n"
    
    verdict, cex = verify_refinement(src, tgt, config.verification)
    assert verdict == Verdict.REJECTED
    assert cex is not None
