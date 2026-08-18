"""Dissertation figures from the evaluation CSVs.

Replaces the hardcoded-Mac-path assumptions in make_paper_figs.py (its ROOT and
OUT point at /Users/girishrawat/... and it reads a spec_results.csv that no
longer exists). Paths here are CLI arguments and default to the repo root.

Three figures:

  fig1_syntax_taxonomy   WHY the models fail. Buckets from
                         categorize_syntax_failures.py, grouped by model. This
                         is the novel result -- ~91% of 3b's syntax failures are
                         SSA value-numbering incoherence, not truncation.
  fig2_verdicts_by_model WHAT happens, per model, as a share of COMPLETED
                         attempts (pending/error excluded -- they are a harness
                         artifact, not a model result).
  fig3_capability_cliff  WHERE it fails in (complexity, tokens) space, with the
                         single verified real optimisation annotated.

Colour: Okabe-Ito, the standard colourblind-safe qualitative palette, matching
the existing house style in make_paper_figs.py. The verdict->colour and
model->colour maps are FIXED, so a verdict keeps its colour across every figure
and adding a model never repaints the others. Validated with the dataviz
skill's checker (all checks pass; the two low-contrast-vs-surface hues carry
direct value labels as the required relief).

Usage:
    python3 -m scripts.make_result_figs --out-dir figures
"""

import argparse
import csv
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from scripts.categorize_syntax_failures import categorize

plt.rcParams.update({
    "font.family": "serif",
    "font.size": 9,
    "axes.grid": True,
    "grid.alpha": 0.25,
    "axes.axisbelow": True,
    "figure.dpi": 200,
})

# Okabe-Ito. Fixed assignment by entity, never cycled by rank.
C_GREEN, C_VERM, C_ORANGE, C_PINK, C_BLUE, C_SKY, C_GREY = (
    "#009E73", "#D55E00", "#E69F00", "#CC79A7", "#0072B2", "#56B4E9", "#999999")

VERDICT_COLOR = {
    "passed": C_GREEN,
    "syntax_fail": C_VERM,
    "unsupported": C_ORANGE,
    "rejected": C_PINK,
    "pending": C_GREY,
}
VERDICT_ORDER = ["passed", "unsupported", "rejected", "syntax_fail"]
VERDICT_LABEL = {
    "passed": "Passed\n(proven)", "syntax_fail": "Syntax\nfail",
    "unsupported": "Alive2\nunsupported", "rejected": "Rejected", "pending": "Pending",
}

MODEL_COLOR = {
    "qwen2.5-coder:3b": C_BLUE,
    "qwen2.5-coder:7b": C_SKY,
    "qwen2.5-coder:32b": C_VERM,
    "gemini-3.5-flash": C_GREEN,
    "3b + instnamer": C_PINK,
}

BUCKET_ORDER = [
    "SSA_FORWARD_REF", "SSA_NUMBER_TOO_LOW", "SSA_TYPE_MISMATCH",
    "SSA_SELF_REFERENCE", "INVALID_LABEL_REF", "UNDECLARED_REFERENCE",
    "MALFORMED_SYNTAX", "SSA_REUSE", "STRUCTURAL", "TRUNCATED", "OTHER",
]

NON_ATTEMPT = {"pending", "error"}

# label -> results CSV. Missing files are skipped, so this runs before every
# arm has finished.
#
# DELIBERATELY all on the same 40-function target_subset.csv population, not
# the 114-function full corpus. The full-corpus 32b run measured a materially
# different syntax_fail rate on its own population (37.3% for 3b, vs 67.6% on
# the subset) because that corpus is dominated by functionobjects.bc's 47
# small, easy C++ template instantiations -- a corpus-composition effect, not
# a model-capability effect. Point ANY arm here at full-corpus data and this
# chart silently starts conflating "bigger model" with "easier functions".
# The full-corpus CSVs (qwen32b_full_corpus_results.csv,
# qwen3b_full_corpus_results.csv, qwen3b_full_corpus_instnamed_results.csv)
# exist for their own self-contained same-corpus comparison (baseline vs
# instnamed, or model vs model, each pair on identical inputs) via
# categorize_syntax_failures.py directly -- not for this chart.
ARMS = [
    ("qwen2.5-coder:3b",  "syntax_diag_3b_results.csv"),
    ("qwen2.5-coder:7b",  "syntax_diag_7b_results.csv"),
    ("qwen2.5-coder:32b", "qwen32b_subset_results.csv"),
    ("3b + instnamer",    "syntax_diag_3b_instnamed_results.csv"),
    ("gemini-3.5-flash",  "gemini_subset_results.csv"),
]


