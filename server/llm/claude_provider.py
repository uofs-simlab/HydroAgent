from __future__ import annotations

import json
import os
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Tuple

from anthropic import Anthropic

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


def _model_supports_temperature(model: str) -> bool:
    """Newer Claude models reject non-default sampling parameters."""
    model_id = (model or "").lower()
    deprecated_sampling_markers = (
        "claude-sonnet-5",
        "claude-fable-5",
        "claude-opus-4-7",
        "claude-opus-4-8",
    )
    return not any(marker in model_id for marker in deprecated_sampling_markers)


def _model_prefers_thinking_disabled(model: str) -> bool:
    """Adaptive thinking is on by default on newer models and can exhaust output budget."""
    model_id = (model or "").lower()
    adaptive_thinking_markers = (
        "claude-sonnet-5",
        "claude-fable-5",
        "claude-opus-4-7",
        "claude-opus-4-8",
    )
    return any(marker in model_id for marker in adaptive_thinking_markers)


def _sanitize_json_schema(node: Any) -> Any:
    """Adapt JSON Schema for Anthropic structured output (union types → anyOf)."""
    if isinstance(node, list):
        return [_sanitize_json_schema(item) for item in node]
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
        out[key] = _sanitize_json_schema(value)
    return out


class ClaudeProvider:
    def __init__(self, api_key: str | None = None):
        api_key = api_key or os.getenv("ANTHROPIC_API_KEY") or os.getenv("CLAUDE_API_KEY")
        if not api_key:
            raise RuntimeError("Missing ANTHROPIC_API_KEY or CLAUDE_API_KEY")
        self.client = Anthropic(api_key=api_key)

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

    def _response_text_chunks(self, response) -> list[str]:
        chunks: list[str] = []
        for block in getattr(response, "content", []) or []:
            if getattr(block, "type", None) == "text":
                text = getattr(block, "text", "") or ""
                if isinstance(text, str) and text.strip():
                    chunks.append(text)
        return chunks

    def _extract_json_from_response(self, response) -> Dict[str, Any] | None:
        parsed_output = getattr(response, "parsed_output", None)
        if isinstance(parsed_output, dict):
            return parsed_output

        for block in getattr(response, "content", []) or []:
            block_parsed = getattr(block, "parsed_output", None)
            if isinstance(block_parsed, dict):
                return block_parsed

        for chunk in self._response_text_chunks(response):
            loaded = self._loads_json_from_text(chunk)
            if loaded is not None:
                return loaded
        return None

    def _describe_response_failure(self, response) -> str:
        details: list[str] = []
        stop_reason = getattr(response, "stop_reason", None)
        if stop_reason:
            details.append(f"stop_reason={stop_reason}")

        blocks = getattr(response, "content", []) or []
        if not blocks:
            details.append("no content blocks")
        else:
            block_types = [getattr(block, "type", "?") for block in blocks]
            details.append(f"content_types={','.join(block_types)}")

        text_preview = " ".join(self._response_text_chunks(response))
        if text_preview:
            preview = text_preview[:240].replace("\n", " ")
            details.append(f"text preview: {preview!r}")
        else:
            details.append("empty response text")

        return "; ".join(details)

    def _base_message_kwargs(
        self,
        *,
        model: str,
        max_output_tokens: int,
        system_prompt: str,
        user_prompt: str,
    ) -> Dict[str, Any]:
        kwargs: Dict[str, Any] = {
            "model": model,
            "max_tokens": max_output_tokens,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
        }
        if _model_supports_temperature(model):
            kwargs["temperature"] = 0.2
        if _model_prefers_thinking_disabled(model):
            kwargs["thinking"] = {"type": "disabled"}
        return kwargs

    def _call_json_schema(
        self,
        *,
        model: str,
        schema: Dict[str, Any],
        system_prompt: str,
        user_prompt: str,
        max_output_tokens: int,
    ) -> Dict[str, Any]:
        claude_schema = _sanitize_json_schema(deepcopy(schema))
        token_budgets = [max_output_tokens]
        if max_output_tokens < 8192:
            token_budgets.append(8192)

        last_failure = "unknown error"
        fallback_system = (
            system_prompt
            + "\n\nIMPORTANT: Return ONLY a single valid JSON object. "
            "No numbering, no comments, no markdown, no trailing commas."
        )

        for attempt_idx, token_budget in enumerate(token_budgets):
            create_kwargs = self._base_message_kwargs(
                model=model,
                max_output_tokens=token_budget,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )

            try:
                response = self.client.messages.create(
                    **create_kwargs,
                    output_config={
                        "format": {
                            "type": "json_schema",
                            "schema": claude_schema,
                        }
                    },
                )
                parsed = self._extract_json_from_response(response)
                if parsed is not None:
                    return parsed
                last_failure = self._describe_response_failure(response)
            except TypeError as exc:
                last_failure = f"structured output unsupported: {exc}"
            except Exception as exc:
                last_failure = f"structured output error: {type(exc).__name__}: {exc}"

            response2 = self.client.messages.create(
                **self._base_message_kwargs(
                    model=model,
                    max_output_tokens=token_budget,
                    system_prompt=fallback_system,
                    user_prompt=user_prompt,
                ),
            )
            parsed2 = self._extract_json_from_response(response2)
            if parsed2 is not None:
                return parsed2
            last_failure = self._describe_response_failure(response2)

            if attempt_idx + 1 < len(token_budgets):
                continue

        raise RuntimeError(
            "No JSON returned from Claude after schema + fallback attempt "
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
    ) -> Tuple[str, Dict[str, Any], bool]:
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
