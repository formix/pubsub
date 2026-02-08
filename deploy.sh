#!/bin/bash
# Deployment orchestration script for formix-pubsub
# Coordinates all deployment steps and handles git tagging

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}╔════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║   formix-pubsub Deployment Pipeline    ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════╝${NC}\n"

# Get version from pyproject.toml
VERSION=$(grep '^version = ' pyproject.toml | sed 's/version = "\(.*\)"/\1/')

if [ -z "$VERSION" ]; then
    echo -e "${RED}Error: Could not read version from pyproject.toml${NC}"
    exit 1
fi

echo -e "${BLUE}Version: ${GREEN}$VERSION${NC}\n"

# Check for uncommitted changes
if ! git diff-index --quiet HEAD --; then
    echo -e "${RED}Error: You have uncommitted changes in your working directory.${NC}"
    echo "Please commit or stash your changes before deploying."
    echo ""
    echo "Uncommitted changes:"
    git status --short
    exit 1
fi

if [ -n "$(git ls-files --others --exclude-standard)" ]; then
    echo -e "${YELLOW}Warning: You have untracked files in your working directory.${NC}"
    echo "Untracked files:"
    git ls-files --others --exclude-standard
    echo ""
    read -p "Continue with deployment anyway? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo -e "${RED}Deployment cancelled.${NC}"
        exit 1
    fi
fi

# Check if this version already has a git tag
LATEST_TAG=$(git tag --sort=-version:refname | head -1)

if [ -n "$LATEST_TAG" ]; then
    # Remove 'v' prefix if present for comparison
    LATEST_TAG_CLEAN=${LATEST_TAG#v}

    if [ "$VERSION" == "$LATEST_TAG_CLEAN" ]; then
        echo -e "${RED}Error: Version $VERSION already exists as git tag.${NC}"
        echo "Please update the version in pyproject.toml before deploying."
        exit 1
    fi
    echo -e "Previous version: $LATEST_TAG"
else
    echo -e "No previous git tags found."
fi

echo -e "\n${BLUE}Starting deployment pipeline...${NC}\n"

# Make scripts executable
chmod +x scripts/*.sh

# Step 1: Check dependencies
./scripts/check-dependencies.sh || {
    echo -e "${RED}✗ Dependency check failed${NC}"
    exit 1
}

# Step 2: Run tests
./scripts/run-tests.sh || {
    echo -e "${RED}✗ Tests failed${NC}"
    exit 1
}

# Step 3: Build documentation
./scripts/build-docs.sh || {
    echo -e "${RED}✗ Documentation build failed${NC}"
    exit 1
}

# Step 4: Build package
./scripts/build-package.sh || {
    echo -e "${RED}✗ Package build failed${NC}"
    exit 1
}

# All checks passed - create and push git tag
echo -e "${YELLOW}Creating git tag $VERSION...${NC}"
git tag -a "$VERSION" -m "Release $VERSION"
echo -e "${GREEN}✓ Git tag $VERSION created${NC}\n"

echo -e "${YELLOW}Pushing tag to remote...${NC}"
git push --tags
echo -e "${GREEN}✓ Tag pushed to remote${NC}\n"

# Step 5: Publish to PyPI
./scripts/publish-pypi.sh || {
    echo -e "${RED}✗ PyPI publication failed${NC}"
    echo -e "${YELLOW}Note: Git tag has been created and pushed${NC}"
    exit 1
}

echo ""
echo -e "${GREEN}╔════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║    Deployment Completed Successfully   ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════╝${NC}"
echo ""
echo -e "${YELLOW}Note: ReadTheDocs will automatically build documentation from the new tag.${NC}"
echo "Check: https://readthedocs.org/projects/formix-pubsub/"

echo "Tag: $VERSION"
echo "Installation: pip install formix-pubsub==$VERSION"
echo ""
echo -e "${YELLOW}Note: ReadTheDocs will automatically build documentation from the new tag.${NC}"
echo "Check: https://readthedocs.org/projects/formix-pubsub/"
