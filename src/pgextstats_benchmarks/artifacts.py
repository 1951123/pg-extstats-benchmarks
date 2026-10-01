"""Serializable, metadata-only benchmark artifacts."""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping
import json

ARTIFACT_TYPES = frozenset(
    {"raw_dataset", "prepared_dataset", "workload", "truth", "schema", "other"}
)


@dataclass(frozen=True)
class Artifact:
    """A logical artifact; constructing one never reads or writes its path."""

    id: str
    type: str
    path: str | Path | None = None
    digest: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    created_at: str | None = None
    created_by: str | None = None
    creation_info: Mapping[str, Any] = field(default_factory=dict)
    parent_artifacts: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id.strip():
            raise ValueError("artifact id must be a nonempty string")
        if not isinstance(self.type, str) or not self.type.strip():
            raise ValueError("artifact type must be a nonempty string")
        if self.path is not None and not isinstance(self.path, (str, Path)):
            raise TypeError("artifact path must be a string, Path, or None")
        if self.digest is not None and (
            not isinstance(self.digest, str) or not self.digest.strip()
        ):
            raise ValueError("artifact digest must be a nonempty string or None")
        if not isinstance(self.metadata, Mapping):
            raise TypeError("artifact metadata must be a mapping")
        if not isinstance(self.creation_info, Mapping):
            raise TypeError("creation_info must be a mapping")
        if any(not isinstance(parent, str) or not parent.strip() for parent in self.parent_artifacts):
            raise ValueError("parent artifact IDs must be nonempty strings")

    @property
    def artifact_id(self) -> str:
        """Compatibility spelling used by the original lineage model."""
        return self.id

    @property
    def artifact_type(self) -> str:
        """Compatibility spelling used by the original lineage model."""
        return self.type

    def to_dict(self) -> dict[str, Any]:
        value = {
            "id": self.id,
            "type": self.type,
            "path": str(self.path) if self.path is not None else None,
            "digest": self.digest,
            "metadata": dict(self.metadata),
            "created_at": self.created_at,
            "created_by": self.created_by,
            "creation_info": dict(self.creation_info),
            "parent_artifacts": list(self.parent_artifacts),
        }
        # Validate serializability now, rather than during an eventual run write.
        json.dumps(value, sort_keys=True)
        return value

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, indent=2) + "\n"

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Artifact":
        fields = dict(value)
        fields["parent_artifacts"] = tuple(fields.get("parent_artifacts", ()))
        return cls(**fields)
