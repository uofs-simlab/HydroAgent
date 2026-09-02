import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.core.routed_flow import ensure_routed_flow_csv


def main():
    mizu_dir = Path.cwd()
    csv_path = ensure_routed_flow_csv(mizu_dir)
    if csv_path is None:
        raise SystemExit("No mizuRoute history files found, or could not extract routed_flow.csv.")
    print("Saved:", csv_path.resolve())
    print(csv_path.read_text(encoding="utf-8").splitlines()[:6])


if __name__ == "__main__":
    main()
