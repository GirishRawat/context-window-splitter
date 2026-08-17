"""Subprocess wrappers for the Phase 5 verification toolchain.

Uses llvm-as for syntax checking and alive-tv (Alive2) for SMT-based
refinement proofs. Bounded timeouts are enforced to prevent hanging.
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
from typing import Tuple

from llmcompile.models import Verdict
from llmcompile.config import VerificationConfig

logger = logging.getLogger(__name__)

def check_syntax(ir_text: str, config: VerificationConfig) -> Tuple[bool, str | None]:
    """Run llvm-as to perform a fast syntax and structural validity check.

    Args:
        ir_text: The standalone LLVM IR string to check.
        config: Verification configuration with llvm_as_path.

    Returns:
        (True, None) if llvm-as exits with code 0 (syntax OK).
        (False, diagnostic) otherwise, where diagnostic is llvm-as's stderr
        (falling back to stdout, then a synthesized message) explaining why —
        needed to distinguish truncation/hallucinated-reference/malformed-
        syntax failure modes instead of collapsing them all into SYNTAX_FAIL.
    """
    with tempfile.NamedTemporaryFile(mode="w", suffix=".ll") as f:
        f.write(ir_text)
        f.flush()

        try:
            # We don't care about the object file, just checking syntax
            # llvm-as -disable-output validates without writing to disk
            result = subprocess.run(
                [config.llvm_as_path, "-disable-output", f.name],
                capture_output=True,
                text=True,
                timeout=config.llvm_as_timeout,
                check=False
            )
            if result.returncode == 0:
                return True, None
            diagnostic = (result.stderr or result.stdout or "").strip() or \
                f"llvm-as exited {result.returncode} with no output"
            return False, diagnostic
        except FileNotFoundError:
            # llvm-as not found in PATH or config path is wrong
            logger.error(f"Syntax check failed: {config.llvm_as_path} not found")
            return False, f"{config.llvm_as_path} not found"
        except subprocess.TimeoutExpired:
            logger.error(f"Syntax check timed out after {config.llvm_as_timeout}s")
            return False, f"llvm-as timed out after {config.llvm_as_timeout}s"
        except Exception as e:
            logger.error(f"Syntax check failed unexpectedly: {e}")
            return False, f"unexpected error: {e}"

def verify_refinement(original_ir: str, candidate_ir: str, config: VerificationConfig) -> Tuple[Verdict, str | None]:
    """Run alive-tv to prove the candidate is a sound refinement of the original.
    
    Args:
        original_ir: The original -O0 function IR (the source).
        candidate_ir: The LLM-optimized function IR (the target).
        config: Verification configuration with tool paths and timeouts.
        
    Returns:
        Tuple of (Verdict, counterexample_text). 
        Counterexample is None unless Verdict is REJECTED.
    """
    with tempfile.NamedTemporaryFile(mode="w", suffix="_src.ll") as f_src, \
         tempfile.NamedTemporaryFile(mode="w", suffix="_tgt.ll") as f_tgt:
         
        f_src.write(original_ir)
        f_src.flush()
        
        f_tgt.write(candidate_ir)
        f_tgt.flush()
        
        cmd = [
            config.alive_tv_path,
            # alive-tv's internal SMT-query timeout/memory cap default to
            # 10000ms / 1024MB and are independent of the subprocess-level
            # alive_tv_timeout below -- without these flags, complex candidates
            # hit Alive2's own tight defaults and come back UNSUPPORTED long
            # before the outer timeout (or this machine's real memory) matters.
            f"--smt-to={config.smt_timeout * 1000}",
            f"--smt-max-mem={config.smt_max_mem_mb}",
            f_src.name,
            f_tgt.name
        ]
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=config.alive_tv_timeout,
                check=False
            )
            
            output = result.stdout + "\n" + result.stderr

            # Parse standard Alive2 output strings. Check the FAILURE marker
            # first: the README requires treating anything other than a proven
            # refinement as a failure, so if an output ever carries both markers
            # (batch runs, future phrasing) we must not misclassify it as PASSED.
            if "doesn't verify!" in output:
                # Return the full output so the developer can see the SAT model
                # / counterexample.
                return Verdict.REJECTED, output.strip()

            elif "Transformation seems to be correct!" in output:
                return Verdict.PASSED, None

            else:
                # Alive2 timed out internally, crashed, unsupported instruction, etc.
                logger.warning(f"alive-tv undecided or unsupported. Full output:\n{output}")
                return Verdict.UNSUPPORTED, None
                
        except FileNotFoundError:
            logger.error(f"Verification failed: {config.alive_tv_path} not found")
            return Verdict.UNSUPPORTED, None
        except subprocess.TimeoutExpired:
            logger.warning(f"Verification timed out after {config.alive_tv_timeout}s")
            return Verdict.UNSUPPORTED, None
        except Exception as e:
            logger.error(f"Verification failed unexpectedly: {e}")
            return Verdict.UNSUPPORTED, None
