"""Tests for Phase 6 fallback assembly.

Run with:
    python -m pytest llmcompile/tests/test_p6_assemble.py -v
"""

from __future__ import annotations

import llvmlite.binding as llvm

from llmcompile.models import Verdict
from llmcompile.phases.p1_parse import parse_module, extract_function_body
from llmcompile.phases.p6_assemble import assemble_module

TWO_FN_IR = (
    "define i32 @keep(i32 %a) {\n"
    "entry:\n"
    "  %r = add i32 %a, 1\n"
    "  ret i32 %r\n"
    "}\n"
    "define i32 @opt(i32 %a) {\n"
    "entry:\n"
    "  %r = add i32 %a, 0\n"
    "  ret i32 %r\n"
    "}\n"
)


def _parsed_with_candidate():
    """A parsed module where @opt has a PASSED candidate and @keep does not."""
    parsed = parse_module(TWO_FN_IR)
    opt = next(f for f in parsed.functions if f.name == "opt")
    keep = next(f for f in parsed.functions if f.name == "keep")

    # @opt: a proven optimization (identity of add 0 -> just return the arg)
    opt.llm_output = "define i32 @opt(i32 %a) {\nentry:\n  ret i32 %a\n}"
    opt.verdict = Verdict.PASSED

    # @keep: rejected candidate -> must fall back to original
    keep.llm_output = "define i32 @keep(i32 %a) {\nentry:\n  ret i32 999\n}"
    keep.verdict = Verdict.REJECTED
    return parsed, keep, opt


def test_passed_locks_in_optimization_rejected_falls_back():
    parsed, keep, opt = _parsed_with_candidate()
    module_ir = assemble_module(parsed)

    # @opt got the optimized body
    assert opt.final_ir.strip() == "define i32 @opt(i32 %a) {\nentry:\n  ret i32 %a\n}"
    # @keep fell back to its original body (NOT the rejected 999 candidate)
    assert opt.final_ir != keep.final_ir
    assert "ret i32 999" not in keep.final_ir
    assert keep.final_ir.strip() == extract_function_body(keep.original_ir, "keep").strip()


def test_assembled_module_is_valid_ir():
    parsed, _, _ = _parsed_with_candidate()
    module_ir = assemble_module(parsed)
    assert module_ir == parsed.final_module_ir
    # the reassembled full module must parse + verify
    m = llvm.parse_assembly(module_ir)
    m.verify()
    # both functions present, optimized body reflected
    assert "@keep" in module_ir and "@opt" in module_ir
    assert "ret i32 %a" in module_ir


def test_non_passed_verdicts_all_fall_back():
    for verdict in (Verdict.PENDING, Verdict.SYNTAX_FAIL, Verdict.UNSUPPORTED, Verdict.REJECTED):
        parsed = parse_module(TWO_FN_IR)
        for f in parsed.functions:
            f.llm_output = f"define i32 @{f.name}(i32 %a) {{\nentry:\n  ret i32 42\n}}"
            f.verdict = verdict
        assemble_module(parsed)
        for f in parsed.functions:
            # nothing was PASSED -> everything is the original body
            assert "ret i32 42" not in f.final_ir
            assert f.final_ir.strip() == extract_function_body(f.original_ir, f.name).strip()


def test_triaged_out_uses_original_body():
    parsed = parse_module(TWO_FN_IR)
    for f in parsed.functions:
        f.triaged_out = True  # never routed, verdict stays PENDING
    assemble_module(parsed)
    for f in parsed.functions:
        assert f.final_ir.strip() == extract_function_body(f.original_ir, f.name).strip()


def test_assembly_is_deterministic():
    p1, _, _ = _parsed_with_candidate()
    p2, _, _ = _parsed_with_candidate()
    assert assemble_module(p1) == assemble_module(p2)
