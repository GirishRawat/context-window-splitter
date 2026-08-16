#!/bin/bash

# Run indefinitely
while true; do
    # Check if there are any changes (modified, untracked, or deleted)
    if [[ -n $(git status -s) ]]; then
        echo "Changes detected at $(date). Committing and pushing..."
        git add .
        git commit -m "Auto-commit: $(date)"
        git push origin main
    else
        echo "No changes detected at $(date). Skipping push."
    fi
    
    # Sleep for 30 minutes (1800 seconds)
    sleep 1800
done
