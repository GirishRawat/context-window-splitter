"""Phase 4 — Candidate Reconstruction (deterministic).

Mechanically substitutes each function's LLM candidate body back into its own
standalone context, producing ``FunctionRecord.candidate_ir`` — the artifact
Phase 5 verifies against the original. Per README §3, this phase does **no
validation**; it only rebuilds IR text. Whether the candidate is correct (or
even syntactically valid) is exclusively Phase 5's job.

Why per-function standalone reconstruction (not one merged module): the
INVIOLABLE constraint is that each function is optimized and verified in
isolation. ``candidate_ir`` mirrors ``original_ir`` exactly — same preamble,
same sibling ``declare`` lines — differing only in the one function body, so
``alive-tv`` compares like against like and pairs functions by name.
"""

from __future__ import annotations

import logging

from llmcompile.models import ParsedModule
from llmcompile.config import PipelineConfig, get_config
from llmcompile.phases.p1_parse import replace_function_body

logger = logging.getLogger(__name__)


def reconstruct_module(parsed: ParsedModule, config: PipelineConfig | None = None) -> None:
    """Build ``candidate_ir`` for every function that has an ``llm_output``.

    Mutates ``parsed.functions`` in place. Functions that were triaged out or
    have no ``llm_output`` are left with ``candidate_ir = None`` (Phase 5 skips
    them, Phase 6 falls back to the original). Deterministic.

    A candidate that cannot be re-wrapped (e.g. the model emitted the wrong or
    no ``define`` block) leaves ``candidate_ir = None`` and is logged — no
    validation or verdict is set here; the missing candidate simply routes to
    fallback, which is the fail-safe outcome.

    Args:
        parsed: The ParsedModule after Phase 3 routing.
        config: Pipeline configuration (uses DEFAULT_CONFIG if None).
    """
    if config is None:
        config = get_config()

    for record in parsed.functions:
        if record.triaged_out or record.llm_output is None:
            continue

        try:
            record.candidate_ir = replace_function_body(
                record.original_ir, record.name, record.llm_output
            )
            logger.debug(f"[{record.name}] reconstructed standalone candidate")
        except ValueError as exc:
            logger.warning(f"[{record.name}] could not reconstruct candidate: {exc}")
            record.candidate_ir = None
