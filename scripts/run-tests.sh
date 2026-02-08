#!/bin/bash
# Run all tests before deployment

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}[2/5] Running tests...${NC}"

# Use PYTHON from environment or default
PYTHON=${PYTHON:-python3}

# Run tests with best available test runner
if $PYTHON -c "import green" 2>/dev/null; then
    echo "Running tests with green..."
    $PYTHON -m green tests -vv
elif $PYTHON -c "import pytest" 2>/dev/null; then
    echo "Running tests with pytest..."
    $PYTHON -m pytest tests/ -v
else
    echo "Running tests with unittest..."
    $PYTHON -m unittest discover -s tests -v
fi

echo -e "${GREEN}✓ All tests passed${NC}\n"
