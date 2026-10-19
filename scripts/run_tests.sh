#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "$ROOT/.test-tmp"
export TMPDIR="$ROOT/.test-tmp"
export PYTHONDONTWRITEBYTECODE=1
cd "$ROOT"
python3 -m unittest -v test_benchmark.py
cd "$ROOT/quality-kit"
python3 -m unittest -v test_kit.py
