"""Serializable lineage over the canonical :class:`artifacts.Artifact`."""
from dataclasses import dataclass
import json

from .artifacts import Artifact


@dataclass(frozen=True)
class Lineage:
    """A collection of artifacts with validated parent references."""

    artifacts: tuple[Artifact, ...]

    def __post_init__(self) -> None:
        if not all(isinstance(artifact, Artifact) for artifact in self.artifacts):
            raise TypeError("lineage entries must be Artifact objects")
        ids = [artifact.id for artifact in self.artifacts]
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
    def from_dict(cls, value: dict) -> "Lineage":
        return cls(tuple(Artifact.from_dict(item) for item in value["artifacts"]))


# Contract-v1 callers used this name; retain it as a compatibility entry point
# while keeping Lineage as the single implementation and model.
ArtifactLineage = Lineage
