#!/bin/bash
# Build Python package

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}[4/5] Building package...${NC}"

# Use PYTHON from environment or default
PYTHON=${PYTHON:-python3}

# Clean old builds
echo "Cleaning old builds..."
rm -rf dist/ build/ *.egg-info formix_pubsub.egg-info

# Build the package
echo "Building distribution packages..."
$PYTHON -m build

# Check the built package
echo "Checking package integrity..."
$PYTHON -m twine check dist/*

echo -e "${GREEN}✓ Package built successfully${NC}\n"
