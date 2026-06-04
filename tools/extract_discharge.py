import glob
from pathlib import Path
from netCDF4 import Dataset, num2date
import pandas as pd

def main():
    # assumes you run from a domain's mizuRoute output folder
    files = sorted(glob.glob("exp_*.h.*.nc"))
    if not files:
        raise SystemExit("No mizuRoute history files found (exp_*.h.*.nc).")

    out_csv = Path("routed_flow.csv")

    # concatenate all time chunks
    rows = []
    for f in files:
        with Dataset(f) as ds:
            if "IRFroutedRunoff" not in ds.variables:
                raise SystemExit(f"Missing IRFroutedRunoff in {f}")
            q = ds.variables["IRFroutedRunoff"][:]  # (time, seg)
            t = ds.variables["time"]
            tt = num2date(t[:], units=t.units, calendar=getattr(t, "calendar", "standard"))

            # seg=0 since you have one segment/outlet
            for i in range(len(tt)):
                rows.append((pd.to_datetime(str(tt[i])), float(q[i, 0])))

    df = pd.DataFrame(rows, columns=["time", "IRFroutedRunoff"])
    df["time"] = df["time"].dt.round("s")
    df.sort_values("time", inplace=True)
    df.to_csv(out_csv, index=False)
    print("Saved:", out_csv.resolve())
    print(df.head())

if __name__ == "__main__":
    main()
