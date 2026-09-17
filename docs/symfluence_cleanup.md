# SYMFLUENCE cleanup status

The backend changes have been reduced to two fixes. No Git commands were run.

| Remaining file change under `symfluence/` | Reason to keep it |
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

## Publish the backend before updating HydroAgent's pointer

These commands are instructions for you; none were executed here. From the
HydroAgent root:

```sh
git -C symfluence switch -c cleanup/backend-fixes
git -C symfluence add pixi.toml pixi.lock
git -C symfluence commit -m "Use conda-forge CPU PyTorch with NumPy 2"
git -C symfluence add examples/01_point_vertical_flux_estimation/01a_point_scale_snotel.ipynb
git -C symfluence commit -m "Correct Paradise SNOTEL station metadata"
git -C symfluence push -u origin cleanup/backend-fixes
```

Open a backend PR targeting `hydroagent-v2` in
`uofs-simlab/SYMFLUENCE-HydroAgent`. After it is merged, check out the published
merge commit inside `symfluence/`, then stage `symfluence` in the parent
HydroAgent repository alongside the HydroAgent changes. Commit and push the
parent afterward. The parent stores a backend commit ID; it does not include
uncommitted files inside the submodule.

If you publish only HydroAgent now, leave its submodule pointer at the
already-published backend commit. Fresh clones will not receive the local
PyTorch fix until a published backend commit containing it is referenced.
