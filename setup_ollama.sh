#!/usr/bin/env bash
set -e

# Setup script for Ollama local models used by Phase 3 (LLM routing).
# Checks Ollama installation, pulls the required models, and verifies connectivity.
#
# Models are chosen for an M4 Mac with 16GB RAM:
#   - qwen2.5-coder:3b  (fast tier — lightweight, quick inference)
#   - qwen2.5-coder:7b  (mid/frontier tier — best quality within 16GB budget)

echo "========================================"
echo " Ollama Setup for LLM Compile Pipeline "
echo "========================================"

# Step 1: Check if Ollama is installed
echo ""
echo "[1/3] Checking Ollama installation..."
if ! command -v ollama &>/dev/null; then
    echo "❌ Ollama is not installed."
    echo ""
    echo "Install it from: https://ollama.com/download"
    echo "  macOS: Download the .dmg from the website"
    echo "  Linux: curl -fsSL https://ollama.com/install.sh | sh"
    echo ""
    exit 1
fi
echo "✅ Ollama is installed: $(ollama --version 2>/dev/null || echo 'version unknown')"

# Step 2: Pull required models
echo ""
echo "[2/3] Pulling required models (this may take a few minutes on first run)..."
echo ""

echo "→ Pulling qwen2.5-coder:3b (fast tier, ~2GB)..."
ollama pull qwen2.5-coder:3b

echo ""
echo "→ Pulling qwen2.5-coder:7b (mid/frontier tier, ~4.5GB)..."
ollama pull qwen2.5-coder:7b

# Step 3: Verify Ollama server connectivity
echo ""
echo "[3/3] Verifying Ollama server connectivity..."

OLLAMA_URL="${OLLAMA_BASE_URL:-http://localhost:11434}"

if curl -s "${OLLAMA_URL}/api/tags" > /dev/null 2>&1; then
    echo "✅ Ollama server is running at ${OLLAMA_URL}"
    echo ""
    echo "Available models:"
    curl -s "${OLLAMA_URL}/api/tags" | python3 -c "
import sys, json
data = json.load(sys.stdin)
for m in data.get('models', []):
    size_gb = m.get('size', 0) / (1024**3)
    print(f\"  • {m['name']:30s} ({size_gb:.1f} GB)\")
" 2>/dev/null || echo "  (could not parse model list)"
else
    echo "⚠️  Ollama server is not running at ${OLLAMA_URL}"
    echo ""
    echo "The models have been pulled. To start the server:"
    echo "  ollama serve"
    echo ""
    echo "Or on macOS, just open the Ollama app — it starts the server automatically."
fi

echo ""
echo "========================================"
echo " Setup Complete!                        "
echo "========================================"
echo ""
echo "Next steps:"
echo "  1. Make sure Ollama is running (open the app or run 'ollama serve')"
echo "  2. Start the API:  uvicorn api:app --reload"
echo "  3. Start the UI:   cd ui && npm run dev"
echo "  4. Navigate to Phase 3 and try routing some IR!"
echo ""
