"""Phase 1 — Parsing (deterministic).

Ingests raw LLVM IR (compiled at ``-O0``), validates it, and extracts every
complete function *definition* into a ``FunctionRecord`` whose ``original_ir``
is a standalone, ``llvm-as``-assemblable IR string. The live ``llvmlite``
module is retained in the returned ``ParsedModule`` for the whole run so that
Phase 6 can fall back to the untouched original.

Design (see TECHNICAL_REQUIREMENTS.md §5.1, §2):

* Chunking is strictly at FUNCTION level. Never basic-block level — that would
  sever use-def chains, liveness, and CFG structure.
* Only ``define`` bodies become records. ``declare`` (foreign declarations)
  are kept as shared module context, not optimised.
* Each extracted function is made independently assemblable by prepending a
  module-level *preamble* (target datalayout/triple, named types, globals,
  attribute groups, metadata, foreign declarations) plus *declarations* of all
  the other defined functions, so any symbol the function references resolves.
* The original module text and ModuleRef are never mutated here.

Bring-up tip: compile your corpus at ``-O0`` WITHOUT ``-g``. Debug metadata
(``-g``) introduces module-level nodes that reference functions by name and is
the main source of standalone-extraction edge cases (the Milestone-3 hardening
target). Clean ``-O0`` IR avoids that entirely.
"""

from __future__ import annotations

import re

from llmcompile.models import FunctionRecord, ParsedModule

try:
    import llvmlite.binding as llvm
except ImportError as exc:  # pragma: no cover - environment guard
    raise ImportError(
        "Phase 1 requires llvmlite. In a JupyterHub notebook run:  %pip install llvmlite"
    ) from exc


# --------------------------------------------------------------------------- #
# llvmlite initialisation (idempotent)
# --------------------------------------------------------------------------- #

_INITIALIZED = False


def _ensure_llvm_initialized() -> None:
    global _INITIALIZED
    if _INITIALIZED:
        return
    llvm.initialize()
    llvm.initialize_native_target()
    llvm.initialize_native_asmprinter()
    _INITIALIZED = True


# --------------------------------------------------------------------------- #
# Text helpers
# --------------------------------------------------------------------------- #

# The function name is the @-symbol immediately preceding the parameter list.
# Handles both quoted (@"weird name") and bare (@foo.bar) identifiers.
_FUNC_NAME_RE = re.compile(r'@(?:"(?P<quoted>[^"]*)"|(?P<bare>[\w.$\-]+))\s*\(')

# Function-level metadata attachments in canonical emission look like ' !dbg !12'.
_FN_METADATA_RE = re.compile(r"\s+!\w+\s+!\d+")

# Definition-only trailing clauses that are illegal on a `declare`.
_DEFINITION_ONLY_CLAUSES = (
    " personality ",
    " prologue ",
    " prefix ",
    " gc ",
    " section ",
    " comdat",
)


def _function_name(define_or_declare_line: str) -> str:
    """Extract the (unquoted) function name from a `define`/`declare` line."""
    m = _FUNC_NAME_RE.search(define_or_declare_line)
    if not m:
        raise ValueError(f"could not parse function name from: {define_or_declare_line!r}")
    return m.group("quoted") if m.group("quoted") is not None else m.group("bare")


def _signature_to_declaration(signature_line: str) -> str:
    """Convert a `define ... {` signature line into a valid `declare` line.

    Best-effort and deterministic. Strips the trailing brace, function-level
    metadata attachments, and definition-only trailing clauses, then swaps the
    leading keyword. Exotic signatures are the Milestone-3 hardening target;
    the lossless ModuleRef in ParsedModule remains the source of truth.
    """
    sig = signature_line.strip()
    if sig.endswith("{"):
        sig = sig[:-1].rstrip()

    sig = _FN_METADATA_RE.sub("", sig)

    earliest = len(sig)
    for clause in _DEFINITION_ONLY_CLAUSES:
        idx = sig.find(clause)
        if idx != -1:
            earliest = min(earliest, idx)
    sig = sig[:earliest].rstrip()

    if not sig.startswith("define"):
        raise ValueError(f"expected a `define` signature, got: {signature_line!r}")
    return "declare" + sig[len("define"):]


def _split_module_text(canonical_ir: str) -> tuple[list[str], list[dict]]:
    """Split canonical module text into (preamble_lines, definition_blocks).

    A definition block runs from a line starting with ``define`` to the line
    that is exactly ``}`` (canonical LLVM closes a function body with a brace
    in column zero). Everything else — datalayout, triple, type defs, globals,
    attribute groups, metadata, and ``declare`` lines — is preamble.
    """
    lines = canonical_ir.splitlines()
    preamble_lines: list[str] = []
    blocks: list[dict] = []

    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if line.lstrip().startswith("define "):
            signature = line
            body = [line]
            i += 1
            while i < n:
                body.append(lines[i])
                if lines[i].rstrip() == "}":
                    break
                i += 1
            else:
                raise ValueError(
                    f"unterminated function body starting at: {signature.strip()!r}"
                )
            blocks.append(
                {
                    "name": _function_name(signature),
                    "signature": signature,
                    "text": "\n".join(body),
                }
            )
            i += 1
        else:
            preamble_lines.append(line)
            i += 1

    return preamble_lines, blocks


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


