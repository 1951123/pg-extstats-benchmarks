"""Confined external storage for StatisticsRepositoryArtifact manifests."""
from __future__ import annotations

import json
from pathlib import Path

from .sample_storage import _reject_symlink_components, _safe_root
from .statistics_repository import StatisticsRepositoryArtifact


def repository_artifact_dir(benchmark_id: str, artifact_id: str, root: Path | None = None) -> Path:
    base = _safe_root(root)
    for value, label in ((benchmark_id, "benchmark_id"), (artifact_id, "artifact_id")):
        if not isinstance(value, str) or not value or Path(value).name != value or "/" in value or "\\" in value or value in {".", ".."}:
            raise ValueError(f"{label} must be a safe path component")
    path = (base / benchmark_id / "artifacts" / artifact_id).resolve()
    if not path.is_relative_to(base):
        raise ValueError("repository artifact path escapes benchmark data root")
    return path


def allocate_repository_artifact_dir(benchmark_id: str, artifact_id: str, root: Path | None = None) -> Path:
    path = repository_artifact_dir(benchmark_id, artifact_id, root)
    if path.exists():
        raise FileExistsError(f"repository artifact already exists: {path}")
    _reject_symlink_components(_safe_root(root), path.parent)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink() or not path.parent.resolve().is_relative_to(_safe_root(root)):
        raise ValueError("repository artifact path escapes benchmark data root")
    path.mkdir()
    return path


def write_repository_artifact(artifact: StatisticsRepositoryArtifact, root: Path | None = None) -> Path:
    directory = repository_artifact_dir(artifact.benchmark_id, artifact.artifact_id, root)
    if not directory.is_dir() or directory.is_symlink():
        raise FileNotFoundError(f"repository artifact directory is missing: {directory}")
    manifest = directory / "manifest.json"
    repository = directory / "repository.json"
    if manifest.exists() or repository.exists():
        raise FileExistsError(f"repository artifact already has metadata: {directory}")
    data = artifact.to_json()
    with manifest.open("x", encoding="utf-8") as stream:
        stream.write(data)
    with repository.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(artifact.canonical_dict(), sort_keys=True, indent=2) + "\n")
    return manifest


def load_repository_artifact(benchmark_id: str, artifact_id: str, root: Path | None = None) -> StatisticsRepositoryArtifact:
    directory = repository_artifact_dir(benchmark_id, artifact_id, root)
    manifest = directory / "manifest.json"
    if not manifest.is_file() or manifest.is_symlink():
        raise FileNotFoundError(f"repository manifest is missing: {manifest}")
    artifact = StatisticsRepositoryArtifact.from_dict(json.loads(manifest.read_text(encoding="utf-8")))
    if artifact.benchmark_id != benchmark_id or artifact.artifact_id != artifact_id:
        raise ValueError("repository manifest identity does not match requested artifact")
    return artifact


__all__ = [
    "allocate_repository_artifact_dir", "load_repository_artifact",
    "repository_artifact_dir", "write_repository_artifact",
]
