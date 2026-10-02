"""Confined external storage for EstimateArtifact manifests."""
from __future__ import annotations

import json
from pathlib import Path

from .estimate import EstimateArtifact
from .sample_storage import _reject_symlink_components, _safe_root


def estimate_artifact_dir(benchmark_id: str, artifact_id: str, root: Path | None = None) -> Path:
    base = _safe_root(root)
    for value, label in ((benchmark_id, "benchmark_id"), (artifact_id, "artifact_id")):
        if not isinstance(value, str) or not value or Path(value).name != value or "/" in value or "\\" in value or value in {".", ".."}:
            raise ValueError(f"{label} must be a safe path component")
    path = (base / benchmark_id / "artifacts" / artifact_id).resolve()
    if not path.is_relative_to(base):
        raise ValueError("estimate artifact path escapes benchmark data root")
    return path


def allocate_estimate_artifact_dir(benchmark_id: str, artifact_id: str, root: Path | None = None) -> Path:
    path = estimate_artifact_dir(benchmark_id, artifact_id, root)
    if path.exists():
        raise FileExistsError(f"estimate artifact already exists: {path}")
    base = _safe_root(root)
    _reject_symlink_components(base, path.parent)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink() or not path.parent.resolve().is_relative_to(base):
        raise ValueError("estimate artifact path escapes benchmark data root")
    path.mkdir()
    return path


def write_estimate_artifact(artifact: EstimateArtifact, root: Path | None = None) -> Path:
    directory = estimate_artifact_dir(artifact.benchmark_id, artifact.artifact_id, root)
    if not directory.is_dir() or directory.is_symlink():
        raise FileNotFoundError(f"estimate artifact directory is missing: {directory}")
    manifest = directory / "manifest.json"
    estimates = directory / "estimates.json"
    if manifest.exists() or estimates.exists():
        raise FileExistsError(f"estimate artifact already has metadata: {directory}")
    with manifest.open("x", encoding="utf-8") as stream:
        stream.write(artifact.to_json())
    with estimates.open("x", encoding="utf-8") as stream:
        json.dump({"query_estimates": [item.to_dict() for item in artifact.query_estimates]}, stream, sort_keys=True, indent=2)
        stream.write("\n")
    return manifest


def load_estimate_artifact(benchmark_id: str, artifact_id: str, root: Path | None = None) -> EstimateArtifact:
    directory = estimate_artifact_dir(benchmark_id, artifact_id, root)
    manifest = directory / "manifest.json"
    if not manifest.is_file() or manifest.is_symlink():
        raise FileNotFoundError(f"estimate manifest is missing: {manifest}")
    artifact = EstimateArtifact.from_dict(json.loads(manifest.read_text(encoding="utf-8")))
    if artifact.benchmark_id != benchmark_id or artifact.artifact_id != artifact_id:
        raise ValueError("estimate manifest identity does not match requested artifact")
    return artifact


__all__ = ["allocate_estimate_artifact_dir", "estimate_artifact_dir", "load_estimate_artifact", "write_estimate_artifact"]
