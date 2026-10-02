"""Read-only loading of established TruthArtifact directories."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .sample_storage import _safe_root
from .truth import TruthArtifact


def truth_artifact_dir(benchmark_id: str, artifact_id: str, root: Path | None = None) -> Path:
    base = _safe_root(root)
    for value, label in ((benchmark_id, "benchmark_id"), (artifact_id, "artifact_id")):
        if not isinstance(value, str) or not value or Path(value).name != value or "/" in value or "\\" in value or value in {".", ".."}:
            raise ValueError(f"{label} must be a safe path component")
    path = (base / benchmark_id / "artifacts" / artifact_id).resolve()
    if not path.is_relative_to(base):
        raise ValueError("truth artifact path escapes benchmark data root")
    return path


def load_truth_artifact_manifest(benchmark_id: str, artifact_id: str, root: Path | None = None) -> dict:
    directory = truth_artifact_dir(benchmark_id, artifact_id, root)
    manifest_path = directory / "manifest.json"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise FileNotFoundError(f"truth manifest is missing: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("artifact_id") != artifact_id:
        raise ValueError("truth manifest identity does not match requested artifact")
    return manifest


def load_truth_artifact(benchmark_id: str, artifact_id: str, root: Path | None = None) -> TruthArtifact:
    directory = truth_artifact_dir(benchmark_id, artifact_id, root)
    manifest = load_truth_artifact_manifest(benchmark_id, artifact_id, root)
    truth_path = directory / "truth.json"
    if not truth_path.is_file() or truth_path.is_symlink():
        raise FileNotFoundError(f"truth artifact is missing: {truth_path}")
    expected = manifest.get("sha256")
    actual = hashlib.sha256(truth_path.read_bytes()).hexdigest()
    if expected and expected != actual:
        raise ValueError(f"truth artifact checksum mismatch: expected {expected}, got {actual}")
    truth = TruthArtifact.from_dict(json.loads(truth_path.read_text(encoding="utf-8")))
    if truth.benchmark_id != benchmark_id or truth.workload_id != manifest.get("workload_id", truth.workload_id):
        raise ValueError("truth artifact identity does not match manifest")
    return truth


__all__ = ["load_truth_artifact", "load_truth_artifact_manifest", "truth_artifact_dir"]
