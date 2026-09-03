# Contributing to ChanakyaTrade CLI

Thanks for your interest in contributing! This document explains how to get started.

## Getting Started

1. Fork the repo
2. Clone your fork: `git clone https://github.com/<your-username>/chanakya-trade.git`
3. Create a feature branch: `git checkout -b feature/my-feature`
4. Bootstrap the self-healing development environment: `bash scripts/bootstrap.sh` (or `./scripts/bootstrap.ps1` on Windows)

## Development Setup

**Requires Python 3.11+.** CI tests against 3.11, 3.12, and 3.13.

```bash
# macOS / Linux
bash scripts/bootstrap.sh

# Windows PowerShell
.\scripts\bootstrap.ps1
```

The bootstrap checks that `.venv` can actually start. If its original Python
installation was removed, it moves the stale environment to a recoverable
`.venv.broken-<timestamp>` directory, creates a fresh one, and installs
`.[dev]`. Set `CHANAKYA_PYTHON` when Python is installed outside PATH.

Test without a broker account:

```bash
trade --no-broker
```

## Running Tests

```bash
# Windows PowerShell (also works when .venv is stale or missing)
.\scripts\test.ps1

# macOS / Linux
bash scripts/test.sh
```

The wrappers default to unit/fast tests (`not network and not slow`) and pass
additional arguments through to pytest. Use `--all`, `--network`, or `--slow`
when those tiers are explicitly needed.

By default, tests that require network access (yfinance, NSE API) are **excluded**. To run the full suite including network tests:

```bash
bash scripts/test.sh --all            # all tests (needs network)
bash scripts/test.sh --network        # only network tests
```

## Code Style

This project uses [Ruff](https://docs.astral.sh/ruff/) for linting and formatting:

```bash
ruff check .
ruff format .
```

Configuration is in `pyproject.toml`. Target is Python 3.11, line length 100.

## Submitting Changes

1. Make your changes on a feature branch
2. Add tests if applicable
3. Run `pytest` and `ruff check .` locally
4. Submit a pull request against `main`
5. Describe what your PR does and link any related issues

## Reporting Bugs

Open an issue with:
- Steps to reproduce
- Expected vs actual behavior
- Python version and OS
- Full traceback if applicable

## Feature Requests

Open an issue describing:
- The problem you're trying to solve
- Your proposed solution
- Any alternatives you've considered

## Code of Conduct

See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). Be respectful and constructive.
