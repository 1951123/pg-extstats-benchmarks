"""Stable workload and query models with semantics-preserving normalization."""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True)
class Query:
    """One query with a deterministic identifier and verbatim SQL text."""

    query_id: str
    sql: str

    def __post_init__(self) -> None:
        if not isinstance(self.query_id, str) or not self.query_id.strip():
            raise ValueError("query_id must be a nonempty string")
        if not isinstance(self.sql, str) or not self.sql.strip():
            raise ValueError("query SQL must be nonempty")

    def to_dict(self) -> dict[str, str]:
        return {"query_id": self.query_id, "sql": self.sql}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Query":
        return cls(query_id=value["query_id"], sql=value["sql"])


@dataclass(frozen=True)
class Workload:
    """An ordered, normalized workload and its source provenance."""

    workload_id: str
    queries: tuple[Query, ...]
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.workload_id, str) or not self.workload_id.strip():
            raise ValueError("workload_id must be a nonempty string")
        if not isinstance(self.queries, (list, tuple)):
            raise TypeError("queries must be a list or tuple")
        if not all(isinstance(query, Query) for query in self.queries):
            raise TypeError("queries must contain Query objects")
        if len({query.query_id for query in self.queries}) != len(self.queries):
            raise ValueError("query IDs must be unique")
        if not isinstance(self.metadata, Mapping):
            raise TypeError("workload metadata must be a mapping")
        if isinstance(self.queries, list):
            object.__setattr__(self, "queries", tuple(self.queries))

    @property
    def query_count(self) -> int:
        return len(self.queries)

    def to_dict(self) -> dict[str, Any]:
        value = {
            "workload_id": self.workload_id,
            "queries": [query.to_dict() for query in self.queries],
            "metadata": dict(self.metadata),
        }
        json.dumps(value, sort_keys=True)
        return value

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, indent=2) + "\n"

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Workload":
        return cls(
            workload_id=value["workload_id"],
            queries=tuple(Query.from_dict(item) for item in value.get("queries", ())),
            metadata=value.get("metadata", {}),
        )


def normalize_workload(
    source: str | bytes,
    *,
    workload_id: str,
    source_checksum: str | None = None,
    query_id_format: str = "qNNN",
    metadata_source_checksum: str | None = None,
) -> Workload:
    """Normalize Census's line-oriented ``SQL||source-cardinality`` file.

    The SQL portion of each line is retained byte-for-byte apart from its line
    ending. The ``||`` suffix is source metadata, not SQL, and is excluded from
    execution without changing any predicate or expression.
    """

    if isinstance(source, bytes):
        raw = source
        text = source.decode("utf-8")
    elif isinstance(source, str):
        text = source
        raw = source.encode("utf-8")
    else:
        raise TypeError("workload source must be text or bytes")
    checksum = hashlib.sha256(raw).hexdigest()
    if source_checksum is not None and checksum != source_checksum:
        raise ValueError(f"workload checksum mismatch: expected {source_checksum}, got {checksum}")

    queries: list[Query] = []
    source_lines = 0
    if query_id_format == "qNNN":
        query_id_width = 3
    elif query_id_format == "qNNNN":
        query_id_width = 4
    else:
        raise ValueError("unsupported query_id_format")
    for source_lines, line in enumerate(text.splitlines(), start=1):
        if not line:
            continue
        sql, separator, _source_cardinality = line.partition("||")
        if not separator:
            # A generic workload may contain plain SQL lines. Census's source
            # carries an additional ``||`` cardinality suffix, which is
            # removed above when present.
            sql = line
        if not sql.strip().upper().startswith("SELECT"):
            raise ValueError(f"workload line {source_lines} is not a SELECT query")
        queries.append(Query(query_id=f"q{len(queries) + 1:0{query_id_width}d}", sql=sql))
    return Workload(
        workload_id=workload_id,
        queries=tuple(queries),
        metadata={
            "source_checksum": metadata_source_checksum or checksum,
            "source_bytes": len(raw),
            "source_line_count": source_lines,
            "query_count": len(queries),
            "normalization": "preserve SELECT text; remove only || source-cardinality suffix",
            "query_id_format": query_id_format,
        },
    )


def load_workload_artifact(artifact_path: str | Path) -> Workload:
    """Read a normalized workload artifact directory without changing it."""

    root = Path(artifact_path).expanduser().resolve()
    manifest_path = root / "manifest.json"
    query_path = root / "query.sql"
    if not manifest_path.is_file() or not query_path.is_file():
        raise FileNotFoundError(f"workload artifact is incomplete: {root}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    # DMV preserves the original source query separately and stores the
    # checksum of the normalized executable query in ``sha256``.  Legacy
    # artifacts continue to use ``source_checksum`` for query.sql itself.
    normalized_checksum = manifest.get("normalized_sha256", manifest.get("sha256"))
    return normalize_workload(
        query_path.read_bytes(),
        workload_id=manifest["artifact_id"],
        source_checksum=normalized_checksum,
        query_id_format=manifest.get("query_id_format", "qNNN"),
        metadata_source_checksum=manifest.get("source_checksum", normalized_checksum),
    )
