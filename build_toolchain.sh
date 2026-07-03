#!/usr/bin/env bash
set -e

# Build script for Milestone 0 (M0): Toolchain Spike
# Compiles LLVM (with RTTI/EH) and Alive2 from source.
# WARNING: This requires a well-resourced machine (RAM > 16GB) and may take 1-2 hours.

echo "========================================"
echo " Starting M0 Toolchain Build Process "
echo "========================================"

# Step 1: Install prerequisites
echo "[1/4] Installing build dependencies..."
if command -v apt-get >/dev/null; then
    echo "Attempting to install dependencies via apt-get..."
    sudo -n apt-get update || echo "Warning: sudo failed, skipping apt-get update. Assuming dependencies are already installed via conda/system."
    sudo -n DEBIAN_FRONTEND=noninteractive apt-get install -y cmake ninja-build git python3 libz3-dev build-essential re2c || echo "Warning: sudo install failed. Please ensure cmake, ninja, re2c, and z3 are installed (e.g. via conda)."
elif command -v brew >/dev/null; then
    brew install cmake ninja git python z3 re2c
else
    echo "Unsupported OS or missing package manager. Please install cmake, ninja, z3-dev, re2c manually."
fi

# Fallback: if re2c is still missing and conda is available, install it via conda
if ! command -v re2c >/dev/null && command -v conda >/dev/null; then
    echo "re2c not found but conda is available. Installing re2c via conda-forge..."
    conda install -y -c conda-forge re2c
fi

# Define workspace directory for tools
# We use $HOME/llvm_toolchain to avoid space-in-path compilation issues with LLVM/CMake
TOOLCHAIN_DIR="$HOME/llvm_toolchain"
mkdir -p "$TOOLCHAIN_DIR"
cd "$TOOLCHAIN_DIR"

# Step 2: Clone and build LLVM from source
echo "[2/4] Cloning and configuring LLVM..."
if [ ! -d "llvm-project" ]; then
    git clone --depth 1 -b llvmorg-18.1.8 https://github.com/llvm/llvm-project.git
fi

cd llvm-project/llvm
mkdir -p build && cd build

echo "Configuring LLVM with RTTI=ON and EH=ON (Required for Alive2)..."
cmake -GNinja \
  -DLLVM_ENABLE_WERROR=OFF \
  -DLLVM_ENABLE_RTTI=ON \
  -DLLVM_ENABLE_EH=ON \
  -DBUILD_SHARED_LIBS=ON \
  -DCMAKE_BUILD_TYPE=Release \
  -DLLVM_TARGETS_TO_BUILD=X86 \
  -DLLVM_ENABLE_ASSERTIONS=ON \
  -DLLVM_ENABLE_PROJECTS="llvm;clang" \
  ..

echo "Compiling LLVM (This will take a while!)..."
ninja
LLVM_BUILD_DIR="$(pwd)"
cd ../../../

# Step 3: Clone and build Alive2
echo "[3/4] Cloning and configuring Alive2..."
if [ ! -d "alive2" ]; then
    git clone https://github.com/AliveToolkit/alive2.git
fi

cd alive2
mkdir -p build && cd build

echo "Configuring Alive2..."
cmake -GNinja -DCMAKE_BUILD_TYPE=Release \
  -DLLVM_DIR="$LLVM_BUILD_DIR/lib/cmake/llvm" ..

echo "Compiling Alive2..."
ninja

# Step 4: Finish and export
ALIVE_TV_PATH="$(pwd)/alive-tv"
LLVM_AS_PATH="$LLVM_BUILD_DIR/bin/llvm-as"

echo "========================================"
echo " Build Complete! "
echo "========================================"
echo "Alive-tv binary: $ALIVE_TV_PATH"
echo "llvm-as binary:  $LLVM_AS_PATH"
echo ""
echo "Next Steps: Update llmcompile/config.py to point VerificationConfig to these paths!"
