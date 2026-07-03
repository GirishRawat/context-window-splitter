"""Phase 3 — LLM Execution & Routing.

This is the *only* phase permitted to be probabilistic and async (see README
§2). Replaces the Milestone 1 identity stub with real LLM integration using
LiteLLM and asyncio concurrency.

Contract established here (relied on by Phases 4-6):

* ``FunctionRecord.llm_output`` is a single ``define`` block for the *same*
  function — NOT a full module and NOT wrapped in the shared preamble. Phase 4
  re-wraps it into a standalone candidate; Phase 6 substitutes it into the final
  module. The real Phase 3 must sanitize model output down to exactly this.
* Triaged-out functions are skipped entirely (no ``llm_output``); they fall
  through to Phase 6 as the untouched original.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

# Ensure litellm is imported. If it fails, Phase 3 will loudly fail when run,
# which is correct since it's an M4 dependency.
try:
    import litellm
except ImportError:
    litellm = None

from llmcompile.models import ParsedModule, FunctionRecord
from llmcompile.config import PipelineConfig, get_config

logger = logging.getLogger(__name__)


def sanitize_llm_output(raw_text: str) -> str | None:
    """Extract a valid ``define ... }`` block from the LLM output.

    Strips markdown fences and conversational prose. If the LLM returns multiple
    functions or malformed text that doesn't cleanly bound a define block,
    it returns None so downstream phases fall back safely.
    """
    # Attempt to find the outermost define block. We use a non-greedy match
    # up to a closing brace on its own line, or fallback to the last brace.
    # LLMs often wrap in ```llvm ... ``` or add "Here is the code:".
    
    # Strategy 1: strict regex for a block starting with define and ending with }
    match = re.search(r"(define\s+.*?^})", raw_text, re.DOTALL | re.MULTILINE)
    if match:
        return match.group(1).strip()
        
    # Strategy 2: fallback search for first 'define ' and last '}'
    start_idx = raw_text.find("define ")
    end_idx = raw_text.rfind("}")
    
    if start_idx != -1 and end_idx != -1 and start_idx < end_idx:
        candidate = raw_text[start_idx:end_idx+1].strip()
        # Basic sanity check: does it look like a function body?
        if candidate.startswith("define ") and candidate.endswith("}"):
            return candidate
            
    return None


async def _optimize_function(
    record: FunctionRecord,
    model_name: str,
    timeout_seconds: int,
    semaphore: asyncio.Semaphore,
) -> None:
    """Execute the LLM call for a single function under a concurrency semaphore."""
    if litellm is None:
        logger.error("litellm is not installed. Cannot execute LLM optimization.")
        record.llm_output = None
        return

    system_prompt = (
        "You are an expert compiler optimization engineer. "
        "Your goal is to optimize the provided LLVM IR function while preserving exactly "
        "its semantic behavior. Focus on instruction reduction, loop unrolling, and "
        "simplifying control flow where mathematically safe.\n\n"
        "Output ONLY the optimized `define` block for the function. "
        "Do not output markdown formatting, preamble, explanations, or any text other than the IR."
    )
    
    user_prompt = f"Optimize this LLVM IR function:\n\n{record.original_ir}"

    async with semaphore:
        logger.debug(f"[{record.name}] Sending to {model_name}...")
        try:
            response = await litellm.acompletion(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.0, # Deterministic (greedy) decoding
                timeout=timeout_seconds,
            )
            raw_output = response.choices[0].message.content
            sanitized = sanitize_llm_output(raw_output)
            
            if sanitized:
                record.llm_output = sanitized
                logger.info(f"[{record.name}] Optimization returned cleanly from {model_name}")
            else:
                logger.warning(f"[{record.name}] Failed to extract valid IR from {model_name} output")
                record.llm_output = None
                
        except Exception as e:
            logger.error(f"[{record.name}] LLM call to {model_name} failed: {e}")
            record.llm_output = None


async def _route_module_async(parsed: ParsedModule, config: PipelineConfig) -> None:
    """Async core of Phase 3."""
    tasks = []
    
    # We create a semaphore per tier based on max_concurrent
    semaphores = {}
    for tier_name, tier_config in config.llm_routing.tiers.items():
        semaphores[tier_name] = asyncio.Semaphore(tier_config.max_concurrent)

    for record in parsed.functions:
        if record.triaged_out:
            logger.debug(f"Skipping routing for {record.name} (triaged out)")
            continue

        # 1. Determine Tier based on token count
        token_count = record.token_count or 0
        assigned_tier_name = "fast" # default
        
        for name, (min_t, max_t) in config.triage.token_tier_boundaries.items():
            if min_t <= token_count < max_t:
                assigned_tier_name = name
                break
                
        # 2. Select Model (Deterministic: first model in the tier's list)
        tier_config = config.llm_routing.tiers[assigned_tier_name]
        if not tier_config.models:
            logger.warning(f"No models configured for tier '{assigned_tier_name}'. Falling back.")
            record.llm_output = None
            continue
            
        model_name = tier_config.models[0]
        record.assigned_model = model_name
        
        # 3. Schedule task
        task = asyncio.create_task(
            _optimize_function(
                record=record,
                model_name=model_name,
                timeout_seconds=tier_config.timeout_seconds,
                semaphore=semaphores[assigned_tier_name],
            )
        )
        tasks.append(task)

    if tasks:
        await asyncio.gather(*tasks)


def route_module(parsed: ParsedModule, config: PipelineConfig | None = None) -> None:
    """Populate each non-triaged function's ``llm_output`` via concurrent LLM calls.

    Mutates ``parsed.functions`` in place, setting ``assigned_model`` and
    ``llm_output`` for every function that was not triaged out. Maintains a 
    synchronous exterior API to keep the orchestrator deterministic.

    Args:
        parsed: The ParsedModule from Phase 1, after Phase 2 triage.
        config: Pipeline configuration (uses DEFAULT_CONFIG if None).
    """
    if config is None:
        config = get_config()

    # Bridge the sync/async boundary cleanly.
    asyncio.run(_route_module_async(parsed, config))
