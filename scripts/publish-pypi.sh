#!/bin/bash
# Publish package to PyPI

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}[5/5] Publishing to PyPI...${NC}"

# Use PYTHON from environment or prefer the venv if present
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
if [ -x "$ROOT_DIR/.venv/bin/python" ]; then
    PYTHON="$ROOT_DIR/.venv/bin/python"
else
    PYTHON=${PYTHON:-python3}
fi

# Get version from pyproject.toml
VERSION=$(grep '^version = ' pyproject.toml | sed 's/version = "\(.*\)"/\1/' | tr -d '\r')

if [ -z "$VERSION" ]; then
    echo -e "${RED}Error: Could not read version from pyproject.toml${NC}"
    exit 1
fi

echo "Publishing version $VERSION..."

# Upload to PyPI
$PYTHON -m twine upload dist/*

echo -e "${GREEN}✓ Package published to PyPI${NC}\n"
echo -e "${GREEN}🎉 Deployment Complete!${NC}"
echo "Version: $VERSION"
echo "Installation: pip install formix-pubsub==$VERSION"
