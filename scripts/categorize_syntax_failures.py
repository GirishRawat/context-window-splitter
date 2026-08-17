"""Categorize the root causes of Verdict.SYNTAX_FAIL rows.

Across the historical 387-function routed corpus (new_spec_results.csv),
122 functions (31.5%) failed with syntax_fail -- the LLM's IR didn't even
parse. Only 5 were ever semantically-wrong-but-valid (rejected). That raw
diagnostic text (llvm-as stderr, Ollama's finish_reason) was discarded at
the time and is unrecoverable; see SYNTAX_FAILURE_DIAGNOSIS.md for the full
background. This script buckets a *freshly regenerated* sample (same model family,
qwen2.5-coder 3b/7b, run via scripts/run_openrouter_subset.py after the
diagnostic-persistence fix) into failure modes, to tell truncation apart
from hallucinated references apart from garbled syntax.

Usage:
    python3 -m scripts.categorize_syntax_failures \
        syntax_diag_3b_results.csv syntax_diag_7b_results.csv
"""

import argparse
import csv
import re
from collections import Counter, defaultdict
from pathlib import Path

# Priority-ordered buckets. finish_reason is checked first (a direct signal,
# no parsing needed); the rest are regexes over llvm-as's stderr text.
#
# The first regeneration (qwen2.5-coder:3b, 23 syntax_fail rows) showed the
# original plan's guessed buckets (from SYNTAX_FAILURE_DIAGNOSIS.md) covered
# only 3/23 -- 87% fell into OTHER. Manual review of all 20 OTHER rows found
# one dominant, distinctive real failure mode not anticipated by the plan:
# the model cannot keep a coherent unnamed/implicit SSA value counter across
# a long function body. This surfaces as three different llvm-as error texts
# depending on exactly how the miscount manifests, so they get three buckets
# below (self-reference, forward-reference, type-mismatched reuse) rather
# than being force-fit into one -- keeping them separate is more diagnostic,
# and a caller who wants the aggregate can sum the three. 12/20 were
# SSA_FORWARD_REF alone, e.g. `%190 = getelementptr ..., i64 %190` -- the
# model reuses its own about-to-be-defined number as an operand.
_PATTERNS = [
    ("SSA_SELF_REFERENCE", re.compile(r"may reference their own value", re.IGNORECASE)),
    ("SSA_FORWARD_REF", re.compile(r"forward referenced", re.IGNORECASE)),
    # The inverse symptom: found at 32b scale (10/11 of that model's OTHER
    # bucket, near-identical wording), not seen at 3b/7b. Same root cause --
    # incoherent SSA numbering -- but here the model reuses/repeats a smaller
    # number instead of continuing the sequence, so llvm-as reports the next
    # instruction needed a HIGHER number than it got, rather than an
    # as-yet-undefined one. E.g. `%45 = load ...` where %49+ was required.
    ("SSA_NUMBER_TOO_LOW", re.compile(r"expected to be numbered .* or greater", re.IGNORECASE)),
    ("SSA_TYPE_MISMATCH", re.compile(r"defined with type .* but expected", re.IGNORECASE)),
    ("INVALID_LABEL_REF", re.compile(r"is not a basic block", re.IGNORECASE)),
    ("UNDECLARED_REFERENCE", re.compile(r"undefined value", re.IGNORECASE)),
    ("MALFORMED_SYNTAX", re.compile(
        r"expected value token|expected type|expected instruction opcode|expected '='", re.IGNORECASE)),
    ("SSA_REUSE", re.compile(r"multiple definition of", re.IGNORECASE)),
    ("STRUCTURAL", re.compile(r"expected top-level entity|unterminated", re.IGNORECASE)),
]


def categorize(finish_reason: str | None, syntax_error: str | None) -> str:
    if finish_reason == "length":
        return "TRUNCATED"
    text = syntax_error or ""
    for label, pattern in _PATTERNS:
        if pattern.search(text):
            return label
    return "OTHER"


def load_rows(paths: list[Path]) -> list[dict]:
    rows = []
    for path in paths:
        if not path.exists():
            print(f"warning: {path} not found, skipping")
            continue
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                row["_source_file"] = path.name
                rows.append(row)
    return rows


def token_bucket(tokens_str: str | None) -> str:
    try:
        tokens = int(float(tokens_str))
    except (TypeError, ValueError):
        return "unknown"
    if tokens < 2000:
        return "<2k"
    if tokens < 8000:
        return "2k-8k"
    if tokens < 16000:
        return "8k-16k"
    return "16k+"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_paths", nargs="+", type=Path,
                         help="One or more results CSVs (from run_openrouter_subset.py) to combine")
    parser.add_argument("--show-other", action="store_true",
                         help="Print the verbatim syntax_error text for every OTHER-bucketed row")
    args = parser.parse_args()

    rows = load_rows(args.csv_paths)
    if not rows:
        print("No rows loaded -- nothing to categorize.")
        return

    fail_rows = [r for r in rows if r.get("verdict") == "syntax_fail"]

    print(f"Loaded {len(rows)} rows from {len(args.csv_paths)} file(s); "
          f"{len(fail_rows)} are syntax_fail.\n")

    if not fail_rows:
        print("No syntax_fail rows to categorize.")
        return

    bucket_counts = Counter()
    by_model = defaultdict(Counter)
    by_token_bucket = defaultdict(Counter)
    other_rows = []

    for row in fail_rows:
        bucket = categorize(row.get("finish_reason"), row.get("syntax_error"))
        row["_bucket"] = bucket
        bucket_counts[bucket] += 1
        model = row.get("model") or "unknown"
        by_model[model][bucket] += 1
        by_token_bucket[token_bucket(row.get("tokens"))][bucket] += 1
        if bucket == "OTHER":
            other_rows.append(row)

    print("=== Bucket totals ===")
    for bucket, count in bucket_counts.most_common():
        pct = 100.0 * count / len(fail_rows)
        print(f"  {bucket:<22} {count:>4}  ({pct:5.1f}%)")

    print("\n=== By model ===")
    for model in sorted(by_model):
        total = sum(by_model[model].values())
        parts = ", ".join(f"{b}={c}" for b, c in by_model[model].most_common())
        print(f"  {model:<28} n={total:<4} {parts}")

    print("\n=== By token bucket ===")
    for tb in ["<2k", "2k-8k", "8k-16k", "16k+", "unknown"]:
        if tb not in by_token_bucket:
            continue
        total = sum(by_token_bucket[tb].values())
        parts = ", ".join(f"{b}={c}" for b, c in by_token_bucket[tb].most_common())
        print(f"  {tb:<10} n={total:<4} {parts}")

    if other_rows:
        print(f"\n=== OTHER bucket: {len(other_rows)} row(s) unmatched by any regex ===")
        if args.show_other:
            for row in other_rows:
                print(f"  [{row['_source_file']}] {row.get('file_name')}::{row.get('function_name')}"
                      f" (finish_reason={row.get('finish_reason')!r})")
                print(f"    {row.get('syntax_error')!r}")
        else:
            print("  Pass --show-other to print each one verbatim for manual review.")


if __name__ == "__main__":
    main()
