from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Dict

from google import genai
from google.genai import types

from server.llm.plan_shared import (
    PLANNER_PROMPT_PATH,
    PLAN_REFINEMENT_PROMPT_PATH,
    build_plan_refinement_schema,
    build_plan_refinement_user_prompt,
    build_run_plan_schema,
    finalize_plan_refinement,
    finalize_run_plan,
    _extract_bounding_box,
    _extract_hydrological_model,
)


class GeminiProvider:
    def __init__(self, api_key: str | None = None):
        api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise RuntimeError("Missing GEMINI_API_KEY or GOOGLE_API_KEY")
        self.client = genai.Client(api_key=api_key)

    def _loads_json_from_text(self, text: str) -> Dict[str, Any] | None:
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

    def _call_json_schema(
        self,
        *,
        model: str,
        schema: Dict[str, Any],
        system_prompt: str,
        user_prompt: str,
        max_output_tokens: int,
    ) -> Dict[str, Any]:
        contents = [
            types.Content(
                role="user",
                parts=[types.Part(text=f"{system_prompt}\n\nUser request:\n{user_prompt}")],
            )
        ]
        config = types.GenerateContentConfig(
            temperature=0.2,
            max_output_tokens=max_output_tokens,
            response_mime_type="application/json",
            response_json_schema=schema,
        )

        resp = self.client.models.generate_content(
            model=model,
            contents=contents,
            config=config,
        )
        parsed = self._loads_json_from_text(getattr(resp, "text", "") or "")
        if parsed is not None:
            return parsed

        fallback_prompt = (
            f"{system_prompt}\n\n"
            "IMPORTANT: Return ONLY a single valid JSON object. "
            "No numbering, no comments, no markdown, no trailing commas.\n\n"
            f"User request:\n{user_prompt}"
        )
        resp2 = self.client.models.generate_content(
            model=model,
            contents=fallback_prompt,
            config=types.GenerateContentConfig(
                temperature=0.2,
                max_output_tokens=max_output_tokens,
                response_mime_type="application/json",
            ),
        )
        parsed2 = self._loads_json_from_text(getattr(resp2, "text", "") or "")
        if parsed2 is not None:
            return parsed2

        raise RuntimeError("No JSON returned from Gemini after schema + fallback attempt.")

    def generate_run_plan(self, *, model: str, user_request: str) -> Dict[str, Any]:
        planner_prompt = PLANNER_PROMPT_PATH.read_text(encoding="utf-8")
        schema = build_run_plan_schema()

        plan = self._call_json_schema(
            model=model,
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
    ) -> tuple[str, dict[str, Any], bool]:
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
        )

    def generate_config_spec(self, *, model: str, user_request: str) -> Dict[str, Any]:
        schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "domain_name": {"type": ["string", "null"]},
                "experiment_id": {"type": ["string", "null"]},
                "pour_point_coords": {"type": ["string", "null"]},
                "bounding_box_coords": {"type": ["string", "null"]},
                "hydrological_model": {
                    "type": ["string", "null"],
                },
                "domain_def": {
                    "type": ["string", "null"],
                    "enum": ["lumped", "point", "subset", "delineate", None],
                },
                "experiment_time_start": {"type": ["string", "null"]},
                "experiment_time_end": {"type": ["string", "null"]},
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

    def transcribe_audio(
        self,
        *,
        audio_bytes: bytes,
        filename: str = "recording.webm",
        model: str = "gemini-2.5-flash",
    ) -> str:
        """Speech-to-text via Gemini multimodal audio understanding."""
        suffix = Path(filename).suffix or ".webm"
        tmp_path = ""
        try:
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(audio_bytes)
                tmp_path = tmp.name
            audio_file = self.client.files.upload(file=tmp_path)
            response = self.client.models.generate_content(
                model=model,
                contents=[
                    "Transcribe this audio accurately. Return only the spoken words, no commentary.",
                    audio_file,
                ],
            )
            text = getattr(response, "text", None) or ""
            return text.strip()
        finally:
            if tmp_path:
                Path(tmp_path).unlink(missing_ok=True)
