# SYMFLUENCE cleanup status

The backend changes have been reduced to two fixes, committed as `1b79a581`
with message `fix python package compatibility and paradise SNOTEL metadata`.

| Retained file change under `symfluence/` | Reason to keep it |
| --- | --- |
| `pixi.toml` and `pixi.lock` | Use the conda-forge CPU PyTorch build with the NumPy 2 stack. Keep the manifest and matching lock together. |
| `examples/01_point_vertical_flux_estimation/01a_point_scale_snotel.ipynb` | Correct Paradise's station ID from `602` to `679` in the config and introduction, and correct the stated elevation to approximately 1,570 m. |

The station correction is supported by the
[NRCS Paradise record](https://wcc.sc.egov.usda.gov/nwcc/site?sitenum=679&state=wa).
The notebook otherwise matches the original unexecuted version, including its
metadata; local outputs and execution counts have been removed by restoring that
version.

The following files were restored exactly to the backend snapshot from the audit:

- `config_BowRiver.yaml`
- `examples/02_watershed_modelling/02b_basin_semi_distributed.ipynb`
- `examples/02_watershed_modelling/config_semi_distributed.yaml`

This discards the local demo paths, DEM switches, cloud-tutorial rewrite,
generated config expansion, notebook outputs, and local kernel changes. Existing
paths and other settings in the original examples remain as they were upstream.
HydroAgent's saved runs and data were not changed.

## Validate the environment fix

From the HydroAgent root:

```sh
pixi install --manifest-path symfluence/pixi.toml --locked -e build
pixi run --manifest-path symfluence/pixi.toml --locked -e build python -c \
  'import numpy as np, torch, netCDF4, h5py, rasterio; x=np.arange(4, dtype=np.float64); np.testing.assert_array_equal(torch.from_numpy(x).numpy(), x); print("NumPy/Torch conversion and native imports passed")'
```

The current lock uses format version 7 and contains Linux, macOS, and Windows
packages. Use a compatible Pixi version and have CI test those platforms. A local
macOS smoke test does not validate the Linux or Windows packages. Do not hand-edit
the lock or publish it separately from the manifest.

## Published backend

The fixes are published on
[`tristanmontoya/SYMFLUENCE`, branch `ciroh-asm-2026`](https://github.com/tristanmontoya/SYMFLUENCE/tree/ciroh-asm-2026).
HydroAgent's `.gitmodules` points to that fork and branch, and the submodule
remains pinned to commit `1b79a581`. This lets fresh clones fetch the retained
fixes without requiring write access to the upstream repository.

HydroAgent is published on
[`tristanmontoya/HydroAgent`, branch `main`](https://github.com/tristanmontoya/HydroAgent/tree/main).
To contribute the backend fixes upstream, open a separate PR targeting
`hydroagent-v2` in `uofs-simlab/SYMFLUENCE-HydroAgent`. If that PR is merged,
HydroAgent can switch back to the upstream URL and pin the published merge commit.
