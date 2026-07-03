"""Configuration for the LLM compilation orchestration pipeline.

All thresholds, model names, tool paths, timeouts, and routing logic are
centralized here. No hard-coded constants in phase modules.

Credentials (API keys) should come from environment variables, never committed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict


# ---------------------------------------------------------------------------
# Phase 2: Triage thresholds
# ---------------------------------------------------------------------------

@dataclass
class TriageConfig:
    """Phase 2 triage thresholds."""

    # Functions below this complexity are triaged out (skip LLM optimization)
    complexity_threshold: int = 5

    # Token count boundaries for routing tiers (used in Phase 3)
    token_tier_boundaries: Dict[str, tuple[int, int]] = None

    def __post_init__(self):
        if self.token_tier_boundaries is None:
            # Format: tier_name -> (min_tokens, max_tokens)
            # max_tokens can be float('inf') for unbounded
            self.token_tier_boundaries = {
                "fast": (0, 8000),           # < 8k tokens -> fast/local models
                "mid": (8000, 32000),        # 8k-32k -> mid-tier models
                "frontier": (32000, float('inf'))  # 32k+ -> frontier models
            }


# ---------------------------------------------------------------------------
# Phase 3: LLM routing configuration
# ---------------------------------------------------------------------------

@dataclass
class ModelTier:
    """Configuration for a model tier."""
    name: str
    models: list[str]  # Model identifiers for LiteLLM
    max_concurrent: int = 10  # Concurrency limit per tier
    timeout_seconds: int = 120


@dataclass
class LLMRoutingConfig:
    """Phase 3 LLM routing configuration."""

    # Model tiers by name (matches TriageConfig tier names)
    tiers: Dict[str, ModelTier] = None

    # Global concurrency limit across all tiers
    global_max_concurrent: int = 50

    def __post_init__(self):
        if self.tiers is None:
            self.tiers = {
                "fast": ModelTier(
                    name="fast",
                    models=["qwen/qwen-3b"],  # Example - adjust based on availability
                    max_concurrent=20,
                    timeout_seconds=60
                ),
                "mid": ModelTier(
                    name="mid",
                    models=["meta-llama/Llama-3-8b", "qwen/qwen-7b"],
                    max_concurrent=15,
                    timeout_seconds=90
                ),
                "frontier": ModelTier(
                    name="frontier",
                    models=["gpt-4o", "claude-3-5-sonnet-20241022", "qwen/qwen-32b"],
                    max_concurrent=5,
                    timeout_seconds=180
                )
            }


# ---------------------------------------------------------------------------
# Phase 5: Verification toolchain paths
# ---------------------------------------------------------------------------

@dataclass
class VerificationConfig:
    """Phase 5 verification toolchain configuration."""

    # Path to llvm-as (system llvm-as or from custom build)
    llvm_as_path: str = "llvm-as"

    # Path to alive-tv binary (from Alive2 build)
    alive_tv_path: str = "alive-tv"

    # llvm-as syntax-check timeout in seconds (should be near-instant)
    llvm_as_timeout: int = 10

    # alive-tv timeout in seconds
    alive_tv_timeout: int = 30

    # SMT solver timeout. Reserved: intended to be passed to alive-tv (e.g.
    # --smt-to) once the exact flag/units are pinned against the Alive2 build.
    # Until then the subprocess-level alive_tv_timeout is the hard guard, so we
    # do NOT pass an unverified flag that could break every real invocation.
    smt_timeout: int = 20

    def __post_init__(self):
        # Default fallback paths for JupyterHub build if they exist on the host
        jovyan_llvm_as = "/home/jovyan/llvm_toolchain/llvm-project/llvm/build/bin/llvm-as"
        jovyan_alive_tv = "/home/jovyan/llvm_toolchain/alive2/build/alive-tv"

        if os.path.exists(jovyan_llvm_as) and self.llvm_as_path == "llvm-as":
            self.llvm_as_path = jovyan_llvm_as
        if os.path.exists(jovyan_alive_tv) and self.alive_tv_path == "alive-tv":
            self.alive_tv_path = jovyan_alive_tv

        # Allow override from environment
        self.llvm_as_path = os.getenv("LLVM_AS_PATH", self.llvm_as_path)
        self.alive_tv_path = os.getenv("ALIVE_TV_PATH", self.alive_tv_path)


# ---------------------------------------------------------------------------
# Global pipeline configuration
# ---------------------------------------------------------------------------

@dataclass
class PipelineConfig:
    """Global configuration for the entire pipeline."""

    triage: TriageConfig = None
    llm_routing: LLMRoutingConfig = None
    verification: VerificationConfig = None

    # Logging level
    log_level: str = "INFO"

    # Reproducibility seed (for any randomness in Phase 3 model selection)
    random_seed: int = 42

    def __post_init__(self):
        if self.triage is None:
            self.triage = TriageConfig()
        if self.llm_routing is None:
            self.llm_routing = LLMRoutingConfig()
        if self.verification is None:
            self.verification = VerificationConfig()


# ---------------------------------------------------------------------------
# Default configuration instance
# ---------------------------------------------------------------------------

# This is the config used by default throughout the pipeline.
# Can be overridden by creating a new PipelineConfig instance.
DEFAULT_CONFIG = PipelineConfig()


def get_config() -> PipelineConfig:
    """Get the default pipeline configuration."""
    return DEFAULT_CONFIG
