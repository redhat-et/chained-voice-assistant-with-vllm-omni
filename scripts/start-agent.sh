#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../agent"

if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
    .venv/bin/pip install -e .
fi

exec .venv/bin/python src/agent.py dev
