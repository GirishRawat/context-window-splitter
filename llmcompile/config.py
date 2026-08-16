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

    Routes ALL tiers to a single cloud model, selected via ``LLM_BACKEND``
    ("gemini" (default) or "openrouter"), via LiteLLM's ``gemini/`` or
    ``openrouter/`` provider, to evaluate whether a stronger model produces
    verified optimizations where local Qwen models only echoed the input. To
    revert to local inference, set each tier's ``models`` back to an
    ``ollama/...`` id.

    Because both free tiers are rate-limited (RPM/RPD), the real throttle is
    the module-level wall-clock rate limiter in ``p3_route.py`` (paced to
    ``requests_per_minute``), NOT the per-tier concurrency semaphore. Concurrency
    is kept modest so a handful of calls can overlap up to the RPM budget.
    """

    # Model tiers by name (matches TriageConfig tier names)
    tiers: Dict[str, ModelTier] = None

    # Global concurrency limit across all tiers
    global_max_concurrent: int = 4

    # --- Rate limiting / retry (used by the gemini/ path in p3_route.py) ---
    # Requests-per-minute cap enforced globally across all Gemini calls. Set
    # conservatively for the free tier; overridable via GEMINI_RPM.
    requests_per_minute: int = 5
    # Retry attempts on rate-limit (429) / transient errors before falling back.
    max_retries: int = 5
    # Base delay (seconds) for exponential backoff between retries.
    retry_base_delay: float = 4.0

    def __post_init__(self):
        # Which backend to route to, selected via LLM_BACKEND env var:
        #   "gemini"     (default) -- Google Gemini free tier
        #   "openrouter" -- free-tier frontier-scale models via OpenRouter,
        #                   no daily 20-request cliff like Gemini's free tier
        #                   (50 req/day unfunded, 20 req/min)
        #   "local_gpu"  -- self-hosted Ollama on a real GPU box (e.g. a
        #                   JupyterHub instance with an A40/A100), no rate
        #                   limiting or daily caps at all since it's your
        #                   own hardware. Uses the same raw-HTTP Ollama path
        #                   in p3_route.py as the earlier qwen 3b/7b runs
        #                   (model_name.startswith("ollama/")), just pointed
        #                   at a bigger model.
        backend = os.getenv("LLM_BACKEND", "gemini").lower()

        if backend == "openrouter":
            # Default: Nemotron 3 Ultra (550B/55B-active MoE), the largest,
            # most frontier-scale model on OpenRouter's free tier as of
            # 2026-08. Override via OPENROUTER_MODEL, e.g.
            # "openrouter/cohere/north-mini-code:free" as a coding-specialist
            # fallback if Nemotron gets provider-side throttled.
            model_id = os.getenv(
                "OPENROUTER_MODEL",
                "openrouter/nvidia/nemotron-3-ultra-550b-a55b:free",
            )
            default_rpm = 15  # stay under the 20/min free-tier cap
        elif backend == "local_gpu":
            # Default: Qwen2.5-Coder-32B-Instruct, 4-bit quantized (~20GB,
            # fits comfortably on a 46GB A40 with headroom for KV cache).
            # Pull it first with: ollama pull qwen2.5-coder:32b
            # Override via OLLAMA_MODEL for a different local model.
            model_id = os.getenv("OLLAMA_MODEL", "ollama/qwen2.5-coder:32b")
            default_rpm = 1000  # no meaningful cap on your own hardware
        else:
            # Model id is overridable via GEMINI_MODEL (e.g. set to
            # "gemini/gemini-1.5-flash" for higher free-tier throughput).
            model_id = os.getenv("GEMINI_MODEL", "gemini/gemini-3.5-flash")
            default_rpm = 5

        # Local GPU inference has no provider-side throttling, but a single
        # A40 still decodes one request at a time in practice (Ollama
        # defaults to serializing per-model), and our largest functions
        # (~24k prompt tokens) can take a while even on-GPU -- give it a
        # generous timeout rather than the 120s tuned for cloud APIs.
        # Raised from 300s for local_gpu: the 32b subset run came back 26/39
        # `pending`, and the completed rows averaged 234s with a max of 297s --
        # i.e. the 300s ceiling was clipping the tail of the latency
        # distribution, turning slow-but-fine generations into empty-message
        # asyncio timeouts. Override with LLM_TIMEOUT_SECONDS.
        timeout_seconds = 600 if backend == "local_gpu" else 120
        timeout_env = os.getenv("LLM_TIMEOUT_SECONDS")
        if timeout_env:
            try:
                timeout_seconds = int(timeout_env)
            except ValueError:
                pass

        if self.tiers is None:
            self.tiers = {
                "fast": ModelTier(
                    name="fast",
                    models=[model_id],
                    max_concurrent=1,
                    timeout_seconds=timeout_seconds
                ),
                "mid": ModelTier(
                    name="mid",
                    models=[model_id],
                    max_concurrent=1,
                    timeout_seconds=timeout_seconds
                ),
                "frontier": ModelTier(
                    name="frontier",
                    models=[model_id],
                    max_concurrent=1,
                    timeout_seconds=timeout_seconds
                )
            }

        self.requests_per_minute = default_rpm

        # Allow overriding the RPM cap from the environment (checked in order;
        # the backend-specific var wins if both happen to be set).
        rpm_env = os.getenv("OPENROUTER_RPM") if backend == "openrouter" else os.getenv("GEMINI_RPM")
        if rpm_env:
            try:
                self.requests_per_minute = int(rpm_env)
            except ValueError:
                pass


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

    # Path to opt (LLVM optimizer, used only to compute the -O2 baseline
    # metric for eval reporting -- not part of the correctness-critical path)
    opt_path: str = "opt"

    # llvm-as syntax-check timeout in seconds (should be near-instant)
    llvm_as_timeout: int = 10

    # alive-tv timeout in seconds. Raised from 30s: the local-model runs mostly
    # asked Alive2 to prove trivial no-ops (every `passed` row on real code was
    # a 0.00% reduction), so 30s was never actually exercised. A model that
    # returns genuinely *changed* IR gives the solver real work, and a too-tight
    # budget silently converts real wins into UNSUPPORTED. Override with
    # ALIVE_TV_TIMEOUT.
    alive_tv_timeout: int = 120

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
        opt_is_default = self.opt_path == "opt"

        # Default fallback paths for JupyterHub build if they exist on the host
        jovyan_llvm_as = "/home/jovyan/llvm_toolchain/llvm-project/llvm/build/bin/llvm-as"
        jovyan_alive_tv = "/home/jovyan/llvm_toolchain/alive2/build/alive-tv"
        jovyan_opt = "/home/jovyan/llvm_toolchain/llvm-project/llvm/build/bin/opt"

        if llvm_as_is_default and os.path.exists(jovyan_llvm_as):
            self.llvm_as_path = jovyan_llvm_as
        if alive_tv_is_default and os.path.exists(jovyan_alive_tv):
            self.alive_tv_path = jovyan_alive_tv
        if opt_is_default and os.path.exists(jovyan_opt):
            self.opt_path = jovyan_opt

        # Default fallback path for the local Mac build if it exists on the host
        mac_opt = os.path.expanduser("~/llvm_toolchain/llvm-project/llvm/build/bin/opt")
        if opt_is_default and os.path.exists(mac_opt):
            self.opt_path = mac_opt

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
                        elif opt_is_default and line.startswith("opt_path="):
                            self.opt_path = os.path.expandvars(line.split("=", 1)[1])
            except Exception:
                pass

        # Environment variables override only default (non-explicit) paths.
        if llvm_as_is_default:
            self.llvm_as_path = os.getenv("LLVM_AS_PATH", self.llvm_as_path)
        if alive_tv_is_default:
            self.alive_tv_path = os.getenv("ALIVE_TV_PATH", self.alive_tv_path)
        if opt_is_default:
            self.opt_path = os.getenv("OPT_PATH", self.opt_path)

        # Timeouts are env-overridable so a long unattended corpus run can be
        # retuned without editing code (README rule: no hard-coded timeouts).
        for env_name, attr in (
            ("ALIVE_TV_TIMEOUT", "alive_tv_timeout"),
            ("LLVM_AS_TIMEOUT", "llvm_as_timeout"),
        ):
            raw = os.getenv(env_name)
            if raw:
                try:
                    setattr(self, attr, int(raw))
                except ValueError:
                    pass


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
