"""Immutable native planner estimate artifacts."""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import math
import re
from typing import Any, Mapping

from .workload_executor import Workload


_DIGEST = re.compile(r"[0-9a-f]{64}")
_STATUSES = frozenset({"PASS", "UNSUPPORTED", "ERROR"})


def workload_digest(workload: Workload) -> str:
    semantic = {
        "workload_id": workload.workload_id,
        "queries": [{"query_id": q.query_id, "sql": q.sql} for q in workload.queries],
    }
    raw = json.dumps(semantic, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class QueryEstimate:
    query_id: str
    status: str
    estimated_rows: float | None = None
    plan_fingerprint: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.query_id, str) or not self.query_id.strip():
            raise ValueError("query_id must be nonempty")
        if self.status not in _STATUSES:
            raise ValueError("query estimate status must be PASS, UNSUPPORTED, or ERROR")
        if self.status == "PASS":
            if not isinstance(self.estimated_rows, (int, float)) or isinstance(self.estimated_rows, bool):
                raise ValueError("PASS query estimate requires estimated_rows")
            if not math.isfinite(float(self.estimated_rows)) or float(self.estimated_rows) < 0:
                raise ValueError("estimated_rows must be finite and nonnegative")
        elif self.estimated_rows is not None:
            raise ValueError("non-PASS query estimate cannot contain estimated_rows")
        if not isinstance(self.metadata, Mapping):
            raise TypeError("query estimate metadata must be a mapping")

    def to_dict(self) -> dict[str, Any]:
        value = {
            "query_id": self.query_id,
            "status": self.status,
            "estimated_rows": self.estimated_rows,
            "plan_fingerprint": self.plan_fingerprint,
            "metadata": dict(self.metadata),
        }
        json.dumps(value, sort_keys=True)
        return value

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "QueryEstimate":
        return cls(
            query_id=value["query_id"], status=value["status"],
            estimated_rows=value.get("estimated_rows"),
            plan_fingerprint=value.get("plan_fingerprint"), metadata=value.get("metadata", {}),
        )

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "query_id": self.query_id,
            "status": self.status,
            "estimated_rows": self.estimated_rows,
        }


