from __future__ import annotations
import argparse
from pathlib import Path
import pandas as pd

def summarize(csv_path: Path) -> dict:
    df = pd.read_csv(csv_path, parse_dates=["time"])
    if "IRFroutedRunoff" not in df.columns:
        raise ValueError(f"Expected column IRFroutedRunoff in {csv_path.name}, got {list(df.columns)}")

    q = df["IRFroutedRunoff"].astype(float)

    out = {
        "csv": str(csv_path),
        "n_rows": int(len(df)),
        "start": str(df["time"].min()),
        "end": str(df["time"].max()),
        "min_q_m3s": float(q.min()),
        "max_q_m3s": float(q.max()),
        "mean_q_m3s": float(q.mean()),
        "peak_time": str(df.loc[q.idxmax(), "time"]),
    }
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True, help="Path to routed_flow.csv")
    args = ap.parse_args()

    csv_path = Path(args.csv).expanduser().resolve()
    out = summarize(csv_path)

    # Print in LLM-friendly way
    print("=== Routed discharge summary ===")
    for k, v in out.items():
        print(f"{k}: {v}")

if __name__ == "__main__":
    main()
