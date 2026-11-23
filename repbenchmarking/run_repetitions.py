"""Run each benchmark prompt several times and summarize stability.

From the HydroAgent directory:

    python -m repbenchmarking.run_repetitions --self-check
    python -m repbenchmarking.run_repetitions --providers openai --limit 3 --repeats 3
    python -m repbenchmarking.run_repetitions --providers openai,gemini,claude

The 25 prompts and references stay in benchmarking/inputs/. This folder stores
a separate results tree and does not overwrite the one-call benchmark.
"""

from __future__ import annotations

import argparse
import json
import re
import traceback
from datetime import datetime, timezone
from pathlib import Path

from benchmarking.run_evaluation import (
    PROVIDER_ENV,
    _make_provider,
    _provider_ready,
    _write_text,
    evaluate_one,
)
from benchmarking.score import load_prompts, load_references, prompt_dirname, write_json
from server.capabilities.load_catalog import load_catalog
from server.core.plan_rules import default_symfluence_data_dir

from repbenchmarking.protocol import (
    CALL_SETTINGS,
    PAPER_MODELS,
    PROMPTS_PATH,
    REFERENCES_PATH,
    protocol_record,
    sdk_version,
)
from repbenchmarking.report import summarize_repeats

RESULTS_ROOT = Path(__file__).resolve().parent / "results"
IDENTIFICATION = (
    "Repeated-trial evaluation of the same prompts, providers, and reference specifications. "
    "Each prompt is called more than once. This is not the original one-call provider table."
)


def _attempt_labels(raw_text: str) -> list[str]:
    return re.findall(r"^===== ([A-Z0-9_]+) =====$", raw_text, flags=re.MULTILINE)


def _response_model(raw_text: str) -> str | None:
    match = re.search(r"^===== SCHEMA_CALL =====\n(.*?)(?:\n===== |\Z)", raw_text, flags=re.DOTALL)
    if not match:
        return None
    body = match.group(1).strip()
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return None
    model = payload.get("model") if isinstance(payload, dict) else None
    return str(model) if model else None


def _new_run_dir(explicit: Path | None) -> Path:
    if explicit is not None:
        if explicit.exists():
            raise SystemExit(f"Refusing to overwrite existing evaluation directory: {explicit}")
        explicit.mkdir(parents=True)
        return explicit
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = RESULTS_ROOT / f"repeat_{stamp}"
    run_dir.mkdir(parents=True)
    return run_dir


def _call_metadata(
    *,
    provider: str,
    prompt: dict,
    repeat: int,
    repeats: int,
    out_dir: Path,
    score: dict | None,
    error: str | None,
) -> dict:
    settings = CALL_SETTINGS[provider]
    raw_path = out_dir / "raw_response.txt"
    raw_text = raw_path.read_text(encoding="utf-8") if raw_path.is_file() else ""
    labels = _attempt_labels(raw_text)
    protocol = protocol_record()
    return {
        "provider": provider,
        "requested_model": settings["requested_model"],
        "response_model": _response_model(raw_text),
        "sdk_version": sdk_version(provider),
        "repeat_index": repeat,
        "repeats": repeats,
        "prompt_id": prompt["id"],
        "temperature": settings["temperature"],
        "sampling": settings["sampling"],
        "structured_output": settings["structured_output"],
        "max_output_tokens": settings["max_output_tokens"],
        "prompt_sha256": protocol["inputs"]["prompts_sha256"],
        "reference_sha256": protocol["inputs"]["references_sha256"],
        "planner_prompt_sha256": protocol["inputs"]["planner_prompt_sha256"],
        "attempts": labels,
        "fallback_used": "FALLBACK_CALL" in labels,
        "completed": error is None and score is not None,
        "error": error,
        "exact_plan_match": None if not score else score.get("exact_plan_match"),
        "final_score": score,
    }


