from __future__ import annotations

WORKFLOW_PRIORITY = {
    "validate_config": 0,
    "setup_project": 10,
    "create_pour_point": 20,
    "acquire_attributes": 30,
    "define_domain": 40,
    "discretize_domain": 50,
    "process_observed_data": 60,
    "acquire_forcings": 70,
    "model_agnostic_preprocessing": 80,
    "model_specific_preprocessing": 90,
    "run_model": 100,
    "postprocess_results": 110,
    "calibrate_model": 120,
}


def index_operations(catalog: dict) -> dict:
    return {op["name"]: op for op in catalog.get("operations", [])}


def build_producer_index(catalog: dict) -> dict:
    producer = {}
    for op in catalog.get("operations", []):
        for artifact in op.get("produces", []):
            producer.setdefault(artifact, []).append(op["name"])
    return producer


def resolve_step_dependencies(target_step: str, catalog: dict, include_validate: bool = True) -> list[str]:
    ops = index_operations(catalog)
    producers = build_producer_index(catalog)
    visited = set()
    collected = []

    def visit(step: str):
        if step in visited:
            return
        visited.add(step)

        op = ops.get(step, {})
        for req in op.get("requires", []):
            for producer in producers.get(req, []):
                visit(producer)

        collected.append(step)

    visit(target_step)

    if include_validate and "validate_config" not in collected:
        collected.insert(0, "validate_config")

    collected = sorted(
        collected,
        key=lambda s: WORKFLOW_PRIORITY.get(s, 999),
    )

    return collected