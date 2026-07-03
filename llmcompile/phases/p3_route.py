"""Phase 3 — LLM Execution & Routing.

This is the *only* phase permitted to be probabilistic and async (see README
§2). For Milestone 1 (the walking skeleton) it is stubbed as a deterministic
**identity transform**: the "optimized" candidate for every function is simply
its own original body, unchanged. This proves the whole 1→6 spine end-to-end
with zero API calls and zero non-determinism — the real routing (LiteLLM,
concurrency, complexity-tiered model selection) lands in Milestone 4.

Contract established here (relied on by Phases 4-6):

* ``FunctionRecord.llm_output`` is a single ``define`` block for the *same*
  function — NOT a full module and NOT wrapped in the shared preamble. Phase 4
  re-wraps it into a standalone candidate; Phase 6 substitutes it into the final
  module. The real Phase 3 must sanitize model output down to exactly this.
* Triaged-out functions are skipped entirely (no ``llm_output``); they fall
  through to Phase 6 as the untouched original.
"""

from __future__ import annotations

import logging

from llmcompile.models import ParsedModule
from llmcompile.config import PipelineConfig, get_config
from llmcompile.phases.p1_parse import extract_function_body

logger = logging.getLogger(__name__)

# Sentinel model name recorded for the identity stub so downstream reporting and
# tests can tell a walking-skeleton run apart from a real LLM run.
IDENTITY_MODEL = "identity"


def route_module(parsed: ParsedModule, config: PipelineConfig | None = None) -> None:
    """Populate each non-triaged function's ``llm_output`` (identity for M1).

    Mutates ``parsed.functions`` in place, setting ``assigned_model`` and
    ``llm_output`` for every function that was not triaged out. Deterministic:
    identical input yields identical output.

    Args:
        parsed: The ParsedModule from Phase 1, after Phase 2 triage.
        config: Pipeline configuration (uses DEFAULT_CONFIG if None).
    """
    if config is None:
        config = get_config()

    for record in parsed.functions:
        if record.triaged_out:
            logger.debug(f"Skipping routing for {record.name} (triaged out)")
            continue

        # Identity transform: the candidate body IS the original body.
        record.assigned_model = IDENTITY_MODEL
        record.llm_output = extract_function_body(record.original_ir, record.name)
        logger.info(f"[{record.name}] routed to {IDENTITY_MODEL} (walking skeleton)")
