#!/usr/bin/env bash
# Launch the HydroAgent Streamlit UI from the frozen project environment.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

if command -v uv >/dev/null 2>&1; then
  exec uv run --frozen streamlit run app/ui_agent.py --server.headless true "$@"
fi

if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
  echo "HydroAgent environment is missing. Install uv, then run: uv sync --frozen" >&2
  exit 1
fi

exec "$ROOT/.venv/bin/python" -m streamlit run app/ui_agent.py --server.headless true "$@"
