"""Execution records and repository-local JSON persistence."""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping
import json
import uuid

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _artifact_id(value: object) -> str:
    if isinstance(value, str):
        return value
    identifier = getattr(value, "id", None)
    if identifier is None:
        identifier = getattr(value, "artifact_id", None)
    if not isinstance(identifier, str) or not identifier.strip():
        raise ValueError("execution artifacts must be IDs or Artifact objects")
    return identifier


@dataclass(frozen=True)
class ExecutionRecord:
    """A JSON-serializable account of one adapter stage execution."""

    execution_id: str
    benchmark_id: str
    stage: str
    status: str
    repository_commit: str
    timestamp: str
    input_artifacts: tuple[str, ...]
    output_artifacts: tuple[str, ...]
    message: str
    metadata: Mapping[str, Any] = field(default_factory=dict)
    operation: str = "stage"

    def __post_init__(self) -> None:
        for name in ("execution_id", "benchmark_id", "stage", "status", "message"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise ValueError(f"{name} must be a nonempty string")
        if not isinstance(self.repository_commit, str) or not self.repository_commit.strip():
            raise ValueError("repository_commit must be a nonempty string")
        if not isinstance(self.timestamp, str) or not self.timestamp.strip():
            raise ValueError("timestamp must be a nonempty string")
        for artifact_id in (*self.input_artifacts, *self.output_artifacts):
            if not isinstance(artifact_id, str) or not artifact_id.strip():
                raise ValueError("artifact IDs must be nonempty strings")
        if not isinstance(self.metadata, Mapping):
            raise TypeError("execution metadata must be a mapping")
        if not isinstance(self.operation, str) or not self.operation.strip():
            raise ValueError("operation must be a nonempty string")

    @property
    def benchmark(self) -> str:
        """Short alias matching the human-facing example format."""
        return self.benchmark_id

    @property
    def inputs(self) -> tuple[str, ...]:
        return self.input_artifacts

    @property
    def outputs(self) -> tuple[str, ...]:
        return self.output_artifacts

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "benchmark_id": self.benchmark_id,
            "stage": self.stage,
            "status": self.status,
            "repository_commit": self.repository_commit,
            "timestamp": self.timestamp,
            "input_artifacts": list(self.input_artifacts),
            "output_artifacts": list(self.output_artifacts),
            "message": self.message,
            "metadata": dict(self.metadata),
            "operation": self.operation,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, indent=2) + "\n"

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ExecutionRecord":
        return cls(
            execution_id=value["execution_id"],
            benchmark_id=value.get("benchmark_id", value.get("benchmark")),
            stage=value["stage"],
            status=value["status"],
            repository_commit=value["repository_commit"],
            timestamp=value["timestamp"],
            input_artifacts=tuple(value.get("input_artifacts", value.get("inputs", ()))),
            output_artifacts=tuple(value.get("output_artifacts", value.get("outputs", ()))),
            message=value["message"],
            metadata=value.get("metadata", {}),
            operation=value.get("operation", "stage"),
        )


def repository_commit(repo_root: Path = _REPO_ROOT) -> str:
    """Read the current commit from local Git metadata without subprocesses."""
    git_dir = repo_root / ".git"
    try:
        head = (git_dir / "HEAD").read_text(encoding="utf-8").strip()
        if head.startswith("ref: "):
            ref = head[6:]
            return (git_dir / ref).read_text(encoding="utf-8").strip()
        return head
    except (OSError, ValueError):
        return "unknown"


def new_execution_id() -> str:
    """Return a filesystem-safe short execution identifier."""
    return uuid.uuid4().hex[:12]


def write_execution_record(record: ExecutionRecord, repo_root: Path = _REPO_ROOT) -> Path:
    """Write one record below the repository-local ``runs/`` directory."""
    runs_root = repo_root / "runs"
    if runs_root.exists() and (runs_root.is_symlink() or not runs_root.is_dir()):
        raise ValueError("runs must be a repository-local directory")
    runs_root.mkdir(exist_ok=True)
    if runs_root.resolve() != runs_root:
        raise ValueError("runs must not resolve through a symlink")
    filename = f"{record.benchmark_id}-{record.stage}-{record.execution_id}.json"
    path = runs_root / filename
    path.write_text(record.to_json(), encoding="utf-8")
    return path
