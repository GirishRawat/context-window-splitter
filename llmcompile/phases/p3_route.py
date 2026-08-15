"""Phase 3 — LLM Execution & Routing.

This is the *only* phase permitted to be probabilistic and async (see README
§2). Uses Ollama for local inference via LiteLLM's ``ollama_chat/`` provider
prefix — zero API costs, all computation on-device.

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
import time
from typing import Any

# Ensure litellm is imported. If it fails, Phase 3 will loudly fail when run.
try:
    import litellm
except ImportError:
    litellm = None

# httpx is used for the lightweight Ollama health check (also a litellm dep).
try:
    import httpx
except ImportError:
    httpx = None

from llmcompile.models import ParsedModule, FunctionRecord
from llmcompile.config import PipelineConfig, get_config
from llmcompile.phases.p1_parse import extract_function_body

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
    # Relaxed to not require `}` to be at the start of a line, to handle 
    # hallucinated stops from models. Uses greedy matching (.*) to avoid stopping
    # prematurely at inline braces (e.g. `load { i32, i32 }`).
    match = re.search(r"(define\s+.*\})", raw_text, re.DOTALL)
    if match:
        return match.group(1).strip()
        
    # Strategy 2: fallback search for first 'define ' and last '}'
    start_idx = raw_text.find("define ")
    end_idx = raw_text.rfind("}")
    
    if start_idx != -1 and end_idx != -1 and start_idx < end_idx:
        candidate = raw_text[start_idx:end_idx+1].strip()
        if candidate.startswith("define") and candidate.endswith("}"):
            return candidate
            
    return None


async def _check_ollama_health(base_url: str) -> bool:
    """Ping the Ollama server to check if it is running and reachable.

    Returns True if Ollama responds, False otherwise. Uses httpx for a
    lightweight async check; falls back to a basic urllib check if httpx
    is unavailable.
    """
    tags_url = f"{base_url}/api/tags"

    if httpx is not None:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(tags_url)
                if resp.status_code == 200:
                    data = resp.json()
                    model_names = [m.get("name", "?") for m in data.get("models", [])]
                    logger.info(f"Ollama is running. Available models: {model_names}")
                    return True
                else:
                    logger.warning(f"Ollama responded with status {resp.status_code}")
                    return False
        except Exception as e:
            logger.warning(f"Ollama health check failed: {e}")
            return False
    else:
        # Fallback: synchronous urllib probe (httpx missing is unusual since
        # it's a litellm dependency, but handle it gracefully).
        import urllib.request
        try:
            req = urllib.request.Request(tags_url, method="GET")
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status == 200
        except Exception as e:
            logger.warning(f"Ollama health check failed (urllib fallback): {e}")
            return False


async def _optimize_function(
    record: FunctionRecord,
    model_name: str,
    timeout_seconds: int,
    semaphore: asyncio.Semaphore,
    config: PipelineConfig,
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
    
    # Strengthened one-shot example with basic blocks, phi nodes, and icmp.
    example_user = "Optimize this LLVM IR function:\n\n" + """define i32 @max(i32 %a, i32 %b) {
entry:
  %cmp = icmp sgt i32 %a, %b
  br i1 %cmp, label %if.then, label %if.else

if.then:
  br label %return

if.else:
  br label %return

return:
  %retval = phi i32 [ %a, %if.then ], [ %b, %if.else ]
  ret i32 %retval
}"""
    
    example_assistant = """```llvm
define i32 @max(i32 %a, i32 %b) {
entry:
  %cmp = icmp sgt i32 %a, %b
  %retval = select i1 %cmp, i32 %a, i32 %b
  ret i32 %retval
}
```"""

    user_prompt = f"Optimize this LLVM IR function:\n\n{record.original_ir}"

    # Isolate this function's own define block (skips the preamble/sibling
    # declares in original_ir, which can contain '{' of their own, e.g.
    # `attributes #0 = { ... }` or named struct types) before locating the
    # signature's opening brace.
    function_block = extract_function_body(record.original_ir, record.name)
    idx = function_block.find("{")
    if idx != -1:
        signature = function_block[:idx+1]
    else:
        signature = "define "

    assistant_prefill = f"```llvm\n{signature}\n"

    async with semaphore:
        logger.debug(f"[{record.name}] Sending to {model_name}...")
        try:
            t0 = time.perf_counter()
            
            if model_name.startswith("ollama/"):
                # Use httpx for raw text completion for Ollama to force the prefill mid-sentence
                # without any chat template interference from LiteLLM or Ollama.
                import httpx
                
                # Strip the ollama/ prefix for the direct API call
                actual_model = model_name.replace("ollama/", "")
                
                raw_prompt = f"<|im_start|>system\n{system_prompt}<|im_end|>\n<|im_start|>user\n{example_user}<|im_end|>\n<|im_start|>assistant\n{example_assistant}<|im_end|>\n<|im_start|>user\n{user_prompt}<|im_end|>\n<|im_start|>assistant\n{assistant_prefill}"
                
                payload = {
                    "model": actual_model,
                    "prompt": raw_prompt,
                    "raw": True,
                    "stream": False,
                    "options": {
                        "temperature": 0.0,
                        "seed": config.random_seed
                    }
                }
                
                # Use a larger timeout for the direct HTTP request
                async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                    resp = await client.post(
                        f"{config.ollama.base_url}/api/generate",
                        json=payload
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    
                raw_output = data.get("response", "")
                finish_reason = data.get("done_reason", "stop")
                
                # Because we prefilled the exact signature, the model's output will 
                # be everything AFTER the brace. We must prepend the signature back to it.
                raw_output = signature + "\n" + raw_output
                
            else:
                # For chat models (like Claude 3), use the Messages API with assistant prefill
                response = await litellm.acompletion(
                    model=model_name,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": example_user},
                        {"role": "assistant", "content": example_assistant},
                        {"role": "user", "content": user_prompt},
                        {"role": "assistant", "content": assistant_prefill}
                    ],
                    temperature=0.0,
                    timeout=timeout_seconds,
                )
                raw_output = response.choices[0].message.content
                finish_reason = getattr(response.choices[0], "finish_reason", "stop")
                
                raw_output = signature + "\n" + raw_output

            record.llm_latency_seconds = time.perf_counter() - t0
            logger.info(f"[{record.name}] LLM finished with reason: '{finish_reason}', length: {len(raw_output)}")
            
            # Dump raw output for empirical debugging
            import os
            os.makedirs("scratch", exist_ok=True)
            with open(f"scratch/raw_output_{record.name}.txt", "w") as f:
                f.write(f"FINISH REASON: {finish_reason}\n\n{raw_output}")
                
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

    # --- Ollama health check ---
    # If any configured model uses Ollama, verify the server is reachable
    # before dispatching calls. This prevents confusing timeout errors.
    uses_ollama = any(
        model.startswith("ollama")
        for tier in config.llm_routing.tiers.values()
        for model in tier.models
    )

    if uses_ollama:
        ollama_ok = await _check_ollama_health(config.ollama.base_url)
        if not ollama_ok:
            logger.error(
                f"Ollama server at {config.ollama.base_url} is not reachable. "
                "All functions will fall back to their original IR. "
                "Start Ollama with: ollama serve"
            )
            for record in parsed.functions:
                if not record.triaged_out:
                    record.llm_output = None
            return

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
                config=config,
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

    Uses Ollama for local inference by default — no API keys required.

    Args:
        parsed: The ParsedModule from Phase 1, after Phase 2 triage.
        config: Pipeline configuration (uses DEFAULT_CONFIG if None).
    """
    if config is None:
        config = get_config()

    # Bridge the sync/async boundary cleanly.
    asyncio.run(_route_module_async(parsed, config))
