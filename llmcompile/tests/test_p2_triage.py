"""Tests for Phase 2 triage.

Run with:
    python -m pytest llmcompile/tests/test_p2_triage.py -v

Or in JupyterHub:
    !python -m pytest llmcompile/tests/test_p2_triage.py -v
"""

from __future__ import annotations

import pytest

from llmcompile.phases.p1_parse import parse_module
from llmcompile.phases.p2_triage import triage_module, summarize
from llmcompile.config import PipelineConfig, TriageConfig


# Sample IR with functions of varying complexity
SAMPLE_IR = """\
; ModuleID = 'sample'
source_filename = "sample.c"
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-f80:128-n8:16:32:64-S128"
target triple = "x86_64-unknown-linux-gnu"

; Straight-line function: complexity = 1
define i32 @simple_add(i32 %a, i32 %b) {
entry:
  %sum = add i32 %a, %b
  ret i32 %sum
}

; Function with one conditional: complexity = 2
define i32 @max(i32 %a, i32 %b) {
entry:
  %cmp = icmp sgt i32 %a, %b
  br i1 %cmp, label %if.then, label %if.else

if.then:
  ret i32 %a

if.else:
  ret i32 %b
}

; Function with nested conditionals: complexity > 2
define i32 @complex_logic(i32 %x, i32 %y, i32 %z) {
entry:
  %cmp1 = icmp sgt i32 %x, %y
  br i1 %cmp1, label %if.then, label %if.else

if.then:
  %cmp2 = icmp sgt i32 %x, %z
  br i1 %cmp2, label %return.x, label %return.z

if.else:
  %cmp3 = icmp sgt i32 %y, %z
  br i1 %cmp3, label %return.y, label %return.z

return.x:
  ret i32 %x

return.y:
  ret i32 %y

return.z:
  ret i32 %z
}

; Empty function (minimal complexity)
define void @empty() {
entry:
  ret void
}
"""


@pytest.fixture(scope="module")
def parsed():
    """Parse the sample IR once for all tests."""
    return parse_module(SAMPLE_IR)


@pytest.fixture(scope="module")
def triaged(parsed):
    """Parse and triage the sample IR."""
    # Use a custom config with low threshold for testing
    config = PipelineConfig(triage=TriageConfig(complexity_threshold=3))
    triage_module(parsed, config)
    return parsed


def test_complexity_is_computed(triaged):
    """All functions should have complexity computed."""
    for rec in triaged.functions:
        assert rec.complexity is not None
        assert rec.complexity >= 0


def test_token_count_is_computed(triaged):
    """All functions should have token count computed."""
    for rec in triaged.functions:
        assert rec.token_count is not None
        assert rec.token_count > 0  # Standalone IR is never empty


def test_simple_function_has_low_complexity(triaged):
    """Straight-line function should have complexity = 1."""
    simple = next(r for r in triaged.functions if r.name == "simple_add")
    assert simple.complexity == 1


def test_conditional_function_has_higher_complexity(triaged):
    """Function with conditional should have complexity = 2."""
    max_fn = next(r for r in triaged.functions if r.name == "max")
    assert max_fn.complexity == 2


def test_complex_function_has_highest_complexity(triaged):
    """Function with multiple branches should have complexity > 2."""
    complex_fn = next(r for r in triaged.functions if r.name == "complex_logic")
    assert complex_fn.complexity > 2


def test_empty_function_has_complexity_one(triaged):
    """Empty function (just return) should have minimal complexity."""
    empty = next(r for r in triaged.functions if r.name == "empty")
    # Single block with single return: complexity = 1
    assert empty.complexity == 1


def test_triage_threshold_applied(triaged):
    """Functions below threshold should be triaged out."""
    # Config has threshold=3, so complexity < 3 should be triaged
    simple = next(r for r in triaged.functions if r.name == "simple_add")
    max_fn = next(r for r in triaged.functions if r.name == "max")
    complex_fn = next(r for r in triaged.functions if r.name == "complex_logic")

    # complexity=1 and complexity=2 should be triaged out
    assert simple.triaged_out is True
    assert max_fn.triaged_out is True

    # complexity>2 should NOT be triaged out
    assert complex_fn.triaged_out is False


def test_determinism(parsed):
    """Running triage twice should produce identical results."""
    config = PipelineConfig(triage=TriageConfig(complexity_threshold=3))

    # First run
    triage_module(parsed, config)
    results1 = [
        (r.name, r.complexity, r.token_count, r.triaged_out)
        for r in parsed.functions
    ]

    # Second run (re-parse to reset state)
    parsed2 = parse_module(SAMPLE_IR)
    triage_module(parsed2, config)
    results2 = [
        (r.name, r.complexity, r.token_count, r.triaged_out)
        for r in parsed2.functions
    ]

    # Should be identical
    assert results1 == results2


def test_token_count_scales_with_function_size(triaged):
    """Larger functions should have higher token counts."""
    simple = next(r for r in triaged.functions if r.name == "simple_add")
    complex_fn = next(r for r in triaged.functions if r.name == "complex_logic")

    # complex_logic has more IR lines, should have more tokens
    assert complex_fn.token_count > simple.token_count


def test_summarize_output(triaged):
    """Summarize should produce readable output."""
    summary = summarize(triaged)
    assert "Triage results" in summary
    assert "simple_add" in summary
    assert "complexity=" in summary
    assert "tokens=" in summary
    assert "TRIAGED OUT" in summary or "TO OPTIMIZE" in summary


def test_custom_threshold():
    """Different thresholds should produce different triage results."""
    parsed1 = parse_module(SAMPLE_IR)
    parsed2 = parse_module(SAMPLE_IR)

    # Low threshold: nothing triaged out
    config_low = PipelineConfig(triage=TriageConfig(complexity_threshold=0))
    triage_module(parsed1, config_low)
    triaged_out_low = sum(1 for r in parsed1.functions if r.triaged_out)

    # High threshold: everything triaged out
    config_high = PipelineConfig(triage=TriageConfig(complexity_threshold=100))
    triage_module(parsed2, config_high)
    triaged_out_high = sum(1 for r in parsed2.functions if r.triaged_out)

    # High threshold should triage more functions
    assert triaged_out_high > triaged_out_low


def test_fields_initialized_correctly(triaged):
    """All expected fields should be populated after triage."""
    for rec in triaged.functions:
        # Phase 1 fields
        assert rec.name
        assert rec.original_ir

        # Phase 2 fields (newly populated)
        assert rec.complexity is not None
        assert rec.token_count is not None
        assert rec.triaged_out is not None

        # Phase 3-6 fields (still None/default)
        assert rec.assigned_model is None
        assert rec.llm_output is None
        assert rec.final_ir is None
