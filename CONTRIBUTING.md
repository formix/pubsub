# Contributing to formix-pubsub

Thank you for your interest in contributing! This document provides guidelines for contributing to this project.

## Commit Message Convention

We follow the [Conventional Commits](https://www.conventionalcommits.org/) specification for commit messages.

### Format

```
<type>[(optional scope)]: <description>

[optional body]

[optional footer(s)]
```

### Common Types

| Type | Description | Example |
|------|-------------|---------|
| `feat` | New feature | `feat: add user authentication` |
| `fix` | Bug fix | `fix: resolve login timeout issue` |
| `docs` | Documentation only | `docs: update API documentation` |
| `style` | Code style/formatting | `style: format code with black` |
| `refactor` | Code restructuring | `refactor: simplify validation logic` |
| `perf` | Performance improvement | `perf: optimize database queries` |
| `test` | Add/update tests | `test: add unit tests for auth module` |
| `build` | Build system/dependencies | `build: upgrade django to 4.2` |
| `ci` | CI/CD changes | `ci: add GitHub Actions workflow` |
| `chore` | Maintenance tasks | `chore: update .gitignore` |
| `revert` | Revert previous commit | `revert: revert "feat: add feature X"` |

### Scope (Optional)

Use parentheses after type to specify component/module:

```
feat(api): add endpoint for user profile
fix(ui): correct button alignment
docs(readme): add installation instructions
```

### Breaking Changes

Add `!` after type or `BREAKING CHANGE:` in footer:

```
feat!: remove deprecated API endpoints

refactor(api): change response format

BREAKING CHANGE: API now returns data in different format
```

### Examples

```
feat: add email notifications
fix(auth): prevent duplicate user registration
docs: add contributing guidelines
style: remove trailing whitespace
refactor: extract validation into separate module
perf(database): add indexes to user table
test: add integration tests for payment flow
build: update dependencies
ci: add automated testing on pull requests
chore: clean up unused imports
```

### Rules

- Use lowercase for type and description
- No period at the end of description
- Keep first line under 50-72 characters
- Use imperative mood ("add" not "added" or "adds")
- Separate body from description with blank line

## Development Setup

1. Clone the repository
2. Install development dependencies:
   ```bash
   pip install -e .[dev]
   ```
3. Run tests to verify setup:
   ```bash
   python -m unittest discover -s tests
   ```

## Code Style

This project uses [Ruff](https://docs.astral.sh/ruff/) for both linting and code formatting.

### Code Conventions

- **Line length**: Maximum 100 characters per line
- **Style guide**: Follow PEP 8 guidelines
- **Imports**: Automatically organized by Ruff
- **Formatting**: Use Ruff's automatic formatting

### Using Ruff

**Check for issues:**
```bash
ruff check .
```

**Auto-fix issues:**
```bash
ruff check --fix .
```

**Format code:**
```bash
ruff format .
```

**Check and format (recommended before committing):**
```bash
ruff check --fix . && ruff format .
```

### Pre-commit Hook (Optional)

To automatically check code before committing, install pre-commit hooks:

```bash
pip install pre-commit
pre-commit install
```

This will run Ruff automatically on every commit.

## Running Tests

```bash
# All tests
python -m unittest discover -s tests

# Specific test class
python -m unittest tests.test_pubsub.TestPublish -v

# Specific test
python -m unittest tests.test_channel.TestChannel.test_channel_creation -v
```

## Pull Request Process

1. Fork the repository
2. Create a feature branch from `main`
3. Make your changes following the commit convention
4. Ensure all tests pass
5. Update documentation if needed
6. Submit a pull request

## Questions?

Feel free to open an issue for any questions or suggestions!
