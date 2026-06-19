from __future__ import annotations

import io
import os
import json
from pathlib import Path
from typing import Any, Dict
import re

from openai import OpenAI

from server.llm.plan_shared import (
    PLANNER_PROMPT_PATH,
    PLAN_REFINEMENT_PROMPT_PATH,
    _extract_bounding_box,
    _extract_hydrological_model,
    build_plan_refinement_schema,
    build_plan_refinement_user_prompt,
    build_run_plan_schema,
    finalize_plan_refinement,
    finalize_run_plan,
)


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
            "Extract hydrological_model using SYMFLUENCE registry names (e.g. SUMMA, FUSE, GR, NGEN, MESH, HYPE).\n"
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
        planner_prompt = PLANNER_PROMPT_PATH.read_text(encoding="utf-8")
        schema = build_run_plan_schema()

        plan = self._call_json_schema(
            model=model,
            name="symfluence_run_plan",
            schema=schema,
            system_prompt=planner_prompt,
            user_prompt=user_request,
            max_output_tokens=2500,
        )
        return finalize_run_plan(plan, user_request)

    def refine_run_plan(
        self,
        *,
        model: str,
        user_message: str,
        current_plan: Dict[str, Any],
        conversation_text: str = "",
        context_text: str = "",
        data_dir: Path | None = None,
        preserve_workflow_steps: bool = False,
    ) -> tuple[str, Dict[str, Any], bool]:
        refinement_prompt = PLAN_REFINEMENT_PROMPT_PATH.read_text(encoding="utf-8")
        schema = build_plan_refinement_schema()
        user_prompt = build_plan_refinement_user_prompt(
            current_plan=current_plan,
            user_message=user_message,
            conversation_excerpt=conversation_text,
            context_excerpt=context_text,
        )
        result = self._call_json_schema(
            model=model,
            name="symfluence_plan_refinement",
            schema=schema,
            system_prompt=refinement_prompt,
            user_prompt=user_prompt,
            max_output_tokens=3000,
        )
        return finalize_plan_refinement(
            result,
            current_plan=current_plan,
            conversation_text=conversation_text or user_message,
            data_dir=data_dir,
            preserve_workflow_steps=preserve_workflow_steps,
        )