"""Tests for Phase 3 routing (LiteLLM and asyncio concurrency).

Run with:
    python -m pytest llmcompile/tests/test_p3_route.py -v
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from llmcompile.phases.p1_parse import parse_module
from llmcompile.phases.p2_triage import triage_module
from llmcompile.phases.p3_route import route_module, sanitize_llm_output
from llmcompile.config import PipelineConfig, TriageConfig, LLMRoutingConfig, ModelTier

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


# ---------------------------------------------------------------------------
# Tests for Output Sanitization
# ---------------------------------------------------------------------------

def test_sanitize_perfect_match():
    raw = "define i32 @test() {\n  ret i32 0\n}"
    sanitized = sanitize_llm_output(raw)
    assert sanitized == raw

def test_sanitize_with_markdown():
    raw = "```llvm\ndefine i32 @test() {\n  ret i32 0\n}\n```"
    sanitized = sanitize_llm_output(raw)
    assert sanitized == "define i32 @test() {\n  ret i32 0\n}"

def test_sanitize_with_prose():
    raw = (
        "Here is the optimized function:\n\n"
        "```\n"
        "define i32 @test() {\n"
        "  ret i32 0\n"
        "}\n"
        "```\n"
        "Hope this helps!"
    )
    sanitized = sanitize_llm_output(raw)
    assert sanitized == "define i32 @test() {\n  ret i32 0\n}"

def test_sanitize_failure_returns_none():
    # Only declare, no define block body
    raw = "declare i32 @test()"
    assert sanitize_llm_output(raw) is None
    
    # Missing closing brace
    raw = "define i32 @test() {\n  ret i32 0"
    assert sanitize_llm_output(raw) is None

# ---------------------------------------------------------------------------
# Tests for Async Routing and Model Assignment
# ---------------------------------------------------------------------------

def _setup_config() -> PipelineConfig:
    config = PipelineConfig(
        triage=TriageConfig(
            complexity_threshold=1,
            token_tier_boundaries={
                "fast": (0, 100),       # up to 100
                "mid": (100, 200),      # 100-200
                "frontier": (200, 9999) # 200+
            }
        ),
        llm_routing=LLMRoutingConfig(
            tiers={
                "fast": ModelTier("fast", ["fast-model-1"]),
                "mid": ModelTier("mid", ["mid-model-1", "mid-model-2"]),
                "frontier": ModelTier("frontier", ["frontier-model-1"]),
            }
        )
    )
    return config

def test_routing_tiers_and_model_assignment():
    parsed = parse_module(SAMPLE_IR)
    config = _setup_config()
    
    # Force token counts to simulate routing
    for f in parsed.functions:
        if f.name == "add":
            f.token_count = 50   # should go to fast-model-1
        elif f.name == "branchy":
            f.token_count = 150  # should go to mid-model-1
            
    triage_module(parsed, config)
    
    # Mock litellm.acompletion
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "define i32 @dummy() {\n  ret i32 0\n}"
    
    with patch('llmcompile.phases.p3_route.litellm') as mock_litellm:
        mock_litellm.acompletion = AsyncMock(return_value=mock_response)
        
        route_module(parsed, config)
        
        # Verify calls were made correctly
        assert mock_litellm.acompletion.call_count == 2
        
        fns = {f.name: f for f in parsed.functions}
        assert fns["add"].assigned_model == "fast-model-1"
        assert fns["branchy"].assigned_model == "mid-model-1"  # First in tier list
        
        assert "define" in fns["add"].llm_output
        assert "define" in fns["branchy"].llm_output

def test_triaged_functions_are_skipped():
    parsed = parse_module(SAMPLE_IR)
    config = _setup_config()
    config.triage.complexity_threshold = 2 # add is complexity 1, branchy is 2
    
    triage_module(parsed, config)
    
    with patch('llmcompile.phases.p3_route.litellm') as mock_litellm:
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "define i32 @dummy() { ret i32 0 }"
        mock_litellm.acompletion = AsyncMock(return_value=mock_response)
        
        route_module(parsed, config)
        
        # Only branchy should be routed (1 call)
        assert mock_litellm.acompletion.call_count == 1
        
        fns = {f.name: f for f in parsed.functions}
        assert fns["add"].assigned_model is None
        assert fns["add"].llm_output is None
        assert fns["add"].triaged_out is True
        
        assert fns["branchy"].assigned_model == "mid-model-1" # token_count > 100
        assert fns["branchy"].triaged_out is False

def test_llm_timeout_or_error_falls_back():
    parsed = parse_module(SAMPLE_IR)
    config = _setup_config()
    triage_module(parsed, config)
    
    with patch('llmcompile.phases.p3_route.litellm') as mock_litellm:
        # Mock an exception during API call
        mock_litellm.acompletion = AsyncMock(side_effect=Exception("API Timeout"))
        
        route_module(parsed, config)
        
        fns = {f.name: f for f in parsed.functions}
        # Model should be assigned
        assert fns["add"].assigned_model == "fast-model-1"
        # But output should be gracefully set to None
        assert fns["add"].llm_output is None
