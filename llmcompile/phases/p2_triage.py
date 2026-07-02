"""Phase 2 — Triage & Profiling (deterministic).

Computes cyclomatic complexity and token count for each function, then applies
a triage threshold: functions below the complexity threshold are marked
``triaged_out = True`` and skip Phases 3-5 (LLM optimization and verification),
passing through to Phase 6 unchanged.

Design (see TECHNICAL_REQUIREMENTS.md §3, §9):

* Cyclomatic complexity is computed from the control-flow graph (CFG) via the
  live ``module_ref`` retained in ``ParsedModule``. For a function with N blocks
  and E edges: complexity = E - N + 2 (or equivalently, decision points + 1).
* Token counting uses tiktoken (OpenAI's tokenizer) as a proxy. The count drives
  Phase 3 routing: small functions → fast models, large → frontier models.
* This phase is deterministic: same input produces identical metrics.

Usage:
    parsed = parse_module(ir_text)
    triage_module(parsed, config)
    # Now parsed.functions have complexity, token_count, triaged_out populated
"""

from __future__ import annotations

from llmcompile.models import ParsedModule
from llmcompile.config import PipelineConfig, get_config

try:
    import llvmlite.binding as llvm
except ImportError as exc:  # pragma: no cover
    raise ImportError("Phase 2 requires llvmlite") from exc

try:
    import tiktoken
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "Phase 2 requires tiktoken for token counting. Install with: pip install tiktoken"
    ) from exc


# ---------------------------------------------------------------------------
# Cyclomatic complexity
# ---------------------------------------------------------------------------

def _cyclomatic_complexity_from_text(ir_text: str) -> int:
    """Compute cyclomatic complexity by parsing the IR text.

    This is a simpler, more reliable approach than navigating llvmlite's CFG API.
    We count decision points directly from branch instructions.

    Cyclomatic complexity = decision_points + 1, where decision_points are:
    - Conditional branches (br i1 ..., label %true, label %false)
    - Switch statements
    - Select instructions (ternary operators)

    Args:
        ir_text: The IR text for this function

    Returns:
        Cyclomatic complexity (minimum 1)
    """
    import re

    # Count conditional branches: "br i1 %cond, label %true, label %false"
    conditional_branches = len(re.findall(r'\bbr\s+i1\s+%\w+,', ir_text))

    # Count switch statements: "switch i32 %x, label %default ["
    switches = len(re.findall(r'\bswitch\s+', ir_text))

    # Count select instructions: "select i1 %cond, type %true_val, type %false_val"
    selects = len(re.findall(r'\bselect\s+i1\s+', ir_text))

    # Each of these adds one decision point
    decision_points = conditional_branches + switches + selects

    # Cyclomatic complexity = decision_points + 1
    # Minimum complexity is 1 (straight-line code with no branches)
    return max(1, decision_points + 1)


def _cyclomatic_complexity(llvm_function) -> int:
    """Compute cyclomatic complexity for an llvmlite function.

    Args:
        llvm_function: llvmlite.binding.ValueRef representing a function

    Returns:
        Cyclomatic complexity (minimum 1)
    """
    if llvm_function.is_declaration:
        # Declarations have no body, no complexity
        return 0

    # Convert to text and parse
    # llvmlite functions can be converted to IR text via str()
    function_ir = str(llvm_function)
    return _cyclomatic_complexity_from_text(function_ir)


# ---------------------------------------------------------------------------
# Token counting
# ---------------------------------------------------------------------------

# Cached tokenizer instance (initialized once)
_TOKENIZER = None


def _get_tokenizer():
    """Get or create the tiktoken tokenizer (cl100k_base encoding)."""
    global _TOKENIZER
    if _TOKENIZER is None:
        # cl100k_base is used by GPT-4, GPT-3.5-turbo
        # According to Cummins et al., LLVM IR encodes at ~2 chars/token
        _TOKENIZER = tiktoken.get_encoding("cl100k_base")
    return _TOKENIZER


def _count_tokens(text: str) -> int:
    """Count tokens in the given text using tiktoken.

    Args:
        text: The IR text to tokenize

    Returns:
        Number of tokens
    """
    tokenizer = _get_tokenizer()
    tokens = tokenizer.encode(text)
    return len(tokens)


# ---------------------------------------------------------------------------
# Triage logic
# ---------------------------------------------------------------------------

def triage_module(
    parsed: ParsedModule,
    config: PipelineConfig | None = None
) -> None:
    """Apply Phase 2 triage: compute complexity/tokens, mark triaged_out.

    This function mutates ``parsed.functions`` in place, populating:
    - ``complexity``: cyclomatic complexity (int)
    - ``token_count``: number of tokens in the standalone IR (int)
    - ``triaged_out``: True if complexity < threshold (bool)

    Functions with ``triaged_out = True`` will skip Phases 3-5 and pass
    through to Phase 6 unchanged (the original ``-O0`` IR is kept).

    Args:
        parsed: The ParsedModule from Phase 1
        config: Pipeline configuration (uses DEFAULT_CONFIG if None)
    """
    if config is None:
        config = get_config()

    threshold = config.triage.complexity_threshold
    module_ref = parsed.module_ref

    # Build a mapping from function name to llvmlite function object
    llvm_functions = {fn.name: fn for fn in module_ref.functions}

    for record in parsed.functions:
        llvm_fn = llvm_functions.get(record.name)
        if llvm_fn is None:
            # Should never happen if Phase 1 extraction was correct
            raise RuntimeError(
                f"Phase 2: function {record.name} missing from module_ref"
            )

        # Compute metrics
        record.complexity = _cyclomatic_complexity(llvm_fn)
        record.token_count = _count_tokens(record.original_ir)

        # Apply triage threshold
        record.triaged_out = (record.complexity < threshold)


# ---------------------------------------------------------------------------
# Human-readable summary
# ---------------------------------------------------------------------------

def summarize(parsed: ParsedModule) -> str:
    """Human-readable summary of triage results (handy in a notebook).

    Args:
        parsed: ParsedModule after triage_module() has run

    Returns:
        Multi-line string summarizing triage results
    """
    lines = [f"Triage results for {len(parsed.functions)} function(s):"]
    triaged_out_count = sum(1 for r in parsed.functions if r.triaged_out)
    to_optimize_count = len(parsed.functions) - triaged_out_count

    lines.append(f"  - {triaged_out_count} triaged out (too simple)")
    lines.append(f"  - {to_optimize_count} to optimize via LLM")
    lines.append("")

    for rec in parsed.functions:
        status = "TRIAGED OUT" if rec.triaged_out else "TO OPTIMIZE"
        lines.append(
            f"  {rec.name:<24} complexity={rec.complexity:>3} tokens={rec.token_count:>5} [{status}]"
        )

    return "\n".join(lines)
