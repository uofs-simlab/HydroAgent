# CIROH Logan River demo

The portable [run plan](logan_river_ciroh_demo.plan.json) defines the original
semi-distributed `Logan_River_CIROH_demo` / `water_year_2005` simulation. It contains
configuration and workflow steps; simulation outputs and downloaded inputs stay
in the local data directory.

| Setting | Value |
| --- | --- |
| Model and routing | SUMMA and mizuRoute |
| Forcing and PET | AORC and Oudin |
| Domain | Delineated watershed; stream-threshold GRUs, threshold 5000 |
| Pour point | 41.74355 / -111.78398 |
| Bounds (north/west/south/east) | 42.15 / -111.87 / 41.65 / -111.42 |
| Observations | USGS station 10109000 |
| Simulation | 2003-10-01 01:00 through 2005-09-30 23:00 |
| Spin-up | 2003-10-01 through 2004-09-30 (water year 2004) |
| Evaluation | 2004-10-01 through 2005-09-30 (water year 2005) |

Set local paths using [local_settings.example.yaml](local_settings.example.yaml).
The backend needs its Pixi environment, model executables, and data access as
described in the main [README](../README.md).

To load the plan without generating another one, create a new directory under
`runs/`, copy the example JSON into it as `plan.json`, and select that directory
in **Experiments**. Choose a directory that does not already contain a saved run.
For a fresh simulation, use **Workflows → Input → Start / load run → Start new run**
and click **Create new run folder**. Existing workspaces receive `_1`, `_2`, …
suffixes. Review the plan and rendered config before executing its 13 steps.
Cloud data access can reuse compatible cached inputs and acquire missing data.

To inspect an already completed demo, select its existing assistant run in
**Experiments**, then open **Results**. The saved `config.yaml` identifies the
correct domain, experiment, and data directory. The hydrograph and metrics use
the evaluation period and exclude spin-up.

Standard postprocessed discharge is stored at
`<data_dir>/domain_<domain>/results/<experiment>_results.csv`. The routed CSV lives
at `<data_dir>/domain_<domain>/simulations/<experiment>/mizuRoute/routed_flow.csv`.
These generated files are excluded from the repository.

Routed extraction uses `SIM_REACH_ID` from the saved run config. This is a river
network reach ID, distinct from the USGS station number. HydroAgent attempts to
infer it from the delineated network before postprocessing; an explicit value in
the plan takes precedence. If inference fails, set the correct reach before using
multi-reach routed output. For manual extraction, run from the repository root:

```sh
.venv/bin/python tools/extract_discharge.py \
  --mizu-dir /path/to/data/domain_Demo/simulations/exp/mizuRoute \
  --reach-id 21
```

Replace both example arguments with the output directory and `SIM_REACH_ID` for
your run. `routed_flow.meta.json` records the reach and source-file signatures;
the CSV is rebuilt when either changes. Ambiguous or unverifiable routed output
is omitted from Results with an explanatory warning.
