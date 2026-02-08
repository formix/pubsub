#!/bin/bash
# Check for required dependencies before deployment

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}[1/5] Checking dependencies...${NC}"

# Determine which Python to use
if [ -f .venv/bin/python ]; then
    PYTHON=".venv/bin/python"
    echo "Using virtual environment Python"
else
    PYTHON="python3"
    echo "Using system Python"
fi

# Export PYTHON for other scripts to use
export PYTHON

# Check for required packages
MISSING_PACKAGES=()

if ! $PYTHON -c "import build" 2>/dev/null; then
    MISSING_PACKAGES+=("build")
fi

if ! $PYTHON -c "import twine" 2>/dev/null; then
    MISSING_PACKAGES+=("twine")
fi

if ! $PYTHON -c "import setuptools" 2>/dev/null; then
    MISSING_PACKAGES+=("setuptools")
fi

if ! $PYTHON -c "import wheel" 2>/dev/null; then
    MISSING_PACKAGES+=("wheel")
fi

if ! $PYTHON -c "import sphinx" 2>/dev/null; then
    MISSING_PACKAGES+=("sphinx")
fi

# Check for test runners (not required, but recommended)
if ! $PYTHON -c "import green" 2>/dev/null; then
    if ! $PYTHON -c "import pytest" 2>/dev/null; then
        echo -e "${YELLOW}Warning: Neither 'green' nor 'pytest' found, will use unittest${NC}"
        echo -e "${YELLOW}For better test output, consider installing: pip install green${NC}"
    fi
fi

if [ ${#MISSING_PACKAGES[@]} -gt 0 ]; then
    echo -e "${RED}Error: Missing required packages: ${MISSING_PACKAGES[*]}${NC}"
    echo -e "${YELLOW}Please install them with:${NC}"
    echo "  $PYTHON -m pip install --upgrade ${MISSING_PACKAGES[*]}"
    exit 1
fi

echo -e "${GREEN}✓ All required dependencies are available${NC}\n"
