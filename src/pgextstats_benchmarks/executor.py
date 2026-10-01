"""Read-only execution of one benchmark adapter lifecycle stage."""
from pathlib import Path

from .adapters import get_adapter
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


def run_stage(benchmark_id: str, stage: str) -> dict[str, str]:
    """Validate a registered definition and execute one adapter stage.

    The executor only invokes Python methods. It performs no subprocess,
    filesystem mutation, database operation, or cleanup.
    """
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
    return {
        "benchmark_id": benchmark_id,
        "adapter": adapter_class.__name__,
        "stage": stage,
        "status": status,
        "message": message,
    }