def run_repetitions(
    *,
    providers: list[str],
    repeats: int,
    limit: int | None,
    out_dir: Path | None,
    prompts_path: Path = PROMPTS_PATH,
    references_path: Path = REFERENCES_PATH,
) -> Path:
    if repeats < 1:
        raise SystemExit("--repeats must be at least 1.")
    prompts = load_prompts(prompts_path)
    if limit is not None:
        if limit < 1:
            raise SystemExit("--limit must be at least 1.")
        prompts = prompts[:limit]
    if not prompts:
        raise SystemExit(f"No prompts found in {prompts_path}.")
    references = load_references(references_path)
    missing_keys = [name for name in providers if not _provider_ready(name)]
    if missing_keys:
        needed = ", ".join(f"{name}: {' or '.join(PROVIDER_ENV[name])}" for name in missing_keys)
        raise SystemExit(f"Missing API key for {needed}.")

    run_dir = _new_run_dir(out_dir)
    write_json(run_dir / "protocol.json", protocol_record())
    catalog = load_catalog()
    data_dir = default_symfluence_data_dir()
    clients = {name: _make_provider(name) for name in providers}
    rows: list[dict] = []

    for prompt in prompts:
        reference = references.get(prompt["id"])
        for name in providers:
            for repeat in range(1, repeats + 1):
                dest = run_dir / name / prompt_dirname(prompt["id"]) / f"run_{repeat:02d}"
                score = None
                error = None
                try:
                    score = evaluate_one(
                        provider_name=name,
                        provider=clients[name],
                        model=PAPER_MODELS[name],
                        prompt=prompt,
                        out_dir=dest,
                        catalog=catalog,
                        data_dir=data_dir,
                        reference=reference,
                    )
                    print(f"saved {name} {prompt['id']} repeat {repeat}")
                except Exception as exc:
                    error = str(exc)
                    if not (dest / "error.txt").is_file():
                        dest.mkdir(parents=True, exist_ok=True)
                        _write_text(dest / "error.txt", traceback.format_exc())
                    print(f"failed {name} {prompt['id']} repeat {repeat}: {exc}")
                metadata = _call_metadata(
                    provider=name,
                    prompt=prompt,
                    repeat=repeat,
                    repeats=repeats,
                    out_dir=dest,
                    score=score,
                    error=error,
                )
                write_json(dest / "call_metadata.json", metadata)
                rows.append(
                    {
                        "provider": name,
                        "prompt_id": prompt["id"],
                        "repeat": repeat,
                        "completed": metadata["completed"],
                        "exact_plan_match": metadata["exact_plan_match"],
                    }
                )

    summary = summarize_repeats(rows)
    summary["identification"] = IDENTIFICATION
    summary["run_dir"] = str(run_dir)
    summary["repeats"] = repeats
    summary["models"] = {name: PAPER_MODELS[name] for name in providers}
    write_json(run_dir / "summary.json", summary)
    print(f"summary: {run_dir / 'summary.json'}")
    return run_dir


def self_check() -> None:
    rows = [
        {"provider": "openai", "prompt_id": "001", "repeat": 1, "completed": True, "exact_plan_match": True},
        {"provider": "openai", "prompt_id": "002", "repeat": 1, "completed": True, "exact_plan_match": True},
        {"provider": "openai", "prompt_id": "001", "repeat": 2, "completed": True, "exact_plan_match": True},
        {"provider": "openai", "prompt_id": "002", "repeat": 2, "completed": True, "exact_plan_match": False},
        {"provider": "openai", "prompt_id": "001", "repeat": 3, "completed": True, "exact_plan_match": False},
        {"provider": "openai", "prompt_id": "002", "repeat": 3, "completed": True, "exact_plan_match": False},
        {"provider": "gemini", "prompt_id": "001", "repeat": 1, "completed": True, "exact_plan_match": True},
        {"provider": "gemini", "prompt_id": "002", "repeat": 1, "completed": True, "exact_plan_match": False},
        {"provider": "gemini", "prompt_id": "001", "repeat": 2, "completed": False, "exact_plan_match": None},
        {"provider": "gemini", "prompt_id": "002", "repeat": 2, "completed": True, "exact_plan_match": False},
    ]
    summary = summarize_repeats(rows)
    openai = summary["providers"]["openai"]
    if openai["exact_match_rate_by_repeat"] != [1.0, 0.5, 0.0]:
        raise SystemExit(f"unexpected replicate rates: {openai}")
    if openai["exact_match_rate_mean"] != 0.5:
        raise SystemExit(f"unexpected mean: {openai}")
    if openai["exact_match_rate_std"] is None or abs(openai["exact_match_rate_std"] - 0.5) > 1e-9:
        raise SystemExit(f"unexpected std: {openai}")
    varied = {item["prompt_id"]: item["varied"] for item in openai["per_prompt"]}
    if varied != {"001": True, "002": True}:
        raise SystemExit(f"unexpected per-prompt variation: {varied}")
    if openai["n_failed_calls"] != 0:
        raise SystemExit(openai)
    gemini = summary["providers"]["gemini"]
    if gemini["n_failed_calls"] != 1 or gemini["n_completed_calls"] != 3:
        raise SystemExit(gemini)
    if not summary["provider_differences"]:
        raise SystemExit("expected a provider comparison")
    protocol = protocol_record()
    if protocol["inputs"]["prompts_sha256"] is None or protocol["inputs"]["references_sha256"] is None:
        raise SystemExit("prompt or reference file is missing")
    print("self-check ok")
    print(f"example openai mean exact-match rate: {openai['exact_match_rate_mean']}")
    print(f"example openai sample std: {openai['exact_match_rate_std']}")
    print(f"prompts sha256: {protocol['inputs']['prompts_sha256']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Repeat the planning benchmark and summarize stability.")
    parser.add_argument("--providers", default="openai,gemini,claude")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--limit", type=int, default=None, help="Use only the first N prompts.")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args()
    if args.self_check:
        self_check()
        return
    providers = [name.strip() for name in args.providers.split(",") if name.strip()]
    unknown = [name for name in providers if name not in PAPER_MODELS]
    if unknown:
        raise SystemExit(f"Unknown providers: {', '.join(unknown)}")
    run_repetitions(providers=providers, repeats=args.repeats, limit=args.limit, out_dir=args.out)


if __name__ == "__main__":
    main()
