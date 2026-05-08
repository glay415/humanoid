#!/usr/bin/env bash
# humanoid one-shot setup (Linux / macOS).
# Equivalent Windows script: scripts/setup.ps1.
set -euo pipefail

# 1. Verify uv is installed.
if ! command -v uv &> /dev/null; then
    echo "uv not found. Install via:"
    echo "  curl -LsSf https://astral.sh/uv/install.sh | sh"
    echo "  (or pip install uv)"
    exit 1
fi

# 2. Sync Python dependencies (creates .venv automatically).
uv sync --extra dev --extra ui

# 3. Copy .env.example -> .env if missing.
if [ ! -f .env ]; then
    cp .env.example .env
    echo ""
    echo "Created .env from .env.example. Edit it to set AGENT_OPENAI_API_KEY."
fi

# 4. Frontend deps (optional — UI usage).
if command -v npm &> /dev/null; then
    pushd ui/frontend > /dev/null
    npm install
    popd > /dev/null
    echo "Frontend dependencies installed."
else
    echo "npm not found — skipping frontend setup."
fi

echo ""
echo "Setup complete."
echo "Run backend:  uv run python -m ui.backend"
echo "Run frontend: cd ui/frontend && npm run dev"
echo "Run tests:    uv run pytest tests/ -q"
