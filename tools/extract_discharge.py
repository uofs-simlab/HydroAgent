import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.core.routed_flow import ensure_routed_flow_csv


def main():
    parser = argparse.ArgumentParser(description="Extract one configured mizuRoute reach.")
    parser.add_argument("--mizu-dir", type=Path, default=Path.cwd())
    parser.add_argument("--reach-id", type=int, help="SIM_REACH_ID (required for multi-reach output)")
    args = parser.parse_args()
    try:
        csv_path = ensure_routed_flow_csv(args.mizu_dir, args.reach_id)
    except (OSError, ValueError, ImportError) as exc:
        parser.exit(1, f"Cannot extract routed discharge: {exc}\n")
    if csv_path is None:
        raise SystemExit("No mizuRoute history files found, or could not extract routed_flow.csv.")
    print("Saved:", csv_path.resolve())
    print(csv_path.read_text(encoding="utf-8").splitlines()[:6])


if __name__ == "__main__":
    main()
