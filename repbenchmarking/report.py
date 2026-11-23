"""Summarize repeated exact-match scores.

Each provider-prompt pair has several calls. A replicate is one pass over the
prompts. The provider rate for a replicate is the fraction of prompts whose
normalized plan matched the reference on that pass. The mean and sample
standard deviation are taken across those replicate rates.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

CAUTION = (
    "Three replicates describe stability for these prompts, models, and author-written references. "
    "They do not estimate a general provider ranking."
)


def _sample_std(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    return math.sqrt(variance)


def _matched(row: dict[str, Any]) -> bool | None:
    if "exact_plan_match" in row:
        return row.get("exact_plan_match")
    return row.get("exact_match_after")


def summarize_repeats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_provider: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_provider[row["provider"]].append(row)

    providers: dict[str, Any] = {}
    for provider, items in sorted(by_provider.items()):
        completed = [row for row in items if row.get("completed") and _matched(row) is not None]
        repeats = sorted({int(row["repeat"]) for row in completed})
        prompt_ids = sorted({str(row["prompt_id"]) for row in completed})
        rates: list[float] = []
        for repeat in repeats:
            matched = [
                row for row in completed if int(row["repeat"]) == repeat and _matched(row) is True
            ]
            present = [row for row in completed if int(row["repeat"]) == repeat]
            if present:
                rates.append(len(matched) / len(present))

        per_prompt = []
        varied = 0
        for prompt_id in prompt_ids:
            calls = [row for row in completed if str(row["prompt_id"]) == prompt_id]
            matches = sum(1 for row in calls if _matched(row) is True)
            outcomes = [bool(_matched(row)) for row in calls]
            did_vary = len(set(outcomes)) > 1
            varied += int(did_vary)
            per_prompt.append(
                {
                    "prompt_id": prompt_id,
                    "matches": matches,
                    "n": len(calls),
                    "rate": (matches / len(calls)) if calls else None,
                    "varied": did_vary,
                }
            )

        providers[provider] = {
            "n_prompts": len(prompt_ids),
            "n_repeats": len(repeats),
            "n_completed_calls": len(completed),
            "n_failed_calls": sum(1 for row in items if not row.get("completed")),
            "exact_match_rate_by_repeat": rates,
            "exact_match_rate_mean": (sum(rates) / len(rates)) if rates else None,
            "exact_match_rate_std": _sample_std(rates),
            "n_prompts_that_varied": varied,
            "per_prompt": per_prompt,
        }

    differences = []
    names = list(providers)
    for index, left in enumerate(names):
        for right in names[index + 1 :]:
            left_mean = providers[left]["exact_match_rate_mean"]
            right_mean = providers[right]["exact_match_rate_mean"]
            difference = None
            if left_mean is not None and right_mean is not None:
                difference = left_mean - right_mean
            differences.append(
                {
                    "a": left,
                    "b": right,
                    "mean_rate_difference_a_minus_b": difference,
                    "caution": CAUTION,
                }
            )

    return {"providers": providers, "provider_differences": differences, "caution": CAUTION}
