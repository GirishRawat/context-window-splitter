"""Small-batch Gemini validation: re-run the 33 previously-`unsupported` functions
(from spec_results_prefix.csv) through the now-Gemini pipeline and report
verdict + instruction reduction + latency for each. Confirms the rate limiter,
retry/backoff, and — the real question — how many produce NON-ZERO verified
reductions where the local models only echoed. Prints only; writes no CSV.
"""
import csv
import re
import subprocess
import sys
import time
from collections import defaultdict, Counter
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
SRC_CSV = "spec_results_prefix.csv"


def normalize(t):
    t = t.replace("uwtable(sync)", "uwtable")
    t = re.sub(r"memory\([^)]+\)", "", t)
    t = re.sub(r"!llvm\.module\.flags.*", "", t)
    for md in ("tbaa", "tbaa\\.struct", "range", "alias\\.scope", "noalias"):
        t = re.sub(rf",\s*!{md}\s+![0-9]+", "", t)
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
    print(f"model={config.llm_routing.tiers['fast'].models[0]}  rpm={config.llm_routing.requests_per_minute}\n")

    targets = defaultdict(set)
    for r in csv.DictReader(open(SRC_CSV)):
        if r["verdict"] == "unsupported":
            targets[r["file_name"]].add(r["function_name"])

    verdicts = Counter()
    reductions = []
    t_start = time.time()
    n = 0
    for fname, fns in targets.items():
        bc = find_bc(fname)
        if not bc:
            print(f"[skip] {fname}: .bc not found"); continue
        ll = bc.with_suffix(".gb.ll")
        try:
            subprocess.run(["clang", "-S", "-emit-llvm", str(bc), "-o", str(ll)],
                           check=True, capture_output=True)
            parsed = parse_module(normalize(open(ll).read()))
        except Exception as e:
            print(f"[skip] {fname}: {str(e)[:70]}"); continue

        triage_module(parsed, config)
        for rec in parsed.functions:
            rec.triaged_out = rec.name not in fns
        route_module(parsed, config)
        reconstruct_module(parsed, config)
        verify_module(parsed, config)

        orig_counts = get_instruction_counts(parsed.source_ir)
        for rec in parsed.functions:
            if rec.name in fns:
                v = rec.verdict.value
                verdicts[v] += 1
                n += 1
                oi = orig_counts.get(rec.name, 0)
                red = None
                if v == "passed" and rec.candidate_ir and oi:
                    fi = get_instruction_counts(rec.candidate_ir).get(rec.name, oi)
                    red = 100.0 * (oi - fi) / oi
                    reductions.append(red)
                redtxt = f"{red:+.1f}%" if red is not None else ""
                lat = f"{rec.llm_latency_seconds:.1f}s" if rec.llm_latency_seconds else "-"
                print(f"  {fname:24s} {rec.name[:32]:32s} {v:12s} {redtxt:>7s}  ({lat})")

    elapsed = time.time() - t_start
    print(f"\n=== SUMMARY ({n} functions, {elapsed/60:.1f} min) ===")
    for k, c in verdicts.most_common():
        print(f"  {k:12s} {c}")
    real = [r for r in reductions if r > 0.01]
    print(f"\n  PASSED: {verdicts.get('passed', 0)}  |  with real reduction (>0%): {len(real)}")
    if real:
        print(f"  mean reduction (real): {sum(real)/len(real):.1f}%  |  best: {max(real):.1f}%")


if __name__ == "__main__":
    main()
