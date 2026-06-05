# HydroAgent

A natural-language assistant and Streamlit UI for planning and executing [SYMFLUENCE](https://github.com/your-org/SYMFLUENCE) hydrological modelling workflows. Describe a modelling run in plain English — HydroAgent generates a structured step-by-step plan, resolves inter-step dependencies, writes the SYMFLUENCE `config.yaml`, and executes each step with live log output.

---

## Features

- **Multi-provider LLM plan generation** — Supports OpenAI (GPT), Google (Gemini), and Anthropic (Claude) for natural-language workflow planning
- **Dependency resolution** — Automatically orders and validates workflow steps before execution
- **Interactive map** — Pour-point and bounding-box selection with delineation output overlays via Folium
- **Config generation** — Writes SYMFLUENCE-compatible `config.yaml` from plan parameters
- **Voice input** — Record or upload audio; transcribed via OpenAI Whisper or Gemini
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
│   └── llm/
│       ├── plan_shared.py       # Shared schema and plan utilities across providers
│       ├── openai_provider.py   # OpenAI (GPT) provider
│       ├── gemini_provider.py   # Google Gemini provider
│       └── claude_provider.py   # Anthropic Claude provider
├── prompts/
│   └── planner_prompt.txt   # System prompt for workflow plan generation
├── configs/                 # SYMFLUENCE YAML templates
├── data/capabilities/       # Operation catalog and dependency metadata (JSON)
├── tools/                   # Optional mizuRoute post-processing scripts
├── examples/                # local_settings.example.yaml
├── cli.py                   # Headless plan generator (OpenAI)
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
| LLM API key | OpenAI, Google Gemini, or Anthropic — at least one required for plan generation |

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

# Add whichever LLM key(s) you have — at least one is needed for plan generation
openai_api_key:     sk-...
gemini_api_key:     AIza...
claude_api_key:     sk-ant-...
```

API keys can also be entered directly in the UI sidebar and saved from there. For OpenAI only, you can use `.env`:

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
2. **Workflows → Prompt** — Select a provider, enter your API key, describe the run in plain English, then click **Generate plan**.
3. Review the plan JSON, click **Resolve dependencies**, then **Execute plan** (confirm `RUN` for `run_model` / `calibrate_model` steps).
4. **Output / Results** — Inspect logs and artifacts; use the Results tab for routed-flow plots.

Run outputs are saved under `runs/<domain>_<experiment>/`.

---

## CLI

Generate a plan without the UI (OpenAI only):

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

## UI reference

The Workflows page is divided into three regions: a left sidebar for navigation and global paths, a wide centre panel for workflow inputs and outputs, and a narrower right panel for the LLM assistant.

---

### Left panel (sidebar)

**Navigation**

A radio selector at the top switches between pages:

| Page | Purpose |
|------|---------|
| Dashboard | Overview of all saved runs, system status (repo, data dir, Python interpreter). |
| Workflows | Main working page — inputs, map, assistant, and execution. |
| Experiments | Browse and reload previous runs; trigger calibration runs. |
| Data | Inspect SYMFLUENCE_data domain folders and available shapefiles. |
| Templates | Reserved for a future template management UI. |
| Results | Post-processing and routed-flow visualisation across all runs. |
| Logs | View raw command logs from past runs. |
| Settings | Reminder page pointing to path settings (in the sidebar expander below). |

**Local SYMFLUENCE paths** (expander, always accessible)

Paths are read from `~/.symfluence_assistant/config.yaml` on startup and can be overridden here without editing files.

| Field | What to set |
|-------|------------|
| SYMFLUENCE repo path | Absolute path to the SYMFLUENCE source checkout. |
| SYMFLUENCE data path | Absolute path to the SYMFLUENCE_data directory. |
| SYMFLUENCE Python path | Absolute path to the Python interpreter inside the SYMFLUENCE virtual environment. |
| Save local paths | Writes all three paths to `~/.symfluence_assistant/config.yaml`. Takes effect immediately; a full app restart is only needed if you switch Python environments. |

Below the save button, colour-coded status indicators show whether each path currently exists on disk.

---

### Middle panel (Input and Output tabs)

The centre column contains the core workflow controls split across two tabs.

#### Input tab

**Start / load run** (expander)

| Option | What it does |
|--------|-------------|
| Start new run | Uses the Domain name and Experiment ID fields below to create `runs/<domain>_<experiment>/` containing `config.yaml`, `plan.json`, and `spec.json`. |
| Load assistant run | Dropdown of existing folders under `runs/`; loading restores all session fields from the saved plan and config. |
| Load SYMFLUENCE data domain | Dropdown of `domain_*` folders under `SYMFLUENCE_data/`; reads `config.yaml` from the domain and populates the session fields from it. |

**Workflow settings**

| Field | What to enter |
|-------|--------------|
| Domain name | Short identifier for the geographical domain (e.g. `BowRiver`). Must match the folder name in `SYMFLUENCE_data/domain_<name>`. |
| Experiment ID | Short label for this particular run (e.g. `baseline2010`). Combined with domain name to form the run folder. |
| Run folder name | Auto-filled as `<domain>_<experiment>`. Can be edited manually. |
| Hydrological model | Dropdown: SUMMA, FUSE, GR, HBV, MESH, HYPE, ngen, TOPMODEL, and others supported by SYMFLUENCE. Leave blank to let the LLM choose from the prompt. |
| Domain definition | How the spatial domain is bounded: `delineate` (watershed from pour point), `lumped` (single HRU), `point` (single point), or `subset` (from bounding box). |
| Forcing dataset | Meteorological input source: ERA5, RDRS, MERRA2, NLDAS, or Custom. |
| NUM_PROCESSES | Number of parallel processes for model execution (1–128). |
| Start / End date & time | Simulation time window in `YYYY-MM-DD HH:MM` format. Use the date and time pickers or type directly. |

**Map & Spatial Inputs**

| Control | What it does |
|---------|-------------|
| Map click mode — Pour point | Click anywhere on the map to drop a pour point marker. Coordinates are captured as `lat, lon` and written to the plan config. |
| Map click mode — Bounding box | Click two corners of a rectangle on the map. The first click sets corner 1; the second click finalises the box. Clicking again after the box is set starts a new box. |
| Review layers (expander) | Toggle checkboxes to overlay delineation outputs (DEM, land class, soil class, river basins, HRU/GRU, forcing grid, river network) on the map. Layers appear only when the corresponding shapefiles exist under `SYMFLUENCE_data/domain_<name>/`. |
| Interactive map | Folium map; pan and zoom normally. Click to set spatial inputs according to the mode above. |
| Clear pour point | Removes the current pour point from the session and from the active plan. |
| Clear bounding box | Removes the current bounding box from the session and from the active plan. |
| Pour point (lat/lon) | Text field showing the active coordinates; can also be typed or pasted directly in the format `lat,lon`. |
| Bounding box (north/west/south/east) | Text field for manual entry or display of the active bounding box. |

**Run single step** (expander)

Runs individual SYMFLUENCE steps immediately using the current Input fields, without going through a full plan. Useful for quick checks.

| Button | What it does |
|--------|-------------|
| Validate config | Runs SYMFLUENCE's internal config validation against the current `config.yaml` preview. |
| Dry run (setup) | Runs the `dry_run` step — checks paths and parameters without downloading or modelling data. |
| Proven workflow steps | Buttons for each step that has been verified to work end-to-end (auto-populated from the operation catalog). |
| Run model | Runs `run_model` directly. Requires **Allow dangerous run steps** to be enabled in the right panel. |
| Calibrate model | Runs `calibrate_model` directly. Same safety requirement as Run model. |

#### Output tab

| Section | What it shows |
|---------|--------------|
| Generated config.yaml | Read-only preview of the `config.yaml` that will be (or was) written to the run folder, reflecting all current Input fields and plan parameters. |
| Run results | Post-processing section — routed discharge extraction, flow summarisation, and hydrograph metrics for the active run. |
| Output map layers (expander) | Same layer toggles as the Input tab, shown on a second map so you can inspect delineation outputs without leaving the Output tab. |
| Advanced → Manual SYMFLUENCE steps | Four buttons for running individual steps without a plan: **Internal Validate**, **Dry Run setup**, **Setup Project**, and **Run Model Only** (requires Allow dangerous run steps). For normal use, prefer Execute plan. |
| Workflow progress | Step-by-step status of the active plan — pending, running, completed, or failed — updated live during execution. |
| Command output | Live streaming log of the SYMFLUENCE subprocess output from the most recent step or plan execution. |

---

### Right panel (LLM Assistant)

The right column (28% of the page width) contains the LLM assistant split across two tabs.

#### Prompt tab

**Provider and API key**

| Control | What it does |
|---------|-------------|
| Provider | Selects the LLM backend: **OpenAI (GPT)**, **Google (Gemini)**, or **Anthropic (Claude)**. Switching providers changes the model list and which API key is active. |
| Your API key | Paste the key for the selected provider. Keys are stored per-provider and never leave your machine. |
| Save key | Saves the key for the active provider to `~/.symfluence_assistant/config.yaml` so it persists across sessions. |
| Model | Dropdown of available models for the selected provider. Defaults to the recommended model for each provider. |

Available models by provider:

| Provider | Models |
|----------|--------|
| OpenAI (GPT) | GPT-4o, GPT-4o-mini, GPT-5, and others |
| Google (Gemini) | Gemini 2.5 Flash / Pro (recommended), Gemini 2.0 Flash, Gemini 1.5 (legacy) |
| Anthropic (Claude) | Sonnet 4, Opus 4 (recommended), Sonnet 3.7, Sonnet 3.5, Haiku 3.5 (legacy) |

> **Note:** The `anthropic` and `google-genai` SDK packages must be installed (included in `requirements.txt`). If a provider's SDK is not importable, the UI shows an install hint.

**Natural-language request**

Type a plain-English description of the modelling run — basin name, pour point, model type, date range, and any special requirements. Example:

> *"Lumped SUMMA workflow for Bow River at Banff, 2010–2015, using local domain data."*

**Voice input**

Record directly in the browser. Transcription uses **OpenAI Whisper** (if an OpenAI key is saved) or **Gemini audio** (if a Gemini key is saved). Claude does not have a speech-to-text API and cannot be used for transcription.

| Button | What it does |
|--------|-------------|
| Transcribe to prompt | Converts the recording to text and places it in the prompt box for review before generating a plan. |

**Generate plan**

Sends the prompt to the selected LLM provider and returns a structured JSON run plan with ordered workflow steps, required config parameters, missing input flags, and planner notes. The plan appears in an editable JSON box below the button.

**Editable plan JSON**

After a plan is generated it appears here as editable JSON. You can manually adjust steps, parameters, or config values before proceeding. Changes are applied live to the session.

**Resolve dependencies**

Inspects the current plan against the SYMFLUENCE operation catalog and inserts any prerequisite steps that are missing. For example, if your plan includes `run_model` but skips `setup_project`, this button adds the missing step in the correct position.

**Execution controls**

| Control | What it does |
|---------|-------------|
| Also run create_pour_point | Adds `create_pour_point` to the execution sequence even if it wasn't in the generated plan. Useful when a new pour point was selected on the map. |
| Allow dangerous run steps | Must be enabled before any step that runs or calibrates a model (`run_model`, `calibrate_model`). These steps can take a long time and consume significant compute. |
| Type RUN to allow dangerous execution | Safety confirmation field. Type `RUN` (exact) to unlock the Execute plan button when dangerous steps are present. |
| **Execute plan** | Runs every step in the plan sequentially. Disabled until all required inputs are filled and any dangerous-step confirmation is complete. Output streams live to the Output tab. |
| **Clear plan** | Discards the current plan and resets the assistant panel so you can start fresh. |

#### Chat tab

Shows a conversation view of the current session — your last prompt and the assistant's response (the list of planned steps and any warnings about missing inputs). This is read-only; use the Prompt tab to make changes.

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
| Plan / LLM errors | Check the API key for the selected provider in the sidebar or config file |
| Provider not available | Ensure `anthropic` or `google-genai` is installed in the same Python environment running Streamlit |
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
