# humanoid one-shot setup (Windows PowerShell).
# Equivalent POSIX script: scripts/setup.sh.
$ErrorActionPreference = "Stop"

# 1. Verify uv is installed.
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "uv not found. Install via:"
    Write-Host "  irm https://astral.sh/uv/install.ps1 | iex"
    Write-Host "  (or pip install uv)"
    exit 1
}

# 2. Sync Python dependencies (creates .venv automatically).
uv sync --extra dev --extra ui

# 3. Copy .env.example -> .env if missing.
if (-not (Test-Path .env)) {
    Copy-Item .env.example .env
    Write-Host ""
    Write-Host "Created .env from .env.example. Edit it to set AGENT_OPENAI_API_KEY."
}

# 4. Frontend deps (optional — UI usage).
if (Get-Command npm -ErrorAction SilentlyContinue) {
    Push-Location ui/frontend
    npm install
    Pop-Location
    Write-Host "Frontend dependencies installed."
} else {
    Write-Host "npm not found — skipping frontend setup."
}

Write-Host ""
Write-Host "Setup complete."
Write-Host "Run backend:  uv run python -m ui.backend"
Write-Host "Run frontend: cd ui\frontend; npm run dev"
Write-Host "Run tests:    uv run pytest tests/ -q"
