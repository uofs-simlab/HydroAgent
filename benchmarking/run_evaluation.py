"""Run the five-stage planning evaluation.

From the HydroAgent directory:

    python -m benchmarking.run_evaluation --self-check
    python -m benchmarking.run_evaluation --providers openai,gemini,claude

Put the 25 requests in benchmarking/inputs/prompts.json and the manual
reference plans in benchmarking/inputs/references.json. Each run writes a new
directory under benchmarking/results/ and leaves earlier runs untouched.

This calls the provider adapters directly. It does not prepend LangPrompt
examples and it does not apply Streamlit session overrides before config.yaml.
"""

from __future__ import annotations

import argparse
import os
import traceback
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from server.capabilities.load_catalog import load_catalog
from server.core.plan_rules import default_symfluence_data_dir, resolve_plan_step_dependencies
from server.llm.plan_shared import finalize_run_plan
from server.llm.stage_capture import capture_stages

from benchmarking.config_stage import write_executable_config
from benchmarking.score import (
    IDENTIFICATION,
    PAPER_MODELS,
    load_prompts,
    load_references,
    prompt_dirname,
    rescore_run,
    score_prompt,
    write_json,
)

BENCHMARK_ROOT = Path(__file__).resolve().parent
DEFAULT_PROMPTS = BENCHMARK_ROOT / "inputs" / "prompts.json"
DEFAULT_REFERENCES = BENCHMARK_ROOT / "inputs" / "references.json"
RESULTS_ROOT = BENCHMARK_ROOT / "results"

PROVIDER_ENV = {
    "openai": ("OPENAI_API_KEY",),
    "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    "claude": ("ANTHROPIC_API_KEY", "CLAUDE_API_KEY"),
}


def _provider_ready(name: str) -> bool:
    return any(os.getenv(key) for key in PROVIDER_ENV[name])


def _make_provider(name: str):
    if name == "openai":
        from server.llm.openai_provider import OpenAIProvider

        return OpenAIProvider()
    if name == "gemini":
        from server.llm.gemini_provider import GeminiProvider

        return GeminiProvider()
    if name == "claude":
        from server.llm.claude_provider import ClaudeProvider

        return ClaudeProvider()
    raise ValueError(f"Unknown provider: {name}")


def _new_run_dir(explicit: Path | None) -> Path:
    if explicit is not None:
        if explicit.exists():
            raise SystemExit(f"Refusing to overwrite existing evaluation directory: {explicit}")
        explicit.mkdir(parents=True)
        return explicit
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = RESULTS_ROOT / f"stage_snapshot_{stamp}"
    run_dir.mkdir(parents=True)
    return run_dir


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def evaluate_one(
    *,
    provider_name: str,
    provider,
    model: str,
    prompt: dict,
    out_dir: Path,
    catalog: dict,
    data_dir: Path,
    reference: dict | None,
) -> dict:
    out_dir.mkdir(parents=True, exist_ok=False)
    _write_text(
        out_dir / "prompt.txt",
        f"id: {prompt['id']}\ncategory: {prompt['category']}\nprovider: {provider_name}\nmodel: {model}\n\n{prompt['text']}\n",
    )
    parsed = None
    normalized = None
    resolved = None
    held_capture = None
    try:
        with capture_stages() as capture:
            held_capture = capture
            normalized = provider.generate_run_plan(model=model, user_request=prompt["text"])
            parsed = capture.parsed_plan
        if held_capture is not None:
            _write_text(out_dir / "raw_response.txt", held_capture.raw_text())
        if not isinstance(parsed, dict):
            raise RuntimeError("Provider returned a plan without a captured parsed dictionary.")
        write_json(out_dir / "parsed_plan.json", parsed)
        write_json(out_dir / "normalized_plan.json", normalized)
        resolved = resolve_plan_step_dependencies(
            normalized,
            prompt["text"],
            catalog=catalog,
            data_dir=data_dir,
        )
        write_json(out_dir / "resolved_plan.json", resolved)
        write_executable_config(resolved, out_dir / "config.yaml")
    except Exception:
        _write_text(out_dir / "error.txt", traceback.format_exc())
        if held_capture is not None and not (out_dir / "raw_response.txt").is_file():
            _write_text(out_dir / "raw_response.txt", held_capture.raw_text())
        if isinstance(parsed, dict) and not (out_dir / "parsed_plan.json").is_file():
            write_json(out_dir / "parsed_plan.json", parsed)
        if isinstance(normalized, dict) and not (out_dir / "normalized_plan.json").is_file():
            write_json(out_dir / "normalized_plan.json", normalized)
        if isinstance(resolved, dict) and not (out_dir / "resolved_plan.json").is_file():
            write_json(out_dir / "resolved_plan.json", resolved)
        raise
    row = score_prompt(
        prompt_id=prompt["id"],
        provider=provider_name,
        model=model,
        parsed=parsed,
        normalized=normalized,
        resolved=resolved,
        reference=reference,
    )
    write_json(out_dir / "stage_counts.json", row)
    return row


