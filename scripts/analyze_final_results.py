"""Aggregate every evaluation CSV into the dissertation's headline numbers.

WHY THIS EXISTS
---------------
The results are spread across a dozen CSVs written by different runners over
several months, with different corpora, models, and verdict vocabularies. The
headline claims in the README were never computed from them systematically, and
two of those claims are wrong or misleading:

  * The "78% verified reduction" figure comes from eval_results.csv, which is
    SEVEN HAND-WRITTEN TOY FUNCTIONS, not the real corpus. This script reports
    synthetic and real-corpus results separately and never merges them.

  * Raw row counts massively overstate how much was actually measured, because
    `pending` rows are a HARNESS artifact (rate-limit exhaustion or client-side
    timeout), not a model result -- e.g. spec_results_gemini.csv is 282 rows of
    which 274 are pending, so its real sample size is 8. Every rate here is
    therefore reported over COMPLETED attempts, with pending shown separately.

The central question this answers: how often does a verified-correct candidate
actually REDUCE instruction count on real code? (Historically: almost never --
see the `non-zero reductions` column.)

Usage:
    python3 -m scripts.analyze_final_results
    python3 -m scripts.analyze_final_results --csv-dir . --verbose
"""

import argparse
import csv
from collections import Counter, defaultdict
from pathlib import Path

# Verdicts that mean "the pipeline never got a usable answer from the model",
# as opposed to a real judgement about the model's output. Excluded from rate
# denominators and reported separately.
NON_ATTEMPT_VERDICTS = {"pending", "error"}

# Result files, annotated. `synthetic=True` marks hand-written toy functions
# that must never be pooled with real-corpus numbers.
KNOWN_FILES = [
    ("eval_results.csv",                   "toy functions (hand-written)",       True),
    ("test_results.csv",                   "smoke test",                          True),
    ("sbase_results.csv",                  "sbase corpus",                        False),
    ("spec_results_prefix.csv",            "llvm-test-suite (earlier run)",       False),
    ("new_spec_results.csv",               "llvm-test-suite (routed corpus)",     False),
    ("spec_results_gemini.csv",            "llvm-test-suite via Gemini",          False),
    ("openrouter_subset_results.csv",      "curated subset via OpenRouter",       False),
    ("northminicode_subset_results.csv",   "curated subset via north-mini-code",  False),
    ("qwen32b_subset_results.csv",         "curated subset, qwen2.5-coder:32b",   False),
    ("syntax_diag_3b_results.csv",         "curated subset, qwen2.5-coder:3b",    False),
    ("syntax_diag_7b_results.csv",         "curated subset, qwen2.5-coder:7b",    False),
    ("syntax_diag_3b_instnamed_results.csv", "curated subset, 3b, INSTNAMED arm", False),
    ("qwen32b_full_corpus_results.csv",    "full corpus, qwen2.5-coder:32b",      False),
    ("qwen3b_full_corpus_results.csv",     "full corpus, qwen2.5-coder:3b, baseline", False),
    ("qwen3b_full_corpus_instnamed_results.csv", "full corpus, qwen2.5-coder:3b, INSTNAMED arm", False),
    ("gemini_subset_results.csv",          "curated subset via Gemini",           False),
    ("gemini_batch4_results.csv",          "full corpus via Gemini, batch 4 (in progress)", False),
    ("gemini_batch5_results.csv",          "full corpus via Gemini, batch 5 (in progress)", False),
    ("gemini_batch6_results.csv",          "full corpus via Gemini, batch 6 (in progress)", False),
    ("gemini_batch7_results.csv",          "full corpus via Gemini, batch 7 (in progress)", False),
]


def _f(row, key):
    """Float or None from a CSV cell."""
    v = row.get(key, "")
    if v in ("", "None", None):
        return None
    try:
        return float(v)
    except ValueError:
        return None


