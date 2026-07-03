"""Tests for Phase 5 verification gate.

Run with:
    python -m pytest llmcompile/tests/test_p5_verify.py -v
"""

from __future__ import annotations

import subprocess
import pytest
from unittest.mock import patch, MagicMock

from llmcompile.models import FunctionRecord, ParsedModule, Verdict
from llmcompile.config import PipelineConfig, VerificationConfig
from llmcompile.verification.alive import check_syntax, verify_refinement
from llmcompile.phases.p5_verify import verify_module

@pytest.fixture
def mock_config():
    return VerificationConfig(llvm_as_path="mock-llvm-as", alive_tv_path="mock-alive-tv")


# ---------------------------------------------------------------------------
# Tests for alive.py wrappers
# ---------------------------------------------------------------------------

@patch("subprocess.run")
def test_check_syntax_passes(mock_run, mock_config):
    # Mock successful execution
    mock_run.return_value = MagicMock(returncode=0)
    
    result = check_syntax("define void @f() { ret void }", mock_config)
    assert result is True
    mock_run.assert_called_once()
    assert "mock-llvm-as" in mock_run.call_args[0][0]


@patch("subprocess.run")
def test_check_syntax_fails(mock_run, mock_config):
    # Mock failed execution (syntax error)
    mock_run.return_value = MagicMock(returncode=1)
    
    result = check_syntax("define void @f() { broken }", mock_config)
    assert result is False


@patch("subprocess.run")
def test_check_syntax_timeout(mock_run, mock_config):
    mock_run.side_effect = subprocess.TimeoutExpired(cmd="mock-llvm-as", timeout=10)
    
    result = check_syntax("define void @f() { ret void }", mock_config)
    assert result is False


@patch("subprocess.run")
def test_verify_refinement_passed(mock_run, mock_config):
    mock_run.return_value = MagicMock(
        stdout="Transformation seems to be correct!\n",
        stderr="",
        returncode=0
    )
    
    verdict, cex = verify_refinement("original", "candidate", mock_config)
    
    assert verdict == Verdict.PASSED
    assert cex is None
    mock_run.assert_called_once()
    assert "mock-alive-tv" in mock_run.call_args[0][0]


@patch("subprocess.run")
def test_verify_refinement_rejected(mock_run, mock_config):
    mock_output = "Transformation doesn't verify!\nERROR: Value mismatch"
    mock_run.return_value = MagicMock(
        stdout=mock_output,
        stderr="",
        returncode=0
    )
    
    verdict, cex = verify_refinement("original", "candidate", mock_config)
    
    assert verdict == Verdict.REJECTED
    assert cex == mock_output


@patch("subprocess.run")
def test_verify_refinement_unsupported_or_undecided(mock_run, mock_config):
    mock_run.return_value = MagicMock(
        stdout="Timeout during SMT solving",
        stderr="",
        returncode=0
    )
    
    verdict, cex = verify_refinement("original", "candidate", mock_config)
    
    assert verdict == Verdict.UNSUPPORTED
    assert cex is None


@patch("subprocess.run")
def test_verify_refinement_timeout(mock_run, mock_config):
    mock_run.side_effect = subprocess.TimeoutExpired(cmd="mock-alive-tv", timeout=30)
    
    verdict, cex = verify_refinement("original", "candidate", mock_config)
    
    assert verdict == Verdict.UNSUPPORTED
    assert cex is None


# ---------------------------------------------------------------------------
# Tests for p5_verify.py orchestration
# ---------------------------------------------------------------------------

def _define(name: str, marker: str = "") -> str:
    """A minimal, self-contained ``define`` block for tests."""
    comment = f"  ; {marker}\n" if marker else ""
    return f"define i32 @{name}() {{\nentry:\n{comment}  ret i32 0\n}}\n"


