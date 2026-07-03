"""Tests for Phase 3 routing (identity stub for the M1 walking skeleton).

Run with:
    python -m pytest llmcompile/tests/test_p3_route.py -v
"""

from __future__ import annotations

from llmcompile.phases.p1_parse import parse_module
from llmcompile.phases.p2_triage import triage_module
from llmcompile.phases.p3_route import route_module, IDENTITY_MODEL
from llmcompile.config import PipelineConfig, TriageConfig

# Two functions: @add (straight-line, low complexity) and @branchy (a branch).
SAMPLE_IR = (
    "define i32 @add(i32 %a, i32 %b) {\n"
    "entry:\n"
    "  %r = add i32 %a, %b\n"
    "  ret i32 %r\n"
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


def _routed(threshold: int = 1) -> dict:
    parsed = parse_module(SAMPLE_IR)
    config = PipelineConfig(triage=TriageConfig(complexity_threshold=threshold))
    triage_module(parsed, config)
    route_module(parsed, config)
    return {f.name: f for f in parsed.functions}


def test_identity_sets_llm_output_to_original_body():
    fns = _routed(threshold=1)  # threshold 1 -> nothing triaged out
    for name, rec in fns.items():
        assert rec.assigned_model == IDENTITY_MODEL
        assert rec.llm_output is not None
        # identity: candidate body is exactly the original define block
        assert rec.llm_output.strip().startswith(f"define i32 @{name}")
        assert rec.llm_output.strip().endswith("}")


def test_identity_output_is_bare_define_block_no_preamble():
    fns = _routed(threshold=1)
    add = fns["add"]
    # llm_output must be a single define block, NOT the full standalone module
    assert add.llm_output.count("define ") == 1
    assert "target datalayout" not in add.llm_output
    assert "declare" not in add.llm_output


def test_triaged_functions_are_not_routed():
    # threshold 2: @add (complexity 1) triaged out, @branchy (2) routed
    fns = _routed(threshold=2)
    assert fns["add"].triaged_out is True
    assert fns["add"].llm_output is None
    assert fns["add"].assigned_model is None

    assert fns["branchy"].triaged_out is False
    assert fns["branchy"].llm_output is not None
    assert fns["branchy"].assigned_model == IDENTITY_MODEL


def test_routing_is_deterministic():
    a = _routed(threshold=1)
    b = _routed(threshold=1)
    assert {n: r.llm_output for n, r in a.items()} == {n: r.llm_output for n, r in b.items()}