def load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, newline="") as f:
        return [r for r in csv.DictReader(f) if r.get("verdict")]


def _bar_labels(ax, bars, fmt="{:.0f}", horizontal=False):
    """Direct value labels -- required relief for the low-contrast hues, and
    good practice regardless: the reader never has to measure against the axis."""
    for b in bars:
        v = b.get_width() if horizontal else b.get_height()
        if v <= 0:
            continue
        if horizontal:
            ax.text(v + ax.get_xlim()[1] * 0.015, b.get_y() + b.get_height() / 2,
                    fmt.format(v), va="center", ha="left", fontsize=6.5, color="#333333")
        else:
            ax.text(b.get_x() + b.get_width() / 2, v + ax.get_ylim()[1] * 0.02,
                    fmt.format(v), ha="center", va="bottom", fontsize=6.5, color="#333333")


# ---------------------------------------------------------------------------
def fig1_syntax_taxonomy(data: dict[str, list[dict]], out: Path):
    """Why the models fail: syntax-failure buckets, grouped by model."""
    # Rows written before the diagnostic instrumentation landed carry neither
    # syntax_error nor finish_reason. They are UNCATEGORIZABLE, not "OTHER" --
    # bucketing them would invent a failure mode that was never observed (the
    # qwen32b subset run's 2 syntax failures are exactly this case). Drop them,
    # and drop any arm left with too few to be worth a percentage.
    MIN_N = 5
    per_model: dict[str, Counter] = {}
    for label, rows in data.items():
        fails = [r for r in rows if r["verdict"] == "syntax_fail"]
        usable = [r for r in fails if (r.get("syntax_error") or r.get("finish_reason"))]
        dropped = len(fails) - len(usable)
        if dropped:
            print(f"  fig1: {label}: dropped {dropped} syntax_fail row(s) with no "
                  f"diagnostics (pre-instrumentation)")
        if len(usable) < MIN_N:
            if usable:
                print(f"  fig1: {label}: only {len(usable)} categorizable failure(s) "
                      f"(< {MIN_N}), excluded — too few for a percentage")
            continue
        per_model[label] = Counter(
            categorize(r.get("finish_reason"), r.get("syntax_error")) for r in usable)
    if not per_model:
        print("  fig1: no categorizable syntax_fail rows yet, skipped")
        return

    buckets = [b for b in BUCKET_ORDER if any(c.get(b) for c in per_model.values())]
    models = list(per_model)
    y = np.arange(len(buckets))
    h = 0.8 / max(len(models), 1)

    fig, ax = plt.subplots(figsize=(6.2, 0.52 * len(buckets) + 1.5))
    for i, m in enumerate(models):
        total = sum(per_model[m].values())
        vals = [100.0 * per_model[m].get(b, 0) / total for b in buckets]
        offset = (i - (len(models) - 1) / 2) * h
        bars = ax.barh(y + offset, vals, h * 0.92,  # 8% gap = surface spacer
                       color=MODEL_COLOR.get(m, C_GREY),
                       label=f"{m} (n={total})", edgecolor="white", linewidth=0.5)
        _bar_labels(ax, bars, "{:.0f}%", horizontal=True)

    ax.set_yticks(y)
    ax.set_yticklabels([b.replace("_", " ").title().replace("Ssa", "SSA") for b in buckets],
                       fontsize=7.5)
    ax.invert_yaxis()
    ax.set_xlabel("Share of that model's syntax failures (%)")
    ax.set_xlim(0, max(60, ax.get_xlim()[1] * 1.18))
    ax.grid(axis="y", visible=False)
    # Legend below the axes: inside the plot it collides with the longest bars.
    ax.legend(frameon=False, fontsize=7, ncol=min(len(models), 3),
              loc="upper center", bbox_to_anchor=(0.5, -0.16 - 0.02 * len(buckets) / 3))
    ax.set_title("Why candidates fail to parse: SSA value-numbering dominates",
                 fontsize=9.5, pad=8)
    fig.tight_layout()
    fig.savefig(out / "fig1_syntax_taxonomy.pdf", bbox_inches="tight")
    fig.savefig(out / "fig1_syntax_taxonomy.png", bbox_inches="tight")
    plt.close(fig)
    print(f"  fig1: {len(buckets)} buckets x {len(models)} models")


