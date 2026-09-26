#!/bin/bash
# Run all quality checks: formatting, then tests
set -e
cd "$(dirname "$0")/.."
echo "==> Checking formatting (black)"
uv run black --check backend main.py
echo "==> Running tests (pytest)"
uv run pytest
echo "All quality checks passed."
