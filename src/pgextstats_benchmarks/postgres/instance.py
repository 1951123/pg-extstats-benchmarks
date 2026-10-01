"""Serializable metadata for one managed PostgreSQL database."""

from dataclasses import dataclass, field
import json
from typing import Any, Mapping


@dataclass(frozen=True)
class PostgresInstance:
    instance_id: str
    database_name: str
    status: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("instance_id", "database_name", "status"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a nonempty string")
        if not isinstance(self.metadata, Mapping):
            raise TypeError("instance metadata must be a mapping")

    def to_dict(self) -> dict[str, Any]:
        value = {
            "instance_id": self.instance_id,
            "database_name": self.database_name,
            "status": self.status,
            "metadata": dict(self.metadata),
        }
        json.dumps(value, sort_keys=True)
        return value

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, indent=2) + "\n"

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PostgresInstance":
        return cls(
            instance_id=value["instance_id"],
            database_name=value["database_name"],
            status=value["status"],
            metadata=value.get("metadata", {}),
        )

