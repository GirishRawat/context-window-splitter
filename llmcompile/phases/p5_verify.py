"""Phase 5 — Verification Gate (deterministic).

The gate — nothing else. It consumes the standalone ``candidate_ir`` that
Phase 4 built and, for each candidate:
1. Syntax check via `llvm-as` -> Verdict.SYNTAX_FAIL
2. Refinement proof via `alive-tv` (Alive2/Z3) -> Verdict.PASSED / REJECTED / UNSUPPORTED

Updates `FunctionRecord.verdict` and `FunctionRecord.counterexample` in-place.
Functions with no ``candidate_ir`` (triaged out, no LLM output, or a candidate
Phase 4 could not reconstruct) remain PENDING and fall back to the original IR
in Phase 6. Reconstruction lives in Phase 4; this phase performs no rebuilding.
"""

from __future__ import annotations

import logging
import time

from llmcompile.models import ParsedModule, Verdict
from llmcompile.config import PipelineConfig, get_config
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
        parsed: The ParsedModule after Phase 4 reconstruction (candidate_ir set)
        config: Pipeline configuration (uses DEFAULT_CONFIG if None)
    """
    if config is None:
        config = get_config()

    for record in parsed.functions:
        if record.candidate_ir is None:
            # Triaged out, no LLM output, or Phase 4 could not reconstruct a
            # candidate. Leave verdict PENDING so Phase 6 uses original_ir.
            logger.debug(f"Skipping verification for {record.name} (no candidate)")
            continue

        logger.info(f"Verifying candidate for {record.name}...")

        # 1. Syntax check (cheap filter before the expensive SMT proof).
        syntax_ok = check_syntax(record.candidate_ir, config.verification)
        if not syntax_ok:
            logger.warning(f"[{record.name}] Syntax check failed")
            record.verdict = Verdict.SYNTAX_FAIL
            continue

        # 2. Refinement proof: source = original, target = candidate.
        t0 = time.perf_counter()
        verdict, counterexample = verify_refinement(
            record.original_ir,
            record.candidate_ir,
            config.verification
        )
        record.verification_latency_seconds = time.perf_counter() - t0
        
        record.verdict = verdict
        record.counterexample = counterexample
        
        if verdict == Verdict.PASSED:
            logger.info(f"[{record.name}] PASSED (proven refinement)")
        elif verdict == Verdict.REJECTED:
            logger.warning(f"[{record.name}] REJECTED (counterexample found)")
        else:
            logger.warning(f"[{record.name}] UNSUPPORTED (timeout or unable to prove)")
