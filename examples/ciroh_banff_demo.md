# CIROH Banff basin demo

## Primary domain: coarse semi-distributed

The prepared demonstration domain is `Bow_at_Banff_CIROH_coarse`. It uses a
stream threshold of `10000` and contains 13 GRUs. Each delineated sub-basin is
used as one GRU, with no additional elevation, land-cover, or soil subdivision.

The first cloud setup used a threshold of `5000` and produced 29 GRUs. It was
then made coarser without downloading the attributes again:

> Re-delineate the existing Bow_at_Banff_CIROH_coarse domain using its existing local data. Use experiment domain_setup_02, pour point 51.1722/-115.5717, bounds north 51.85, west -116.80, south 50.80, east -115.15, stream threshold 10000, domain definition delineate, and GRU discretization. Include only these workflow steps: validate_config, define_domain, discretize_domain.

Before executing, confirm that the plan has `data_access: local` and exactly
these steps:

```text
validate_config
define_domain
discretize_domain
```

In **Output → Review layers**, show the GRUs, sub-basin boundaries, river network,
pour point, and bounding box. The categorical legend should be headed
`GRUs (13)`; the non-consecutive values are routing identifiers, not missing
units.

## Lumped fallback

### Input

> Delineate a lumped Bow River watershed above the Banff gauge, reusing existing local data when available and downloading only missing inputs. Stop after domain definition. Use domain Bow_at_Banff_CIROH_lumped, experiment basin_setup_local_01, pour point 51.1722, -115.5717, bounds north 51.85, west -116.80, south 50.80, east -115.15, stream threshold 1000, and dates 2003-01-01 to 2003-12-31.

### Expected plan

Only the material fields are shown; generated notes and unused optional fields may vary.

```json
{
  "config": {
    "data_access": "local",
    "domain_name": "Bow_at_Banff_CIROH_lumped",
    "experiment_id": "basin_setup_local_01",
    "pour_point_coords": "51.1722/-115.5717",
    "bounding_box_coords": "51.85/-116.80/50.80/-115.15",
    "hydrological_model": "SUMMA",
    "domain_def": "lumped",
    "experiment_time_start": "2003-01-01 01:00",
    "experiment_time_end": "2003-12-31 23:00",
    "stream_threshold": 1000,
    "extra_config": {
      "DATA_ACCESS": "LOCAL",
      "PARAMETER_REGIONALIZATION": "lumped",
      "ROUTING_DELINEATION": "lumped",
      "STREAM_THRESHOLD": 1000
    }
  },
  "steps": [
    "validate_config",
    "setup_project",
    "create_pour_point",
    "acquire_attributes",
    "define_domain"
  ],
  "needs_user_input": [],
  "workflow_plan_mode": "simulation"
}
```
