import argparse
import csv
import json
import logging
import os
import sys
import time
import subprocess
from datetime import datetime, timezone
from pathlib import Path
import re

import llvmlite.binding as llvm

from llmcompile.orchestrator import compile_module
from llmcompile.config import get_config
from llmcompile.models import ParsedModule
from llmcompile.eval.harness import get_instruction_counts

logger = logging.getLogger(__name__)

def process_spec_corpus(build_dir: Path, output_csv: Path, complexity_threshold: int) -> None:
    """Run the evaluation harness over .bc files in the LLVM test-suite build dir."""
    if not build_dir.exists() or not build_dir.is_dir():
        logger.error(f"Build directory {build_dir} does not exist.")
        sys.exit(1)
        
    config = get_config()
    config.triage.complexity_threshold = complexity_threshold
    
    # Setup LLVM
    llvm.initialize()
    llvm.initialize_native_target()
    llvm.initialize_native_asmprinter()
    llvm.set_option("llvmlite", "-opaque-pointers")
    
    fieldnames = [
        "file_name", "function_name", "complexity", "tokens", "triaged_out", 
        "model", "llm_latency_s", "verification_latency_s", "verdict", 
        "orig_instrs", "final_instrs", "reduction_pct"
    ]
    
    completed_files = set()
    if output_csv.exists() and output_csv.stat().st_size > 0:
        try:
            with open(output_csv, "r") as csvfile:
                reader = csv.DictReader(csvfile)
                for row in reader:
                    if row.get("file_name"):
                        completed_files.add(row["file_name"])
            logger.info(f"Resuming evaluation: found {len(completed_files)} unique files already processed in {output_csv}")
        except Exception as e:
            logger.warning(f"Could not read existing CSV for resumption: {e}. Starting fresh.")
            
    if not completed_files:
        with open(output_csv, "w", newline="") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
        
    total_evaluated = 0
    
    bc_files = list(build_dir.rglob("*.bc"))
    logger.info(f"Found {len(bc_files)} .bc files in {build_dir}")
    
    for bc_file in bc_files:
        if bc_file.name in completed_files:
            logger.info(f"Skipping {bc_file.name} (already processed)")
            continue
            
        logger.info(f"Processing {bc_file.name}...")
        ll_file = bc_file.with_suffix(".ll")
        
        # Find the original object file (CMake uses .c.o or .cpp.o)
        o_file = None
        for p in bc_file.parent.glob(f"{bc_file.stem}.*.o"):
            o_file = p
            break
        if not o_file:
            o_file = bc_file.with_suffix(".o")
        
        try:
            # 1. Disassemble .bc to .ll
            subprocess.run(["clang", "-S", "-emit-llvm", str(bc_file), "-o", str(ll_file)], check=True)
            
            with open(ll_file, "r") as f:
                ir_text = f.read()
                
            # Normalize IR for llvmlite 0.42.0 (LLVM 14) compatibility
            ir_text = ir_text.replace("uwtable(sync)", "uwtable")
            ir_text = re.sub(r"memory\([^)]+\)", "", ir_text)
            ir_text = re.sub(r"!llvm\.module\.flags.*", "", ir_text)

            # Strip instruction-level alias/TBAA metadata attachments. Alive2
            # cannot translate `!tbaa` (metadata kind 1), which Clang attaches to
            # every load/store even at -O0, so it returns "Could not translate
            # ... to Alive IR" (verdict UNSUPPORTED) for any memory-touching
            # function -- even the identity transform. Stripping these here (on
            # the input, before parsing) makes original_ir TBAA-free, so both the
            # source and the Phase-4 candidate are translatable. This is applied
            # to the reference the candidate is proven against, so it is sound:
            # Alive2 simply assumes all memory may alias (conservative), which
            # can only cause more rejections, never a false PASS.
            ir_text = re.sub(r",\s*!tbaa\s+![0-9]+", "", ir_text)
            ir_text = re.sub(r",\s*!tbaa\.struct\s+![0-9]+", "", ir_text)
            ir_text = re.sub(r",\s*!range\s+![0-9]+", "", ir_text)
            ir_text = re.sub(r",\s*!alias\.scope\s+![0-9]+", "", ir_text)
            ir_text = re.sub(r",\s*!noalias\s+![0-9]+", "", ir_text)
                
            # 2. Run the full compilation pipeline
            t0 = time.perf_counter()
            parsed: ParsedModule = compile_module(ir_text, config)
            pipeline_latency = time.perf_counter() - t0
            
            # 3. Write final IR back to .ll
            with open(ll_file, "w") as f:
                f.write(parsed.final_module_ir)
                
            # 4. Compile optimized .ll to .o
            subprocess.run(["clang", "-c", str(ll_file), "-o", str(o_file)], check=True)
            
            # Record metrics
            orig_counts = get_instruction_counts(parsed.source_ir)
            final_counts = get_instruction_counts(parsed.final_module_ir)
            
            for record in parsed.functions:
                orig_inst = orig_counts.get(record.name, 0)
                final_inst = final_counts.get(record.name, orig_inst)
                
                reduction_pct = 0.0
                if orig_inst > 0:
                    reduction_pct = ((orig_inst - final_inst) / orig_inst) * 100.0
                    
                row = {
                    "file_name": bc_file.name,
                    "function_name": record.name,
                    "complexity": record.complexity,
                    "tokens": record.token_count,
                    "triaged_out": record.triaged_out,
                    "model": record.assigned_model,
                    "llm_latency_s": round(record.llm_latency_seconds, 3) if record.llm_latency_seconds is not None else None,
                    "verification_latency_s": round(record.verification_latency_seconds, 3) if record.verification_latency_seconds is not None else None,
                    "verdict": record.verdict.value,
                    "orig_instrs": orig_inst,
                    "final_instrs": final_inst,
                    "reduction_pct": round(reduction_pct, 2)
                }
                
                with open(output_csv, "a", newline="") as csvfile:
                    writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                    writer.writerow(row)
                total_evaluated += 1
                
        except Exception as e:
            logger.error(f"Failed to process {bc_file.name}: {e}")
            error_row = {
                "file_name": bc_file.name,
                "function_name": "unknown_failed_module",
                "complexity": None,
                "tokens": None,
                "triaged_out": False,
                "model": "error",
                "llm_latency_s": None,
                "verification_latency_s": None,
                "verdict": "error",
                "orig_instrs": 0,
                "final_instrs": 0,
                "reduction_pct": 0.0
            }
            with open(output_csv, "a", newline="") as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writerow(error_row)
            total_evaluated += 1
            continue
            
    logger.info(f"Wrote {total_evaluated} rows to {output_csv}")
    logger.info("DONE. Run `ninja` in the build directory to relink the executables with the modified .o files.")
        
def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    
    parser = argparse.ArgumentParser(description="SPEC Evaluation Harness for llvm-test-suite.")
    parser.add_argument("--build-dir", type=str, required=True, help="Directory containing llvm-test-suite CMake build")
    parser.add_argument("--output-csv", type=str, default="spec_results.csv", help="Output CSV path")
    parser.add_argument("--complexity-threshold", type=int, default=5, help="Override triage complexity threshold")
    
    args = parser.parse_args()
    process_spec_corpus(Path(args.build_dir), Path(args.output_csv), args.complexity_threshold)

if __name__ == "__main__":
    main()
