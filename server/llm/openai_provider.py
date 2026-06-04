from __future__ import annotations

import io
import os
import json
from typing import Any, Dict, List
import re
from pathlib import Path

from openai import OpenAI

from server.core.plan_rules import (
    WORKFLOW_STEP_NAMES,
    extract_steps_from_request,
    normalize_local_workflow_plan,
    plan_requires_bounding_box,
    plan_uses_local_data,
)


def _normalize_domain_name_for_config(name: str | None):
    if not name:
        return None
    name = re.sub(r"\s+", "_", name.strip())
    name = re.sub(r"[^A-Za-z0-9_\-]", "", name)
    return name


def _extract_domain_name(text: str):
    if not text:
        return None

    text = text.strip()

    m = re.search(
        r"for\s+([A-Za-z0-9_\-\s]+?)(?:\s+at|\s+from|\s+with|\s+using|$)",
        text,
        re.IGNORECASE,
    )
    if m:
        return m.group(1).strip()

    m = re.search(r"run\s+(?:summa|fuse|gr|hbv|mesh|hype|ngen|topmodel)?\s+for\s+([A-Za-z0-9_\-\s]+)", text, re.IGNORECASE)
    if m:
        return m.group(1).strip()

    return None

def _compact_plan_config(cfg: dict) -> dict:
    """
    Keep required core fields, but remove optional fields whose value is None.
    This keeps OpenAI's strict schema valid while keeping the displayed plan clean.
    """
    core_keys = {
        "domain_name",
        "experiment_id",
        "pour_point_coords",
        "bounding_box_coords",
        "hydrological_model",
        "domain_def",
        "experiment_time_start",
        "experiment_time_end",
    }

    compact = {}

    for k, v in cfg.items():
        if k in core_keys:
            compact[k] = v
        elif v is not None:
            compact[k] = v

    return compact

def _extract_hydrological_model(text: str) -> str | None:
    if not text:
        return None

    model_map = {
        "SUMMA": "SUMMA",
        "FUSE": "FUSE",
        "GR": "GR",
        "HBV": "HBV",
        "MESH": "MESH",
        "HYPE": "HYPE",
        "NGEN": "ngen",
        "NGEN.": "ngen",
        "TOPMODEL": "TOPMODEL",
    }

    upper = text.upper()
    for key, value in model_map.items():
        if re.search(rf"\b{re.escape(key)}\b", upper):
            return value

    return None


def _extract_bounding_box(text: str) -> str | None:
    if not text:
        return None

    # Looks for four slash-separated numbers, usually north/west/south/east.
    m = re.search(
        r"(-?\d+(?:\.\d+)?)\s*/\s*(-?\d+(?:\.\d+)?)\s*/\s*(-?\d+(?:\.\d+)?)\s*/\s*(-?\d+(?:\.\d+)?)",
        text,
    )
    if m:
        return "/".join(x.strip() for x in m.groups())

    return None


PLANNER_PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "planner_prompt.txt"


