"""End-to-end tests for the M1 walking skeleton (phases 1->6).

Two paths are exercised without needing the real verification toolchain:
* verification mocked to PASS -> the "everything trivially passes" M1 path;
* verification tools absent -> everything fails closed to fallback.
Both must yield a valid final module that behaves like the unoptimised input.

Run with:
    python -m pytest llmcompile/tests/test_orchestrator.py -v
"""

from __future__ import annotations

from unittest.mock import patch

import llvmlite.binding as llvm

from llmcompile.models import Verdict
from llmcompile.config import PipelineConfig, TriageConfig, VerificationConfig
from llmcompile.orchestrator import compile_module, summarize_run
from llmcompile.phases.p1_parse import extract_function_body

# Preamble (datalayout/triple/global/foreign declare) + three functions,
# including @use which calls sibling @add and foreign @ext.
SAMPLE_IR = (
    "target datalayout = \"e-m:e-i64:64-f80:128-n8:16:32:64-S128\"\n"
    "target triple = \"x86_64-unknown-linux-gnu\"\n"
    "@g = global i32 0, align 4\n"
    "declare i32 @ext(i32)\n"
    "define i32 @add(i32 %a, i32 %b) {\n"
    "entry:\n"
    "  %r = add i32 %a, %b\n"
    "  ret i32 %r\n"
    "}\n"
    "define i32 @use(i32 %x) {\n"
    "entry:\n"
    "  %t = call i32 @add(i32 %x, i32 1)\n"
    "  %e = call i32 @ext(i32 %t)\n"
    "  ret i32 %e\n"
    "}\n"
    "define i32 @branchy(i32 %a) {\n"
    "entry:\n"
    "  %c = icmp sgt i32 %a, 0\n"
    "  br i1 %c, label %t, label %f\n"
    "t:\n"
    "  ret i32 1\n"
    "f:\n"
    "  ret i32 0\n"
    "}\n"
)


def _cfg(threshold=1, **verif):
    return PipelineConfig(
        triage=TriageConfig(complexity_threshold=threshold),
        verification=VerificationConfig(**verif) if verif else None,
    )


# ---------------------------------------------------------------------------
# Path 1: verification mocked to PASS (the M1 "everything passes" guarantee)
# ---------------------------------------------------------------------------

@patch("llmcompile.phases.p5_verify.verify_refinement", return_value=(Verdict.PASSED, None))
@patch("llmcompile.phases.p5_verify.check_syntax", return_value=True)
def test_end_to_end_all_pass_is_identity(mock_syntax, mock_verify):
    parsed = compile_module(SAMPLE_IR, _cfg(threshold=1))

    # every function routed, reconstructed, verified PASSED
    for r in parsed.functions:
        assert r.triaged_out is False
        assert r.candidate_ir is not None
        assert r.verdict == Verdict.PASSED
        # identity transform: the final body equals the original body
        assert r.final_ir.strip() == extract_function_body(r.original_ir, r.name).strip()

    # the reassembled final module is valid IR and preserves every function
    m = llvm.parse_assembly(parsed.final_module_ir)
    m.verify()
    for name in ("add", "use", "branchy"):
        assert f"@{name}" in parsed.final_module_ir


@patch("llmcompile.phases.p5_verify.verify_refinement", return_value=(Verdict.PASSED, None))
@patch("llmcompile.phases.p5_verify.check_syntax", return_value=True)
def test_end_to_end_triage_mix(mock_syntax, mock_verify):
    # threshold 2: @add & @use (complexity 1) triaged out, @branchy (2) optimized
    parsed = compile_module(SAMPLE_IR, _cfg(threshold=2))
    fns = {f.name: f for f in parsed.functions}

    assert fns["add"].triaged_out and fns["add"].verdict == Verdict.PENDING
    assert fns["use"].triaged_out and fns["use"].verdict == Verdict.PENDING
    assert not fns["branchy"].triaged_out and fns["branchy"].verdict == Verdict.PASSED

    # triaged funcs were never even sent to reconstruction/verification
    assert fns["add"].candidate_ir is None
    assert fns["branchy"].candidate_ir is not None

    m = llvm.parse_assembly(parsed.final_module_ir)
    m.verify()


# ---------------------------------------------------------------------------
# Path 2: toolchain absent -> fail closed to fallback (still valid output)
# ---------------------------------------------------------------------------

def test_end_to_end_toolchain_absent_falls_back():
    config = _cfg(
        threshold=1,
        llvm_as_path="__no_such_llvm_as__",
        alive_tv_path="__no_such_alive_tv__",
    )
    parsed = compile_module(SAMPLE_IR, config)

    for r in parsed.functions:
        # llvm-as missing -> syntax check fails closed
        assert r.verdict == Verdict.SYNTAX_FAIL
        # fallback: final body is the untouched original
        assert r.final_ir.strip() == extract_function_body(r.original_ir, r.name).strip()

    # even on the fallback path the assembled module is valid and complete
    m = llvm.parse_assembly(parsed.final_module_ir)
    m.verify()


def test_original_ir_is_never_mutated():
    config = _cfg(threshold=1, llvm_as_path="__no_such_llvm_as__")
    parsed = compile_module(SAMPLE_IR, config)
    for r in parsed.functions:
        # original_ir must still be independently assemblable and unchanged
        m = llvm.parse_assembly(r.original_ir)
        m.verify()


# ---------------------------------------------------------------------------
# Determinism + reporting
# ---------------------------------------------------------------------------

def test_pipeline_is_deterministic():
    config = _cfg(threshold=1, llvm_as_path="__no_such_llvm_as__")
    a = compile_module(SAMPLE_IR, config).final_module_ir
    b = compile_module(SAMPLE_IR, config).final_module_ir
    assert a == b


def test_summarize_run_mentions_functions():
    config = _cfg(threshold=1, llvm_as_path="__no_such_llvm_as__")
    parsed = compile_module(SAMPLE_IR, config)
    summary = summarize_run(parsed)
    for name in ("add", "use", "branchy"):
        assert name in summary
