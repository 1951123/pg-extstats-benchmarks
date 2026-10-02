"""Serializable exact-cardinality truth artifacts."""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any, Mapping

from .query_runner import QueryExecutionResult


@dataclass(frozen=True)
class TruthArtifact:
    benchmark_id: str
    workload_id: str
    query_results: tuple[QueryExecutionResult, ...]
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("benchmark_id", "workload_id"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise ValueError(f"{name} must be a nonempty string")
        if not isinstance(self.query_results, (list, tuple)):
            raise TypeError("query_results must be a list or tuple")
        if not all(isinstance(result, QueryExecutionResult) for result in self.query_results):
            raise TypeError("query_results must contain QueryExecutionResult objects")
        if len({result.query_id for result in self.query_results}) != len(self.query_results):
            raise ValueError("truth query IDs must be unique")
        if not isinstance(self.metadata, Mapping):
            raise TypeError("truth metadata must be a mapping")
        if isinstance(self.query_results, list):
            object.__setattr__(self, "query_results", tuple(self.query_results))

    @property
    def query_count(self) -> int:
        return len(self.query_results)

    @property
    def successful_queries(self) -> int:
        return sum(result.status == "PASS" for result in self.query_results)

    def to_dict(self) -> dict[str, Any]:
        value = {
            "benchmark_id": self.benchmark_id,
            "workload_id": self.workload_id,
            "query_results": [result.to_dict() for result in self.query_results],
            "metadata": dict(self.metadata),
        }
        json.dumps(value, sort_keys=True)
        return value

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, indent=2) + "\n"

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TruthArtifact":
        return cls(
            benchmark_id=value["benchmark_id"],
            workload_id=value["workload_id"],
            query_results=tuple(
                QueryExecutionResult.from_dict(item)
                for item in value.get("query_results", ())
            ),
            metadata=value.get("metadata", {}),
        )
