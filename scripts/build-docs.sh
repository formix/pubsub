#!/bin/bash
# Build documentation

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}[3/5] Building documentation...${NC}"

# Use PYTHON from environment or default
PYTHON=${PYTHON:-python3}

# Locate sphinx-build: prefer the venv, fall back to PATH
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
if [ -x "$ROOT_DIR/.venv/bin/sphinx-build" ]; then
    SPHINXBUILD="$ROOT_DIR/.venv/bin/sphinx-build"
elif $PYTHON -m sphinx --version &>/dev/null; then
    SPHINXBUILD="$PYTHON -m sphinx"
elif command -v sphinx-build &>/dev/null; then
    SPHINXBUILD="sphinx-build"
else
    echo -e "${RED}Error: sphinx-build not found. Install docs dependencies:${NC}"
    echo "  pip install formix-pubsub[docs]"
    exit 1
fi

# Change to docs directory
cd "$ROOT_DIR/docs"

# Clean previous builds
echo "Cleaning previous builds..."
make clean SPHINXBUILD="$SPHINXBUILD"

# Build HTML documentation
echo "Building HTML documentation..."
make html SPHINXBUILD="$SPHINXBUILD"

# Return to root directory
cd "$ROOT_DIR"

echo -e "${GREEN}✓ Documentation built successfully${NC}\n"
