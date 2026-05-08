# Justfile — humanoid common tasks.
# Install just from https://github.com/casey/just (optional convenience).

# Default: list available tasks.
default:
    @just --list

# One-shot setup environment (cross-platform).
setup:
    @scripts/setup.sh

# Run FastAPI backend (port 8000).
backend:
    uv run python -m ui.backend

# Run Vite frontend dev server (port 5173).
frontend:
    cd ui/frontend && npm run dev

# Run all tests.
test:
    uv run pytest tests/ -q

# Run only spec §12 27-scenario integration tests.
scenarios:
    uv run pytest tests/scenarios/ -q

# Run only Wave 14C e2e trends.
trends:
    uv run pytest tests/e2e_trends/ -q
