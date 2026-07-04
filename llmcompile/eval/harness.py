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

import llvmlite.binding as llvm

from llmcompile.orchestrator import compile_module
from llmcompile.config import get_config
from llmcompile.models import ParsedModule

logger = logging.getLogger(__name__)

def get_instruction_counts(ir_text: str) -> dict[str, int]:
    """Parse a full module using llvmlite and return a dict mapping function name to instruction count.
    
    This is the rigorous counting method required for the dissertation metrics.
    """
    mod = llvm.parse_assembly(ir_text)
    mod.verify()
    counts = {}
    for func in mod.functions:
        if func.is_declaration:
            continue
        count = sum(len(list(bb.instructions)) for bb in func.blocks)
        counts[func.name] = count
    return counts

def process_corpus(input_dir: Path, output_csv: Path, complexity_threshold: int) -> None:
    """Run the evaluation harness over a directory of .ll files."""
    if not input_dir.exists() or not input_dir.is_dir():
        logger.error(f"Input directory {input_dir} does not exist.")
        sys.exit(1)
        
    config = get_config()
    config.triage.complexity_threshold = complexity_threshold
    
    # Setup LLVM
    llvm.initialize()
    llvm.initialize_native_target()
    llvm.initialize_native_asmprinter()
    llvm.set_option("llvmlite", "-opaque-pointers")
    
    results = []
    
    ll_files = list(input_dir.glob("*.ll"))
    logger.info(f"Found {len(ll_files)} .ll files in {input_dir}")
    
    for ll_file in ll_files:
        logger.info(f"Processing {ll_file.name}...")
        
        try:
            with open(ll_file, "r") as f:
                ir_text = f.read()
                
            # Run the full compilation pipeline
            t0 = time.perf_counter()
            parsed: ParsedModule = compile_module(ir_text, config)
            pipeline_latency = time.perf_counter() - t0
            
            # Obtain exact instruction counts via llvmlite parsing
            orig_counts = get_instruction_counts(parsed.source_ir)
            final_counts = get_instruction_counts(parsed.final_module_ir)
            
            for record in parsed.functions:
                orig_inst = orig_counts.get(record.name, 0)
                final_inst = final_counts.get(record.name, orig_inst)
                
                reduction_pct = 0.0
                if orig_inst > 0:
                    reduction_pct = ((orig_inst - final_inst) / orig_inst) * 100.0
                    
                row = {
                    "file_name": ll_file.name,
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
                results.append(row)
                
        except Exception as e:
            logger.error(f"Failed to process {ll_file.name}: {e}")
            # Could append an error row here if desired, but skipping is safer for clean data
            continue
            
    # Write CSV
    if results:
        fieldnames = list(results[0].keys())
        with open(output_csv, "w", newline="") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(results)
        logger.info(f"Wrote {len(results)} rows to {output_csv}")
    else:
        logger.warning("No results to write.")
        
    # Gather Ollama digests
    digests = {}
    try:
        res = subprocess.run(["ollama", "list"], capture_output=True, text=True, check=True)
        for line in res.stdout.splitlines()[1:]: # skip header
            parts = line.split()
            if len(parts) >= 2:
                digests[parts[0]] = parts[1]
    except Exception as e:
        logger.warning(f"Could not fetch Ollama digests: {e}")

    # Write Metadata sidecar
    meta_path = output_csv.with_suffix('.meta.json')
    meta_data = {
        "timestamp": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
        "random_seed": config.random_seed,  # Read from config
        "models_configured": {
            tier: tc.models for tier, tc in config.llm_routing.tiers.items()
        },
        "ollama_digests": digests,
        "toolchain_paths": {
            "llvm_as": config.verification.llvm_as_path,
            "alive_tv": config.verification.alive_tv_path
        },
        "total_files_processed": len(ll_files),
        "total_functions_evaluated": len(results)
    }
    with open(meta_path, "w") as f:
        json.dump(meta_data, f, indent=2)
    logger.info(f"Wrote metadata to {meta_path}")

def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    
    parser = argparse.ArgumentParser(description="M5 Evaluation Harness for llmcompile pipeline.")
    parser.add_argument("--input-dir", type=str, required=True, help="Directory containing .ll corpus files")
    parser.add_argument("--output-csv", type=str, default="eval_results.csv", help="Output CSV path")
    parser.add_argument("--complexity-threshold", type=int, default=5, help="Override triage complexity threshold")
    
    args = parser.parse_args()
    process_corpus(Path(args.input_dir), Path(args.output_csv), args.complexity_threshold)

if __name__ == "__main__":
    main()
