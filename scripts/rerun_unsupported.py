"""Step 2: re-run the functions that previously came back UNSUPPORTED, now that
the sanitization strips !tbaa. For each (file, function) that was `unsupported`
in new_spec_results.csv, apply the fixed sanitization, run the pipeline phases on
just that function, and report the before->after verdict.

Reuses the same normalization as spec_runner.py (including the new tbaa strip)
so this is a faithful re-run, not a separate code path.
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

BUILD = Path("build")


def normalize(ir_text: str) -> str:
    """Identical to spec_runner.py normalization, including the tbaa fix."""
    ir_text = ir_text.replace("uwtable(sync)", "uwtable")
    ir_text = re.sub(r"memory\([^)]+\)", "", ir_text)
    ir_text = re.sub(r"!llvm\.module\.flags.*", "", ir_text)
    ir_text = re.sub(r",\s*!tbaa\s+![0-9]+", "", ir_text)
    ir_text = re.sub(r",\s*!tbaa\.struct\s+![0-9]+", "", ir_text)
    ir_text = re.sub(r",\s*!range\s+![0-9]+", "", ir_text)
    ir_text = re.sub(r",\s*!alias\.scope\s+![0-9]+", "", ir_text)
    ir_text = re.sub(r",\s*!noalias\s+![0-9]+", "", ir_text)
    return ir_text


def find_bc(name: str):
    for p in BUILD.rglob(name):
        return p
    return None


def main():
    llvm.initialize()
    llvm.initialize_native_target()
    llvm.initialize_native_asmprinter()
    try:
        llvm.set_option("llvmlite", "-opaque-pointers")
    except Exception:
        pass

    config = get_config()

    targets = defaultdict(set)
    for r in csv.DictReader(open("new_spec_results.csv")):
        if r["verdict"] == "unsupported":
            targets[r["file_name"]].add(r["function_name"])

    total = sum(len(v) for v in targets.values())
    print(f"Re-running {total} previously-unsupported functions across "
          f"{len(targets)} files\n")

    results = []
    for fname, fns in targets.items():
        bc = find_bc(fname)
        if not bc:
            print(f"[skip] {fname}: .bc not found")
            continue
        ll = bc.with_suffix(".rerun.ll")
        try:
            subprocess.run(["clang", "-S", "-emit-llvm", str(bc), "-o", str(ll)],
                           check=True, capture_output=True)
            ir = normalize(open(ll).read())
            parsed = parse_module(ir)
        except Exception as e:
            print(f"[skip] {fname}: parse failed: {str(e)[:80]}")
            continue

        triage_module(parsed, config)
        # Force-route ONLY the previously-unsupported targets in this file.
        for rec in parsed.functions:
            rec.triaged_out = rec.name not in fns

        route_module(parsed, config)
        reconstruct_module(parsed, config)
        verify_module(parsed, config)

        for rec in parsed.functions:
            if rec.name in fns:
                v = rec.verdict.value
                results.append((fname, rec.name, v))
                print(f"  {fname:26s} {rec.name[:34]:34s} unsupported -> {v}")

    print("\n=== SUMMARY (was unsupported, now) ===")
    from collections import Counter
    c = Counter(v for _, _, v in results)
    for k, n in c.most_common():
        print(f"  {k:14s} {n}")
    print(f"  re-run total: {len(results)}")


if __name__ == "__main__":
    main()