def run_evaluation(
    prompts_path: Path,
    references_path: Path,
    providers: list[str],
    out_dir: Path | None,
    limit: int | None = None,
) -> Path:
    prompts = load_prompts(prompts_path)
    if limit is not None:
        if limit < 1:
            raise SystemExit("--limit must be at least 1.")
        prompts = prompts[:limit]
    if not prompts:
        raise SystemExit(
            "No prompts found. Add the 25 benchmark requests to "
            f"{prompts_path} as {{\"prompts\": [{{\"id\": \"001\", \"category\": \"...\", \"text\": \"...\"}}]}}."
        )
    references = load_references(references_path)
    missing_keys = [name for name in providers if not _provider_ready(name)]
    if missing_keys:
        needed = ", ".join(f"{name}: {' or '.join(PROVIDER_ENV[name])}" for name in missing_keys)
        raise SystemExit(f"Missing API key for {needed}.")

    run_dir = _new_run_dir(out_dir)
    catalog = load_catalog()
    data_dir = default_symfluence_data_dir()
    clients = {name: _make_provider(name) for name in providers}
    failures: list[str] = []
    for prompt in prompts:
        reference = references.get(prompt["id"])
        for name in providers:
            dest = run_dir / name / prompt_dirname(prompt["id"])
            try:
                evaluate_one(
                    provider_name=name,
                    provider=clients[name],
                    model=PAPER_MODELS[name],
                    prompt=prompt,
                    out_dir=dest,
                    catalog=catalog,
                    data_dir=data_dir,
                    reference=reference,
                )
                print(f"saved {name} {prompt['id']} -> {dest}")
            except Exception as exc:
                failures.append(f"{name} prompt {prompt['id']}: {exc}")
                print(f"failed {name} {prompt['id']}: {exc}")
    summary = rescore_run(run_dir, references)
    summary["identification"] = IDENTIFICATION
    summary["models"] = {name: PAPER_MODELS[name] for name in providers}
    summary["failures"] = failures
    write_json(run_dir / "summary.json", summary)
    print(f"summary: {run_dir / 'summary.json'}")
    if failures:
        print(f"{len(failures)} provider-prompt call(s) failed. Snapshots saved before the failure are kept.")
    return run_dir


