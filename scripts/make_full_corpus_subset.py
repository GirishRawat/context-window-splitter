"""Generate a subset CSV covering EVERY routed function in the corpus.

`run_openrouter_subset.py` drives off a subset CSV (default
`target_subset.csv`, a curated 40-function sample). For the full-corpus arm we
want every function that actually reaches the LLM -- i.e. everything that
survives Phase 2 triage -- rather than a hand-picked sample.

This runs Phases 1 and 2 only (parse + triage, both deterministic and local --
no LLM calls, no GPU) and emits the same schema `load_subset` expects, so the
existing runner consumes it unchanged.

Measured on eval_subset_corpus_sanitized: 371 total functions across 25 files,
of which 114 survive triage at complexity_threshold=5. `lists.bc` is excluded
automatically because it fails to parse in Phase 1 (a newer-LLVM attribute
llvmlite 0.43 rejects; see commit a59b5ad).

Usage:
    python3 -m scripts.make_full_corpus_subset \
        --build-dir eval_subset_corpus_sanitized \
        --output full_corpus_subset.csv
"""

import argparse
import csv
import subprocess
import sys
from pathlib import Path

import llvmlite.binding as llvm

from llmcompile.config import get_config
from llmcompile.phases.p1_parse import parse_module
from llmcompile.phases.p2_triage import triage_module
from scripts.run_openrouter_subset import normalize_ir

FIELDNAMES = ["file_name", "function_name", "complexity", "tokens", "orig_instrs"]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--build-dir", type=Path, default=Path("eval_subset_corpus_sanitized"))
    ap.add_argument("--output", type=Path, default=Path("full_corpus_subset.csv"))
    ap.add_argument("--complexity-threshold", type=int, default=5)
    ap.add_argument("--include-triaged", action="store_true",
                    help="Also list functions triaged out (they would pass through "
                         "unchanged; normally excluded since they never reach the LLM)")
    args = ap.parse_args()

    llvm.initialize()
    llvm.initialize_native_target()
    llvm.initialize_native_asmprinter()
    llvm.set_option("llvmlite", "-opaque-pointers")

    config = get_config()
    config.triage.complexity_threshold = args.complexity_threshold

    bc_files = sorted(args.build_dir.glob("*.bc"))
    if not bc_files:
        sys.exit(f"no .bc files under {args.build_dir}")

    rows: list[dict] = []
    total_funcs = 0
    skipped: list[tuple[str, str]] = []

    for bc in bc_files:
        ll = bc.with_suffix(".fullsubset.ll")
        try:
            subprocess.run(["clang", "-S", "-emit-llvm", str(bc), "-o", str(ll)],
                           check=True, capture_output=True)
            parsed = parse_module(normalize_ir(ll.read_text()))
            triage_module(parsed, config)
        except subprocess.CalledProcessError as e:
            skipped.append((bc.name, f"clang failed: {e}"))
            continue
        except Exception as e:
            # Phase 1 parse failures are an input-corpus issue (see lists.bc);
            # skip the file rather than abort the whole listing.
            skipped.append((bc.name, f"{type(e).__name__}: {str(e).splitlines()[0][:80]}"))
            continue
        finally:
            ll.unlink(missing_ok=True)

        total_funcs += len(parsed.functions)
        for rec in parsed.functions:
            if rec.triaged_out and not args.include_triaged:
                continue
            rows.append({
                "file_name": bc.name,
                "function_name": rec.name,
                "complexity": rec.complexity,
                "tokens": rec.token_count,
                "orig_instrs": "",
            })
        print(f"  {bc.name}: {len(parsed.functions)} funcs, "
              f"{sum(1 for r in parsed.functions if not r.triaged_out)} routed")

    with open(args.output, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES)
        w.writeheader()
        w.writerows(rows)

    print(f"\n{len(bc_files)} files scanned, {total_funcs} total functions")
    print(f"{len(rows)} rows written to {args.output} "
          f"({'including' if args.include_triaged else 'excluding'} triaged-out functions)")
    if skipped:
        print(f"\n{len(skipped)} file(s) skipped:")
        for name, why in skipped:
            print(f"  {name}: {why}")


if __name__ == "__main__":
    main()
