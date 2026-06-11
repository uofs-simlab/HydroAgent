"""UI option lists aligned with SYMFLUENCE core/config Pydantic models."""

from __future__ import annotations

# symfluence.core.config.models.forcing.ForcingDatasetType
FORCING_DATASET_OPTIONS: list[str] = [
    "NLDAS",
    "NLDAS2",
    "NEX-GDDP",
    "ERA5",
    "EM-EARTH",
    "RDRS",
    "CASR",
    "CARRA",
    "CERRA",
    "MSWEP",
    "AORC",
    "CONUS404",
    "HRRR",
    "DAYMET",
    "NWM3_RETROSPECTIVE",
    "local",
]

# symfluence.core.config.models.forcing.PETMethodType
PET_METHOD_OPTIONS: list[str] = [
    "oudin",
    "hargreaves",
    "priestley_taylor",
    "penman",
    "fao56",
]

# symfluence.cli.argument_parser.DOMAIN_DEFINITION_METHODS
DOMAIN_DEF_OPTIONS: list[str] = ["delineate", "lumped", "point", "subset"]

# symfluence.core.config.models.model_configs.HYDROLOGICAL_MODEL_REGISTRY keys
HYDROLOGICAL_MODEL_OPTIONS: list[str] = [
    "",
    "CLM",
    "CLMPARFLOW",
    "CRHM",
    "FUSE",
    "GNN",
    "GR",
    "GSFLOW",
    "HYPE",
    "HYDROGEOSPHERE",
    "LSTM",
    "MESH",
    "MHM",
    "MODFLOW",
    "NGEN",
    "PARFLOW",
    "PIHM",
    "PRMS",
    "RHESSYS",
    "SUMMA",
    "SWAT",
    "VIC",
    "WATFLOOD",
    "WFLOW",
    "WRFHYDRO",
]

# Common subset of symfluence.core.config.constants.VALID_OPTIMIZATION_ALGORITHMS
CALIBRATION_ALGORITHMS: list[str] = [
    "DE",
    "DDS",
    "PSO",
    "NSGA-II",
    "SCE-UA",
    "ADAM",
    "LBFGS",
    "CMA-ES",
]

# symfluence.core.config.models.optimization.OptimizationMetricType
CALIBRATION_METRICS: list[str] = [
    "KGE",
    "KGEP",
    "NSE",
    "RMSE",
    "MAE",
    "PBIAS",
    "R2",
    "CORRELATION",
    "COMPOSITE",
]

# Used throughout SYMFLUENCE optimization/evaluation resampling
CALIBRATION_TIMESTEPS: list[str] = ["native", "hourly", "daily"]

# Assistant convention; SYMFLUENCE accepts free-text STREAMFLOW_DATA_PROVIDER
STREAMFLOW_PROVIDER_OPTIONS: list[str] = ["WSC", "USGS", "VI", "NIWA"]

CALIBRATION_TARGETS: list[str] = [
    "streamflow",
    "swe",
    "snow_depth",
    "et",
    "groundwater",
]

_LEGACY_FORCING_ALIASES: dict[str, str] = {
    "custom": "local",
    "merra2": "ERA5",
    "merra-2": "ERA5",
}

_UNSUPPORTED_HYDRO_MODELS: frozenset[str] = frozenset({"HBV", "TOPMODEL"})
