"""Configuration for the LLM compilation orchestration pipeline.

All thresholds, model names, tool paths, timeouts, and routing logic are
centralized here. No hard-coded constants in phase modules.

Local inference via Ollama — no API keys or cloud costs required.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
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
# Ollama (local inference) configuration
# ---------------------------------------------------------------------------

@dataclass
class OllamaConfig:
    """Configuration for the local Ollama inference server.

    Ollama runs models locally on-device. It exposes an OpenAI-compatible API
    that LiteLLM can target using the ``ollama_chat/`` model prefix.
    See: https://ollama.com/
    """

    # Base URL of the Ollama server (default local install)
    base_url: str = "http://localhost:11434"

    # Whether to auto-pull missing models when referenced (requires internet)
    pull_on_start: bool = False

    def __post_init__(self):
        # Allow override from environment
        self.base_url = os.getenv("OLLAMA_BASE_URL", self.base_url)


# ---------------------------------------------------------------------------
# Phase 3: LLM routing configuration
# ---------------------------------------------------------------------------

@dataclass
class ModelTier:
    """Configuration for a model tier."""
    name: str
    models: list[str]  # Model identifiers for LiteLLM (use ollama_chat/ prefix)
    max_concurrent: int = 2  # Concurrency limit per tier (low for local inference)
    timeout_seconds: int = 120


@dataclass
class LLMRoutingConfig:
    """Phase 3 LLM routing configuration.

    All models use the ``ollama_chat/`` prefix for LiteLLM's Ollama provider.
    Concurrency is kept low because local GPU inference is sequential.
    Timeouts are generous because local models are slower than cloud APIs.
    """

    # Model tiers by name (matches TriageConfig tier names)
    tiers: Dict[str, ModelTier] = None

    # Global concurrency limit across all tiers
    global_max_concurrent: int = 4

    def __post_init__(self):
        if self.tiers is None:
            self.tiers = {
                "fast": ModelTier(
                    name="fast",
                    models=["ollama_chat/qwen2.5-coder:3b"],
                    max_concurrent=2,
                    timeout_seconds=120
                ),
                "mid": ModelTier(
                    name="mid",
                    models=["ollama_chat/qwen2.5-coder:7b"],
                    max_concurrent=1,
                    timeout_seconds=180
                ),
                "frontier": ModelTier(
                    name="frontier",
                    models=["ollama_chat/qwen2.5-coder:7b"],
                    max_concurrent=1,
                    timeout_seconds=300
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
        # Auto-detection only fills in paths left at their default sentinel.
        # An explicitly-provided path (constructor arg) is authoritative and is
        # never overridden — this keeps tests hermetic and lets callers pin a
        # specific toolchain regardless of what happens to be on the host.
        llvm_as_is_default = self.llvm_as_path == "llvm-as"
        alive_tv_is_default = self.alive_tv_path == "alive-tv"

        # Default fallback paths for JupyterHub build if they exist on the host
        jovyan_llvm_as = "/home/jovyan/llvm_toolchain/llvm-project/llvm/build/bin/llvm-as"
        jovyan_alive_tv = "/home/jovyan/llvm_toolchain/alive2/build/alive-tv"

        if llvm_as_is_default and os.path.exists(jovyan_llvm_as):
            self.llvm_as_path = jovyan_llvm_as
        if alive_tv_is_default and os.path.exists(jovyan_alive_tv):
            self.alive_tv_path = jovyan_alive_tv

        # Read from toolchain_versions.lock if it exists (for local Mac builds)
        lock_path = os.path.expanduser("~/llvm_toolchain/toolchain_versions.lock")
        if os.path.exists(lock_path):
            try:
                with open(lock_path, "r") as f:
                    for line in f:
                        line = line.strip()
                        if llvm_as_is_default and line.startswith("llvm_as_path="):
                            self.llvm_as_path = os.path.expandvars(line.split("=", 1)[1])
                        elif alive_tv_is_default and line.startswith("alive_tv_path="):
                            self.alive_tv_path = os.path.expandvars(line.split("=", 1)[1])
            except Exception:
                pass

        # Environment variables override only default (non-explicit) paths.
        if llvm_as_is_default:
            self.llvm_as_path = os.getenv("LLVM_AS_PATH", self.llvm_as_path)
        if alive_tv_is_default:
            self.alive_tv_path = os.getenv("ALIVE_TV_PATH", self.alive_tv_path)


# ---------------------------------------------------------------------------
# Phase 6: Final Compilation configuration
# ---------------------------------------------------------------------------

@dataclass
class CompilationConfig:
    """Phase 6 binary compilation configuration."""
    clang_path: str = "clang"
    compile_flags: list[str] = field(default_factory=lambda: ["-O0"])
    timeout_seconds: int = 60

# ---------------------------------------------------------------------------
# Global pipeline configuration
# ---------------------------------------------------------------------------

@dataclass
class PipelineConfig:
    """Global configuration for the entire pipeline."""

    triage: TriageConfig = None
    llm_routing: LLMRoutingConfig = None
    verification: VerificationConfig = None
    ollama: OllamaConfig = None
    compilation: CompilationConfig = None

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
        if self.ollama is None:
            self.ollama = OllamaConfig()
        if self.compilation is None:
            self.compilation = CompilationConfig()


# ---------------------------------------------------------------------------
# Default configuration instance
# ---------------------------------------------------------------------------

# This is the config used by default throughout the pipeline.
# Can be overridden by creating a new PipelineConfig instance.
DEFAULT_CONFIG = PipelineConfig()


def get_config() -> PipelineConfig:
    """Get the default pipeline configuration."""
    return DEFAULT_CONFIG
