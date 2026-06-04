from __future__ import annotations
import json
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
CATALOG = BASE / "data" / "capabilities" / "symfluence_operation_catalog.json"

def load_catalog() -> dict:
    if not CATALOG.exists():
        return {}
    return json.loads(CATALOG.read_text(encoding="utf-8"))