# ---------------------------------------------------------------------------
def fig2_verdicts_by_model(data: dict[str, list[dict]], out: Path):
    """Verdict mix per model, over COMPLETED attempts only."""
    stats = {}
    for label, rows in data.items():
        completed = [r for r in rows if r["verdict"] not in NON_ATTEMPT]
        if completed:
            stats[label] = (Counter(r["verdict"] for r in completed), len(completed),
                            sum(1 for r in rows if r["verdict"] in NON_ATTEMPT))
    if not stats:
        print("  fig2: no completed rows, skipped")
        return

    models = list(stats)
    x = np.arange(len(models))
    fig, ax = plt.subplots(figsize=(6.2, 3.1))
    bottom = np.zeros(len(models))
    for v in VERDICT_ORDER:
        vals = np.array([100.0 * stats[m][0].get(v, 0) / stats[m][1] for m in models])
        if not vals.any():
            continue
        ax.bar(x, vals, 0.62, bottom=bottom, color=VERDICT_COLOR[v],
               label=VERDICT_LABEL[v].replace("\n", " "),
               edgecolor="white", linewidth=1.2)  # white edge = 2px surface gap
        for xi, (v0, b0) in enumerate(zip(vals, bottom)):
            if v0 >= 7:
                ax.text(xi, b0 + v0 / 2, f"{v0:.0f}%", ha="center", va="center",
                        fontsize=6.8, color="white", fontweight="bold")
        bottom += vals

    ax.set_xticks(x)
    ax.set_xticklabels([f"{m}\n(n={stats[m][1]}, {stats[m][2]} pending)" for m in models],
                       fontsize=7)
    ax.set_ylabel("Share of completed attempts (%)")
    ax.set_ylim(0, 100)
    ax.grid(axis="x", visible=False)
    ax.legend(frameon=False, fontsize=7, ncol=4, loc="upper center",
              bbox_to_anchor=(0.5, -0.22))
    ax.set_title("Verdict mix by model (pending excluded — harness artifact)",
                 fontsize=9.5, pad=8)
    fig.tight_layout()
    fig.savefig(out / "fig2_verdicts_by_model.pdf", bbox_inches="tight")
    fig.savefig(out / "fig2_verdicts_by_model.png", bbox_inches="tight")
    plt.close(fig)
    print(f"  fig2: {len(models)} models")


