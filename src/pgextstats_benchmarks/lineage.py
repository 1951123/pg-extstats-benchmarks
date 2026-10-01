"""Small, serializable artifact lineage records."""
from dataclasses import dataclass
import json
import re


@dataclass(frozen=True)
class Artifact:
    """One immutable artifact and the operation that produced it."""

    artifact_id: str
    artifact_type: str
    parent_artifacts: tuple[str, ...]
    producing_tool: str
    producing_commit: str | None
    digest: str

    def __post_init__(self) -> None:
        if not self.artifact_id.strip() or not self.artifact_type.strip():
            raise ValueError("artifact_id and artifact_type are required")
        if not self.producing_tool.strip():
            raise ValueError("producing_tool is required")
        if any(not parent.strip() for parent in self.parent_artifacts):
            raise ValueError("parent artifact IDs must be nonempty")
        if re.fullmatch(r"[0-9a-f]{64}", self.digest) is None:
            raise ValueError("digest must be lowercase SHA256 hex")

    def to_dict(self) -> dict:
        return {
            "artifact_id": self.artifact_id,
            "artifact_type": self.artifact_type,
            "parent_artifacts": list(self.parent_artifacts),
            "producing_tool": self.producing_tool,
            "producing_commit": self.producing_commit,
            "digest": self.digest,
        }

    @classmethod
    def from_dict(cls, value: dict) -> "Artifact":
        fields = dict(value)
        fields["parent_artifacts"] = tuple(fields["parent_artifacts"])
        return cls(**fields)


@dataclass(frozen=True)
class ArtifactLineage:
    """A collection of artifacts with parent-reference validation."""

    artifacts: tuple[Artifact, ...]

    def __post_init__(self) -> None:
        ids = [artifact.artifact_id for artifact in self.artifacts]
        if len(ids) != len(set(ids)):
            raise ValueError("artifact IDs must be unique")
        known = set(ids)
        for artifact in self.artifacts:
            unknown = set(artifact.parent_artifacts) - known
            if unknown:
                raise ValueError(f"unknown parent artifacts: {sorted(unknown)}")

    def to_dict(self) -> dict:
        return {"artifacts": [artifact.to_dict() for artifact in self.artifacts]}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, indent=2) + "\n"

    @classmethod
    def from_dict(cls, value: dict) -> "ArtifactLineage":
        return cls(tuple(Artifact.from_dict(item) for item in value["artifacts"]))
