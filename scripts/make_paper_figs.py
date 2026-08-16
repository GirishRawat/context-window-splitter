"""Generate figures for the dissertation paper from the real evaluation CSVs.
Outputs PDFs into the LaTeX template directory. Academic styling, colourblind-safe.
"""
import csv
from collections import Counter
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path("/Users/girishrawat/Documents/Projects/context-window-splitter")
OUT = Path("/Users/girishrawat/Downloads/Dissertation_Paper_Template - LATEX")

plt.rcParams.update({
    "font.family": "serif",
    "font.size": 9,
    "axes.grid": True,
    "grid.alpha": 0.3,
    "figure.dpi": 200,
})

# Colourblind-safe (Okabe-Ito subset)
C_SBASE = "#0072B2"   # blue
C_SPEC = "#D55E00"    # vermillion
C_GREEN = "#009E73"
C_ORANGE = "#E69F00"
C_GREY = "#999999"


def load(path):
    with open(path) as f:
        return list(csv.DictReader(f))


def _num(rows, key):
    out = []
    for r in rows:
        v = r.get(key, "")
        if v not in ("", "None", None):
            try:
                out.append((r, float(v)))
            except ValueError:
                pass
    return out


# ---------------------------------------------------------------------------
# Figure 1: complexity vs token count scatter (sbase + llvm-test-suite)
# ---------------------------------------------------------------------------
def fig_complexity():
    sbase = load(ROOT / "sbase_results.csv")
    spec = load(ROOT / "spec_results.csv")

    fig, ax = plt.subplots(figsize=(3.4, 2.6))
    for rows, colour, label in [(sbase, C_SBASE, "sbase"),
                                (spec, C_SPEC, "llvm-test-suite")]:
        xs, ys = [], []
        for r in rows:
            try:
                c = float(r["complexity"]); t = float(r["tokens"])
            except (ValueError, KeyError):
                continue
            xs.append(c); ys.append(t)
        ax.scatter(xs, ys, s=10, alpha=0.55, edgecolors="none",
                   color=colour, label=label)

    ax.axvline(5, color=C_GREY, ls="--", lw=0.9)
    ax.text(5.3, ax.get_ylim()[1]*0.94, "triage\nthreshold",
            fontsize=6.5, color=C_GREY, va="top")
    ax.set_xlabel("Cyclomatic complexity")
    ax.set_ylabel("Token count")
    ax.set_xscale("symlog")
    ax.legend(frameon=False, fontsize=7, loc="lower right")
    fig.tight_layout()
    fig.savefig(OUT / "complexity_plot.pdf", bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Figure 2: verdict distribution for routed functions (sbase + llvm-test-suite)
# ---------------------------------------------------------------------------
def fig_verdicts():
    sbase = load(ROOT / "sbase_results.csv")
    spec = load(ROOT / "spec_results.csv")

    order = ["pending", "syntax_fail", "unsupported", "rejected", "passed"]
    pretty = {"pending": "No IR\n(pending)", "syntax_fail": "Syntax\nfail",
              "unsupported": "Alive2\nunsupported", "rejected": "Rejected",
              "passed": "Passed"}
    colours = {"pending": C_GREY, "syntax_fail": C_ORANGE,
               "unsupported": C_SPEC, "rejected": "#CC79A7", "passed": C_GREEN}

    def counts(rows):
        c = Counter(r["verdict"] for r in rows if r["triaged_out"] == "False"
                    and r["verdict"] != "error")
        total = sum(c.values())
        return [100.0 * c.get(k, 0) / total for k in order], total

    sb, sb_n = counts(sbase)
    sp, sp_n = counts(spec)

    import numpy as np
    x = np.arange(len(order)); w = 0.38
    fig, ax = plt.subplots(figsize=(3.4, 2.6))
    ax.bar(x - w/2, sb, w, color=C_SBASE, label=f"sbase (n={sb_n})")
    ax.bar(x + w/2, sp, w, color=C_SPEC, label=f"llvm-test-suite (n={sp_n})")
    ax.set_xticks(x)
    ax.set_xticklabels([pretty[k] for k in order], fontsize=6.5)
    ax.set_ylabel("Share of routed functions (%)")
    ax.legend(frameon=False, fontsize=7)
    fig.tight_layout()
    fig.savefig(OUT / "verdict_plot.pdf", bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Figure 3: engineering journey - pre-fix vs post-fix verdict rates
# ---------------------------------------------------------------------------
def fig_journey():
    pre = load(ROOT / "spec_results.csv")          # before today's fixes
    post = load(ROOT / "new_spec_results.csv")      # after fixes (sample)

    order = ["pending", "syntax_fail", "unsupported"]
    labels = ["No IR extracted", "Syntax fail", "Reached Alive2"]
    colours = [C_GREY, C_ORANGE, C_GREEN]

    def rates(rows):
        c = Counter(r["verdict"] for r in rows if r["triaged_out"] == "False"
                    and r["verdict"] != "error")
        total = sum(c.values())
        return [100.0 * c.get(k, 0) / total for k in order], total

    pre_r, pre_n = rates(pre)
    post_r, post_n = rates(post)

    import numpy as np
    x = np.arange(len(order)); w = 0.38
    fig, ax = plt.subplots(figsize=(3.4, 2.6))
    b1 = ax.bar(x - w/2, pre_r, w, color=C_GREY, label=f"Pre-fix (n={pre_n})")
    b2 = ax.bar(x + w/2, post_r, w, color=C_GREEN, label=f"Post-fix (n={post_n})")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=7)
    ax.set_ylabel("Share of routed functions (%)")
    ax.legend(frameon=False, fontsize=7)
    fig.tight_layout()
    fig.savefig(OUT / "journey_plot.pdf", bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    fig_complexity()
    fig_verdicts()
    fig_journey()
    print("wrote figures to", OUT)