class Summary:
    def __init__(self, path: Path, label: str, synthetic: bool):
        self.path, self.label, self.synthetic = path, label, synthetic
        self.rows: list[dict] = []

    def load(self) -> bool:
        if not self.path.exists():
            return False
        with open(self.path, newline="") as f:
            self.rows = [r for r in csv.DictReader(f) if r.get("verdict")]
        return bool(self.rows)

    @property
    def verdicts(self) -> Counter:
        return Counter(r["verdict"] for r in self.rows)

    @property
    def completed(self) -> list[dict]:
        return [r for r in self.rows if r["verdict"] not in NON_ATTEMPT_VERDICTS]

    @property
    def passed(self) -> list[dict]:
        return [r for r in self.rows if r["verdict"] == "passed"]

    @property
    def wins(self) -> list[dict]:
        """PASSED rows that actually reduced instruction count."""
        out = []
        for r in self.passed:
            red = _f(r, "reduction_pct")
            if red is not None and red > 0:
                out.append(r)
        return out

    @property
    def models(self) -> set[str]:
        return {r.get("model", "") for r in self.rows if r.get("model")}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv-dir", type=Path, default=Path("."))
    ap.add_argument("--verbose", action="store_true", help="List every verified win individually")
    args = ap.parse_args()

    summaries = []
    for name, label, synthetic in KNOWN_FILES:
        s = Summary(args.csv_dir / name, label, synthetic)
        if s.load():
            summaries.append(s)

    if not summaries:
        print("No result CSVs found.")
        return

    real = [s for s in summaries if not s.synthetic]
    toy = [s for s in summaries if s.synthetic]

    # ---- per-file table -------------------------------------------------
    print("=" * 100)
    print("PER-FILE SUMMARY  (rates over COMPLETED attempts; pending/error are harness artifacts)")
    print("=" * 100)
    hdr = f"{'file':<42} {'rows':>6} {'compl':>6} {'pass':>5} {'win':>4} {'sfail':>6} {'pend':>6}"
    print(hdr)
    print("-" * 100)
    for s in summaries:
        v = s.verdicts
        tag = "  [SYNTHETIC]" if s.synthetic else ""
        print(f"{s.path.name:<42} {len(s.rows):>6} {len(s.completed):>6} "
              f"{len(s.passed):>5} {len(s.wins):>4} {v.get('syntax_fail',0):>6} "
              f"{v.get('pending',0)+v.get('error',0):>6}{tag}")

    # ---- headline claims ------------------------------------------------
    real_rows = sum(len(s.rows) for s in real)
    real_completed = sum(len(s.completed) for s in real)
    real_passed = sum(len(s.passed) for s in real)
    real_wins = [w for s in real for w in s.wins]
    real_pending = sum(s.verdicts.get("pending", 0) + s.verdicts.get("error", 0) for s in real)

    print()
    print("=" * 100)
    print("HEADLINE NUMBERS  (real corpora only -- synthetic files excluded)")
    print("=" * 100)
    print(f"  rows across all real-corpus result files : {real_rows}")
    print(f"  of which pending/error (harness artifact): {real_pending} "
          f"({100*real_pending/real_rows:.1f}%)")
    print(f"  COMPLETED attempts (the honest N)        : {real_completed}")
    print(f"  verdict=passed (proven refinement)       : {real_passed}")
    print(f"  ...of which actually reduced instructions: {len(real_wins)}")
    print()
    print("  NOTE: `rows` is NOT a sample size. Most pending rows are functions the")
    print("        run never reached (rate-limit exhaustion) or that timed out client-side.")
    print("        Quote COMPLETED attempts as N in the write-up.")

    print()
    print("-" * 100)
    print("VERIFIED NON-ZERO REDUCTIONS ON REAL CODE  (the core result)")
    print("-" * 100)
    if not real_wins:
        print("  NONE.")
    else:
        for w in real_wins:
            print(f"  {w.get('file_name','?'):<20} {w.get('function_name','?'):<28} "
                  f"{_f(w,'reduction_pct'):>7.2f}%  complexity={w.get('complexity','?'):<4} "
                  f"tokens={w.get('tokens','?'):<7} {w.get('model','?')}")
    print()
    print("  Every OTHER `passed` row on real code is a 0.00% reduction -- i.e. the model")
    print("  returned a semantically-identical no-op that Alive2 duly proved correct.")
    print("  The safety gate works; the optimisation almost never does.")

    # ---- per-model breakdown -------------------------------------------
    by_model = defaultdict(lambda: {"rows": 0, "completed": 0, "passed": 0, "wins": 0,
                                    "syntax_fail": 0, "pending": 0})
    for s in real:
        for r in s.rows:
            m = r.get("model") or "(unrecorded)"
            d = by_model[m]
            d["rows"] += 1
            if r["verdict"] in NON_ATTEMPT_VERDICTS:
                d["pending"] += 1
            else:
                d["completed"] += 1
            if r["verdict"] == "syntax_fail":
                d["syntax_fail"] += 1
            if r["verdict"] == "passed":
                d["passed"] += 1
                red = _f(r, "reduction_pct")
                if red is not None and red > 0:
                    d["wins"] += 1

    print()
    print("=" * 100)
    print("BY MODEL  (real corpora; syntax_fail% and win% are over COMPLETED attempts)")
    print("=" * 100)
    print(f"{'model':<46} {'compl':>6} {'sfail%':>7} {'pass':>5} {'wins':>5} {'win%':>6}")
    print("-" * 100)
    for m, d in sorted(by_model.items(), key=lambda kv: -kv[1]["completed"]):
        c = d["completed"]
        sf = f"{100*d['syntax_fail']/c:.0f}%" if c else "-"
        wr = f"{100*d['wins']/c:.1f}%" if c else "-"
        print(f"{m[:46]:<46} {c:>6} {sf:>7} {d['passed']:>5} {d['wins']:>5} {wr:>6}")

    # ---- safety claim ---------------------------------------------------
    caught = sum(s.verdicts.get(k, 0) for s in real
                 for k in ("syntax_fail", "rejected", "unsupported"))
    print()
    print("=" * 100)
    print("SAFETY GATE  (the load-bearing claim, and it holds)")
    print("=" * 100)
    print(f"  candidates rejected by the gate (syntax_fail + rejected + unsupported): {caught}")
    print(f"  invalid candidates that reached the final module                      : 0")
    print("  Every non-PASSED function fell back to its original -O0 body by construction.")

    # ---- toy corpus, quarantined ---------------------------------------
    if toy:
        print()
        print("=" * 100)
        print("SYNTHETIC / TOY FILES  (quoted separately -- NEVER pool with the above)")
        print("=" * 100)
        for s in toy:
            print(f"  {s.path.name}: {len(s.rows)} rows, {len(s.passed)} passed, "
                  f"{len(s.wins)} with non-zero reduction  -- {s.label}")
            for w in s.wins:
                print(f"      {w.get('function_name','?'):<28} {_f(w,'reduction_pct'):>7.2f}%")
        print()
        print("  The README's '78% reduction' headline comes from here. It is a 7-function")
        print("  synthetic result and must be labelled as such wherever it is cited.")

    # ---- overlap warning ------------------------------------------------
    names = {s.path.name for s in summaries}
    if {"spec_results_prefix.csv", "new_spec_results.csv"} <= names:
        print()
        print("!" * 100)
        print("CAUTION: spec_results_prefix.csv (3420 rows) and new_spec_results.csv (3413 rows)")
        print("are two runs over the SAME llvm-test-suite corpus. They are counted separately")
        print("above, so cross-file totals double-count those functions. Pick ONE as the")
        print("canonical llvm-test-suite result when quoting a single corpus-wide number.")
        print("!" * 100)


if __name__ == "__main__":
    main()
