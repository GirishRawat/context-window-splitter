"""Phase 5 — Verification Gate (deterministic).

Applies formal verification to LLM candidates.
For each function that wasn't triaged out and has an llm_output:
1. Syntax check via `llvm-as` -> Verdict.SYNTAX_FAIL
2. Refinement proof via `alive-tv` (Alive2/Z3) -> Verdict.PASSED / REJECTED / UNSUPPORTED

Updates `FunctionRecord.verdict` and `FunctionRecord.counterexample` in-place.
Functions that are `triaged_out` remain PENDING (or skip verification) and will
naturally fall back to the original IR in Phase 6.
"""

from __future__ import annotations

import logging

from llmcompile.models import ParsedModule, Verdict
from llmcompile.config import PipelineConfig, get_config
from llmcompile.phases.p1_parse import replace_function_body
from llmcompile.verification.alive import check_syntax, verify_refinement

logger = logging.getLogger(__name__)

def verify_module(
    parsed: ParsedModule,
    config: PipelineConfig | None = None
) -> None:
    """Run the verification gate on all LLM candidates.
    
    Mutates ``parsed.functions`` in place, populating:
    - ``verdict``: The outcome of the verification gate
    - ``counterexample``: Proof of failure if REJECTED
    
    Args:
        parsed: The ParsedModule from Phase 1 (with Phase 3 llm_output populated)
        config: Pipeline configuration (uses DEFAULT_CONFIG if None)
    """
    if config is None:
        config = get_config()
        
    for record in parsed.functions:
        if record.triaged_out:
            logger.debug(f"Skipping verification for {record.name} (triaged out)")
            continue
            
        if record.llm_output is None:
            logger.debug(f"Skipping verification for {record.name} (no LLM output)")
            # Leaves verdict as PENDING so Phase 6 uses original_ir
            continue
            
        logger.info(f"Verifying candidate for {record.name}...")

        # 1. Syntax check
        # Build the candidate by swapping only the function body into this
        # function's own standalone IR, so it keeps the same preamble AND sibling
        # declarations as the source. (Prepending just the module preamble would
        # drop sibling declares and spuriously fail any function calling a sibling.)
        try:
            candidate_ir = replace_function_body(
                record.original_ir, record.name, record.llm_output
            )
        except ValueError as exc:
            logger.warning(f"[{record.name}] could not reconstruct candidate: {exc}")
            record.verdict = Verdict.SYNTAX_FAIL
            continue

        syntax_ok = check_syntax(candidate_ir, config.verification)
        if not syntax_ok:
            logger.warning(f"[{record.name}] Syntax check failed")
            record.verdict = Verdict.SYNTAX_FAIL
            continue
            
        # 2. Refinement proof
        verdict, counterexample = verify_refinement(
            record.original_ir,
            candidate_ir,
            config.verification
        )
        
        record.verdict = verdict
        record.counterexample = counterexample
        
        if verdict == Verdict.PASSED:
            logger.info(f"[{record.name}] PASSED (proven refinement)")
        elif verdict == Verdict.REJECTED:
            logger.warning(f"[{record.name}] REJECTED (counterexample found)")
        else:
            logger.warning(f"[{record.name}] UNSUPPORTED (timeout or unable to prove)")
