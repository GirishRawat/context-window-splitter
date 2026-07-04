#!/usr/bin/env bash
set -e

# Build script for Milestone 0 (M0): Toolchain Spike
# Compiles LLVM (with RTTI/EH) and Alive2 from source on macOS (Apple Silicon).
# Expected runtime: 30–60 min on M4.  Disk: ~15 GB in $HOME/llvm_toolchain.

echo "========================================"
echo " Starting M0 Toolchain Build Process   "
echo "========================================"

# ------------------------------------------------------------------
# Step 1: Install prerequisites via Homebrew
# ------------------------------------------------------------------
echo "[1/4] Installing build dependencies via Homebrew..."
brew install cmake ninja git z3 re2c || true   # 'true' so we don't abort if already installed

# Verify the key tools are present
for cmd in cmake ninja git z3; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "ERROR: '$cmd' not found after brew install. Please install it manually."
    exit 1
  fi
done
echo "  cmake  : $(cmake --version | head -1)"
echo "  ninja  : $(ninja --version)"
echo "  z3     : $(z3 --version)"

# ------------------------------------------------------------------
# Locate Z3 (Homebrew installs it at a well-known prefix)
# ------------------------------------------------------------------
Z3_PREFIX="$(brew --prefix z3)"
Z3_INCLUDE="$Z3_PREFIX/include"
Z3_LIB="$Z3_PREFIX/lib/libz3.dylib"

if [ ! -f "$Z3_LIB" ]; then
  echo "ERROR: z3 library not found at $Z3_LIB.  Run: brew install z3"
  exit 1
fi
echo "  z3 prefix: $Z3_PREFIX"

# ------------------------------------------------------------------
# Workspace directory (no spaces — CMake hates them)
# ------------------------------------------------------------------
TOOLCHAIN_DIR="$HOME/llvm_toolchain"
mkdir -p "$TOOLCHAIN_DIR"
cd "$TOOLCHAIN_DIR"

# ------------------------------------------------------------------
# Step 2: Clone LLVM (shallow, pinned to 18.1.8)
# ------------------------------------------------------------------
echo "[2/4] Cloning LLVM 18.1.8 (shallow, ~1.2 GB)..."
if [ ! -d "llvm-project" ]; then
  git clone --depth 1 -b llvmorg-18.1.8 \
    https://github.com/llvm/llvm-project.git
else
  echo "  llvm-project already cloned, skipping."
fi

# Record the commit hash for the lockfile
LLVM_COMMIT=$(git -C llvm-project rev-parse HEAD)
echo "  LLVM commit: $LLVM_COMMIT"

# ------------------------------------------------------------------
# Configure + build LLVM
# ------------------------------------------------------------------
echo "[2/4] Configuring LLVM (AArch64, RTTI=ON, EH=ON, Release)..."
mkdir -p llvm-project/llvm/build
cd llvm-project/llvm/build

cmake -GNinja \
  -DCMAKE_BUILD_TYPE=Release \
  -DLLVM_TARGETS_TO_BUILD="AArch64;X86" \
  -DLLVM_ENABLE_PROJECTS="clang" \
  -DLLVM_ENABLE_RTTI=ON \
  -DLLVM_ENABLE_EH=ON \
  -DBUILD_SHARED_LIBS=ON \
  -DLLVM_ENABLE_ASSERTIONS=ON \
  -DLLVM_ENABLE_WERROR=OFF \
  -DLLVM_INCLUDE_TESTS=OFF \
  -DLLVM_INCLUDE_BENCHMARKS=OFF \
  ..

echo "Compiling LLVM with ninja (this takes 30–50 min on first run)..."
ninja llvm-as llc opt clang   # build only the tools we need, not the whole LLVM
LLVM_BUILD_DIR="$(pwd)"
cd "$TOOLCHAIN_DIR"

# ------------------------------------------------------------------
# Step 3: Clone + build Alive2
# ------------------------------------------------------------------
echo "[3/4] Cloning Alive2..."
if [ ! -d "alive2" ]; then
  git clone https://github.com/AliveToolkit/alive2.git
else
  echo "  alive2 already cloned, skipping."
fi

ALIVE2_COMMIT=$(git -C alive2 rev-parse HEAD)
echo "  Alive2 commit: $ALIVE2_COMMIT"

echo "[3/4] Configuring Alive2..."
mkdir -p alive2/build
cd alive2/build

cmake -GNinja \
  -DCMAKE_BUILD_TYPE=Release \
  -DLLVM_DIR="$LLVM_BUILD_DIR/lib/cmake/llvm" \
  -DZ3_INCLUDE_DIR="$Z3_INCLUDE" \
  -DZ3_LIBRARIES="$Z3_LIB" \
  -DBUILD_TV=ON \
  ..

echo "Compiling Alive2..."
ninja alive-tv
cd "$TOOLCHAIN_DIR"

# ------------------------------------------------------------------
# Step 4: Verify binaries exist
# ------------------------------------------------------------------
ALIVE_TV_PATH="$TOOLCHAIN_DIR/alive2/build/alive-tv"
LLVM_AS_PATH="$TOOLCHAIN_DIR/llvm-project/llvm/build/bin/llvm-as"

if [ ! -f "$ALIVE_TV_PATH" ]; then
  echo "ERROR: alive-tv binary not found at $ALIVE_TV_PATH"
  exit 1
fi
if [ ! -f "$LLVM_AS_PATH" ]; then
  echo "ERROR: llvm-as binary not found at $LLVM_AS_PATH"
  exit 1
fi

# ------------------------------------------------------------------
# Step 5: Write version lockfile
# ------------------------------------------------------------------
LOCKFILE="$TOOLCHAIN_DIR/toolchain_versions.lock"
cat > "$LOCKFILE" <<EOF
# M0 Toolchain Version Lock — generated $(date -u +%Y-%m-%dT%H:%M:%SZ)
llvm_tag=llvmorg-18.1.8
llvm_commit=$LLVM_COMMIT
alive2_commit=$ALIVE2_COMMIT
z3_version=$(z3 --version)
llvmlite=$(python3 -c "import llvmlite; print(llvmlite.__version__)" 2>/dev/null || echo "not-installed")
alive_tv_path=$ALIVE_TV_PATH
llvm_as_path=$LLVM_AS_PATH
EOF
echo "Version lockfile written: $LOCKFILE"
cat "$LOCKFILE"

# ------------------------------------------------------------------
# Done
# ------------------------------------------------------------------
echo ""
echo "========================================"
echo " Build Complete!                        "
echo "========================================"
echo ""
echo "alive-tv : $ALIVE_TV_PATH"
echo "llvm-as  : $LLVM_AS_PATH"
echo ""
echo "Next steps:"
echo "  1. Run the M0 spike test:"
echo "       python -m pytest llmcompile/tests/test_m0_spike.py -v"
echo "  2. Update config.py VerificationConfig with the paths above."
