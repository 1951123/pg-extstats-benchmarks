"""Read-only execution of one benchmark adapter lifecycle stage."""
from pathlib import Path
from datetime import datetime, timezone

from .adapters import get_adapter
from .artifacts import Artifact
from .execution import (
    ExecutionRecord,
    _artifact_id,
    new_execution_id,
    repository_commit,
    write_execution_record,
)
from .loader_registry import get_loader
from .registry import load_manifest, load_registry
from .instances import LoadedInstance
from .validation import ValidationReport
from .validator_registry import get_validator

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


def load_artifact(
    benchmark_id: str | None = None,
    loader: str | None = None,
    *,
    benchmark: str | None = None,
    destroy: bool = False,
    record: bool = False,
) -> dict:
    """Pass a prepared metadata artifact through a registered mock loader.

    This is an execution-framework demonstration only. It validates the
    benchmark manifest, obtains prepared artifact metadata from the adapter,
    and invokes the loader contract. It never opens a database or executes
    SQL.
    """
    if benchmark_id is None:
        benchmark_id = benchmark
    elif benchmark is not None and benchmark != benchmark_id:
        raise ValueError("benchmark and benchmark_id must match")
    if not isinstance(benchmark_id, str) or not benchmark_id:
        raise ValueError("benchmark_id is required")
    if not isinstance(loader, str) or not loader:
        raise ValueError("loader is required")

    benchmarks = load_registry(_REPO_ROOT)
    try:
        definition = benchmarks[benchmark_id]
    except KeyError as exc:
        raise ValueError(f"Unknown benchmark: {benchmark_id}") from exc
    load_manifest(definition)

    adapter_class = get_adapter(benchmark_id)
    prepared = getattr(adapter_class(), "prepare")()
    prepared_artifacts = prepared.get("output_artifacts", prepared.get("outputs", ()))
    if not isinstance(prepared_artifacts, (list, tuple)):
        prepared_artifacts = (prepared_artifacts,)
    prepared_artifacts = tuple(prepared_artifacts)
    if not prepared_artifacts or not all(isinstance(item, Artifact) for item in prepared_artifacts):
        raise ValueError(f"Adapter {adapter_class.__name__}.prepare returned no prepared artifacts")

    loader_class = get_loader(loader)
    loader_instance = loader_class()
    instance = None
    destroyed = False
    try:
        instance = loader_instance.create_instance(benchmark_id)
        for artifact in prepared_artifacts:
            instance = loader_instance.load_artifact(instance, artifact)
        validation = loader_instance.validate_instance(instance)
        if not isinstance(validation, dict):
            raise ValueError(f"Loader {loader_class.__name__}.validate_instance must return a mapping")
        status = validation.get("status")
        message = validation.get("message", f"{loader_class.__name__} validation completed")
        if not isinstance(status, str) or not isinstance(message, str):
            raise ValueError(f"Loader {loader_class.__name__}.validate_instance must return status/message")
        result = {
            "benchmark_id": benchmark_id,
            "loader": loader_class.__name__,
            "instance": instance.to_dict(),
            "artifact_ids": [artifact.id for artifact in prepared_artifacts],
            "status": status,
            "message": message,
            "load": {"status": "PASS", "message": f"{loader_class.__name__} loaded artifacts"},
            "validation": validation,
        }
        if destroy:
            cleanup = loader_instance.destroy_instance(instance)
            destroyed = cleanup.get("status") == "PASS"
            result["cleanup"] = cleanup
            if not destroyed:
                result["status"] = "FAIL"
        provenance = {
            "artifact_id": prepared_artifacts[0].id,
            "artifact_ids": [artifact.id for artifact in prepared_artifacts],
            "postgres_version": instance.metadata.get("postgres_version"),
            "loader_type": loader_class.__name__,
            "instance_metadata": dict(instance.metadata),
        }
        result["provenance"] = provenance
        if record:
            execution = ExecutionRecord(
                execution_id=new_execution_id(),
                benchmark_id=benchmark_id,
                stage="load",
                status=result["status"],
                repository_commit=repository_commit(_REPO_ROOT),
                timestamp=datetime.now(timezone.utc).isoformat(),
                input_artifacts=tuple(artifact.id for artifact in prepared_artifacts),
                output_artifacts=(),
                message=message,
                metadata=provenance,
            )
            path = write_execution_record(execution, _REPO_ROOT)
            result["execution"] = execution.to_dict()
            result["execution_path"] = str(path.relative_to(_REPO_ROOT))
        return result
    finally:
        if destroy and instance is not None and not destroyed:
            try:
                loader_instance.destroy_instance(instance)
            except Exception:
                pass
        close = getattr(loader_instance, "close", None)
        if callable(close):
            close()


def validate_instance(
    benchmark_id: str | None = None,
    instance: LoadedInstance | None = None,
    validator: str | None = None,
    *,
    benchmark: str | None = None,
) -> dict:
    """Validate a loaded instance with a registered benchmark validator."""
    if benchmark_id is None:
        benchmark_id = benchmark
    elif benchmark is not None and benchmark != benchmark_id:
        raise ValueError("benchmark and benchmark_id must match")
    if not isinstance(benchmark_id, str) or not benchmark_id:
        raise ValueError("benchmark_id is required")
    if not isinstance(instance, LoadedInstance):
        raise TypeError("instance must be a LoadedInstance")
    if instance.benchmark_id != benchmark_id:
        raise ValueError("instance benchmark_id does not match benchmark")
    if not isinstance(validator, str) or not validator:
        raise ValueError("validator is required")

    benchmarks = load_registry(_REPO_ROOT)
    try:
        definition = benchmarks[benchmark_id]
    except KeyError as exc:
        raise ValueError(f"Unknown benchmark: {benchmark_id}") from exc
    load_manifest(definition)

    validator_class = get_validator(validator)
    report = validator_class().validate_instance(instance)
    if not isinstance(report, ValidationReport):
        raise ValueError(
            f"Validator {validator_class.__name__}.validate_instance must return a report"
        )
    return {
        "benchmark_id": benchmark_id,
        "validator": validator_class.__name__,
        "instance": instance.to_dict(),
        "report": report.to_dict(),
        "status": report.status,
        "message": f"{validator_class.__name__} completed",
    }
