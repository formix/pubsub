# Deployment Scripts

This directory contains modular deployment scripts for formix-pubsub. Each script handles a specific step of the deployment pipeline.

## Scripts Overview

### 1. check-dependencies.sh
**Purpose:** Verify all required dependencies are installed
**Checks:**
- Python environment (venv or system)
- Required packages: build, twine, setuptools, wheel, sphinx
- pytest (optional, falls back to unittest)

**Exit codes:**
- 0: All dependencies available
- 1: Missing required dependencies

### 2. run-tests.sh
**Purpose:** Execute the test suite
**Actions:**
- Runs pytest if available, otherwise uses unittest
- Executes all tests in the `tests/` directory
- Displays verbose output

**Exit codes:**
- 0: All tests passed
- 1: One or more tests failed

### 3. build-docs.sh
**Purpose:** Build Sphinx documentation
**Actions:**
- Changes to `docs/` directory
- Cleans previous builds (`make clean`)
- Builds HTML documentation (`make html`)
- Returns to root directory

**Exit codes:**
- 0: Documentation built successfully
- 1: Documentation build failed

### 4. build-package.sh
**Purpose:** Build Python distribution packages
**Actions:**
- Cleans old build artifacts
- Builds source distribution and wheel
- Validates package integrity with twine

**Exit codes:**
- 0: Package built successfully
- 1: Package build or validation failed

### 5. publish-pypi.sh
**Purpose:** Upload package to PyPI
**Actions:**
- Reads version from pyproject.toml
- Uploads distribution packages to PyPI
- Displays success message with installation command

**Exit codes:**
- 0: Package published successfully
- 1: Upload failed

## Usage

### Run Individual Scripts
Each script can be run independently:
```bash
./scripts/check-dependencies.sh
./scripts/run-tests.sh
./scripts/build-docs.sh
./scripts/build-package.sh
./scripts/publish-pypi.sh
```

### Full Deployment Pipeline
Use the main deployment script:
```bash
./deploy.sh
```

The main script:
1. Checks version and git tags
2. Runs all scripts in sequence
3. Creates and pushes git tag after all checks pass
4. Stops on any failure

## Environment Variables

- `PYTHON`: Python executable path (set by check-dependencies.sh)
  - Auto-detected: `.venv/bin/python` or `python3`
  - Can be overridden manually

## Error Handling

All scripts use `set -e` to exit immediately on error. The main deployment script catches failures and provides clear error messages.

## Design Philosophy

Each script is:
- **Self-contained:** Can run independently
- **Single-purpose:** Does one thing well
- **Fail-fast:** Exits immediately on error
- **Informative:** Uses color-coded output
- **Numbered:** Shows progress (e.g., [1/5], [2/5])
