from __future__ import annotations

import json
import os
import re
import tempfile
from copy import deepcopy
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


def _sanitize_schema_for_gemini(node: Any) -> Any:
    """Adapt JSON Schema for Gemini structured output (union types → anyOf)."""
    if isinstance(node, list):
        return [_sanitize_schema_for_gemini(item) for item in node]
    if not isinstance(node, dict):
        return node

    out: Dict[str, Any] = {}
    for key, value in node.items():
        if key == "type" and isinstance(value, list):
            non_null = [item for item in value if item != "null"]
            if "null" in value:
                if len(non_null) == 1:
                    out["anyOf"] = [{"type": non_null[0]}, {"type": "null"}]
                elif non_null:
                    out["anyOf"] = [{"type": item} for item in non_null] + [{"type": "null"}]
                else:
                    out["type"] = "null"
            else:
                out["type"] = value
            continue
        if key == "enum" and isinstance(value, list):
            out[key] = [item if item is not None else None for item in value]
            continue
        out[key] = _sanitize_schema_for_gemini(value)
    return out


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

    def _response_text_chunks(self, resp) -> list[str]:
        chunks: list[str] = []
        text = getattr(resp, "text", None)
        if isinstance(text, str) and text.strip():
            chunks.append(text)

        for candidate in getattr(resp, "candidates", None) or []:
            content = getattr(candidate, "content", None)
            for part in getattr(content, "parts", None) or []:
                part_text = getattr(part, "text", None)
                if isinstance(part_text, str) and part_text.strip():
                    chunks.append(part_text)

        return chunks

    def _extract_json_from_response(self, resp) -> Dict[str, Any] | None:
        parsed = getattr(resp, "parsed", None)
        if isinstance(parsed, dict):
            return parsed

        for chunk in self._response_text_chunks(resp):
            loaded = self._loads_json_from_text(chunk)
            if loaded is not None:
                return loaded
        return None

    def _describe_response_failure(self, resp) -> str:
        details: list[str] = []
        prompt_feedback = getattr(resp, "prompt_feedback", None)
        if prompt_feedback is not None:
            block_reason = getattr(prompt_feedback, "block_reason", None)
            if block_reason:
                details.append(f"prompt blocked ({block_reason})")

        candidates = getattr(resp, "candidates", None) or []
        if not candidates:
            details.append("no candidates returned")
        for idx, candidate in enumerate(candidates):
            finish_reason = getattr(candidate, "finish_reason", None)
            if finish_reason:
                details.append(f"candidate[{idx}] finish_reason={finish_reason}")
            safety = getattr(candidate, "safety_ratings", None) or []
            blocked = [
                f"{getattr(r, 'category', '?')}={getattr(r, 'probability', '?')}"
                for r in safety
                if str(getattr(r, "probability", "")).upper() in {"HIGH", "MEDIUM"}
            ]
            if blocked:
                details.append(f"candidate[{idx}] safety={', '.join(blocked)}")

        text_preview = " ".join(self._response_text_chunks(resp))
        if text_preview:
            preview = text_preview[:240].replace("\n", " ")
            details.append(f"text preview: {preview!r}")
        else:
            details.append("empty response text")

        return "; ".join(details) if details else "unknown Gemini response failure"

    def _call_json_schema(
        self,
        *,
        model: str,
        schema: Dict[str, Any],
        system_prompt: str,
        user_prompt: str,
        max_output_tokens: int,
    ) -> Dict[str, Any]:
        gemini_schema = _sanitize_schema_for_gemini(deepcopy(schema))
        token_budgets = [max_output_tokens]
        if max_output_tokens < 8192:
            token_budgets.append(8192)

        last_failure = "unknown error"
        for attempt_idx, token_budget in enumerate(token_budgets):
            config = types.GenerateContentConfig(
                temperature=0.2,
                max_output_tokens=token_budget,
                system_instruction=system_prompt,
                response_mime_type="application/json",
                response_json_schema=gemini_schema,
            )
            resp = self.client.models.generate_content(
                model=model,
                contents=user_prompt,
                config=config,
            )
            parsed = self._extract_json_from_response(resp)
            if parsed is not None:
                return parsed
            last_failure = self._describe_response_failure(resp)

            fallback_config = types.GenerateContentConfig(
                temperature=0.2,
                max_output_tokens=token_budget,
                system_instruction=(
                    system_prompt
                    + "\n\nIMPORTANT: Return ONLY a single valid JSON object. "
                    "No numbering, no comments, no markdown, no trailing commas."
                ),
                response_mime_type="application/json",
            )
            resp2 = self.client.models.generate_content(
                model=model,
                contents=user_prompt,
                config=fallback_config,
            )
            parsed2 = self._extract_json_from_response(resp2)
            if parsed2 is not None:
                return parsed2
            last_failure = self._describe_response_failure(resp2)

            if attempt_idx + 1 < len(token_budgets):
                continue

        raise RuntimeError(
            "No JSON returned from Gemini after schema + fallback attempt "
            f"({last_failure})."
        )

    def generate_run_plan(self, *, model: str, user_request: str) -> Dict[str, Any]:
        planner_prompt = PLANNER_PROMPT_PATH.read_text(encoding="utf-8")
        schema = build_run_plan_schema()

        plan = self._call_json_schema(
            model=model,
            schema=schema,
            system_prompt=planner_prompt,
            user_prompt=user_request,
            max_output_tokens=8192,
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
            max_output_tokens=8192,
        )
        return finalize_plan_refinement(
            result,
            current_plan=current_plan,
            conversation_text=conversation_text or user_message,
            data_dir=data_dir,
            preserve_workflow_steps=preserve_workflow_steps,
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