def self_check() -> None:
    """Exercise finalize, dependency resolution, config rendering, and scoring without an API call."""
    import tempfile

    parsed = {
        "config": {
            "domain_name": "Bow_River",
            "experiment_id": None,
            "pour_point_coords": "51.35, -116.02",
            "bounding_box_coords": "51.50/-116.20/51.20/-115.80",
            "hydrological_model": "summa",
            "domain_def": None,
            "experiment_time_start": "2004-01-01",
            "experiment_time_end": "2004-01-10",
        },
        "steps": ["run_model", "setup_project"],
        "needs_user_input": [],
        "notes": "self-check",
    }
    user_request = (
        "Run SUMMA for domain_name Bow_River at 51.35/-116.02 "
        "from 2004-01-01 to 2004-01-10. "
        "Bounding box 51.50/-116.20/51.20/-115.80. Do not calibrate."
    )
    original = deepcopy(parsed)
    normalized = finalize_run_plan(parsed, user_request)
    parsed = original
    resolved = resolve_plan_step_dependencies(
        normalized,
        user_request,
        catalog=load_catalog(),
        data_dir=default_symfluence_data_dir(),
    )
    reference = {
        "requested_config": {
            "domain_name": "Bow_River",
            "hydrological_model": "SUMMA",
            "pour_point_coords": "51.35/ -116.02",
            "experiment_time_start": "2004-01-01 01:00",
            "experiment_time_end": "2004-01-10 23:00",
        },
        "required_steps": ["setup_project", "run_model"],
        "prohibited_steps": ["calibrate_model"],
        "needs_user_input": [],
    }
    with tempfile.TemporaryDirectory() as tmp:
        out_dir = Path(tmp) / "openai" / "prompt_001"
        out_dir.mkdir(parents=True)
        _write_text(out_dir / "raw_response.txt", "===== SCHEMA_CALL =====\nself-check\n")
        write_json(out_dir / "parsed_plan.json", parsed)
        write_json(out_dir / "normalized_plan.json", normalized)
        write_json(out_dir / "resolved_plan.json", resolved)
        config_path = write_executable_config(resolved, out_dir / "config.yaml")
        row = score_prompt(
            prompt_id="001",
            provider="openai",
            model=PAPER_MODELS["openai"],
            parsed=parsed,
            normalized=normalized,
            resolved=resolved,
            reference=reference,
        )
        write_json(out_dir / "stage_counts.json", row)
        summary = rescore_run(Path(tmp), {"001": reference})
        required_files = [
            "raw_response.txt",
            "parsed_plan.json",
            "normalized_plan.json",
            "resolved_plan.json",
            "config.yaml",
            "stage_counts.json",
        ]
        missing = [name for name in required_files if not (out_dir / name).is_file()]
        if missing:
            raise SystemExit(f"self-check missing files: {missing}")
        if not config_path.is_file() or config_path.stat().st_size == 0:
            raise SystemExit("self-check wrote an empty config.yaml")
        if row["exact_plan_match"] is not True:
            raise SystemExit(f"self-check expected a normalized-plan match, got {row}")
        if row["parsed_plan"]["exact_plan_match"] is not False:
            raise SystemExit(f"self-check expected a parsed-plan mismatch, got {row}")
        if row["configuration_accuracy"] != 1.0:
            raise SystemExit(f"self-check expected full configuration accuracy, got {row}")
        if "calibrate_model" in steps_from(resolved):
            raise SystemExit("self-check resolved plan included calibrate_model")
        if "openai" not in summary["providers"]:
            raise SystemExit(f"self-check summary missing provider: {summary}")
    print("self-check ok")
    print(f"configuration accuracy: {row['configuration_accuracy']}")
    print(f"step precision: {row['step_precision']}")
    print(f"step recall: {row['step_recall']}")
    print(f"exact plan match: {row['exact_plan_match']}")


def steps_from(plan: dict) -> list[str]:
    steps = plan.get("steps") or []
    return [step for step in steps if isinstance(step, str)]


def main() -> None:
    parser = argparse.ArgumentParser(description="Save and score the five HydroAgent planning stages.")
    parser.add_argument("--prompts", type=Path, default=DEFAULT_PROMPTS)
    parser.add_argument("--references", type=Path, default=DEFAULT_REFERENCES)
    parser.add_argument(
        "--providers",
        default="openai,gemini,claude",
        help="Comma-separated subset of openai,gemini,claude.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="New results directory. Refuses to overwrite an existing path.",
    )
    parser.add_argument(
        "--rescore",
        type=Path,
        default=None,
        help="Recompute summary.json from an existing stage-snapshot directory.",
    )
    parser.add_argument("--limit", type=int, default=None, help="Run only the first N prompts.")
    parser.add_argument("--self-check", action="store_true", help="Run the local pipeline check without API calls.")
    args = parser.parse_args()

    if args.self_check:
        self_check()
        return
    if args.rescore is not None:
        references = load_references(args.references)
        summary = rescore_run(args.rescore, references)
        print(f"rescored {args.rescore}")
        for name, stats in summary["providers"].items():
            print(name, stats)
        return

    providers = [name.strip() for name in args.providers.split(",") if name.strip()]
    unknown = [name for name in providers if name not in PAPER_MODELS]
    if unknown:
        raise SystemExit(f"Unknown providers: {', '.join(unknown)}")
    run_evaluation(args.prompts, args.references, providers, args.out, args.limit)


if __name__ == "__main__":
    main()
