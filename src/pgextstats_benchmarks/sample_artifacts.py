"""Core model for one persisted PostgreSQL ANALYZE sample realization.

The payload is intentionally opaque to Python.  PostgreSQL owns decoding and
compatibility checks for the ``PGEXTSC1`` binary format.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import math
from pathlib import PurePosixPath
from typing import Any, Mapping


def _mapping(value: Mapping[str, Any], name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be a mapping")
    result = dict(value)
    json.dumps(result, sort_keys=True)
    return result


@dataclass(frozen=True)
class SampleArtifact:
    """Metadata for one ANALYZE sample, without decoding its binary payload."""

    artifact_id: str
    benchmark_id: str
    relation_identity: str
    parent_data_artifact_id: str
    loaded_instance_id: str
    format: str
    format_version: int
    payload_relative_path: str
    payload_sha256: str
    sample_tuple_count: int
    estimated_total_rows: float
    postgres_source: Mapping[str, Any]
    acquisition: Mapping[str, Any]
    schema_fingerprint: str
    lineage: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in (
            "artifact_id", "benchmark_id", "relation_identity",
            "parent_data_artifact_id", "loaded_instance_id", "payload_relative_path",
            "payload_sha256", "schema_fingerprint",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a nonempty string")
        if self.relation_identity.lower().startswith("oid:"):
            raise ValueError("relation_identity must be logical, not an OID")
        if self.format != "PGEXTSC1":
            raise ValueError("sample format must be PGEXTSC1")
        if self.format_version != 1:
            raise ValueError("sample format_version must be 1")
        relative = PurePosixPath(self.payload_relative_path)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("sample payload path must be relative and confined")
        if len(self.payload_sha256) != 64:
            raise ValueError("payload_sha256 must be a SHA256 hex digest")
        try:
            int(self.payload_sha256, 16)
        except ValueError as exc:
            raise ValueError("payload_sha256 must be a SHA256 hex digest") from exc
        if not isinstance(self.sample_tuple_count, int) or self.sample_tuple_count < 0:
            raise ValueError("sample_tuple_count must be a nonnegative integer")
        if (
            not isinstance(self.estimated_total_rows, (int, float))
            or not math.isfinite(float(self.estimated_total_rows))
            or self.estimated_total_rows < 0
        ):
            raise ValueError("estimated_total_rows must be nonnegative")
        source = _mapping(self.postgres_source, "postgres_source")
        for key in ("repository", "source_commit", "upstream_base_commit", "server_version"):
            if not isinstance(source.get(key), str) or not source[key].strip():
                raise ValueError(f"postgres_source.{key} is required")
        acquisition = _mapping(self.acquisition, "acquisition")
        if acquisition.get("mechanism") != "postgres_analyze_sample_cache":
            raise ValueError("acquisition.mechanism is invalid")
        _mapping(self.lineage, "lineage")

    def to_dict(self) -> dict[str, Any]:
        value = {
            "artifact_id": self.artifact_id,
            "benchmark_id": self.benchmark_id,
            "relation_identity": self.relation_identity,
            "parent_data_artifact_id": self.parent_data_artifact_id,
            "loaded_instance_id": self.loaded_instance_id,
            "format": self.format,
            "format_version": self.format_version,
            "payload_relative_path": self.payload_relative_path,
            "payload_sha256": self.payload_sha256,
            "sample_tuple_count": self.sample_tuple_count,
            "estimated_total_rows": self.estimated_total_rows,
            "postgres_source": dict(self.postgres_source),
            "acquisition": dict(self.acquisition),
            "schema_fingerprint": self.schema_fingerprint,
            "lineage": dict(self.lineage),
        }
        json.dumps(value, sort_keys=True)
        return value

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, indent=2) + "\n"

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SampleArtifact":
        return cls(
            artifact_id=value["artifact_id"],
            benchmark_id=value["benchmark_id"],
            relation_identity=value["relation_identity"],
            parent_data_artifact_id=value["parent_data_artifact_id"],
            loaded_instance_id=value["loaded_instance_id"],
            format=value["format"],
            format_version=value["format_version"],
            payload_relative_path=value["payload_relative_path"],
            payload_sha256=value["payload_sha256"],
            sample_tuple_count=value["sample_tuple_count"],
            estimated_total_rows=value["estimated_total_rows"],
            postgres_source=value["postgres_source"],
            acquisition=value["acquisition"],
            schema_fingerprint=value["schema_fingerprint"],
            lineage=value.get("lineage", {}),
        )

    @staticmethod
    def sha256(path: str) -> str:
        digest = hashlib.sha256()
        with open(path, "rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()


# A short module name is useful to downstream callers while retaining the
# explicit plural module used by the package.
