"""Immutable metadata for one fixed-sample native statistics repository."""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import re
from typing import Any, Mapping


STATES = frozenset({"PRESENT", "ABSENT_NATIVE"})


def _json_mapping(value: Mapping[str, Any], name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be a mapping")
    result = dict(value)
    json.dumps(result, sort_keys=True)
    return result


@dataclass(frozen=True)
class CandidatePayloadState:
    candidate_id: str
    kind: str
    columns: tuple[str, ...]
    state: str
    payload_fingerprint: str | None
    native_metadata: Mapping[str, Any] = field(default_factory=dict)
    acquisition_status: str = "SUCCESS"
    acquisition_error: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.candidate_id, str) or not self.candidate_id.strip():
            raise ValueError("candidate_id must be nonempty")
        if self.kind not in {"mcv", "fd"}:
            raise ValueError("candidate kind must be mcv or fd")
        if not isinstance(self.columns, (tuple, list)) or len(self.columns) < 2:
            raise ValueError("candidate state requires columns")
        if isinstance(self.columns, list):
            object.__setattr__(self, "columns", tuple(self.columns))
        if self.state not in STATES:
            raise ValueError(f"invalid native candidate state: {self.state}")
        if self.state == "PRESENT":
            if not isinstance(self.payload_fingerprint, str) or not re.fullmatch(r"[0-9a-f]{64}", self.payload_fingerprint):
                raise ValueError("PRESENT candidate requires a SHA256 payload fingerprint")
        elif self.payload_fingerprint is not None:
            raise ValueError("ABSENT_NATIVE candidate cannot contain a payload fingerprint")
        if self.acquisition_status not in {"SUCCESS", "ERROR"}:
            raise ValueError("acquisition_status must be SUCCESS or ERROR")
        if self.acquisition_status == "ERROR" and not self.acquisition_error:
            raise ValueError("acquisition errors require acquisition_error")
        _json_mapping(self.native_metadata, "native_metadata")

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "kind": self.kind,
            "columns": list(self.columns),
            "state": self.state,
            "payload_fingerprint": self.payload_fingerprint,
            "native_metadata": dict(self.native_metadata),
            "acquisition_status": self.acquisition_status,
            "acquisition_error": self.acquisition_error,
        }

    def canonical_dict(self) -> dict[str, Any]:
        """Semantic content; generated PostgreSQL OIDs and names are excluded."""
        return {
            "candidate_id": self.candidate_id,
            "kind": self.kind,
            "columns": list(self.columns),
            "state": self.state,
            "payload_fingerprint": self.payload_fingerprint,
            "acquisition_status": self.acquisition_status,
        }


