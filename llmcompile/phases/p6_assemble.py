"""Phase 6 — Fallback Assembly (deterministic).

The final gate on what reaches the output. For each function:

* ``verdict == PASSED``  → the proven-correct candidate body is locked in.
* anything else (REJECTED, SYNTAX_FAIL, UNSUPPORTED, PENDING, triaged out)
  → the untouched original ``-O0`` body is reinserted from memory.

This makes the output **valid by construction**: every function is either a
formally-proven refinement of the original, or the original itself. The per-
function choice is stored on ``FunctionRecord.final_ir`` (a ``define`` block),
and the full reassembled module text on ``ParsedModule.final_module_ir``.

Compiling that module to an executable is the real Phase 6 tail; it needs a
system ``clang``/``llc`` (like the Alive2 toolchain, an M0 dependency) and is
deferred. Here we assemble and return the final module IR text, which is the
input that compilation step would consume.
"""

from __future__ import annotations

import logging

from llmcompile.models import ParsedModule, Verdict
from llmcompile.config import PipelineConfig, get_config
from llmcompile.phases.p1_parse import extract_function_body

logger = logging.getLogger(__name__)


def assemble_module(parsed: ParsedModule, config: PipelineConfig | None = None) -> str:
    """Select each function's final body and assemble the final module.

    Mutates ``parsed.functions`` in place (sets ``final_ir`` per record) and
    sets ``parsed.final_module_ir``. Returns the assembled module IR text.
    Deterministic.

    Args:
        parsed: The ParsedModule after Phase 5 verification.
        config: Pipeline configuration (uses DEFAULT_CONFIG if None).

    Returns:
        The final module IR: shared preamble followed by every function's
        chosen ``define`` block, in original order.
    """
    if config is None:
        config = get_config()

    final_bodies: list[str] = []
    for record in parsed.functions:
        optimized = (
            record.verdict == Verdict.PASSED and record.llm_output is not None
        )
        if optimized:
            body = record.llm_output.strip()
            logger.info(f"[{record.name}] locking in proven optimization")
        else:
            # Fallback to the untouched original body (source of truth).
            body = extract_function_body(record.original_ir, record.name).strip()
            logger.info(f"[{record.name}] falling back to original ({record.verdict.value})")

        record.final_ir = body
        final_bodies.append(body)

    preamble = parsed.preamble.strip()
    parts = [preamble] if preamble else []
    parts.extend(final_bodies)
    module_ir = "\n\n".join(parts).strip() + "\n"

    parsed.final_module_ir = module_ir
    return module_ir
