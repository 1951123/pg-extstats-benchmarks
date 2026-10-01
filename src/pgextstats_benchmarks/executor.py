"""Read-only execution of one benchmark adapter lifecycle stage."""
from pathlib import Path
from datetime import datetime, timezone

from .adapters import get_adapter
from .execution import (
    ExecutionRecord,
    _artifact_id,
    new_execution_id,
    repository_commit,
    write_execution_record,
)
from .registry import load_manifest, load_registry

STAGES = (
    "fetch",
    "prepare",
    "load",
    "validate",
    "normalize_workload",
    "collect_truth",
)
_REPO_ROOT = Path(__file__).resolve().parents[2]


def run_stage(
    benchmark_id: str | None = None,
    stage: str | None = None,
    record: bool = False,
    *,
    benchmark: str | None = None,
) -> dict:
    """Validate a registered definition and execute one adapter stage.

    The executor only invokes Python methods. It performs no subprocess,
    database operation, or cleanup. With ``record=True``, it writes one JSON
    execution record below the repository-local ``runs/`` directory.
    """
    if benchmark_id is None:
        benchmark_id = benchmark
    elif benchmark is not None and benchmark != benchmark_id:
        raise ValueError("benchmark and benchmark_id must match")
    if not isinstance(benchmark_id, str) or not benchmark_id:
        raise ValueError("benchmark_id is required")
    if stage not in STAGES:
        choices = ", ".join(STAGES)
        raise ValueError(f"Invalid stage: {stage}. Choose one of: {choices}")
    benchmarks = load_registry(_REPO_ROOT)
    try:
        benchmark = benchmarks[benchmark_id]
    except KeyError as exc:
        raise ValueError(f"Unknown benchmark: {benchmark_id}") from exc
    load_manifest(benchmark)
    adapter_class = get_adapter(benchmark_id)
    result = getattr(adapter_class(), stage)()
    if not isinstance(result, dict):
        raise ValueError(f"Adapter {adapter_class.__name__}.{stage} must return a mapping")
    status = result.get("status")
    message = result.get("message")
    if not isinstance(status, str) or not isinstance(message, str):
        raise ValueError(f"Adapter {adapter_class.__name__}.{stage} must return status/message")
    stage_result = {
        "benchmark_id": benchmark_id,
        "adapter": adapter_class.__name__,
        "stage": stage,
        "status": status,
        "message": message,
    }
    if not record:
        return stage_result

    def artifact_ids(key: str, alias: str) -> tuple[str, ...]:
        values = result.get(key, result.get(alias, ()))
        if values is None:
            return ()
        if not isinstance(values, (list, tuple)):
            values = (values,)
        return tuple(_artifact_id(value) for value in values)

    execution = ExecutionRecord(
        execution_id=new_execution_id(),
        benchmark_id=benchmark_id,
        stage=stage,
        status=status,
        repository_commit=repository_commit(_REPO_ROOT),
        timestamp=datetime.now(timezone.utc).isoformat(),
        input_artifacts=artifact_ids("input_artifacts", "inputs"),
        output_artifacts=artifact_ids("output_artifacts", "outputs"),
        message=message,
    )
    path = write_execution_record(execution, _REPO_ROOT)
    stage_result["execution"] = execution.to_dict()
    stage_result["execution_path"] = str(path.relative_to(_REPO_ROOT))
    return stage_result
