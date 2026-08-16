"""Research: is valuable optimization theoretically possible + verifiable on real
functions? For each function, take the pipeline's standalone original_ir, apply
LLVM's OWN optimizer (mem2reg, then -O2), measure instruction reduction, and run
Alive2 on (original, optimized). This isolates the ceiling:

- big reduction + Alive2 PASSES  => headroom real AND verifiable; only the MODEL
  is the gap (it just needs to produce what `opt` produces).
- big reduction + Alive2 UNSUPPORTED/TIMEOUT => verifier can't handle real opts.
- small reduction => less headroom than assumed.
"""
import re, subprocess, sys
sys.path.insert(0, ".")
import llvmlite.binding as llvm

from llmcompile.phases.p1_parse import parse_module
from llmcompile.eval.harness import get_instruction_counts

TOOL = "/Users/girishrawat/llvm_toolchain/llvm-project/llvm/build/bin"
OPT = f"{TOOL}/opt"
ALIVE = "/Users/girishrawat/llvm_toolchain/alive2/build/alive-tv"


def normalize(t):
    t = t.replace("uwtable(sync)", "uwtable")
    t = re.sub(r"memory\([^)]+\)", "", t)
    t = re.sub(r"!llvm\.module\.flags.*", "", t)
    for md in ("tbaa", "tbaa\\.struct", "range", "alias\\.scope", "noalias"):
        t = re.sub(rf",\s*!{md}\s+![0-9]+", "", t)
    return t


def find_bc(name):
    import pathlib
    for p in pathlib.Path("build").rglob(name):
        return p
    return None


def run_opt(src_ll, passes):
    """Return optimized IR text, or None on failure."""
    try:
        r = subprocess.run([OPT, "-S", passes, src_ll, "-o", "/tmp/opt_out.ll"],
                           capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            return None
        return open("/tmp/opt_out.ll").read()
    except Exception:
        return None


def alive(src_ll, tgt_ll):
    try:
        r = subprocess.run([ALIVE, src_ll, tgt_ll], capture_output=True,
                           text=True, timeout=90)
        out = r.stdout + r.stderr
        if "1 correct transformation" in out and "0 incorrect" in out:
            return "PASSED"
        if "incorrect transformation" in out and "1 incorrect" in out:
            return "REJECTED"
        if "Could not translate" in out or "Unsupported" in out:
            return "UNSUPPORTED"
        return "?"
    except subprocess.TimeoutExpired:
        return "TIMEOUT"


CASES = [("floyd-warshall.bc", "init_array"),
         ("perlin.bc", "grad"),
         ("fasta.bc", "random_fasta"),
         ("richards_benchmark.bc", "handlerfn")]


def main():
    llvm.initialize(); llvm.initialize_native_target(); llvm.initialize_native_asmprinter()
    try: llvm.set_option("llvmlite", "-opaque-pointers")
    except Exception: pass

    print(f"{'function':22s} {'orig':>5s} {'mem2reg':>18s} {'-O2':>18s}")
    print("-" * 68)
    for fname, fn in CASES:
        bc = find_bc(fname)
        if not bc:
            print(f"{fn:22s} [bc not found]"); continue
        ll = bc.with_suffix(".hr.ll")
        subprocess.run(["clang", "-S", "-emit-llvm", str(bc), "-o", str(ll)],
                       check=True, capture_output=True)
        parsed = parse_module(normalize(open(ll).read()))
        rec = [f for f in parsed.functions if f.name == fn]
        if not rec:
            print(f"{fn:22s} [not found]"); continue
        rec = rec[0]
        src = "/tmp/hr_src.ll"
        open(src, "w").write(rec.original_ir)
        orig = get_instruction_counts(rec.original_ir).get(fn, 0)

        row = f"{fn[:22]:22s} {orig:5d}"
        for passes in ("-passes=mem2reg", "-passes=default<O2>"):
            opt_ir = run_opt(src, passes)
            if opt_ir is None:
                row += f" {'opt-fail':>18s}"; continue
            opt_ir = normalize(opt_ir)  # opt re-adds memory(...) attrs; strip again
            open("/tmp/hr_tgt.ll", "w").write(opt_ir)
            new = get_instruction_counts(opt_ir).get(fn, orig)
            red = 100.0 * (orig - new) / orig if orig else 0.0
            verdict = alive(src, "/tmp/hr_tgt.ll")
            row += f" {new:3d}({red:+4.0f}%){verdict:>9s}"
        print(row)


if __name__ == "__main__":
    main()
