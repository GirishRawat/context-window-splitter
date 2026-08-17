#!/usr/bin/env bash
#
# auto_commit_results.sh — checkpoint eval results to git every 30 min.
#
# The overnight runs append a row per function and take hours; this keeps
# partial progress safe without needing anyone awake. Deliberately scoped to
# result CSVs rather than `git add .` (as scripts/auto_push.sh does) so an
# unattended loop can never sweep up a stray file, a large artifact, or a
# credential that happens to appear in the tree.
#
# Usage:  nohup ./scripts/auto_commit_results.sh &
set -uo pipefail
cd "$(dirname "$0")/.."

INTERVAL="${1:-2700}"

while true; do
  # Only ever stage known result files.
  git add -- '*_results.csv' 2>/dev/null

  if ! git diff --cached --quiet 2>/dev/null; then
    summary=$(python3 - <<'PY' 2>/dev/null || echo ""
import csv, glob
from collections import Counter
bits = []
for f in sorted(glob.glob("*_results.csv")):
    try:
        rows = [r for r in csv.DictReader(open(f)) if r.get("verdict")]
    except Exception:
        continue
    if not rows:
        continue
    c = Counter(r["verdict"] for r in rows)
    done = sum(v for k, v in c.items() if k not in ("pending", "error"))
    bits.append(f"{f}={len(rows)}r/{done}done")
print("; ".join(bits))
PY
)
    git commit -q -m "Checkpoint eval results: $(date '+%Y-%m-%d %H:%M')

${summary}

Periodic checkpoint from scripts/auto_commit_results.sh while long
unattended eval runs are in flight. Scoped to *_results.csv only."
    git push -q origin main && echo "[$(date '+%Y-%m-%d %H:%M')] pushed: ${summary}"
  else
    echo "[$(date '+%Y-%m-%d %H:%M')] no result changes"
  fi

  sleep "${INTERVAL}"
done
