"""Explicit, immutable candidate-subset configuration contract."""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import re
from typing import Any, Mapping

from .statistics_repository import StatisticsRepositoryArtifact, STATES


_DIGEST = re.compile(r"[0-9a-f]{64}")


def _canonical(value: Mapping[str, Any]) -> str:
    return json.dumps(dict(value), sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class StatisticsConfiguration:
    """One explicit subset of PRESENT candidates from one repository."""

    configuration_id: str
    repository_artifact_id: str
    repository_digest: str
    selected_candidate_ids: tuple[str, ...]
    relation_identity: str
    effective_statistics_target: int = 100
    selected_candidate_count: int | None = None
    configuration_digest: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    lineage: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("configuration_id", "repository_artifact_id", "repository_digest"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be nonempty")
        if not isinstance(self.relation_identity, str):
            raise TypeError("relation_identity must be a string")
        if not _DIGEST.fullmatch(self.repository_digest):
            raise ValueError("repository_digest must be a lowercase SHA256 digest")
        if not isinstance(self.selected_candidate_ids, (tuple, list)):
            raise TypeError("selected_candidate_ids must be a list or tuple")
        selected = tuple(str(value) for value in self.selected_candidate_ids)
        if any(not value.strip() for value in selected):
            raise ValueError("selected candidate IDs must be nonempty")
        if len(set(selected)) != len(selected):
            raise ValueError("selected candidate IDs must be unique")
        ordered = tuple(sorted(selected))
        if selected != ordered:
            object.__setattr__(self, "selected_candidate_ids", ordered)
        count = len(ordered)
        if self.selected_candidate_count is None:
            object.__setattr__(self, "selected_candidate_count", count)
        elif self.selected_candidate_count != count:
            raise ValueError("selected_candidate_count does not match selected_candidate_ids")
        if not isinstance(self.effective_statistics_target, int) or self.effective_statistics_target != 100:
            raise ValueError("effective_statistics_target must be the fixed target 100")
        if not isinstance(self.metadata, Mapping) or not isinstance(self.lineage, Mapping):
            raise TypeError("configuration metadata and lineage must be mappings")
        digest = self.compute_configuration_digest()
        if self.configuration_digest:
            if not _DIGEST.fullmatch(self.configuration_digest):
                raise ValueError("configuration_digest must be a lowercase SHA256 digest")
            if self.configuration_digest != digest:
                raise ValueError("configuration_digest does not match canonical content")
        else:
            object.__setattr__(self, "configuration_digest", digest)

    def canonical_dict(self) -> dict[str, Any]:
        """Return semantic content; metadata, paths, and timestamps are excluded."""

        return {
            "format": "statistics-configuration-v1",
            "configuration_id": self.configuration_id,
            "repository_artifact_id": self.repository_artifact_id,
            "repository_digest": self.repository_digest,
            "selected_candidate_ids": list(self.selected_candidate_ids),
            "relation_identity": self.relation_identity,
            "effective_statistics_target": self.effective_statistics_target,
        }

    def compute_configuration_digest(self) -> str:
        return hashlib.sha256(_canonical(self.canonical_dict()).encode()).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        value = {
            "configuration_id": self.configuration_id,
            "repository_artifact_id": self.repository_artifact_id,
            "repository_digest": self.repository_digest,
            "selected_candidate_ids": list(self.selected_candidate_ids),
            "selected_candidate_count": self.selected_candidate_count,
            "relation_identity": self.relation_identity,
            "effective_statistics_target": self.effective_statistics_target,
            "configuration_digest": self.configuration_digest,
            "metadata": dict(self.metadata),
            "lineage": dict(self.lineage),
        }
        json.dumps(value, sort_keys=True)
        return value

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, indent=2) + "\n"

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "StatisticsConfiguration":
        return cls(
            configuration_id=value["configuration_id"],
            repository_artifact_id=value["repository_artifact_id"],
            repository_digest=value["repository_digest"],
            selected_candidate_ids=tuple(value.get("selected_candidate_ids", ())),
            selected_candidate_count=value.get("selected_candidate_count"),
            relation_identity=value.get("relation_identity", ""),
            effective_statistics_target=value.get("effective_statistics_target", 100),
            configuration_digest=value.get("configuration_digest", ""),
            metadata=value.get("metadata", {}),
            lineage=value.get("lineage", {}),
        )

    @classmethod
    def from_file(cls, path: str) -> "StatisticsConfiguration":
        with open(path, "r", encoding="utf-8") as stream:
            return cls.from_dict(json.load(stream))

    def validate_against(self, repository: StatisticsRepositoryArtifact) -> None:
        if not isinstance(repository, StatisticsRepositoryArtifact):
            raise TypeError("repository must be a StatisticsRepositoryArtifact")
        if self.repository_artifact_id != repository.artifact_id:
            raise ValueError("configuration repository artifact ID does not match")
        if self.repository_digest != repository.repository_digest:
            raise ValueError("configuration repository digest does not match")
        if self.relation_identity and self.relation_identity != repository.relation_identity:
            raise ValueError("configuration relation does not match repository")
        effective = repository.statistics_target.get("effective")
        if self.effective_statistics_target != effective:
            raise ValueError("configuration target does not match repository effective target")
        states = {item.candidate_id: item for item in repository.candidate_states}
        unknown = [item for item in self.selected_candidate_ids if item not in states]
        if unknown:
            raise ValueError(f"configuration references unknown candidates: {unknown}")
        absent = [
            item for item in self.selected_candidate_ids
            if states[item].state == "ABSENT_NATIVE"
        ]
        if absent:
            raise ValueError(f"configuration cannot activate ABSENT_NATIVE candidates: {absent}")
        if any(states[item].state not in STATES for item in self.selected_candidate_ids):
            raise ValueError("configuration contains an invalid repository state")


__all__ = ["StatisticsConfiguration"]
