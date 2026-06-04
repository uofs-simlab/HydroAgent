# HydroAgent

A natural-language assistant and Streamlit UI for planning and executing [SYMFLUENCE](https://github.com/your-org/SYMFLUENCE) hydrological modelling workflows. Describe a modelling run in plain English — HydroAgent generates a structured step-by-step plan, resolves inter-step dependencies, writes the SYMFLUENCE `config.yaml`, and executes each step with live log output.

---

## Features

- **Natural-language plan generation** — Converts free-text modelling requests into structured JSON run plans via OpenAI
- **Dependency resolution** — Automatically orders and validates workflow steps before execution
- **Interactive map** — Pour-point selection and basin visualisation via Folium
- **Config generation** — Writes SYMFLUENCE-compatible `config.yaml` from plan parameters
- **CLI mode** — Headless plan generation without the UI
- **mizuRoute post-processing** — Optional tools for routed-flow extraction and summarisation

---

## Project layout

```
HydroAgent/
├── app/
│   ├── ui_agent.py          # Main Streamlit application
│   └── workflow_extras.py   # Results, maps, calibration shortcuts
├── server/
│   ├── core/                # Config templates, validation, parameter registry, plan rules
│   ├── capabilities/        # Operation catalog, dependency resolution, proven-status flags
│   └── llm/                 # OpenAI provider for plan generation
├── prompts/
│   └── planner_prompt.txt   # System prompt for workflow plan generation
├── configs/                 # SYMFLUENCE YAML templates
├── data/capabilities/       # Operation catalog and dependency metadata (JSON)
├── tools/                   # Optional mizuRoute post-processing scripts
├── examples/                # local_settings.example.yaml
├── cli.py                   # Headless plan generator
├── run.sh                   # Launch script
├── requirements.txt
└── runs/                    # Per-run output folders (config.yaml, plan.json, logs)
```

---

## Prerequisites

| Requirement | Notes |
|-------------|-------|
| Python 3.11+ | 3.12 or 3.13 tested |
| [SYMFLUENCE](https://github.com/your-org/SYMFLUENCE) | Installed and working |
| SYMFLUENCE_data | Geospatial cache, model installs, domain data |
| OpenAI API key | Required for plan generation (UI + CLI) |

### Geospatial stack

GeoPandas and Folium require GDAL. On Linux/macOS, conda-forge is the easiest path:

```bash
conda create -n hydroagent python=3.12
conda activate hydroagent
conda install -c conda-forge geopandas folium pyyaml pandas
pip install -r requirements.txt
```

Alternatively, use a plain venv if GDAL is already available system-wide:

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

---

## Configuration

Copy the example settings file and edit paths for your machine:

```bash
mkdir -p ~/.symfluence_assistant
cp examples/local_settings.example.yaml ~/.symfluence_assistant/config.yaml
```

```yaml
# ~/.symfluence_assistant/config.yaml
symfluence_repo:    /path/to/SYMFLUENCE
symfluence_data_dir: /path/to/SYMFLUENCE_data
symfluence_python:  /path/to/SYMFLUENCE/venv/bin/python
openai_api_key:     sk-...          # or set via .env / UI sidebar
```

For the API key only, you can alternatively copy `.env.example` to `.env`:

```bash
cp .env.example .env
# edit .env and set OPENAI_API_KEY
```

---

## Quick start

```bash
chmod +x run.sh
./run.sh
```

Open `http://localhost:8501` in your browser.

### Typical workflow

1. **Workflows → Input** — Set domain, experiment ID, pour point, model, and date range (or click **Load data domain**).
2. **Workflows → Prompt** — Describe the run in plain English, then click **Generate run plan**.
3. Review the plan JSON, click **Resolve dependencies**, then **Execute plan** (confirm `RUN` for `run_model` / `calibrate_model` steps).
4. **Output / Results** — Inspect logs and artifacts; use the Results tab for routed-flow plots.

Run outputs are saved under `runs/<domain>_<experiment>/`.

---

## CLI

Generate a plan without the UI:

```bash
export OPENAI_API_KEY=sk-...
python cli.py run "Lumped SUMMA workflow for Bow River at Banff, 2010-2015" \
    --json-out runs/bow_river_plan.json
```

Options:

| Flag | Default | Description |
|------|---------|-------------|
| `--model` | `gpt-5` | OpenAI model name |
| `--api-key` | env | Override `OPENAI_API_KEY` |
| `--json-out` | — | Save plan JSON to file |

---

## Local / pre-existing domain data

For workflows that skip download steps, place data under:

```
SYMFLUENCE_data/domain_<DOMAIN_NAME>/
```

Set `domain_name` and `experiment_id` as separate plan fields (do not merge them into `DOMAIN_NAME`).

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `symfluence workflow step` not found | Check `symfluence_python` in `~/.symfluence_assistant/config.yaml` |
| DEM / shapefile missing | Verify `DOMAIN_NAME` matches a `SYMFLUENCE_data/domain_*` folder |
| Plan / OpenAI errors | Check API key in sidebar or config file |
| GeoPandas import errors | Install GDAL via conda-forge (see Prerequisites) |

---

## Contributing & pushing to GitHub

```bash
# From the repo root (or a repo containing only HydroAgent/)
git add HydroAgent/
git commit -m "Add HydroAgent distributable UI package"
git remote add origin git@github.com:<org>/<repo>.git   # if not already set
git push origin main
```

> **Never commit** `.env`, API keys, or the contents of `runs/` — these are already covered by `.gitignore`.

---

## License

SYMFLUENCE and any bundled third-party model binaries carry their own licenses. Refer to your organisation's terms for redistribution.
