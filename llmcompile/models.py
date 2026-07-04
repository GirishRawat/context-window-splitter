"""Shared data model for the LLM compilation orchestration pipeline.

A single ``FunctionRecord`` per IR function flows through all six phases,
accumulating state. ``ParsedModule`` is the Phase 1 output: it owns the
in-memory module that MUST persist for the whole run so Phase 6 can fall
back to the untouched ``-O0`` original.

See TECHNICAL_REQUIREMENTS.md sections 4 and 5.1.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Verdict(Enum):
    """Outcome of the Phase 5 verification gate for a single function."""

    PENDING = "pending"          # not yet verified
    PASSED = "passed"            # llvm-as OK AND alive-tv proved refinement
    REJECTED = "rejected"        # alive-tv found a counterexample (SAT)
    SYNTAX_FAIL = "syntax_fail"  # llvm-as rejected the candidate
    UNSUPPORTED = "unsupported"  # alive-tv could not decide / timed out / unsupported construct


@dataclass
class FunctionRecord:
    """Carrier object for one IR function, mutated in place across phases.

    Fields are grouped by the phase that sets them. ``original_ir`` is the
    one field that is immutable after Phase 1 — it is the source of truth the
    Phase 6 fallback relies on, and the reference the Phase 5 gate verifies
    candidates against.
    """

    # --- Set in Phase 1 ---
    name: str
    original_ir: str                       # standalone, llvm-as-assemblable IR for this function. IMMUTABLE after Phase 1.

    # --- Set in Phase 2 ---
    complexity: int | None = None
    token_count: int | None = None
    triaged_out: bool = False              # True => below complexity threshold; skips Phases 3-5

    # --- Set in Phase 3 ---
    assigned_model: str | None = None
    llm_output: str | None = None          # raw candidate function `define` block from the model
    llm_latency_seconds: float | None = None # wall-clock inference time

    # --- Set in Phase 4 ---
    candidate_ir: str | None = None        # standalone candidate IR (preamble + sibling declares + candidate body); the alive-tv target Phase 5 verifies

    # --- Set in Phase 5 ---
    verdict: Verdict = Verdict.PENDING
    counterexample: str | None = None      # populated on REJECTED
    verification_latency_seconds: float | None = None # wall-clock time spent in Alive2 proof

    # --- Set in Phase 6 ---
    final_ir: str | None = None            # final function `define` block: candidate body if PASSED, else the original body


@dataclass
class ParsedModule:
    """Phase 1 output. Owns the in-memory module for the entire run.

    ``module_ref`` is the live ``llvmlite`` ModuleRef (kept so later phases
    never have to re-parse). ``source_ir`` is the canonical, normalised module
    text it was derived from. ``preamble`` is the module-level context
    (datalayout, triple, type defs, globals, attribute groups, metadata,
    foreign declarations) prepended to each function to make it independently
    assemblable.
    """

    source_ir: str                                  # canonical full-module text. Immutable.
    preamble: str                                   # module-level context shared by every extracted function
    functions: list[FunctionRecord] = field(default_factory=list)
    module_ref: Any = None                          # llvmlite.binding.ModuleRef, retained in memory
    final_module_ir: str | None = None              # Phase 6: assembled final module (preamble + every function's final_ir)

    def definitions(self) -> list[FunctionRecord]:
        """Functions that are real definitions (everything in ``functions``;
        declarations are never turned into records)."""
        return list(self.functions)
