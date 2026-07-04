"""Tests for Phase 4 reconstruction and the underlying IR-rewrite helpers.

Run with:
    python -m pytest llmcompile/tests/test_p4_reconstruct.py -v
"""

from __future__ import annotations

import pytest
import llvmlite.binding as llvm

from llmcompile.models import ParsedModule
from llmcompile.phases.p1_parse import (
    parse_module,
    replace_function_body,
    extract_function_body,
)
from llmcompile.phases.p2_triage import triage_module
from llmcompile.phases.p3_route import route_module
from llmcompile.phases.p4_reconstruct import reconstruct_module
from llmcompile.config import PipelineConfig, TriageConfig

# @use calls sibling @add — the case where dropping sibling declarations breaks.
IR_WITH_SIBLING_CALL = (
    "define i32 @add(i32 %a, i32 %b) {\n"
    "entry:\n"
    "  %r = add i32 %a, %b\n"
    "  ret i32 %r\n"
    "}\n"
    "define i32 @use(i32 %x) {\n"
    "entry:\n"
    "  %t = call i32 @add(i32 %x, i32 1)\n"
    "  ret i32 %t\n"
    "}\n"
)


# ---------------------------------------------------------------------------
# Helpers: replace_function_body / extract_function_body
# ---------------------------------------------------------------------------

def test_replace_function_body_keeps_sibling_declarations():
    """The rebuilt candidate must keep the sibling declarations the source has,
    otherwise any function that calls a sibling fails llvm-as (Finding #1)."""
    parsed = parse_module(IR_WITH_SIBLING_CALL)
    use = next(f for f in parsed.functions if f.name == "use")
    assert "declare i32 @add" in use.original_ir  # sanity

    candidate_body = (
        "define i32 @use(i32 %x) {\n"
        "entry:\n"
        "  %t = call i32 @add(i32 %x, i32 1)\n"
        "  ret i32 %t\n"
        "}"
    )
    candidate = replace_function_body(use.original_ir, "use", candidate_body)

    assert "declare i32 @add" in candidate
    # and it must be independently assemblable (no Alive2 needed)
    m = llvm.parse_assembly(candidate)
    m.verify()


def test_replace_function_body_rejects_wrong_function():
    parsed = parse_module("define i32 @f() {\nentry:\n  ret i32 0\n}")
    f = parsed.functions[0]
    with pytest.raises(ValueError):
        replace_function_body(f.original_ir, "nonexistent", "define i32 @f() { ret i32 0 }")


def test_extract_function_body_returns_bare_define():
    parsed = parse_module(IR_WITH_SIBLING_CALL)
    use = next(f for f in parsed.functions if f.name == "use")
    body = extract_function_body(use.original_ir, "use")
    assert body.strip().startswith("define i32 @use")
    assert "declare" not in body
    assert "target datalayout" not in body


def test_extract_function_body_unknown_raises():
    parsed = parse_module("define i32 @f() {\nentry:\n  ret i32 0\n}")
    with pytest.raises(ValueError):
        extract_function_body(parsed.functions[0].original_ir, "ghost")


# ---------------------------------------------------------------------------
# reconstruct_module (Phase 4)
# ---------------------------------------------------------------------------

def _run_through_reconstruct(ir: str, threshold: int = 1) -> dict:
    from unittest.mock import patch, MagicMock
    from llmcompile.config import LLMRoutingConfig, ModelTier

    config = PipelineConfig(
        triage=TriageConfig(complexity_threshold=threshold),
        # Use non-ollama model names so health check is not triggered
        llm_routing=LLMRoutingConfig(
            tiers={
                "fast": ModelTier("fast", ["test-model"], max_concurrent=2),
                "mid": ModelTier("mid", ["test-model"], max_concurrent=1),
                "frontier": ModelTier("frontier", ["test-model"], max_concurrent=1),
            }
        ),
    )

    parsed = parse_module(ir)
    triage_module(parsed, config)

    # Mock litellm to return identity transforms
    async def identity_completion(**kwargs):
        user_msg = kwargs.get("messages", [{}])[1].get("content", "")
        body = user_msg.split("Optimize this LLVM IR function:\n\n")[-1]
        resp = MagicMock()
        resp.choices = [MagicMock()]
        resp.choices[0].message.content = body
        return resp

    with patch('llmcompile.phases.p3_route.litellm') as mock_litellm:
        mock_litellm.acompletion = identity_completion
        route_module(parsed, config)

    reconstruct_module(parsed, config)
    return {f.name: f for f in parsed.functions}


def test_reconstruct_builds_assemblable_candidate_ir():
    fns = _run_through_reconstruct(IR_WITH_SIBLING_CALL, threshold=1)
    for name, rec in fns.items():
        assert rec.candidate_ir is not None
        # candidate must re-parse + verify on its own
        m = llvm.parse_assembly(rec.candidate_ir)
        m.verify()
    # the sibling-calling function keeps the declaration
    assert "declare i32 @add" in fns["use"].candidate_ir


def test_reconstruct_skips_triaged_functions():
    # threshold 2: @add (complexity 1) triaged out -> no candidate
    fns = _run_through_reconstruct(IR_WITH_SIBLING_CALL, threshold=2)
    assert fns["add"].triaged_out is True
    assert fns["add"].candidate_ir is None


def test_reconstruct_skips_when_no_llm_output():
    parsed = parse_module(IR_WITH_SIBLING_CALL)
    config = PipelineConfig(triage=TriageConfig(complexity_threshold=1))
    triage_module(parsed, config)
    # deliberately skip route_module: no llm_output anywhere
    reconstruct_module(parsed, config)
    for rec in parsed.functions:
        assert rec.candidate_ir is None


def test_reconstruct_is_deterministic():
    a = _run_through_reconstruct(IR_WITH_SIBLING_CALL, threshold=1)
    b = _run_through_reconstruct(IR_WITH_SIBLING_CALL, threshold=1)
    assert {n: r.candidate_ir for n, r in a.items()} == {n: r.candidate_ir for n, r in b.items()}