def parse_module(ir_text: str) -> ParsedModule:
    """Parse, validate, and extract functions from raw LLVM IR.

    Raises ``RuntimeError`` if the IR fails to parse or verify (llvm-as-level
    failures of the *input* are caught here, not silently passed downstream).
    """
    _ensure_llvm_initialized()

    # parse_assembly raises on malformed IR; verify() catches structural issues.
    try:
        mod = llvm.parse_assembly(ir_text)
        mod.verify()
    except RuntimeError as exc:
        raise RuntimeError(f"Phase 1: input IR failed to parse/verify: {exc}") from exc

    # Work from canonical text so the preamble and bodies are mutually consistent.
    canonical_ir = str(mod)
    preamble_lines, blocks = _split_module_text(canonical_ir)

    # Cross-check our text split against llvmlite's own enumeration.
    text_def_names = {b["name"] for b in blocks}
    llvm_def_names = {fn.name for fn in mod.functions if not fn.is_declaration}
    if text_def_names != llvm_def_names:
        missing = llvm_def_names ^ text_def_names
        raise RuntimeError(
            "Phase 1: function extraction mismatch vs llvmlite enumeration; "
            f"symmetric difference = {sorted(missing)}"
        )

    base_preamble = "\n".join(preamble_lines).strip()

    # A declaration line for every defined function, used to resolve references
    # from other functions, globals, or metadata without carrying their bodies.
    declarations = {b["name"]: _signature_to_declaration(b["signature"]) for b in blocks}

    records: list[FunctionRecord] = []
    for block in blocks:
        name = block["name"]
        other_decls = [decl for fn_name, decl in declarations.items() if fn_name != name]

        parts = [base_preamble]
        if other_decls:
            parts.append("; --- declarations of sibling functions ---")
            parts.extend(other_decls)
        parts.append("")  # blank line before the body
        parts.append(block["text"])
        standalone_ir = "\n".join(p for p in parts if p is not None).strip() + "\n"

        records.append(FunctionRecord(name=name, original_ir=standalone_ir))

    return ParsedModule(
        source_ir=canonical_ir,
        preamble=base_preamble,
        functions=records,
        module_ref=mod,
    )


def replace_function_body(standalone_ir: str, name: str, new_function_ir: str) -> str:
    """Return ``standalone_ir`` with the ``define`` block for ``name`` swapped.

    A standalone IR string (as produced for ``FunctionRecord.original_ir``) is a
    shared preamble *plus sibling ``declare`` lines* plus exactly one ``define``
    block. This swaps that one block for ``new_function_ir`` (e.g. an LLM
    candidate), keeping the preamble and sibling declarations byte-for-byte.

    Phase 5 uses this to build the ``alive-tv`` *target* so it is structurally
    identical to the *source* (``original_ir``) and differs only in the function
    body. Prepending only the module preamble would drop the sibling
    declarations, making any function that calls a sibling fail ``llvm-as`` and
    be spuriously rejected.

    ``new_function_ir`` is expected to be a single ``define`` block for the same
    function (no module preamble of its own); malformed candidates are caught by
    the Phase 5 syntax check, not here.
    """
    preamble_lines, blocks = _split_module_text(standalone_ir)
    block_names = [b["name"] for b in blocks]
    if block_names != [name]:
        raise ValueError(
            f"expected exactly one definition of {name!r} in the standalone IR, "
            f"found {block_names}"
        )

    prefix = "\n".join(preamble_lines).rstrip()
    body = new_function_ir.strip()
    if not prefix:
        return body + "\n"
    return prefix + "\n\n" + body + "\n"


def parse_module_file(path: str) -> ParsedModule:
    """Convenience wrapper: read a ``.ll`` file and parse it."""
    with open(path, "r", encoding="utf-8") as fh:
        return parse_module(fh.read())


def summarize(parsed: ParsedModule) -> str:
    """Human-readable one-liner per extracted function (handy in a notebook)."""
    lines = [f"Extracted {len(parsed.functions)} function definition(s):"]
    for rec in parsed.functions:
        body_lines = rec.original_ir.count("\n")
        lines.append(f"  - {rec.name:<24} ({body_lines} lines of standalone IR)")
    return "\n".join(lines)