@pytest.fixture
def sample_parsed_module():
    # Phase 5 consumes candidate_ir (built by Phase 4), so the fixture sets it
    # directly rather than relying on reconstruction.
    f1 = FunctionRecord(name="f1", original_ir=_define("f1"))
    f1.llm_output = _define("f1", "f1_opt")
    f1.candidate_ir = _define("f1", "f1_opt")

    f2 = FunctionRecord(name="f2", original_ir=_define("f2"))
    f2.llm_output = _define("f2", "f2_opt")
    f2.candidate_ir = _define("f2", "f2_opt")

    f_triaged = FunctionRecord(name="f_triaged", original_ir=_define("f_triaged"))
    f_triaged.triaged_out = True
    # phase 3/4 don't produce a candidate for triaged functions
    f_triaged.candidate_ir = None

    f_no_output = FunctionRecord(name="f_no_output", original_ir=_define("f_no_output"))
    # triaged_out is False but no candidate (e.g. LLM API failed upstream)
    f_no_output.candidate_ir = None

    return ParsedModule(
        source_ir="source",
        preamble="; preamble",
        functions=[f1, f2, f_triaged, f_no_output]
    )

@patch("llmcompile.phases.p5_verify.check_syntax")
@patch("llmcompile.phases.p5_verify.verify_refinement")
def test_verify_module_pipeline_integration(mock_verify_refinement, mock_check_syntax, sample_parsed_module):
    # Setup mock behavior
    # f1: syntax OK, refinement PASSED
    # f2: syntax FAIL
    def syntax_side_effect(ir_text, config):
        if "f2_opt" in ir_text:
            return False
        return True
        
    mock_check_syntax.side_effect = syntax_side_effect
    
    # verify_refinement is only called for f1 because f2 fails syntax
    mock_verify_refinement.return_value = (Verdict.PASSED, None)
    
    config = PipelineConfig()
    verify_module(sample_parsed_module, config)
    
    # Assertions
    functions = {f.name: f for f in sample_parsed_module.functions}
    
    # f1 should be PASSED
    assert functions["f1"].verdict == Verdict.PASSED
    
    # f2 should be SYNTAX_FAIL
    assert functions["f2"].verdict == Verdict.SYNTAX_FAIL
    
    # f_triaged should be skipped (PENDING)
    assert functions["f_triaged"].verdict == Verdict.PENDING
    
    # f_no_output should be skipped (PENDING)
    assert functions["f_no_output"].verdict == Verdict.PENDING
    
    # verify_refinement should only have been called once (for f1)
    mock_verify_refinement.assert_called_once()


# ---------------------------------------------------------------------------
# Regression tests for alive.py robustness (Findings #2, #5)
# ---------------------------------------------------------------------------

@patch("subprocess.run")
def test_verify_refinement_passes_source_then_target(mock_run, mock_config):
    """alive-tv argument order matters: source (original) then target (candidate).
    README §3: `alive-tv <original> <candidate>`."""
    captured = {}

    def _run(cmd, *args, **kwargs):
        # cmd == [alive_tv_path, source_path, target_path]
        with open(cmd[1]) as s, open(cmd[2]) as t:
            captured["src"] = s.read()
            captured["tgt"] = t.read()
        return MagicMock(stdout="Transformation seems to be correct!\n", stderr="", returncode=0)

    mock_run.side_effect = _run
    verify_refinement("SOURCE_ORIGINAL", "TARGET_CANDIDATE", mock_config)

    assert captured["src"] == "SOURCE_ORIGINAL"
    assert captured["tgt"] == "TARGET_CANDIDATE"


@patch("subprocess.run")
def test_verify_refinement_prefers_failure_when_both_markers_present(mock_run, mock_config):
    """If output somehow carries both markers, it must be REJECTED, never PASSED."""
    mock_run.return_value = MagicMock(
        stdout=(
            "Transformation seems to be correct!\n"
            "...more output...\n"
            "Transformation doesn't verify!\n"
        ),
        stderr="",
        returncode=0,
    )
    verdict, cex = verify_refinement("original", "candidate", mock_config)
    assert verdict == Verdict.REJECTED
    assert cex is not None


@patch("subprocess.run")
def test_check_syntax_binary_missing(mock_run, mock_config):
    mock_run.side_effect = FileNotFoundError()
    assert check_syntax("define void @f() { ret void }", mock_config) is False
