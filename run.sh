#!/usr/bin/env bash
# Launch the HydroAgent Streamlit UI from this folder.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

PYTHON="${PYTHON:-python3}"
if [[ -x "${VENV:-}/bin/python" ]]; then
  PYTHON="${VENV}/bin/python"
elif [[ -x "$ROOT/.venv/bin/python" ]]; then
  PYTHON="$ROOT/.venv/bin/python"
fi

exec "$PYTHON" -m streamlit run app/ui_agent.py --server.headless true "$@"
