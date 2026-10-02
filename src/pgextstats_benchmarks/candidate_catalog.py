"""Explicit candidate-catalog input for statistics repository acquisition.

This module deliberately contains no candidate generation or ranking logic.  A
catalog is an immutable, externally supplied description of the candidates to
materialize.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping


_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_CANDIDATE_ID = re.compile(r"^[A-Za-z0-9_.-]+$")
_KINDS = {"mcv": "mcv", "fd": "fd", "dependencies": "fd", "functional_dependency": "fd"}


def _relation(value: object) -> str:
    if not isinstance(value, str) or value.count(".") != 1:
        raise ValueError("relation identity must be schema.relation")
    schema, name = value.split(".")
    if not _IDENTIFIER.fullmatch(schema) or not _IDENTIFIER.fullmatch(name):
        raise ValueError(f"unsafe relation identity: {value!r}")
    return value


@dataclass(frozen=True)
class CandidateDefinition:
    """One explicit native extended-statistics definition."""

    candidate_id: str
    relation_identity: str
    kind: str
    columns: tuple[str, ...]
    statistics_target: int | None = None
    definition: Mapping[str, Any] = field(default_factory=dict)
    precedence_rank: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.candidate_id, str) or not _CANDIDATE_ID.fullmatch(self.candidate_id):
            raise ValueError(f"unsafe candidate_id: {self.candidate_id!r}")
        _relation(self.relation_identity)
        if self.kind not in {"mcv", "fd"}:
            raise ValueError("candidate kind must be mcv or fd")
        if not isinstance(self.columns, (tuple, list)) or len(self.columns) < 2:
            raise ValueError("candidate requires at least two columns")
        if len(set(self.columns)) != len(self.columns):
            raise ValueError(f"candidate columns must be unique: {self.candidate_id}")
        if any(not isinstance(column, str) or not _IDENTIFIER.fullmatch(column) for column in self.columns):
            raise ValueError(f"candidate columns must be safe identifiers: {self.candidate_id}")
        if self.statistics_target is not None and (
            not isinstance(self.statistics_target, int) or self.statistics_target <= 0
        ):
            raise ValueError("candidate statistics_target must be positive")
        if not isinstance(self.definition, Mapping):
            raise TypeError("candidate definition must be a mapping")
        json.dumps(dict(self.definition), sort_keys=True)
        if self.precedence_rank is not None and (
            not isinstance(self.precedence_rank, int) or self.precedence_rank < 0
        ):
            raise ValueError("precedence_rank must be nonnegative")

    def to_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "candidate_id": self.candidate_id,
            "relation_identity": self.relation_identity,
            "kind": self.kind,
            "columns": list(self.columns),
            "definition": dict(self.definition),
        }
        if self.statistics_target is not None:
            value["statistics_target"] = self.statistics_target
        if self.precedence_rank is not None:
            value["precedence_rank"] = self.precedence_rank
        return value


@dataclass(frozen=True)
class CandidateCatalog:
    """Validated explicit candidate catalog with deterministic ordering."""

    catalog_id: str
    relation_identity: str
    candidates: tuple[CandidateDefinition, ...]
    catalog_sha256: str
    statistics_target: int = 100

    def __post_init__(self) -> None:
        if not isinstance(self.catalog_id, str) or not self.catalog_id.strip():
            raise ValueError("catalog_id must be nonempty")
        _relation(self.relation_identity)
        if not isinstance(self.catalog_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", self.catalog_sha256):
            raise ValueError("catalog_sha256 must be a lowercase SHA256 digest")
        if not isinstance(self.statistics_target, int) or self.statistics_target != 100:
            raise ValueError("statistics_target must be the fixed contract target 100")
        if not isinstance(self.candidates, (tuple, list)) or not self.candidates:
            raise ValueError("candidate catalog must contain at least one candidate")
        if not all(isinstance(item, CandidateDefinition) for item in self.candidates):
            raise TypeError("candidates must contain CandidateDefinition objects")
        ids = [item.candidate_id for item in self.candidates]
        if len(ids) != len(set(ids)):
            raise ValueError("candidate IDs must be unique")
        relations = {item.relation_identity for item in self.candidates}
        if relations != {self.relation_identity}:
            raise ValueError("all candidates must target the catalog relation")
        if any(item.statistics_target not in (None, self.statistics_target) for item in self.candidates):
            raise ValueError("candidate statistics target disagrees with catalog target")
        ordered = tuple(sorted(self.candidates, key=lambda item: item.candidate_id))
        if tuple(self.candidates) != ordered:
            object.__setattr__(self, "candidates", ordered)

    @property
    def candidate_count(self) -> int:
        return len(self.candidates)

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "catalog_id": self.catalog_id,
            "relation_identity": self.relation_identity,
            "statistics_target": self.statistics_target,
            "candidates": [item.to_dict() for item in self.candidates],
        }

    @classmethod
    def from_file(cls, path: Path) -> "CandidateCatalog":
        source = Path(path).expanduser().resolve()
        if not source.is_file() or source.is_symlink():
            raise FileNotFoundError(f"candidate catalog is missing: {source}")
        raw = source.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"candidate catalog is not valid JSON: {source}") from exc
        catalog = cls.from_mapping(value, catalog_sha256=digest)
        declared = value.get("catalog_sha256") if isinstance(value, Mapping) else None
        if declared is not None and declared != digest:
            raise ValueError("declared catalog_sha256 does not match catalog bytes")
        return catalog

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any], *, catalog_sha256: str | None = None) -> "CandidateCatalog":
        if not isinstance(value, Mapping):
            raise TypeError("candidate catalog must be a mapping")
        raw_candidates = value.get("candidates")
        if not isinstance(raw_candidates, list):
            raise ValueError("candidate catalog requires a candidates list")
        relation = value.get("relation_identity", value.get("relation"))
        if relation is None and raw_candidates:
            relation = raw_candidates[0].get("relation_identity", raw_candidates[0].get("relation_name"))
        relation = _relation(relation)
        candidates: list[CandidateDefinition] = []
        for raw in raw_candidates:
            if not isinstance(raw, Mapping):
                raise TypeError("candidate entries must be mappings")
            kind_raw = raw.get("kind", raw.get("mechanism"))
            kind = _KINDS.get(kind_raw) if isinstance(kind_raw, str) else None
            if kind is None:
                raise ValueError("candidate mechanism must be mcv or fd/dependencies")
            columns = raw.get("columns", raw.get("attributes"))
            candidate_relation = raw.get("relation_identity", raw.get("relation_name", relation))
            candidates.append(
                CandidateDefinition(
                    candidate_id=raw["candidate_id"],
                    relation_identity=_relation(candidate_relation),
                    kind=kind,
                    columns=tuple(columns),
                    statistics_target=raw.get("statistics_target"),
                    definition=raw.get("definition", {}),
                    precedence_rank=raw.get("precedence_rank"),
                )
            )
        target = value.get("statistics_target", 100)
        if catalog_sha256 is None:
            canonical = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
            catalog_sha256 = hashlib.sha256(canonical).hexdigest()
        return cls(
            catalog_id=value.get("catalog_id", ""),
            relation_identity=relation,
            candidates=tuple(candidates),
            catalog_sha256=catalog_sha256,
            statistics_target=target,
        )


__all__ = ["CandidateCatalog", "CandidateDefinition"]
