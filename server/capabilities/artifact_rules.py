from __future__ import annotations

ARTIFACT_RULES = {
    "setup_project": {
        "requires": [],
        "produces": ["domain_folder", "run_manifest", "run_summary"],
        "notes": "Initializes project structure and log artifacts.",
    },
    "create_pour_point": {
        "requires": ["domain_folder", "pour_point_coords"],
        "produces": ["pour_point_shapefile"],
        "notes": "Creates shapefile from pour point coordinates.",
    },
    "acquire_attributes": {
        "requires": ["bounding_box_coords"],
        "produces": ["dem_raster", "soil_raster", "landclass_raster"],
        "notes": "Cloud/local attribute acquisition for DEM, soil, and landclass.",
    },
    "define_domain": {
        "requires": ["pour_point_shapefile", "dem_raster"],
        "produces": ["watershed_raster", "river_basins"],
        "notes": "Watershed delineation and basin generation.",
    },
    "discretize_domain": {
        "requires": ["river_basins"],
        "produces": ["hru_gru_shapes", "river_network"],
        "notes": "Creates semidistributed/distributed spatial units and network.",
    },
    "process_observed_data": {
        "requires": [],
        "produces": ["observed_data_processed"],
        "notes": "Processes observations such as streamflow or station inputs.",
    },
    "acquire_forcings": {
        "requires": ["domain_folder", "bounding_box_coords", "experiment_time_start", "experiment_time_end"],
        "produces": ["forcing_inputs"],
        "notes": "Downloads or prepares forcing datasets for the run window.",
    },
    "model_agnostic_preprocessing": {
        "requires": ["forcing_inputs", "hru_gru_shapes"],
        "produces": ["forcing_intersection"],
        "notes": "Intersects or maps forcing data to the domain representation.",
    },
    "model_specific_preprocessing": {
        "requires": ["forcing_intersection"],
        "produces": [
            "fileManager.txt",
            "trialParams.nc",
            "coldState.nc",
            "forcingFileList.txt",
            "attributes.nc",
        ],
        "notes": "Builds model-specific SUMMA settings and input files.",
    },
    "run_model": {
        "requires": ["fileManager.txt"],
        "produces": ["simulation_outputs", "model_logs"],
        "notes": "Runs the configured hydrological model.",
    },
    "calibrate_model": {
        "requires": ["fileManager.txt", "simulation_outputs"],
        "produces": ["calibration_results"],
        "notes": "Runs calibration workflow over model parameters.",
    },
    "postprocess_results": {
        "requires": ["simulation_outputs"],
        "produces": ["plots", "metrics", "summaries"],
        "notes": "Generates summaries, evaluation products, or plots.",
    },
    "dry_run": {
        "requires": [],
        "produces": ["dry_run_report"],
        "notes": "Validates workflow execution path without doing the full run.",
    },
}