@dataclass(frozen=True)
class EstimateArtifact:
    artifact_id: str
    benchmark_id: str
    workload_id: str
    workload_digest: str
    repository_artifact_id: str
    repository_digest: str
    configuration_id: str
    configuration_digest: str
    relation_identity: str
    postgres_source: Mapping[str, Any]
    query_estimates: tuple[QueryEstimate, ...]
    query_count: int
    successful_count: int
    failed_count: int
    estimate_digest: str
    lineage: Mapping[str, Any]
    status: str = "PASS"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def create(cls, **fields: Any) -> "EstimateArtifact":
        provisional = object.__new__(cls)
        for name, value in fields.items():
            object.__setattr__(provisional, name, value)
        estimates = tuple(fields["query_estimates"])
        status = fields.get("status") or cls.derive_status(estimates)
        fields["status"] = status
        fields["estimate_digest"] = provisional.compute_estimate_digest()
        return cls(**fields)

    @staticmethod
    def derive_status(results: tuple[QueryEstimate, ...] | list[QueryEstimate]) -> str:
        statuses = {item.status for item in results}
        if "ERROR" in statuses:
            return "ERROR"
        if "UNSUPPORTED" in statuses:
            return "UNSUPPORTED"
        return "PASS"

    def __post_init__(self) -> None:
        for name in (
            "artifact_id", "benchmark_id", "workload_id", "repository_artifact_id",
            "configuration_id", "relation_identity",
        ):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise ValueError(f"{name} must be nonempty")
        for name in ("workload_digest", "repository_digest", "configuration_digest", "estimate_digest"):
            if not isinstance(getattr(self, name), str) or not _DIGEST.fullmatch(getattr(self, name)):
                raise ValueError(f"{name} must be a lowercase SHA256 digest")
        if not isinstance(self.postgres_source, Mapping) or not isinstance(self.lineage, Mapping):
            raise TypeError("postgres_source and lineage must be mappings")
        for key in ("repository", "source_commit", "upstream_base_commit", "binary_sha256"):
            if not isinstance(self.postgres_source.get(key), str) or not self.postgres_source[key].strip():
                raise ValueError(f"postgres_source.{key} is required")
        if not isinstance(self.postgres_source.get("server_version", self.postgres_source.get("version")), str) or not self.postgres_source.get("server_version", self.postgres_source.get("version")).strip():
            raise ValueError("postgres_source.server_version or postgres_source.version is required")
        if not isinstance(self.query_estimates, (tuple, list)):
            raise TypeError("query_estimates must be a list or tuple")
        if not all(isinstance(item, QueryEstimate) for item in self.query_estimates):
            raise TypeError("query_estimates must contain QueryEstimate objects")
        if len({item.query_id for item in self.query_estimates}) != len(self.query_estimates):
            raise ValueError("query estimate IDs must be unique")
        if isinstance(self.query_estimates, list):
            object.__setattr__(self, "query_estimates", tuple(self.query_estimates))
        if self.query_count != len(self.query_estimates):
            raise ValueError("query_count does not match query_estimates")
        successful = sum(item.status == "PASS" for item in self.query_estimates)
        failed = sum(item.status == "ERROR" for item in self.query_estimates)
        if self.successful_count != successful or self.failed_count != failed:
            raise ValueError("estimate status counts do not match query_estimates")
        if self.status not in _STATUSES or self.status != self.derive_status(self.query_estimates):
            raise ValueError("estimate artifact status does not match query result statuses")
        if self.compute_estimate_digest() != self.estimate_digest:
            raise ValueError("estimate_digest does not match canonical content")
        json.dumps(dict(self.metadata), sort_keys=True)

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "format": "estimate-artifact-v1",
            "benchmark_id": self.benchmark_id,
            "workload_id": self.workload_id,
            "workload_digest": self.workload_digest,
            "repository_artifact_id": self.repository_artifact_id,
            "repository_digest": self.repository_digest,
            "configuration_id": self.configuration_id,
            "configuration_digest": self.configuration_digest,
            "relation_identity": self.relation_identity,
            "query_estimates": [item.canonical_dict() for item in sorted(self.query_estimates, key=lambda x: x.query_id)],
        }

    def compute_estimate_digest(self) -> str:
        raw = json.dumps(self.canonical_dict(), sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(raw).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        value = {
            "artifact_id": self.artifact_id,
            "benchmark_id": self.benchmark_id,
            "workload_id": self.workload_id,
            "workload_digest": self.workload_digest,
            "repository_artifact_id": self.repository_artifact_id,
            "repository_digest": self.repository_digest,
            "configuration_id": self.configuration_id,
            "configuration_digest": self.configuration_digest,
            "relation_identity": self.relation_identity,
            "postgres_source": dict(self.postgres_source),
            "query_estimates": [item.to_dict() for item in self.query_estimates],
            "query_count": self.query_count,
            "successful_count": self.successful_count,
            "failed_count": self.failed_count,
            "estimate_digest": self.estimate_digest,
            "lineage": dict(self.lineage),
            "status": self.status,
            "metadata": dict(self.metadata),
        }
        json.dumps(value, sort_keys=True)
        return value

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, indent=2) + "\n"

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "EstimateArtifact":
        return cls(
            artifact_id=value["artifact_id"], benchmark_id=value["benchmark_id"],
            workload_id=value["workload_id"], workload_digest=value["workload_digest"],
            repository_artifact_id=value["repository_artifact_id"], repository_digest=value["repository_digest"],
            configuration_id=value["configuration_id"], configuration_digest=value["configuration_digest"],
            relation_identity=value["relation_identity"], postgres_source=value["postgres_source"],
            query_estimates=tuple(QueryEstimate.from_dict(item) for item in value.get("query_estimates", ())),
            query_count=value["query_count"], successful_count=value["successful_count"],
            failed_count=value["failed_count"], estimate_digest=value["estimate_digest"],
            lineage=value["lineage"], status=value.get("status", "PASS"), metadata=value.get("metadata", {}),
        )


__all__ = ["EstimateArtifact", "QueryEstimate", "workload_digest"]
