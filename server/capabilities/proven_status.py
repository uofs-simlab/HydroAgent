from __future__ import annotations

PROVEN_STATUS = {
    "setup_project": True,
    "create_pour_point": True,
    "acquire_attributes": True,
    "define_domain": True,
    "discretize_domain": True,
    "process_observed_data": False,
    "acquire_forcings": True,
    "model_agnostic_preprocessing": True,
    "model_specific_preprocessing": True,
    "run_model": False,
    "calibrate_model": False,
    "postprocess_results": False,
    "dry_run": True,
}