# ---------------------------------------------------------------------------
def fig3_capability_cliff(data: dict[str, list[dict]], out: Path, csv_dir: Path):
    """Where failure lives in (complexity, tokens) space, with the one real win."""
    pts = defaultdict(lambda: ([], []))
    for rows in data.values():
        for r in rows:
            if r["verdict"] in NON_ATTEMPT:
                continue
            try:
                c, t = float(r["complexity"]), float(r["tokens"])
            except (ValueError, KeyError, TypeError):
                continue
            pts[r["verdict"]][0].append(c)
            pts[r["verdict"]][1].append(t)
    if not pts:
        print("  fig3: no plottable rows, skipped")
        return

    # Two panels: the scatter plot, and a dedicated key sidebar for the win
    # labels. An in-plot text box only stays collision-free with the data by
    # hand-checking which pixels happen to be empty for the CURRENT dataset --
    # true here, not guaranteed the next time a batch of wins lands. A
    # separate axes for the key can never overlap a data point, by construction,
    # regardless of how many wins there are or where they fall.
    fig, (ax, axk) = plt.subplots(
        1, 2, figsize=(7.4, 4.4), gridspec_kw={"width_ratios": [2.7, 1.15], "wspace": 0.06}
    )
    for v in VERDICT_ORDER:
        if v not in pts:
            continue
        xs, ys = pts[v]
        ax.scatter(xs, ys, s=26, alpha=0.75, edgecolors="white", linewidths=0.6,
                   color=VERDICT_COLOR[v], label=f"{VERDICT_LABEL[v].replace(chr(10),' ')} (n={len(xs)})")

    # Every verified non-zero reduction on real code, across ALL arms plotted
    # here plus Gemini (which lives in its own CSV, not one of `data`'s ARMS).
    # Earlier versions of this figure hardcoded only the Gemini win -- wrong
    # once the overnight instnamer runs produced 4 local-model wins (2 of
    # which are inside the "3b + instnamer" arm already plotted above as
    # ordinary green dots, indistinguishable from a 0%-reduction pass).
    win_rows = list(load(csv_dir / "spec_results_gemini.csv"))
    for rows in data.values():
        win_rows.extend(rows)
    seen = set()
    win_pts = []
    for r in win_rows:
        if r.get("verdict") != "passed" or r.get("reduction_pct") in ("", None):
            continue
        try:
            red = float(r["reduction_pct"])
            if red <= 0:
                continue
            c, t = float(r["complexity"]), float(r["tokens"])
        except (ValueError, TypeError):
            continue
        key = (r.get("file_name"), r.get("function_name"), round(red, 2))
        if key in seen:  # same function can appear in >1 arm (e.g. both instnamed runs)
            continue
        seen.add(key)
        win_pts.append((c, t, r.get("function_name", "?"), red))

    # Numbered markers + a single compact key, instead of text labels on long
    # diagonal leader lines. The leader-line version crossed the whole plot
    # once there were more than ~5 wins (it was built for one), producing an
    # unreadable tangle: labels overlapped each other and the data cloud, and
    # lines cut through the legend. A short local offset for the number plus
    # one legend box in empty plot space scales to any win count without
    # collisions, because it never has to route a line across the figure.
    win_pts.sort(key=lambda w: -w[3])

    for i, (c, t, name, red) in enumerate(win_pts):
        # Plot the point itself, not just the ring -- a win's own arm may not
        # otherwise distinguish it from a 0%-reduction pass at this marker size.
        ax.scatter([c], [t], s=52, color=C_GREEN, edgecolors="white",
                   linewidths=0.8, zorder=6, marker="D",
                   label="Verified reduction" if i == 0 else None)
        ax.scatter([c], [t], s=210, facecolors="none", edgecolors=C_GREEN,
                   linewidths=1.8, zorder=5)
        ax.annotate(str(i + 1), xy=(c, t), xytext=(6, 6),
                    textcoords="offset points", fontsize=6.5, fontweight="bold",
                    color="white", zorder=7,
                    bbox=dict(boxstyle="circle,pad=0.15", fc=C_GREEN, ec="none"))

    axk.axis("off")
    axk.set_title("Verified\nreductions", fontsize=8, loc="left", pad=2)
    if win_pts:
        key_text = "\n\n".join(
            (f"{i + 1}  −{red:.0f}%" if red >= 1 else f"{i + 1}  −{red:.1f}%") + f"\n   {name}"
            for i, (_, _, name, red) in enumerate(win_pts)
        )
        axk.text(0.0, 0.94, key_text, transform=axk.transAxes, fontsize=6.5,
                 va="top", ha="left", linespacing=1.35)

    ax.axvline(5, color=C_GREY, ls="--", lw=0.9)
    ax.text(5.25, ax.get_ylim()[1] * 0.97, "triage threshold", fontsize=6.5,
            color="#666666", va="top")
    ax.set_xlabel("Cyclomatic complexity")
    ax.set_ylabel("Token count")
    ax.set_yscale("log")
    ax.legend(frameon=False, fontsize=6.8, loc="lower right")
    fig.suptitle(f"The capability cliff: verified optimisation is rare ({len(win_pts)} of "
                 f"{sum(len(v[0]) for v in pts.values())} completed attempts shown)",
                 fontsize=9.5, y=0.99)
    fig.savefig(out / "fig3_capability_cliff.pdf", bbox_inches="tight")
    fig.savefig(out / "fig3_capability_cliff.png", bbox_inches="tight")
    plt.close(fig)
    print(f"  fig3: {sum(len(v[0]) for v in pts.values())} points")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv-dir", type=Path, default=Path("."))
    ap.add_argument("--out-dir", type=Path, default=Path("figures"))
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    data = {}
    for label, fname in ARMS:
        rows = load(args.csv_dir / fname)
        if rows:
            data[label] = rows
            print(f"loaded {fname}: {len(rows)} rows -> {label}")
        else:
            print(f"skipped {fname} (absent or empty)")

    if not data:
        print("No data. Nothing to plot.")
        return

    print("\nrendering:")
    fig1_syntax_taxonomy(data, args.out_dir)
    fig2_verdicts_by_model(data, args.out_dir)
    fig3_capability_cliff(data, args.out_dir, args.csv_dir)
    print(f"\nwritten to {args.out_dir}/ (pdf + png)")


if __name__ == "__main__":
    main()
