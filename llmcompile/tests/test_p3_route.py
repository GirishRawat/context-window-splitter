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
        
        # Mock health check to pass so we actually reach the LLM calls
        with patch('llmcompile.phases.p3_route._check_ollama_health', return_value=True):
            route_module(parsed, config)
        
        fns = {f.name: f for f in parsed.functions}
        # Model should be assigned
        assert fns["add"].assigned_model == "fast-model-1"
        # But output should be gracefully set to None
        assert fns["add"].llm_output is None


# ---------------------------------------------------------------------------
# Ollama-Specific Tests
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Gemini-Specific Tests
# ---------------------------------------------------------------------------

def _gemini_config() -> PipelineConfig:
    config = PipelineConfig(
        triage=TriageConfig(
            complexity_threshold=1,
            token_tier_boundaries={"fast": (0, 9999), "mid": (9999, 19999), "frontier": (19999, 99999)}
        ),
        llm_routing=LLMRoutingConfig(
            tiers={
                "fast": ModelTier("fast", ["gemini/gemini-2.5-flash"]),
                "mid": ModelTier("mid", ["gemini/gemini-2.5-flash"]),
                "frontier": ModelTier("frontier", ["gemini/gemini-2.5-flash"]),
            }
        ),
    )
    # No pacing delay in unit tests.
    config.llm_routing.requests_per_minute = 1_000_000
    return config


def test_gemini_branch_no_prefill_no_signature_dup():
    """Gemini path sends no trailing assistant-prefill and does not duplicate the signature."""
    import os
    import llmcompile.phases.p3_route as p3

    config = _gemini_config()
    parsed = parse_module(SAMPLE_IR)
    triage_module(parsed, config)

    # Gemini returns a FULL define block (not a prefill continuation).
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = (
        "define i32 @add(i32 %a, i32 %b) {\n  %r = add i32 %a, %b\n  ret i32 %r\n}"
    )

    p3._req_times.clear()
    with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}):
        with patch('llmcompile.phases.p3_route.litellm') as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_response)
            route_module(parsed, config)

            assert mock_litellm.acompletion.call_count >= 1
            # No assistant prefill: the final message must be the user turn.
            for call in mock_litellm.acompletion.call_args_list:
                messages = call.kwargs["messages"]
                assert messages[-1]["role"] == "user"
            fns = {f.name: f for f in parsed.functions}
            assert fns["add"].assigned_model == "gemini/gemini-2.5-flash"
            # No signature prepend: exactly one define in the recorded output.
            assert fns["add"].llm_output.count("define") == 1


def test_gemini_missing_key_falls_back():
    """With no GEMINI_API_KEY/GOOGLE_API_KEY, pre-flight nulls output and never calls the API."""
    import os

    config = _gemini_config()
    parsed = parse_module(SAMPLE_IR)
    triage_module(parsed, config)

    with patch.dict(os.environ):  # saved/restored automatically
        os.environ.pop("GEMINI_API_KEY", None)
        os.environ.pop("GOOGLE_API_KEY", None)
        with patch('llmcompile.phases.p3_route.litellm') as mock_litellm:
            mock_litellm.acompletion = AsyncMock()
            route_module(parsed, config)

            mock_litellm.acompletion.assert_not_called()
            for fn in parsed.functions:
                if not fn.triaged_out:
                    assert fn.llm_output is None


def test_ollama_health_check_failure_falls_back():
    """When Ollama is unreachable, all functions should get llm_output=None."""
    config = PipelineConfig(
        triage=TriageConfig(complexity_threshold=1),
        llm_routing=LLMRoutingConfig(
            tiers={
                "fast": ModelTier("fast", ["ollama_chat/qwen2.5-coder:3b"]),
                "mid": ModelTier("mid", ["ollama_chat/qwen2.5-coder:7b"]),
                "frontier": ModelTier("frontier", ["ollama_chat/qwen2.5-coder:7b"]),
            }
        )
    )
    
    parsed = parse_module(SAMPLE_IR)
    triage_module(parsed, config)
    
    with patch('llmcompile.phases.p3_route.litellm') as mock_litellm:
        mock_litellm.acompletion = AsyncMock()
        
        # Mock health check to FAIL
        with patch('llmcompile.phases.p3_route._check_ollama_health', return_value=False):
            route_module(parsed, config)
        
        # LLM should never have been called
        mock_litellm.acompletion.assert_not_called()
        
        # All non-triaged functions should have llm_output = None
        for fn in parsed.functions:
            if not fn.triaged_out:
                assert fn.llm_output is None, f"{fn.name} should have None llm_output when Ollama is down"

