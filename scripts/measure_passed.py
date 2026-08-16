"""Measure instruction reduction for the previously-unsupported functions, now
that the !tbaa fix lets them verify. Re-runs (deterministically) only the files
that produced at least one PASS, routing only the previously-unsupported targets,
and reports verdict + orig/final instruction counts + reduction% with full names.
"""
import csv
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, ".")
import llvmlite.binding as llvm

from llmcompile.phases.p1_parse import parse_module
from llmcompile.phases.p2_triage import triage_module
from llmcompile.phases.p3_route import route_module
from llmcompile.phases.p4_reconstruct import reconstruct_module
from llmcompile.phases.p5_verify import verify_module
from llmcompile.config import get_config
from llmcompile.eval.harness import get_instruction_counts

BUILD = Path("build")
# Files that produced at least one PASS in the rerun.
FILES_WITH_PASSES = {
    "fpcmp.bc", "perlin.bc", "floyd-warshall.bc", "fasta.bc",
    "stepanov_abstraction.bc", "functionobjects.bc",
}


def normalize(t):
    t = t.replace("uwtable(sync)", "uwtable")
    t = re.sub(r"memory\([^)]+\)", "", t)
    t = re.sub(r"!llvm\.module\.flags.*", "", t)
    t = re.sub(r",\s*!tbaa\s+![0-9]+", "", t)
    t = re.sub(r",\s*!tbaa\.struct\s+![0-9]+", "", t)
    t = re.sub(r",\s*!range\s+![0-9]+", "", t)
    t = re.sub(r",\s*!alias\.scope\s+![0-9]+", "", t)
    t = re.sub(r",\s*!noalias\s+![0-9]+", "", t)
    return t


def find_bc(name):
    for p in BUILD.rglob(name):
        return p
    return None


def main():
    llvm.initialize(); llvm.initialize_native_target(); llvm.initialize_native_asmprinter()
    try: llvm.set_option("llvmlite", "-opaque-pointers")
    except Exception: pass
    config = get_config()

    targets = defaultdict(set)
    for r in csv.DictReader(open("new_spec_results.csv")):
        if r["verdict"] == "unsupported" and r["file_name"] in FILES_WITH_PASSES:
            targets[r["file_name"]].add(r["function_name"])

    passes = []
    for fname, fns in targets.items():
        bc = find_bc(fname)
        if not bc:
            continue
        ll = bc.with_suffix(".measure.ll")
        try:
            subprocess.run(["clang", "-S", "-emit-llvm", str(bc), "-o", str(ll)],
                           check=True, capture_output=True)
            ir = normalize(open(ll).read())
            parsed = parse_module(ir)
        except Exception as e:
            print(f"[skip] {fname}: {str(e)[:70]}")
            continue

        triage_module(parsed, config)
        for rec in parsed.functions:
            rec.triaged_out = rec.name not in fns
        route_module(parsed, config)
        reconstruct_module(parsed, config)
        verify_module(parsed, config)

        orig_counts = get_instruction_counts(parsed.source_ir)
        for rec in parsed.functions:
            if rec.name in fns and rec.verdict.value == "passed":
                oi = orig_counts.get(rec.name, 0)
                fi = get_instruction_counts(rec.candidate_ir).get(rec.name, oi)
                red = 100.0 * (oi - fi) / oi if oi else 0.0
                passes.append((fname, rec.name, oi, fi, red))
                print(f"PASS {fname:24s} {rec.name[:40]:40s} "
                      f"{oi:4d} -> {fi:4d} instrs  ({red:+.1f}%)")

    print("\n=== VERIFIED OPTIMIZATIONS ON REAL CODE ===")
    real = [p for p in passes if p[4] > 0.01]
    print(f"  total PASSED: {len(passes)}")
    print(f"  with real instruction reduction (>0%): {len(real)}")
    if real:
        avg = sum(p[4] for p in real) / len(real)
        best = max(real, key=lambda p: p[4])
        print(f"  mean reduction (among real): {avg:.1f}%")
        print(f"  best: {best[1][:40]} at {best[4]:.1f}% ({best[2]}->{best[3]} instrs)")


if __name__ == "__main__":
    main()
