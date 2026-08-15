import time
import sys
import os

TOTAL = 147
CSV_FILE = "new_spec_results.csv"

def get_count():
    if not os.path.exists(CSV_FILE): return 0
    with open(CSV_FILE, "r") as f:
        # Subtract 1 to ignore the CSV header
        return max(0, sum(1 for _ in f) - 1)

print(f"Tracking evaluation progress... (Total files: {TOTAL})")
last_count = -1
start_time = time.time()

while True:
    count = get_count()
    if count != last_count:
        elapsed = time.time() - start_time
        # Only start calculating rate after the first file finishes to avoid skewed ETA
        if count > 0:
            rate = count / elapsed
            eta = (TOTAL - count) / rate
        else:
            eta = 0
            
        bar_len = 50
        filled = int(bar_len * count / TOTAL)
        bar = '█' * filled + '-' * (bar_len - filled)
        
        eta_str = f"{int(eta//60)}m {int(eta%60)}s" if eta > 0 else "Calculating..."
        
        sys.stdout.write(f"\r[{bar}] {count}/{TOTAL} ({count/TOTAL*100:.1f}%) | ETA: {eta_str}   ")
        sys.stdout.flush()
        last_count = count
        
    if count >= TOTAL:
        print("\nEvaluation complete!")
        break
        
    time.sleep(2)
