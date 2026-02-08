#!/bin/bash
# Deployment script for formix-pubsub
# Reads version from pyproject.toml, creates git tag, builds and uploads to PyPI

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== formix-pubsub Deployment ===${NC}"

# Determine which Python to use
if [ -f .venv/bin/python ]; then
    PYTHON=".venv/bin/python"
    echo "Using virtual environment Python"
else
    PYTHON="python3"
    echo "Using system Python"
fi

# Check for required packages
echo -e "${YELLOW}Checking required packages...${NC}"
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

if [ ${#MISSING_PACKAGES[@]} -gt 0 ]; then
    echo -e "${RED}Error: Missing required packages: ${MISSING_PACKAGES[*]}${NC}"
    echo -e "${YELLOW}Please install them with:${NC}"
    echo "  $PYTHON -m pip install --upgrade ${MISSING_PACKAGES[*]}"
    exit 1
fi

echo -e "${GREEN}All required packages are available.${NC}\n"

# Get version from pyproject.toml
VERSION=$(grep '^version = ' pyproject.toml | sed 's/version = "\(.*\)"/\1/')

if [ -z "$VERSION" ]; then
    echo -e "${RED}Error: Could not read version from pyproject.toml${NC}"
    exit 1
fi

echo "Version in pyproject.toml: $VERSION"

# Get the latest git tag
LATEST_TAG=$(git tag --sort=-version:refname | head -1)

if [ -z "$LATEST_TAG" ]; then
    echo "No existing git tags found."
else
    echo "Latest git tag: $LATEST_TAG"
    
    # Remove 'v' prefix if present for comparison
    LATEST_TAG_CLEAN=${LATEST_TAG#v}
    
    if [ "$VERSION" == "$LATEST_TAG_CLEAN" ]; then
        echo -e "${RED}Error: Version $VERSION already exists as git tag.${NC}"
        echo "Please update the version in pyproject.toml before deploying."
        exit 1
    fi
fi

echo -e "${GREEN}Version $VERSION is new. Proceeding with deployment...${NC}"

# Clean old builds
echo -e "${YELLOW}Cleaning old builds...${NC}"
rm -rf dist/ build/ *.egg-info formix_pubsub.egg-info

# Build the package
echo -e "${YELLOW}Building package...${NC}"
$PYTHON -m build

# Check the built package
echo -e "${YELLOW}Checking package...${NC}"
$PYTHON -m twine check dist/*

# Create git tag
echo -e "${YELLOW}Creating git tag $VERSION...${NC}"
git tag -a "$VERSION" -m "Release $VERSION"

echo -e "${GREEN}Git tag $VERSION created successfully.${NC}"
echo -e "${YELLOW}Pushing tag to remote...${NC}"
git push --tags

# Upload to PyPI
echo -e "${YELLOW}Uploading to PyPI...${NC}"
$PYTHON -m twine upload dist/*

echo -e "${GREEN}=== Deployment Complete ===${NC}"
echo "Version: $VERSION"
echo "Tag: $VERSION"
echo "Installation: pip install formix-pubsub==$VERSION"
