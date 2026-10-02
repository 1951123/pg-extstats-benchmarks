"""DBMS-independent workload execution contract."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import json
from typing import Any, Mapping

from .instances import LoadedInstance
from .workload_executor import Workload


@dataclass(frozen=True)
class QueryExecutionResult:
    """Outcome and exact cardinality metadata for one executed query."""

    query_id: str
    status: str
    execution_metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.query_id, str) or not self.query_id.strip():
            raise ValueError("query_id must be a nonempty string")
        if not isinstance(self.status, str) or not self.status.strip():
            raise ValueError("query status must be a nonempty string")
        if not isinstance(self.execution_metadata, Mapping):
            raise TypeError("execution metadata must be a mapping")

    @property
    def cardinality(self) -> int | None:
        value = self.execution_metadata.get("cardinality")
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    def to_dict(self) -> dict[str, Any]:
        value = {
            "query_id": self.query_id,
            "status": self.status,
            "execution_metadata": dict(self.execution_metadata),
        }
        if self.cardinality is not None:
            value["cardinality"] = self.cardinality
        json.dumps(value, sort_keys=True)
        return value

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "QueryExecutionResult":
        metadata = dict(value.get("execution_metadata", {}))
        if "cardinality" in value and "cardinality" not in metadata:
            metadata["cardinality"] = value["cardinality"]
        return cls(
            query_id=value["query_id"],
            status=value["status"],
            execution_metadata=metadata,
        )


class QueryRunner(ABC):
    """DBMS-specific execution boundary for an already loaded instance."""

    @abstractmethod
    def execute_workload(
        self, workload: Workload, instance: LoadedInstance
    ) -> tuple[QueryExecutionResult, ...]:
        raise NotImplementedError
