"""Safe external storage and validation for sample artifacts."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .paths import benchmark_data_root
from .sample_artifacts import SampleArtifact


def _safe_root(root: Path | None = None) -> Path:
    selected = Path(root or benchmark_data_root()).expanduser()
    if not selected.is_absolute():
        raise ValueError("benchmark data root must be absolute")
    if selected == Path("/"):
        raise ValueError("benchmark data root may not be filesystem root")
    current = Path(selected.anchor)
    for component in selected.parts[1:]:
        current = current / component
        if current.exists() and current.is_symlink():
            raise ValueError("benchmark data root may not contain symlink components")
    resolved = selected.resolve()
    if resolved == Path("/"):
        raise ValueError("benchmark data root may not resolve to filesystem root")
    return resolved


def _safe_component(value: str, label: str) -> str:
    if not isinstance(value, str) or not value or value in {".", ".."}:
        raise ValueError(f"{label} must be a safe path component")
    if Path(value).name != value or any(ch in value for ch in "/\\"):
        raise ValueError(f"{label} must be a safe path component")
    return value


def sample_artifact_dir(benchmark_id: str, artifact_id: str, root: Path | None = None) -> Path:
    base = _safe_root(root)
    benchmark_id = _safe_component(benchmark_id, "benchmark_id")
    artifact_id = _safe_component(artifact_id, "artifact_id")
    path = base / benchmark_id / "artifacts" / artifact_id
    resolved = path.resolve()
    if not resolved.is_relative_to(base):
        raise ValueError("sample artifact path escapes benchmark data root")
    return resolved


def _reject_symlink_components(base: Path, path: Path) -> None:
    current = base
    relative = path.relative_to(base)
    for component in relative.parts:
        current = current / component
        if current.exists() and current.is_symlink():
            raise ValueError(f"sample artifact path contains symlink: {current}")


def allocate_sample_artifact_dir(benchmark_id: str, artifact_id: str, root: Path | None = None) -> Path:
    base = _safe_root(root)
    path = sample_artifact_dir(benchmark_id, artifact_id, base)
    if path.exists():
        raise FileExistsError(f"sample artifact already exists: {path}")
    _reject_symlink_components(base, path.parent)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink() or not path.parent.resolve().is_relative_to(base):
        raise ValueError("sample artifact parent escapes benchmark data root")
    path.mkdir()
    return path


def payload_path(artifact: SampleArtifact, root: Path | None = None) -> Path:
    base = _safe_root(root)
    relative = Path(artifact.payload_relative_path)
    if relative.is_absolute() or ".." in relative.parts or "\\" in artifact.payload_relative_path:
        raise ValueError("sample payload path must be relative")
    path = (base / relative).resolve()
    if not path.is_relative_to(base):
        raise ValueError("sample payload path escapes benchmark data root")
    return path


def verify_sample_artifact(artifact: SampleArtifact, root: Path | None = None) -> Path:
    path = payload_path(artifact, root)
    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError(f"sample payload is missing: {path}")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != artifact.payload_sha256:
        raise ValueError(f"sample payload checksum mismatch: expected {artifact.payload_sha256}, got {digest}")
    return path


def write_sample_manifest(artifact: SampleArtifact, root: Path | None = None) -> Path:
    path = sample_artifact_dir(artifact.benchmark_id, artifact.artifact_id, root) / "manifest.json"
    if not path.parent.is_dir() or path.parent.is_symlink():
        raise FileNotFoundError(f"sample artifact directory is missing: {path.parent}")
    if path.exists():
        raise FileExistsError(f"sample manifest already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(artifact.to_json())
    return path


def load_sample_manifest(benchmark_id: str, artifact_id: str, root: Path | None = None) -> SampleArtifact:
    directory = sample_artifact_dir(benchmark_id, artifact_id, root)
    path = directory / "manifest.json"
    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError(f"sample manifest is missing: {path}")
    artifact = SampleArtifact.from_dict(json.loads(path.read_text(encoding="utf-8")))
    if artifact.benchmark_id != benchmark_id or artifact.artifact_id != artifact_id:
        raise ValueError("sample manifest identity does not match requested artifact")
    verify_sample_artifact(artifact, root)
    return artifact
