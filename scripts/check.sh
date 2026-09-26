#!/bin/bash
# Verify formatting without modifying files (for CI / pre-commit use)
set -e
cd "$(dirname "$0")/.."
uv run black --check --diff backend main.py