class OpenAIProvider:
    def __init__(self, api_key: str | None = None):
        api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("Missing OPENAI_API_KEY")
        self.client = OpenAI(api_key=api_key)

    def _call_json_schema(
        self,
        *,
        model: str,
        name: str,
        schema: Dict[str, Any],
        system_prompt: str,
        user_prompt: str,
        max_output_tokens: int,
    ) -> Dict[str, Any]:

        def _loads_json_from_text(text: str) -> Dict[str, Any] | None:
            text = (text or "").strip()
            if not text:
                return None

            try:
                return json.loads(text)
            except Exception:
                pass

            m = re.search(r"\{.*\}", text, flags=re.DOTALL)
            if not m:
                return None
            try:
                return json.loads(m.group(0))
            except Exception:
                return None

        def _extract_json(resp) -> Dict[str, Any] | None:
            d = resp.model_dump() if hasattr(resp, "model_dump") else {}

            for item in d.get("output", []) or []:
                for part in item.get("content", []) or []:
                    if part.get("type") == "output_json" and part.get("json") is not None:
                        return part["json"]

            chunks: list[str] = []
            for item in d.get("output", []) or []:
                for part in item.get("content", []) or []:
                    if part.get("type") in ("output_text", "text"):
                        t = part.get("text", "")
                        if isinstance(t, str):
                            chunks.append(t)
                        elif isinstance(t, dict) and "value" in t and isinstance(t["value"], str):
                            chunks.append(t["value"])

            joined = "".join(chunks).strip()
            parsed_joined = _loads_json_from_text(joined)
            if parsed_joined is not None:
                return parsed_joined

            ot = d.get("output_text")
            if isinstance(ot, str) and ot.strip():
                parsed_ot = _loads_json_from_text(ot)
                if parsed_ot is not None:
                    return parsed_ot

            return None

        payload: Dict[str, Any] = {
            "model": model,
            "input": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "text": {"format": {"type": "json_schema", "name": name, "schema": schema}},
            "max_output_tokens": max_output_tokens,
            "reasoning": {"effort": "low"},
        }

        if not model.startswith("gpt-5"):
            payload["temperature"] = 0.2

        resp = self.client.responses.create(**payload)
        parsed = _extract_json(resp)
        if parsed is not None:
            return parsed

        fallback_system = (
            system_prompt
            + "\n\nIMPORTANT: Return ONLY a single valid JSON object. "
            "No numbering, no comments, no markdown, no trailing commas."
        )

        payload2: Dict[str, Any] = {
            "model": model,
            "input": [
                {"role": "system", "content": fallback_system},
                {"role": "user", "content": user_prompt},
            ],
            "max_output_tokens": max_output_tokens,
            "reasoning": {"effort": "low"},
        }

        if not model.startswith("gpt-5"):
            payload2["temperature"] = 0.2

        resp2 = self.client.responses.create(**payload2)
        parsed2 = _extract_json(resp2)
        if parsed2 is not None:
            return parsed2

        d2 = resp2.model_dump() if hasattr(resp2, "model_dump") else {}
        debug = json.dumps(d2, indent=2)[:3000]
        raise RuntimeError(
            "No JSON returned from OpenAI after schema + fallback attempt.\n"
            f"Debug truncated:\n{debug}"
        )

    def generate_config_spec(self, *, model: str, user_request: str) -> Dict[str, Any]:
        schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "domain_name": {"type": ["string", "null"]},
                "experiment_id": {"type": ["string", "null"]},
                "pour_point_coords": {"type": ["string", "null"], "description": "lat/lon like 51.35/-116.02"},
                "bounding_box_coords": {"type": ["string", "null"], "description": "north/west/south/east"},
                "hydrological_model": {
                    "type": ["string", "null"],
                    "enum": ["SUMMA", "FUSE", "GR", "HBV", "MESH", "HYPE", "ngen", "TOPMODEL", None],
                },
                "domain_def": {"type": ["string", "null"], "enum": ["lumped", "point", "subset", "delineate", None]},
                "experiment_time_start": {"type": ["string", "null"], "description": "YYYY-MM-DD HH:MM"},
                "experiment_time_end": {"type": ["string", "null"], "description": "YYYY-MM-DD HH:MM"},
            },
            "required": [
                "domain_name",
                "experiment_id",
                "pour_point_coords",
                "bounding_box_coords",
                "hydrological_model",
                "domain_def",
                "experiment_time_start",
                "experiment_time_end",
            ],
        }

        system_prompt = (
            "You are a hydrology workflow assistant for SYMFLUENCE.\n"
            "Return ONLY JSON that strictly matches the schema.\n"
            "Extract hydrological_model if user mentions SUMMA, FUSE, GR, HBV, MESH, HYPE, ngen, or TOPMODEL.\n"
            "Extract bounding_box_coords if user provides bounding box, bbox, or north/west/south/east values.\n"
            "If times are missing, choose 01:00 for start and 23:00 for end."
        )

        spec = self._call_json_schema(
            model=model,
            name="symfluence_config_spec",
            schema=schema,
            system_prompt=system_prompt,
            user_prompt=user_request,
            max_output_tokens=1200,
        )

        if not spec.get("hydrological_model"):
            spec["hydrological_model"] = _extract_hydrological_model(user_request) or "SUMMA"

        if not spec.get("bounding_box_coords"):
            spec["bounding_box_coords"] = _extract_bounding_box(user_request)

        return spec

    def transcribe_audio(self, *, audio_bytes: bytes, filename: str = "recording.webm") -> str:
        """Speech-to-text via OpenAI Whisper (whisper-1)."""
        buf = io.BytesIO(audio_bytes)
        buf.name = filename
        result = self.client.audio.transcriptions.create(
            model="whisper-1",
            file=buf,
        )
        text = getattr(result, "text", None) or ""
        return text.strip()

    def generate_run_plan(self, *, model: str, user_request: str) -> Dict[str, Any]:
        allowed_steps: List[str] = [
            "validate_config",
            "setup_project",
            "create_pour_point",
            "acquire_attributes",
            "define_domain",
            "discretize_domain",
            "process_observed_data",
            "acquire_forcings",
            "model_agnostic_preprocessing",
            "build_model_ready_store",
            "model_specific_preprocessing",
            "run_model",
            "calibrate_model",
            "run_emulation",
            "run_benchmarking",
            "run_decision_analysis",
            "run_sensitivity_analysis",
            "postprocess_results",
            "dry_run",
        ]

        planner_prompt = PLANNER_PROMPT_PATH.read_text(encoding="utf-8")

        schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "config": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        # Core domain / experiment
                        "domain_name": {"type": ["string", "null"]},
                        "experiment_id": {"type": ["string", "null"]},
                        "pour_point_coords": {"type": ["string", "null"]},
                        "bounding_box_coords": {"type": ["string", "null"]},

                        "hydrological_model": {
                            "type": ["string", "null"],
                            "enum": ["SUMMA", "FUSE", "GR", "HBV", "MESH", "HYPE", "ngen", "TOPMODEL", None],
                        },
                        "domain_def": {
                            "type": ["string", "null"],
                            "enum": ["lumped", "point", "subset", "delineate", None],
                        },

                        # Time
                        "experiment_time_start": {"type": ["string", "null"]},
                        "experiment_time_end": {"type": ["string", "null"]},
                        "spinup_period": {"type": ["string", "null"]},
                        "calibration_period": {"type": ["string", "null"]},
                        "evaluation_period": {"type": ["string", "null"]},

                        # Model setup
                        "forcing_dataset": {"type": ["string", "null"]},
                        "discretization": {"type": ["string", "null"]},
                        "routing_model": {"type": ["string", "null"]},

                        # Observations / SNOTEL
                        "DOWNLOAD_SNOTEL": {"type": ["boolean", "null"]},
                        "SNOTEL_STATION": {"type": ["string", "null"]},
                        "observations_path": {"type": ["string", "null"]},

                        # Calibration / optimization
                        "optimization_target": {"type": ["string", "null"]},
                        "optimization_metric": {"type": ["string", "null"]},
                        "calibration_timestep": {"type": ["string", "null"]},
                        "iterative_optimization_algorithm": {"type": ["string", "null"]},
                        "iterations": {"type": ["integer", "null"]},
                        "POPULATION_SIZE": {"type": ["integer", "null"]},
                        "params_to_calibrate": {"type": ["string", "null"]},

                        # Compute
                        "NUM_PROCESSES": {"type": ["integer", "null"]},
                        "MPI_PROCESSES": {"type": ["integer", "null"]},

                        # Advanced / uncommon SYMFLUENCE YAML parameters
                        "extra_config": {
                            "type": ["object", "null"],
                            "additionalProperties": {
                                "type": ["string", "number", "integer", "boolean", "null"]
                            },
                            "description": "Explicit SYMFLUENCE YAML parameters from the user that are not first-class config fields.",
                        },
                    },
                    "required": [
                        "domain_name",
                        "experiment_id",
                        "pour_point_coords",
                        "bounding_box_coords",
                        "hydrological_model",
                        "domain_def",
                        "experiment_time_start",
                        "experiment_time_end",
                        "spinup_period",
                        "calibration_period",
                        "evaluation_period",
                        "forcing_dataset",
                        "discretization",
                        "routing_model",
                        "DOWNLOAD_SNOTEL",
                        "SNOTEL_STATION",
                        "observations_path",
                        "optimization_target",
                        "optimization_metric",
                        "calibration_timestep",
                        "iterative_optimization_algorithm",
                        "iterations",
                        "POPULATION_SIZE",
                        "params_to_calibrate",
                        "NUM_PROCESSES",
                        "MPI_PROCESSES",
                        "extra_config",
                    ],
                },
                "steps": {
                    "type": "array",
                    "items": {"type": "string", "enum": allowed_steps},
                    "minItems": 1,
                },
                "needs_user_input": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": [
                            "domain_name",
                            "experiment_id",
                            "pour_point_coords",
                            "bounding_box_coords",
                            "hydrological_model",
                            "domain_def",
                            "forcing_dataset",
                            "discretization",
                            "experiment_time_start",
                            "experiment_time_end",
                            "spinup_period",
                            "calibration_period",
                            "evaluation_period",
                            "SNOTEL_STATION",
                        ],
                    },
                },
                "notes": {"type": "string"},
            },
            "required": ["config", "steps", "needs_user_input", "notes"],
        }

        plan = self._call_json_schema(
            model=model,
            name="symfluence_run_plan",
            schema=schema,
            system_prompt=planner_prompt,
            user_prompt=user_request,
            max_output_tokens=2500,
        )

        cfg = plan.get("config", {}) or {}

        if cfg.get("extra_config") is not None and not isinstance(cfg.get("extra_config"), dict):
            cfg["extra_config"] = None

        p = cfg.get("pour_point_coords")
        if isinstance(p, str):
            cfg["pour_point_coords"] = p.replace(",", "/").strip()

        bbox = cfg.get("bounding_box_coords")
        if isinstance(bbox, str):
            cfg["bounding_box_coords"] = bbox.replace(",", "/").strip()

        if not cfg.get("bounding_box_coords"):
            cfg["bounding_box_coords"] = _extract_bounding_box(user_request)

        if not cfg.get("hydrological_model"):
            cfg["hydrological_model"] = _extract_hydrological_model(user_request) or "SUMMA"
        else:
            hm = str(cfg["hydrological_model"]).strip()
            cfg["hydrological_model"] = "ngen" if hm.lower() == "ngen" else hm.upper()

        start = cfg.get("experiment_time_start")
        if isinstance(start, str) and len(start.strip()) == 10:
            cfg["experiment_time_start"] = start.strip() + " 01:00"

        end = cfg.get("experiment_time_end")
        if isinstance(end, str) and len(end.strip()) == 10:
            cfg["experiment_time_end"] = end.strip() + " 23:00"

        if not cfg.get("experiment_id"):
            cfg["experiment_id"] = "exp_001"

        if not cfg.get("domain_def"):
            cfg["domain_def"] = "delineate"

        if not cfg.get("domain_name"):
            extracted = _extract_domain_name(user_request)
            if extracted:
                cfg["domain_name"] = extracted.strip()

        if cfg.get("domain_name"):
            cfg["domain_name"] = _normalize_domain_name_for_config(cfg["domain_name"])

        required_user_fields = [
            "domain_name",
            "hydrological_model",
            "pour_point_coords",
            "experiment_time_start",
            "experiment_time_end",
        ]

        steps_now = plan.get("steps", []) or []
        if plan_requires_bounding_box(cfg, steps_now, user_request):
            required_user_fields.append("bounding_box_coords")

        missing = [f for f in required_user_fields if not cfg.get(f)]

        if missing:
            plan["needs_user_input"] = missing
            plan["steps"] = ["validate_config", "dry_run"]
            plan["notes"] = (
                f"Missing required inputs: {', '.join(missing)}. "
                "Returning a safe validation/dry-run plan until those values are provided."
            )

        plan = normalize_local_workflow_plan(plan, user_request)

        preferred_order = [
            "validate_config",
            "setup_project",
            "create_pour_point",
            "acquire_attributes",
            "define_domain",
            "discretize_domain",
            "process_observed_data",
            "acquire_forcings",
            "model_agnostic_preprocessing",
            "build_model_ready_store",
            "model_specific_preprocessing",
            "run_model",
            "calibrate_model",
            "run_emulation",
            "run_benchmarking",
            "run_decision_analysis",
            "run_sensitivity_analysis",
            "postprocess_results",
            "dry_run",
        ]

        current_steps = plan.get("steps", []) or []
        ordered_steps = [step for step in preferred_order if step in current_steps]
        if ordered_steps:
            plan["steps"] = ordered_steps

        extracted_fields = []
        for k in [
            "domain_name",
            "experiment_id",
            "hydrological_model",
            "pour_point_coords",
            "bounding_box_coords",
            "experiment_time_start",
            "experiment_time_end",
        ]:
            if cfg.get(k):
                extracted_fields.append(k)

        if extracted_fields:
            base_notes = plan.get("notes", "").strip()
            extra = f"Extracted fields: {', '.join(extracted_fields)}"
            plan["notes"] = f"{base_notes} | {extra}" if base_notes else extra

        plan["config"] = _compact_plan_config(cfg)
        return plan