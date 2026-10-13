# Python Project Template

A production-ready Python project template with `uv`, pre-commit hooks, and test infrastructure.

## Quick Start

```bash
# Clone and setup
git clone git@github.com:cdrc1103/python-template.git my-project
cd my-project

# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install dependencies and setup git hooks
uv sync
pre-commit install
```

## Development

### Install Dependencies
```bash
uv add <package>      # Add a runtime dependency
uv add -d <package>   # Add a dev dependency
uv sync               # Sync environment after changes
```

### Run Tests
```bash
uv run pytest tests/ -v
```

### Format & Lint
```bash
uv run ruff format .    # Format code
uv run ruff check .     # Check linting
pre-commit run --all-files  # Run all pre-commit hooks
```

## Project Structure

```
.
├── src/              # Main package code
├── tests/            # Test suite
├── pyproject.toml    # Project metadata & dependencies
├── CLAUDE.md         # Development guidelines
└── README.md         # This file
```

## Tools

- **uv**: Fast Python package manager & virtualenv tool
- **Ruff**: Fast linter + formatter (replacing Black, Flake8, isort)
- **pytest**: Testing framework with coverage support
- **pre-commit**: Git hooks for quality checks

## Pre-commit Hooks

Automatically run on each commit:
- **ruff-format**: Format code
- **ruff-lint**: Check for linting issues (with auto-fix)
- **trailing-whitespace**: Remove trailing spaces
- **end-of-file-fixer**: Fix file endings
- **check-yaml**: Validate YAML files
- **check-added-large-files**: Prevent large files

## License

MIT
