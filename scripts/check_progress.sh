#!/bin/bash

CSV_FILE="sbase_results.csv"
TOTAL=311

if [ ! -f "$CSV_FILE" ]; then
    echo "Progress: 0.0% (0/$TOTAL) - $CSV_FILE not found yet."
    exit 0
fi

# Count lines, subtract 1 for header
LINES=$(wc -l < "$CSV_FILE" | tr -d ' ')
if [ "$LINES" -eq 0 ]; then
    DONE=0
else
    DONE=$((LINES - 1))
fi

if [ "$DONE" -lt 0 ]; then
    DONE=0
fi

# Calculate percentage using awk for float precision
PERCENT=$(awk -v d="$DONE" -v t="$TOTAL" 'BEGIN { printf "%.1f", (d/t)*100 }')

# Draw progress bar
BAR_WIDTH=20
# Integer division for bar fill
FILL_COUNT=$(awk -v d="$DONE" -v t="$TOTAL" -v w="$BAR_WIDTH" 'BEGIN { printf "%d", (d/t)*w }')
EMPTY_COUNT=$((BAR_WIDTH - FILL_COUNT))

BAR="["
for ((i=0; i<FILL_COUNT; i++)); do BAR="${BAR}#"; done
for ((i=0; i<EMPTY_COUNT; i++)); do BAR="${BAR}."; done
BAR="${BAR}]"

echo "Progress: $BAR $PERCENT% ($DONE/$TOTAL functions completed)"
