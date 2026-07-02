"""Tests for Phase 1 parsing.

Run in JupyterHub after `%pip install llvmlite pytest`:

    !python -m pytest llmcompile/tests/test_p1_parse.py -v

The load-bearing assertion is `test_each_function_is_independently_assemblable`:
if every extracted `original_ir` re-parses on its own, the standalone
extraction is sound — which is exactly what Phase 5 will rely on.
"""

from __future__ import annotations

import pytest

import llvmlite.binding as llvm

from llmcompile.models import FunctionRecord, Verdict
from llmcompile.phases.p1_parse import parse_module


# A small but representative -O0-style module:
#  - target datalayout/triple
#  - a global variable
#  - a foreign declaration (@external)
#  - two definitions, where @use calls both @add (sibling) and @external
SAMPLE_IR = """\
; ModuleID = 'sample'
source_filename = "sample.c"
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-f80:128-n8:16:32:64-S128"
target triple = "x86_64-unknown-linux-gnu"

@counter = global i32 0, align 4

declare i32 @external(i32)

define i32 @add(i32 %a, i32 %b) {
entry:
  %r = add i32 %a, %b
  ret i32 %r
}

define i32 @use(i32 %x) {
entry:
  %t = call i32 @add(i32 %x, i32 1)
  %e = call i32 @external(i32 %t)
  ret i32 %e
}
"""


@pytest.fixture(scope="module")
def parsed():
    return parse_module(SAMPLE_IR)


def test_only_definitions_become_records(parsed):
    names = {r.name for r in parsed.functions}
    assert names == {"add", "use"}          # two definitions
    assert "external" not in names          # the declaration is NOT a record


def test_records_are_function_records_in_pending_state(parsed):
    for rec in parsed.functions:
        assert isinstance(rec, FunctionRecord)
        assert rec.verdict is Verdict.PENDING
        assert rec.original_ir.strip()      # non-empty standalone IR
        assert rec.complexity is None        # Phase 2 has not run
        assert rec.final_ir is None          # Phase 6 has not run


def test_module_ref_and_source_retained(parsed):
    assert parsed.module_ref is not None     # live module kept for Phase 6
    assert "target triple" in parsed.source_ir
    assert "target datalayout" in parsed.preamble


def test_sibling_calls_are_declared_not_inlined(parsed):
    use = next(r for r in parsed.functions if r.name == "use")
    # @use calls @add, so a declaration of @add must be present...
    assert "declare" in use.original_ir
    assert "@add" in use.original_ir
    # ...but @add's BODY must not be carried into @use's standalone IR.
    assert "%r = add i32 %a, %b" not in use.original_ir
    # foreign declaration and referenced global come along via the preamble.
    assert "@external" in use.original_ir
    assert "@counter" in use.original_ir


def test_leaf_function_carries_its_own_body(parsed):
    add = next(r for r in parsed.functions if r.name == "add")
    assert "%r = add i32 %a, %b" in add.original_ir
    assert "ret i32 %r" in add.original_ir


def test_each_function_is_independently_assemblable(parsed):
    """The real proof: every extracted function re-parses on its own."""
    llvm.initialize()
    for rec in parsed.functions:
        # Should not raise; a failure here means the standalone IR is broken.
        reparsed = llvm.parse_assembly(rec.original_ir)
        reparsed.verify()
        # The target function survives as a real definition in its own module.
        defs = {fn.name for fn in reparsed.functions if not fn.is_declaration}
        assert rec.name in defs


def test_invalid_ir_raises():
    with pytest.raises(RuntimeError):
        parse_module("define i32 @broken( { this is not valid IR }")
