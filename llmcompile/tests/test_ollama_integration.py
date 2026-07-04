"""Integration tests for Phase 3 with a real Ollama instance.

These tests require Ollama to be running locally with at least one model pulled.
They are automatically skipped if Ollama is not reachable.

Run with:
    python -m pytest llmcompile/tests/test_ollama_integration.py -v
"""

from __future__ import annotations

import pytest
import urllib.request
import json

from llmcompile.phases.p1_parse import parse_module
from llmcompile.phases.p2_triage import triage_module
from llmcompile.phases.p3_route import route_module
from llmcompile.config import PipelineConfig, TriageConfig, LLMRoutingConfig, ModelTier


def _ollama_available() -> bool:
    """Check if Ollama is running and has at least one model."""
    try:
        req = urllib.request.Request("http://localhost:11434/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode())
                return len(data.get("models", [])) > 0
    except Exception:
        pass
    return False


def _get_available_model() -> str | None:
    """Get the name of the first available Ollama model."""
    try:
        req = urllib.request.Request("http://localhost:11434/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode())
                models = data.get("models", [])
                if models:
                    return models[0]["name"]
    except Exception:
        pass
    return None


ollama_is_available = _ollama_available()
skip_reason = "Ollama is not running or has no models pulled"


SIMPLE_IR = (
    "define i32 @add(i32 %a, i32 %b) {\n"
    "entry:\n"
    "  %r = add i32 %a, %b\n"
    "  ret i32 %r\n"
    "}\n"
)


@pytest.mark.skipif(not ollama_is_available, reason=skip_reason)
class TestOllamaIntegration:
    """Integration tests that talk to a real Ollama instance."""

    def test_ollama_responds_to_ir_prompt(self):
        """Send a simple IR function to Ollama and check we get a define block back."""
        model_name = _get_available_model()
        assert model_name is not None, "No model available"

        config = PipelineConfig(
            triage=TriageConfig(complexity_threshold=1),
            llm_routing=LLMRoutingConfig(
                tiers={
                    "fast": ModelTier("fast", [f"ollama_chat/{model_name}"],
                                      max_concurrent=1, timeout_seconds=120),
                    "mid": ModelTier("mid", [f"ollama_chat/{model_name}"],
                                    max_concurrent=1, timeout_seconds=120),
                    "frontier": ModelTier("frontier", [f"ollama_chat/{model_name}"],
                                         max_concurrent=1, timeout_seconds=120),
                }
            )
        )

        parsed = parse_module(SIMPLE_IR)
        triage_module(parsed, config)
        route_module(parsed, config)

        fn = parsed.functions[0]
        assert fn.assigned_model == f"ollama_chat/{model_name}"
        # The model should return *something* — either valid IR or None
        # (we can't guarantee the output is valid IR, just that the pipeline doesn't crash)
        # If llm_output is not None, it should contain 'define'
        if fn.llm_output is not None:
            assert "define" in fn.llm_output, (
                f"Expected 'define' in LLM output, got: {fn.llm_output[:200]}"
            )

    def test_full_pipeline_completes_without_error(self):
        """Run the full pipeline end-to-end with Ollama and verify it completes."""
        from llmcompile.orchestrator import compile_module

        model_name = _get_available_model()
        assert model_name is not None

        config = PipelineConfig(
            triage=TriageConfig(complexity_threshold=1),
            llm_routing=LLMRoutingConfig(
                tiers={
                    "fast": ModelTier("fast", [f"ollama_chat/{model_name}"],
                                      max_concurrent=1, timeout_seconds=120),
                    "mid": ModelTier("mid", [f"ollama_chat/{model_name}"],
                                    max_concurrent=1, timeout_seconds=120),
                    "frontier": ModelTier("frontier", [f"ollama_chat/{model_name}"],
                                         max_concurrent=1, timeout_seconds=120),
                }
            )
        )

        # This should complete without raising
        parsed = compile_module(SIMPLE_IR, config)

        # final_module_ir should always be set (either optimized or fallback)
        assert parsed.final_module_ir is not None
        assert len(parsed.functions) == 1