@dataclass(frozen=True)
class StatisticsRepositoryArtifact:
    artifact_id: str
    benchmark_id: str
    relation_identity: str
    sample_artifact_id: str
    sample_payload_sha256: str
    candidate_catalog: Mapping[str, Any]
    postgres_source: Mapping[str, Any]
    statistics_target: Mapping[str, Any]
    ordinary_statistics_fingerprint: str
    candidate_states: tuple[CandidatePayloadState, ...]
    repository_digest: str
    lineage: Mapping[str, Any]

    @classmethod
    def create(cls, **fields: Any) -> "StatisticsRepositoryArtifact":
        """Construct an artifact and derive its semantic digest canonically."""
        provisional = object.__new__(cls)
        for name, value in fields.items():
            object.__setattr__(provisional, name, value)
        digest = provisional.compute_repository_digest()
        fields["repository_digest"] = digest
        return cls(**fields)

    def __post_init__(self) -> None:
        for name in (
            "artifact_id", "benchmark_id", "relation_identity", "sample_artifact_id",
            "sample_payload_sha256", "ordinary_statistics_fingerprint", "repository_digest",
        ):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise ValueError(f"{name} must be nonempty")
        for name in ("sample_payload_sha256", "ordinary_statistics_fingerprint", "repository_digest"):
            if not re.fullmatch(r"[0-9a-f]{64}", getattr(self, name)):
                raise ValueError(f"{name} must be a lowercase SHA256 digest")
        catalog = _json_mapping(self.candidate_catalog, "candidate_catalog")
        for key in ("catalog_id", "catalog_sha256", "candidate_count"):
            if key not in catalog:
                raise ValueError(f"candidate_catalog.{key} is required")
        if not isinstance(catalog["catalog_id"], str) or not catalog["catalog_id"].strip():
            raise ValueError("candidate_catalog.catalog_id must be nonempty")
        if not re.fullmatch(r"[0-9a-f]{64}", str(catalog["catalog_sha256"])):
            raise ValueError("candidate_catalog.catalog_sha256 must be SHA256")
        if catalog["candidate_count"] != len(self.candidate_states):
            raise ValueError("candidate catalog count does not match repository states")
        ids = [item.candidate_id for item in self.candidate_states]
        if len(ids) != len(set(ids)):
            raise ValueError("repository candidate IDs must be unique")
        source = _json_mapping(self.postgres_source, "postgres_source")
        for key in ("repository", "source_commit", "upstream_base_commit", "server_version", "binary_sha256"):
            if not isinstance(source.get(key), str) or not source[key].strip():
                raise ValueError(f"postgres_source.{key} is required")
        target = _json_mapping(self.statistics_target, "statistics_target")
        if target.get("requested") != 100 or target.get("effective") != 100:
            raise ValueError("statistics target must record requested/effective 100")
        _json_mapping(self.lineage, "lineage")
        expected = self.compute_repository_digest()
        if expected != self.repository_digest:
            raise ValueError("repository_digest does not match canonical repository content")

    def canonical_dict(self) -> dict[str, Any]:
        catalog = dict(self.candidate_catalog)
        return {
            "format": "statistics-repository-v1",
            "benchmark_id": self.benchmark_id,
            "relation_identity": self.relation_identity,
            "sample_artifact_id": self.sample_artifact_id,
            "sample_payload_sha256": self.sample_payload_sha256,
            "candidate_catalog": {
                "catalog_id": catalog["catalog_id"],
                "catalog_sha256": catalog["catalog_sha256"],
                "candidate_count": catalog["candidate_count"],
            },
            "postgres_source": dict(self.postgres_source),
            "statistics_target": dict(self.statistics_target),
            "ordinary_statistics_fingerprint": self.ordinary_statistics_fingerprint,
            "candidate_states": [item.canonical_dict() for item in sorted(self.candidate_states, key=lambda x: x.candidate_id)],
            "lineage": dict(self.lineage),
        }

    def compute_repository_digest(self) -> str:
        raw = json.dumps(self.canonical_dict(), sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(raw).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        value = {
            "artifact_id": self.artifact_id,
            "benchmark_id": self.benchmark_id,
            "relation_identity": self.relation_identity,
            "sample_artifact_id": self.sample_artifact_id,
            "sample_payload_sha256": self.sample_payload_sha256,
            "candidate_catalog": dict(self.candidate_catalog),
            "postgres_source": dict(self.postgres_source),
            "statistics_target": dict(self.statistics_target),
            "ordinary_statistics_fingerprint": self.ordinary_statistics_fingerprint,
            "candidate_states": [item.to_dict() for item in self.candidate_states],
            "repository_digest": self.repository_digest,
            "lineage": dict(self.lineage),
        }
        json.dumps(value, sort_keys=True)
        return value

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, indent=2) + "\n"

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "StatisticsRepositoryArtifact":
        return cls(
            artifact_id=value["artifact_id"], benchmark_id=value["benchmark_id"],
            relation_identity=value["relation_identity"], sample_artifact_id=value["sample_artifact_id"],
            sample_payload_sha256=value["sample_payload_sha256"], candidate_catalog=value["candidate_catalog"],
            postgres_source=value["postgres_source"], statistics_target=value["statistics_target"],
            ordinary_statistics_fingerprint=value["ordinary_statistics_fingerprint"],
            candidate_states=tuple(CandidatePayloadState(**item) for item in value["candidate_states"]),
            repository_digest=value["repository_digest"], lineage=value["lineage"],
        )


__all__ = ["CandidatePayloadState", "StatisticsRepositoryArtifact", "STATES"]
