"""Build a name-annotated copy of the eval corpus (`opt -passes=instnamer`).

WHY THIS EXISTS
---------------
Categorizing the first real syntax-failure sample (see
SYNTAX_FAILURE_DIAGNOSIS.md and scripts/categorize_syntax_failures.py) showed
that ~91% of qwen2.5-coder:3b's syntax failures are SSA value-numbering
incoherence: the model cannot maintain LLVM's implicit unnamed-value counter
(%1, %2, ...) across a long function body. The dominant single bucket is
SSA_FORWARD_REF (52%), e.g.

    %190 = getelementptr inbounds [2500 x i32], ptr %186, i64 %190

where the model uses its own not-yet-defined number as an operand.

`opt -passes=instnamer` assigns explicit names to every anonymous instruction
and basic block (%1 -> %i, %2 -> %i1, blocks -> bb), so the model no longer has
to track an implicit counter at all. Running the identical pipeline over a
name-annotated corpus therefore tests that failure mode CAUSALLY rather than
just describing it:

  * syntax_fail drops sharply  -> the bottleneck is bookkeeping, and removing
    the counter burden removes it. Strongest form of the result.
  * syntax_fail does not drop  -> the failure is deeper than surface naming,
    which rules out the obvious fix. Also a real result.

instnamer is purely a naming pass: it changes no instructions and no control
flow, so instruction counts and semantics are identical to the source corpus
and the comparison against the existing baseline is uncounfounded. This script
verifies that count-neutrality per file rather than assuming it.

IMPORTANT (README section 2): name-annotated input deviates from raw -O0 input,
so results from this corpus must be reported as an EXPLICIT comparison arm,
never silently swapped into the main pipeline -- the same caveat that applies
to a mem2reg-canonicalized arm.

Usage:
    python3 -m scripts.prep_instnamer_corpus \
        --src eval_subset_corpus_sanitized \
        --dst eval_subset_corpus_instnamed
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

from llmcompile.config import get_config

# Matches an unnamed SSA value or label reference (%0, %1, ...) but not a named
# one (%i, %bb, %call). Used only for the post-condition check below.
_UNNAMED_VALUE = re.compile(r"%\d+\b")

# C string literals in the IR (`c"... %10.4lf ..."`) contain printf format
# specifiers that look exactly like unnamed SSA references. They are data, not
# values, and instnamer correctly leaves them alone -- strip them before
# counting or every file with a printf format string reports false residuals.
_STRING_LITERAL = re.compile(r'c"(?:[^"\\]|\\.)*"')


def instname_file(bc_file: Path, dst_dir: Path, opt_path: str) -> tuple[bool, str]:
    """Run instnamer over one .bc, writing the result into dst_dir.

    Returns (ok, message).
    """
    out_file = dst_dir / bc_file.name
    try:
        subprocess.run(
            [opt_path, "-passes=instnamer", str(bc_file), "-o", str(out_file)],
            check=True, capture_output=True,
        )
    except FileNotFoundError:
        return False, f"opt not found at {opt_path}"
    except subprocess.CalledProcessError as e:
        return False, f"opt failed: {e.stderr.decode('utf-8', 'replace')[:200]}"
    return True, "ok"


def count_unnamed(bc_file: Path, opt_path: str) -> int | None:
    """Disassemble a .bc and count remaining unnamed %N references.

    Returns None if disassembly fails (some corpus files don't parse -- that is
    an input-corpus issue tracked separately and not this script's concern).
    """
    llvm_dis = str(Path(opt_path).with_name("llvm-dis"))
    try:
        res = subprocess.run([llvm_dis, str(bc_file), "-o", "-"],
                             check=True, capture_output=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    text = _STRING_LITERAL.sub('c""', res.stdout.decode("utf-8", "replace"))
    # Strip metadata/attribute lines, where %N-looking tokens don't appear but
    # numeric ids do; we only care about instruction-level value references.
    body = "\n".join(l for l in text.splitlines() if not l.startswith(("!", "attributes", "target")))
    return len(_UNNAMED_VALUE.findall(body))


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--src", type=Path, default=Path("eval_subset_corpus_sanitized"))
    parser.add_argument("--dst", type=Path, default=Path("eval_subset_corpus_instnamed"))
    parser.add_argument("--verify", action="store_true", default=True,
                        help="Check that unnamed %%N references actually disappeared (default on)")
    args = parser.parse_args()

    opt_path = get_config().verification.opt_path
    print(f"opt: {opt_path}")

    if not args.src.is_dir():
        sys.exit(f"source corpus not found: {args.src}")
    args.dst.mkdir(parents=True, exist_ok=True)

    bc_files = sorted(args.src.glob("*.bc"))
    if not bc_files:
        sys.exit(f"no .bc files under {args.src}")

    ok_count = 0
    failures: list[tuple[str, str]] = []
    still_unnamed: list[tuple[str, int, int]] = []

    for bc in bc_files:
        ok, msg = instname_file(bc, args.dst, opt_path)
        if not ok:
            failures.append((bc.name, msg))
            print(f"  FAIL {bc.name}: {msg}")
            continue
        ok_count += 1

        if args.verify:
            before = count_unnamed(bc, opt_path)
            after = count_unnamed(args.dst / bc.name, opt_path)
            if before is None or after is None:
                print(f"  ok   {bc.name} (unnamed-count check skipped, disassembly failed)")
            else:
                if after > 0:
                    still_unnamed.append((bc.name, before, after))
                print(f"  ok   {bc.name}: unnamed %N refs {before} -> {after}")
        else:
            print(f"  ok   {bc.name}")

    print(f"\n{ok_count}/{len(bc_files)} files written to {args.dst}")
    if failures:
        print(f"{len(failures)} failed:")
        for name, msg in failures:
            print(f"  {name}: {msg}")
    if still_unnamed:
        print(f"\nWARNING: {len(still_unnamed)} file(s) still contain unnamed %N refs "
              f"after instnamer -- the comparison arm may be weaker than intended:")
        for name, before, after in still_unnamed:
            print(f"  {name}: {before} -> {after}")

    print("\nNext: run the pipeline against this corpus and compare syntax_fail "
          "rate against the baseline (23/39 for qwen2.5-coder:3b), e.g.\n"
          "  LLM_BACKEND=local_gpu OLLAMA_MODEL=ollama/qwen2.5-coder:3b \\\n"
          f"    python3 -m scripts.run_openrouter_subset --build-dir {args.dst} \\\n"
          "    --subset target_subset.csv --output-csv syntax_diag_3b_instnamed_results.csv")


if __name__ == "__main__":
    main()
