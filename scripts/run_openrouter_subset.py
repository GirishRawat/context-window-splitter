"""
Runs the full pipeline over a curated SUBSET of functions (see
target_subset.csv) through a free-tier OpenRouter model, instead of the
whole corpus. This is deliberately budget-aware: OpenRouter's unfunded free
tier caps out at 50 requests/day and 20/minute, so blasting the full
387-function routed set (like the Gemini run) would die the same way the
Gemini run did (that one hit a 20-request/day cap and stalled at 283/3420
rows). A 30-50 function sample fits comfortably inside a single day's quota.

Mechanism: for each .bc file that contains at least one selected function,
run Phase 1 (parse) + Phase 2 (triage) normally, then FORCE triaged_out=True
on every function NOT in the selection -- so only the selected functions
ever reach Phase 3 (the LLM call). This keeps the per-file disassembly/parse
overhead (cheap, local) while making sure API calls are spent only on the
functions we picked.

Usage:
    export OPENROUTER_API_KEY=...
    export LLM_BACKEND=openrouter
    python scripts/run_openrouter_subset.py --build-dir build \
        --subset target_subset.csv --output-csv openrouter_subset_results.csv
"""

import argparse
import csv
import logging
import re
import subprocess
import time
from collections import defaultdict
from pathlib import Path

import llvmlite.binding as llvm

from llmcompile.models import ParsedModule
from llmcompile.config import get_config
from llmcompile.phases.p1_parse import parse_module
from llmcompile.phases.p2_triage import triage_module
from llmcompile.phases.p3_route import route_module
from llmcompile.phases.p4_reconstruct import reconstruct_module
from llmcompile.phases.p5_verify import verify_module
from llmcompile.phases.p6_assemble import assemble_module
from llmcompile.eval.harness import get_instruction_counts

logger = logging.getLogger(__name__)

FIELDNAMES = [
    "file_name", "function_name", "complexity", "tokens", "model",
    "llm_latency_s", "verification_latency_s", "verdict",
    "orig_instrs", "final_instrs", "reduction_pct",
    "finish_reason", "syntax_error",
]


def load_subset(subset_csv: Path) -> dict[str, set[str]]:
    """Returns {file_name: {function_name, ...}}."""
    targets = defaultdict(set)
    with open(subset_csv, "r") as f:
        for row in csv.DictReader(f):
            targets[row["file_name"]].add(row["function_name"])
    return targets


def normalize_ir(ir_text: str) -> str:
    """Same normalization spec_runner.py applies before parsing."""
    ir_text = ir_text.replace("uwtable(sync)", "uwtable")
    ir_text = re.sub(r"memory\([^)]+\)", "", ir_text)
    ir_text = re.sub(r"!llvm\.module\.flags.*", "", ir_text)
    ir_text = re.sub(r",\s*!tbaa\s+![0-9]+", "", ir_text)
    ir_text = re.sub(r",\s*!tbaa\.struct\s+![0-9]+", "", ir_text)
    ir_text = re.sub(r",\s*!range\s+![0-9]+", "", ir_text)
    ir_text = re.sub(r",\s*!alias\.scope\s+![0-9]+", "", ir_text)
    ir_text = re.sub(r",\s*!noalias\s+![0-9]+", "", ir_text)
    return ir_text


def run_subset(build_dir: Path, targets: dict[str, set[str]], output_csv: Path, complexity_threshold: int) -> None:
    config = get_config()
    config.triage.complexity_threshold = complexity_threshold

    llvm.initialize()
    llvm.initialize_native_target()
    llvm.initialize_native_asmprinter()
    llvm.set_option("llvmlite", "-opaque-pointers")

    completed: set[tuple[str, str]] = set()
    if output_csv.exists() and output_csv.stat().st_size > 0:
        with open(output_csv, "r") as f:
            for row in csv.DictReader(f):
                completed.add((row["file_name"], row["function_name"]))
        logger.info(f"Resuming: {len(completed)} functions already in {output_csv}")
    else:
        with open(output_csv, "w", newline="") as f:
            csv.DictWriter(f, fieldnames=FIELDNAMES).writeheader()

    bc_files = sorted(build_dir.rglob("*.bc"))
    bc_by_name = {p.name: p for p in bc_files}

    for file_name, wanted_functions in targets.items():
        remaining = {fn for fn in wanted_functions if (file_name, fn) not in completed}
        if not remaining:
            logger.info(f"Skipping {file_name} (all target functions already done)")
            continue

        bc_file = bc_by_name.get(file_name)
        if bc_file is None:
            logger.error(f"{file_name} not found under {build_dir}")
            continue

        logger.info(f"Processing {file_name} (targets: {sorted(remaining)})...")
        ll_file = bc_file.with_suffix(".subset.ll")
        try:
            subprocess.run(["clang", "-S", "-emit-llvm", str(bc_file), "-o", str(ll_file)], check=True)
        except subprocess.CalledProcessError as e:
            logger.error(f"{file_name}: clang -emit-llvm failed ({e}), skipping this file")
            continue
        ir_text = normalize_ir(ll_file.read_text())

        parsed: ParsedModule = parse_module(ir_text)
        triage_module(parsed, config)

        # Force every non-selected function to skip Phases 3-5.
        for record in parsed.functions:
            if record.name not in remaining:
                record.triaged_out = True

        route_module(parsed, config)
        reconstruct_module(parsed, config)
        verify_module(parsed, config)
        assemble_module(parsed, config)

        orig_counts = get_instruction_counts(parsed.source_ir)
        final_counts = get_instruction_counts(parsed.final_module_ir)

        for record in parsed.functions:
            if record.name not in remaining:
                continue
            orig_inst = orig_counts.get(record.name, 0)
            final_inst = final_counts.get(record.name, orig_inst)
            reduction_pct = 0.0
            if orig_inst > 0:
                reduction_pct = ((orig_inst - final_inst) / orig_inst) * 100.0

            row = {
                "file_name": file_name,
                "function_name": record.name,
                "complexity": record.complexity,
                "tokens": record.token_count,
                "model": record.assigned_model,
                "llm_latency_s": round(record.llm_latency_seconds, 3) if record.llm_latency_seconds is not None else None,
                "verification_latency_s": round(record.verification_latency_seconds, 3) if record.verification_latency_seconds is not None else None,
                "verdict": record.verdict.value,
                "orig_instrs": orig_inst,
                "final_instrs": final_inst,
                "reduction_pct": round(reduction_pct, 2),
                "finish_reason": record.finish_reason,
                "syntax_error": record.syntax_error,
            }
            with open(output_csv, "a", newline="") as f:
                csv.DictWriter(f, fieldnames=FIELDNAMES).writerow(row)
            logger.info(f"  [{record.name}] verdict={record.verdict.value} reduction={reduction_pct:.2f}%")

        ll_file.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-dir", type=Path, required=True)
    parser.add_argument("--subset", type=Path, default=Path("target_subset.csv"))
    parser.add_argument("--output-csv", type=Path, default=Path("openrouter_subset_results.csv"))
    parser.add_argument("--complexity-threshold", type=int, default=5)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    targets = load_subset(args.subset)
    logger.info(f"Loaded {sum(len(v) for v in targets.values())} target functions across {len(targets)} files")
    run_subset(args.build_dir, targets, args.output_csv, args.complexity_threshold)


if __name__ == "__main__":
    main()
