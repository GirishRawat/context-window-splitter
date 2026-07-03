"""Deterministic pipeline orchestrator (the state machine spine).

Runs the six phases in fixed order for a single module. The orchestrator itself
is fully synchronous and deterministic; the only phase permitted internal
non-determinism/async is Phase 3, which for Milestone 1 is an identity stub.
This keeps "deterministic state machine with one contained probabilistic phase"
literally true at the code-structure level (README §4).

    parse (P1) → triage (P2) → route (P3) → reconstruct (P4)
        → verify (P5) → assemble (P6)

Phase 5 needs the external verification toolchain (llvm-as + alive-tv, an M0
dependency). When it is absent, syntax checks fail closed → every function
routes to fallback → ``final_module_ir`` is behaviourally the original module.
That is the correct, fail-safe M1 outcome ("behaves identically to an
unoptimised build"), not an error.
"""

from __future__ import annotations

import logging

from llmcompile.models import ParsedModule, Verdict
from llmcompile.config import PipelineConfig, get_config
from llmcompile.phases.p1_parse import parse_module
from llmcompile.phases.p2_triage import triage_module
from llmcompile.phases.p3_route import route_module
from llmcompile.phases.p4_reconstruct import reconstruct_module
from llmcompile.phases.p5_verify import verify_module
from llmcompile.phases.p6_assemble import assemble_module

logger = logging.getLogger(__name__)


def compile_module(ir_text: str, config: PipelineConfig | None = None) -> ParsedModule:
    """Run the full deterministic pipeline over one module's IR text.

    Args:
        ir_text: Raw LLVM IR (compiled at ``-O0``).
        config: Pipeline configuration (uses DEFAULT_CONFIG if None).

    Returns:
        The ``ParsedModule`` carrying all accumulated per-function state
        (complexity, token_count, verdict, final_ir, ...) and the assembled
        ``final_module_ir``.
    """
    if config is None:
        config = get_config()

    logger.info("Phase 1: parsing")
    parsed = parse_module(ir_text)

    logger.info("Phase 2: triage")
    triage_module(parsed, config)

    logger.info("Phase 3: routing (identity stub)")
    route_module(parsed, config)

    logger.info("Phase 4: reconstruction")
    reconstruct_module(parsed, config)

    logger.info("Phase 5: verification")
    verify_module(parsed, config)

    logger.info("Phase 6: assembly")
    assemble_module(parsed, config)

    return parsed


def summarize_run(parsed: ParsedModule) -> str:
    """Human-readable per-function summary of a completed pipeline run."""
    lines = [f"Pipeline run over {len(parsed.functions)} function(s):"]
    passed = sum(1 for r in parsed.functions if r.verdict == Verdict.PASSED)
    triaged = sum(1 for r in parsed.functions if r.triaged_out)
    lines.append(f"  {passed} optimized (PASSED), {triaged} triaged out, "
                 f"{len(parsed.functions) - passed} on original")
    lines.append("")
    for r in parsed.functions:
        status = "TRIAGED OUT" if r.triaged_out else r.verdict.value.upper()
        lines.append(
            f"  {r.name:<24} complexity={r.complexity} tokens={r.token_count} "
            f"model={r.assigned_model} -> [{status}]"
        )
    return "\n".join(lines)
