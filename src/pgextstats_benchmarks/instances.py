"""Serializable metadata for a loaded benchmark instance."""
from dataclasses import dataclass, field
from typing import Any, Mapping
import json


@dataclass(frozen=True)
class LoadedInstance:
    """A logical materialized instance, without a database handle."""

    instance_id: str
    benchmark_id: str
    loader_type: str
    status: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("instance_id", "benchmark_id", "loader_type", "status"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a nonempty string")
        if not isinstance(self.metadata, Mapping):
            raise TypeError("instance metadata must be a mapping")

    def to_dict(self) -> dict[str, Any]:
        value = {
            "instance_id": self.instance_id,
            "benchmark_id": self.benchmark_id,
            "loader_type": self.loader_type,
            "status": self.status,
            "metadata": dict(self.metadata),
        }
        json.dumps(value, sort_keys=True)
        return value

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, indent=2) + "\n"

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LoadedInstance":
        return cls(
            instance_id=value["instance_id"],
            benchmark_id=value["benchmark_id"],
            loader_type=value["loader_type"],
            status=value["status"],
            metadata=value.get("metadata", {}),
        )


# Short spelling for callers that prefer the domain term.
Instance = LoadedInstance
