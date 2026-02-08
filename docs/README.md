# Documentation

This directory contains the Sphinx documentation for formix-pubsub.

## Building Documentation Locally

### Install dependencies

```bash
pip install -r docs/requirements.txt
# or with dev dependencies
pip install -e .[docs]
```

### Build HTML documentation

```bash
cd docs
make html
```

The built documentation will be in `docs/build/html/index.html`.

### View the documentation

```bash
# On Linux
xdg-open build/html/index.html

# On macOS
open build/html/index.html

# On Windows
start build/html/index.html
```

### Clean build files

```bash
cd docs
make clean
```

## Online Documentation

The documentation is automatically built and hosted on ReadTheDocs:
https://formix-pubsub.readthedocs.io/

ReadTheDocs automatically builds the documentation whenever you:
- Push a new tag
- Push to the main branch
- Create a pull request

## Documentation Structure

- `source/conf.py` - Sphinx configuration
- `source/index.rst` - Main documentation page
- `source/quickstart.rst` - Quick start guide
- `source/api.rst` - API reference (auto-generated from docstrings)
- `source/examples.rst` - Practical examples
