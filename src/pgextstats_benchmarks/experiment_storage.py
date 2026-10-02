"""Confined external storage for ExperimentRunArtifact manifests."""
from __future__ import annotations

import json
from pathlib import Path

from .experiment import ExperimentRunArtifact
from .sample_storage import _reject_symlink_components, _safe_root


def experiment_artifact_dir(benchmark_id: str, experiment_id: str, root: Path | None = None) -> Path:
    base = _safe_root(root)
    for value, label in ((benchmark_id, "benchmark_id"), (experiment_id, "experiment_id")):
        if not isinstance(value, str) or not value or Path(value).name != value or "/" in value or "\\" in value or value in {".", ".."}:
            raise ValueError(f"{label} must be a safe path component")
    path = (base / benchmark_id / "artifacts" / experiment_id).resolve()
    if not path.is_relative_to(base):
        raise ValueError("experiment artifact path escapes benchmark data root")
    return path


def allocate_experiment_artifact_dir(benchmark_id: str, experiment_id: str, root: Path | None = None) -> Path:
    path = experiment_artifact_dir(benchmark_id, experiment_id, root)
    if path.exists():
        raise FileExistsError(f"experiment artifact already exists: {path}")
    base = _safe_root(root)
    _reject_symlink_components(base, path.parent)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink() or not path.parent.resolve().is_relative_to(base):
        raise ValueError("experiment artifact path escapes benchmark data root")
    path.mkdir()
    return path


def write_experiment_artifact(artifact: ExperimentRunArtifact, root: Path | None = None) -> Path:
    directory = experiment_artifact_dir(artifact.benchmark_id, artifact.experiment_id, root)
    if not directory.is_dir() or directory.is_symlink():
        raise FileNotFoundError(f"experiment artifact directory is missing: {directory}")
    manifest = directory / "manifest.json"
    experiment = directory / "experiment.json"
    if manifest.exists() or experiment.exists():
        raise FileExistsError(f"experiment artifact already has metadata: {directory}")
    with manifest.open("x", encoding="utf-8") as stream:
        stream.write(artifact.to_json())
    with experiment.open("x", encoding="utf-8") as stream:
        json.dump(artifact.canonical_dict(), stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    return manifest


def load_experiment_artifact(benchmark_id: str, experiment_id: str, root: Path | None = None) -> ExperimentRunArtifact:
    directory = experiment_artifact_dir(benchmark_id, experiment_id, root)
    manifest = directory / "manifest.json"
    if not manifest.is_file() or manifest.is_symlink():
        raise FileNotFoundError(f"experiment manifest is missing: {manifest}")
    artifact = ExperimentRunArtifact.from_dict(json.loads(manifest.read_text(encoding="utf-8")))
    if artifact.benchmark_id != benchmark_id or artifact.experiment_id != experiment_id:
        raise ValueError("experiment manifest identity does not match requested artifact")
    return artifact


__all__ = ["allocate_experiment_artifact_dir", "experiment_artifact_dir", "load_experiment_artifact", "write_experiment_artifact"]
