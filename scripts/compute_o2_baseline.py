"""
Adds an -O2 baseline column to the eval CSVs, without re-running the LLM
pipeline. This only needs `opt -O2` on each original .bc file, which is
independent of what the LLM produced -- so it's cheap and doesn't touch
Ollama/Gemini quota.

Usage:
    python scripts/compute_o2_baseline.py --build-dir build \
        new_spec_results.csv spec_results_gemini.csv

For each .bc file found under --build-dir:
  1. Run `opt -O2 -S` on it to get the -O2-optimized IR text.
  2. Apply the same normalization spec_runner.py applies to source IR
     (strip constructs llvmlite/LLVM14 can't parse: uwtable(sync),
     memory(...), module flags, !tbaa/!range/!alias.scope/!noalias).
  3. Parse with llvmlite and count instructions per function.

Then, for each input CSV, adds two columns:
  - opt2_instrs: instruction count of that function after -O2 (blank if the
    function no longer exists post-O2, e.g. fully inlined/dead-code-eliminated)
  - pct_of_o2_gap_closed: (orig - final) / (orig - opt2) * 100, i.e. what
    fraction of the *available* optimization headroom (orig -> opt2) the LLM
    pipeline's output actually captured. Blank when opt2_instrs is blank or
    equals orig_instrs (no headroom, would divide by zero).

CSVs are rewritten in place (a .bak copy of each is kept alongside).
"""

import argparse
import csv
import logging
import re
import shutil
import subprocess
from pathlib import Path

import llvmlite.binding as llvm

from llmcompile.config import get_config
from llmcompile.eval.harness import get_instruction_counts

logger = logging.getLogger(__name__)


def normalize_ir(ir_text: str) -> str:
    """Same normalization spec_runner.py applies before parsing with llvmlite,
    plus extra constructs that opt (LLVM 18) emits at -O2 but llvmlite's
    LLVM 14 parser doesn't understand. This is purely for the instruction
    COUNT (not a correctness-critical verification path), so it's fine to be
    aggressive and just drop these newer attributes/flags.
    """
    ir_text = ir_text.replace("uwtable(sync)", "uwtable")
    ir_text = re.sub(r"memory\([^)]+\)", "", ir_text)
    ir_text = re.sub(r"!llvm\.module\.flags.*", "", ir_text)
    ir_text = re.sub(r",\s*!tbaa\s+![0-9]+", "", ir_text)
    ir_text = re.sub(r",\s*!tbaa\.struct\s+![0-9]+", "", ir_text)
    ir_text = re.sub(r",\s*!range\s+![0-9]+", "", ir_text)
    ir_text = re.sub(r",\s*!alias\.scope\s+![0-9]+", "", ir_text)
    ir_text = re.sub(r",\s*!noalias\s+![0-9]+", "", ir_text)
    # LLVM 15+ instruction flags on zext/or (poison-value refinements)
    ir_text = ir_text.replace("zext nneg ", "zext ")
    ir_text = ir_text.replace("or disjoint ", "or ")
    # LLVM 16+ parameter attributes not present at -O0. [ \t]* (not \s*) so we
    # never eat a trailing newline and merge a "; Function Attrs:" comment
    # line into the next line (which would hide a declare/define from the
    # parser and cause spurious "use of undefined value" errors).
    ir_text = re.sub(r"\ballocptr\b[ \t]*", "", ir_text)
    ir_text = re.sub(r"\bdead_on_unwind\b[ \t]*", "", ir_text)
    ir_text = re.sub(r"\bwritable\b[ \t]*", "", ir_text)
    # LLVM 15+ function attribute (allocator-family hints), unknown to LLVM 14
    ir_text = re.sub(r'allockind\("[^"]*"\)[ \t]*', "", ir_text)
    return ir_text


def compute_o2_counts(build_dir: Path, opt_path: str) -> dict[tuple[str, str], int]:
    """Returns {(bc_file_name, function_name): instr_count_after_O2}."""
    counts: dict[tuple[str, str], int] = {}
    bc_files = sorted(build_dir.rglob("*.bc"))
    logger.info(f"Found {len(bc_files)} .bc files in {build_dir}")

    for i, bc_file in enumerate(bc_files, 1):
        try:
            result = subprocess.run(
                [opt_path, "-O2", "-S", str(bc_file), "-o", "-"],
                check=True, capture_output=True, text=True, timeout=120,
            )
            ir_text = normalize_ir(result.stdout)
            func_counts = get_instruction_counts(ir_text)
            for fn, cnt in func_counts.items():
                counts[(bc_file.name, fn)] = cnt
            logger.info(f"[{i}/{len(bc_files)}] {bc_file.name}: {len(func_counts)} functions survived -O2")
        except Exception as e:
            logger.error(f"[{i}/{len(bc_files)}] Failed on {bc_file.name}: {e}")

    return counts


def enrich_csv(csv_path: Path, o2_counts: dict[tuple[str, str], int]) -> None:
    with open(csv_path, "r", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames)
        rows = list(reader)

    if "opt2_instrs" not in fieldnames:
        fieldnames += ["opt2_instrs", "pct_of_o2_gap_closed"]

    matched = 0
    for row in rows:
        key = (row["file_name"], row["function_name"])
        opt2 = o2_counts.get(key)
        if opt2 is None:
            row["opt2_instrs"] = ""
            row["pct_of_o2_gap_closed"] = ""
            continue
        matched += 1
        row["opt2_instrs"] = opt2
        try:
            orig = int(row["orig_instrs"])
            final = int(row["final_instrs"])
        except (KeyError, ValueError):
            row["pct_of_o2_gap_closed"] = ""
            continue
        gap = orig - opt2
        if gap == 0:
            row["pct_of_o2_gap_closed"] = ""
        else:
            row["pct_of_o2_gap_closed"] = round((orig - final) / gap * 100.0, 2)

    backup = csv_path.with_suffix(csv_path.suffix + ".bak")
    shutil.copy(csv_path, backup)
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    logger.info(f"{csv_path}: matched -O2 baseline for {matched}/{len(rows)} rows (backup at {backup})")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_files", nargs="+", type=Path)
    parser.add_argument("--build-dir", type=Path, default=Path("build"))
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    llvm.initialize()
    llvm.initialize_native_target()
    llvm.initialize_native_asmprinter()
    llvm.set_option("llvmlite", "-opaque-pointers")

    config = get_config()
    o2_counts = compute_o2_counts(args.build_dir, config.verification.opt_path)

    for csv_path in args.csv_files:
        enrich_csv(csv_path, o2_counts)


if __name__ == "__main__":
    main()
