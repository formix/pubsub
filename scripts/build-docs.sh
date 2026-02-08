#!/bin/bash
# Build documentation

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}[3/5] Building documentation...${NC}"

# Change to docs directory
cd docs

# Clean previous builds
echo "Cleaning previous builds..."
make clean

# Build HTML documentation
echo "Building HTML documentation..."
make html

# Return to root directory
cd ..

echo -e "${GREEN}✓ Documentation built successfully${NC}\n"
