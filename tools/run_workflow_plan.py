#!/usr/bin/env python3
"""CLI entry point for background SYMFLUENCE workflow execution."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.core.workflow_executor import run_workflow_job  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run assistant workflow plan steps.")
    parser.add_argument("--run-dir", type=Path, required=True, help="Assistant run folder")
    args = parser.parse_args()
    return run_workflow_job(args.run_dir.resolve())


if __name__ == "__main__":
    raise SystemExit(main())
