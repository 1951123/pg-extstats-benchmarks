"""Deterministic, offline truth-versus-estimate evaluation artifacts.

This module deliberately contains no PostgreSQL, filesystem, network, or
advisor dependency.  It compares one already materialized TruthArtifact with
one EstimateArtifact and records only observations; it never ranks or selects
configurations.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import math
import re
from typing import Any, Mapping

from .estimate import EstimateArtifact, QueryEstimate
from .truth import TruthArtifact


_DIGEST = re.compile(r"[0-9a-f]{64}")
_STATUSES = frozenset({"PASS", "EXCLUDED", "ERROR"})


def q_error(estimate: float, truth: int | float) -> float:
    """Return the frozen advisor q-error convention.

    The advisor contract requires strictly positive truth and floors estimates
    below one to one.  A non-positive truth therefore raises ``ValueError``;
    the evaluator catches that condition and records an ``ERROR`` row rather
    than silently inventing a zero-cardinality policy.
    """

    if not isinstance(truth, (int, float)) or isinstance(truth, bool):
        raise ValueError("q-error requires numeric truth")
    if float(truth) <= 0:
        raise ValueError("q-error requires positive truth")
    if not isinstance(estimate, (int, float)) or isinstance(estimate, bool):
        raise ValueError("estimate must be finite and non-negative")
    if not math.isfinite(float(estimate)) or float(estimate) < 0:
        raise ValueError("estimate must be finite and non-negative")
    floored_estimate = max(float(estimate), 1.0)
    return max(floored_estimate / float(truth), float(truth) / floored_estimate)


def _digest_payload(value: Mapping[str, Any]) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _semantic_number(value: float | int | None) -> str | None:
    """Encode finite numbers deterministically for digest input.

    ``float.hex`` preserves the complete IEEE-754 value without display
    rounding and is stable across Python platforms.  Stored artifact fields
    remain ordinary JSON numbers for readability.
    """

    if value is None:
        return None
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("evaluation numbers must be finite")
    return number.hex()


def truth_digest(truth: TruthArtifact) -> str:
    """Digest semantic truth content, excluding runtime metadata and paths."""

    if not isinstance(truth, TruthArtifact):
        raise TypeError("truth must be a TruthArtifact")
    workload_digest = truth.workload_digest
    semantic = {
        "format": "truth-artifact-v1",
        "benchmark_id": truth.benchmark_id,
        "workload_id": truth.workload_id,
        "workload_digest": workload_digest,
        "query_results": [
            {
                "query_id": result.query_id,
                "status": result.status,
                "cardinality": result.cardinality,
            }
            for result in sorted(truth.query_results, key=lambda item: item.query_id)
        ],
    }
    return _digest_payload(semantic)


@dataclass(frozen=True)
class QueryEvaluation:
    """One query's comparable, excluded, or failed evaluation row."""

    query_id: str
    status: str
    truth_cardinality: int | None = None
    estimated_rows: float | None = None
    q_error: float | None = None
    message: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.query_id, str) or not self.query_id.strip():
            raise ValueError("query_id must be nonempty")
        if self.status not in _STATUSES:
            raise ValueError("evaluation status must be PASS, EXCLUDED, or ERROR")
        if self.truth_cardinality is not None:
            if isinstance(self.truth_cardinality, bool) or not isinstance(self.truth_cardinality, int) or self.truth_cardinality < 0:
                raise ValueError("truth_cardinality must be a nonnegative integer or None")
        if self.estimated_rows is not None:
            if isinstance(self.estimated_rows, bool) or not isinstance(self.estimated_rows, (int, float)):
                raise ValueError("estimated_rows must be numeric or None")
            if not math.isfinite(float(self.estimated_rows)) or float(self.estimated_rows) < 0:
                raise ValueError("estimated_rows must be finite and nonnegative")
        if self.q_error is not None:
            if not isinstance(self.q_error, (int, float)) or isinstance(self.q_error, bool):
                raise ValueError("q_error must be numeric or None")
            if not math.isfinite(float(self.q_error)) or float(self.q_error) < 1:
                raise ValueError("q_error must be finite and at least one")
        if self.status == "PASS":
            if self.truth_cardinality is None or self.estimated_rows is None or self.q_error is None:
                raise ValueError("PASS evaluation requires truth, estimate, and q_error")
        elif self.q_error is not None:
            raise ValueError("non-PASS evaluation cannot contain q_error")
        if not isinstance(self.message, str):
            raise TypeError("evaluation message must be a string")

    def to_dict(self) -> dict[str, Any]:
        value = {
            "query_id": self.query_id,
            "status": self.status,
            "truth_cardinality": self.truth_cardinality,
            "estimated_rows": self.estimated_rows,
            "q_error": self.q_error,
            "message": self.message,
        }
        json.dumps(value, sort_keys=True, allow_nan=False)
        return value

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "query_id": self.query_id,
            "status": self.status,
            "truth_cardinality": self.truth_cardinality,
            "estimated_rows": _semantic_number(self.estimated_rows),
            "q_error": _semantic_number(self.q_error),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "QueryEvaluation":
        return cls(
            query_id=value["query_id"],
            status=value["status"],
            truth_cardinality=value.get("truth_cardinality"),
            estimated_rows=value.get("estimated_rows"),
            q_error=value.get("q_error"),
            message=value.get("message", ""),
        )


def nearest_rank(values: list[float] | tuple[float, ...], probability: float) -> float | None:
    """Deterministic one-based nearest-rank percentile.

    For ``n`` sorted values, rank is ``ceil(p*n)`` clamped to one.  Thus p50
    over two values selects the first value, and p90 over ten values selects
    the ninth.  Empty input returns ``None``.
    """

    if not 0 <= probability <= 1:
        raise ValueError("probability must be between zero and one")
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    rank = max(1, math.ceil(probability * len(ordered)))
    return ordered[min(rank, len(ordered)) - 1]


def aggregate_q_errors(values: list[float] | tuple[float, ...]) -> dict[str, Any]:
    """Compute descriptive metrics over PASS rows only."""

    if not values:
        return {
            "count": 0,
            "mean_q_error": None,
            "median_q_error": None,
            "p90_q_error": None,
            "p95_q_error": None,
            "max_q_error": None,
        }
    ordered = sorted(float(value) for value in values)
    return {
        "count": len(ordered),
        "mean_q_error": math.fsum(ordered) / len(ordered),
        "median_q_error": nearest_rank(ordered, 0.5),
        "p90_q_error": nearest_rank(ordered, 0.90),
        "p95_q_error": nearest_rank(ordered, 0.95),
        "max_q_error": max(ordered),
    }


@dataclass(frozen=True)
class EvaluationArtifact:
    """One exact, deterministic comparison of truth and estimates."""

    artifact_id: str
    benchmark_id: str
    workload_id: str
    workload_digest: str
    truth_artifact_id: str
    truth_digest: str
    estimate_artifact_id: str
    estimate_digest: str
    repository_artifact_id: str
    repository_digest: str
    configuration_id: str
    configuration_digest: str
    query_evaluations: tuple[QueryEvaluation, ...]
    query_count: int
    successful_count: int
    excluded_count: int
    failed_count: int
    aggregate_metrics: Mapping[str, Any]
    evaluation_digest: str
    lineage: Mapping[str, Any]
    status: str = "PASS"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def create(cls, **fields: Any) -> "EvaluationArtifact":
        provisional = object.__new__(cls)
        for name, value in fields.items():
            object.__setattr__(provisional, name, value)
        evaluations = tuple(fields["query_evaluations"])
        fields["query_evaluations"] = evaluations
        fields["query_count"] = len(evaluations)
        fields["successful_count"] = sum(item.status == "PASS" for item in evaluations)
        fields["excluded_count"] = sum(item.status == "EXCLUDED" for item in evaluations)
        fields["failed_count"] = sum(item.status == "ERROR" for item in evaluations)
        fields["aggregate_metrics"] = aggregate_q_errors(
            [float(item.q_error) for item in evaluations if item.status == "PASS"]
        )
        fields["status"] = "PASS" if fields["failed_count"] == 0 else "FAIL"
        for name, value in fields.items():
            object.__setattr__(provisional, name, value)
        fields["evaluation_digest"] = provisional.compute_evaluation_digest()
        return cls(**fields)

    def __post_init__(self) -> None:
        for name in (
            "artifact_id", "benchmark_id", "workload_id", "truth_artifact_id",
            "estimate_artifact_id", "repository_artifact_id", "configuration_id",
        ):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise ValueError(f"{name} must be nonempty")
        for name in (
            "workload_digest", "truth_digest", "estimate_digest", "repository_digest",
            "configuration_digest", "evaluation_digest",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not _DIGEST.fullmatch(value):
                raise ValueError(f"{name} must be a lowercase SHA256 digest")
        if not isinstance(self.query_evaluations, (tuple, list)):
            raise TypeError("query_evaluations must be a list or tuple")
        if not all(isinstance(item, QueryEvaluation) for item in self.query_evaluations):
            raise TypeError("query_evaluations must contain QueryEvaluation objects")
        if len({item.query_id for item in self.query_evaluations}) != len(self.query_evaluations):
            raise ValueError("evaluation query IDs must be unique")
        if isinstance(self.query_evaluations, list):
            object.__setattr__(self, "query_evaluations", tuple(self.query_evaluations))
        if self.query_count != len(self.query_evaluations):
            raise ValueError("query_count does not match query_evaluations")
        counts = {
            "successful_count": sum(item.status == "PASS" for item in self.query_evaluations),
            "excluded_count": sum(item.status == "EXCLUDED" for item in self.query_evaluations),
            "failed_count": sum(item.status == "ERROR" for item in self.query_evaluations),
        }
        for name, expected in counts.items():
            if getattr(self, name) != expected:
                raise ValueError(f"{name} does not match query_evaluations")
        if self.status not in {"PASS", "FAIL"}:
            raise ValueError("evaluation artifact status must be PASS or FAIL")
        if self.status != ("PASS" if self.failed_count == 0 else "FAIL"):
            raise ValueError("evaluation artifact status does not match query rows")
        if not isinstance(self.aggregate_metrics, Mapping) or not isinstance(self.lineage, Mapping):
            raise TypeError("aggregate_metrics and lineage must be mappings")
        json.dumps(dict(self.aggregate_metrics), sort_keys=True, allow_nan=False)
        json.dumps(dict(self.metadata), sort_keys=True, allow_nan=False)
        if self.compute_evaluation_digest() != self.evaluation_digest:
            raise ValueError("evaluation_digest does not match canonical content")

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "format": "evaluation-artifact-v1",
            "benchmark_id": self.benchmark_id,
            "workload_id": self.workload_id,
            "workload_digest": self.workload_digest,
            "truth_digest": self.truth_digest,
            "estimate_digest": self.estimate_digest,
            "repository_digest": self.repository_digest,
            "configuration_digest": self.configuration_digest,
            "query_evaluations": [
                item.canonical_dict()
                for item in sorted(self.query_evaluations, key=lambda value: value.query_id)
            ],
            "aggregate_metrics": {
                key: (_semantic_number(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else value)
                for key, value in sorted(self.aggregate_metrics.items())
            },
        }

    def compute_evaluation_digest(self) -> str:
        return _digest_payload(self.canonical_dict())

    def to_dict(self) -> dict[str, Any]:
        value = {
            "artifact_id": self.artifact_id,
            "benchmark_id": self.benchmark_id,
            "workload_id": self.workload_id,
            "workload_digest": self.workload_digest,
            "truth_artifact_id": self.truth_artifact_id,
            "truth_digest": self.truth_digest,
            "estimate_artifact_id": self.estimate_artifact_id,
            "estimate_digest": self.estimate_digest,
            "repository_artifact_id": self.repository_artifact_id,
            "repository_digest": self.repository_digest,
            "configuration_id": self.configuration_id,
            "configuration_digest": self.configuration_digest,
            "query_evaluations": [item.to_dict() for item in self.query_evaluations],
            "query_count": self.query_count,
            "successful_count": self.successful_count,
            "excluded_count": self.excluded_count,
            "failed_count": self.failed_count,
            "aggregate_metrics": dict(self.aggregate_metrics),
            "evaluation_digest": self.evaluation_digest,
            "lineage": dict(self.lineage),
            "status": self.status,
            "metadata": dict(self.metadata),
        }
        json.dumps(value, sort_keys=True, allow_nan=False)
        return value

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, indent=2, allow_nan=False) + "\n"

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "EvaluationArtifact":
        return cls(
            artifact_id=value["artifact_id"], benchmark_id=value["benchmark_id"],
            workload_id=value["workload_id"], workload_digest=value["workload_digest"],
            truth_artifact_id=value["truth_artifact_id"], truth_digest=value["truth_digest"],
            estimate_artifact_id=value["estimate_artifact_id"], estimate_digest=value["estimate_digest"],
            repository_artifact_id=value["repository_artifact_id"], repository_digest=value["repository_digest"],
            configuration_id=value["configuration_id"], configuration_digest=value["configuration_digest"],
            query_evaluations=tuple(QueryEvaluation.from_dict(item) for item in value.get("query_evaluations", ())),
            query_count=value["query_count"], successful_count=value["successful_count"],
            excluded_count=value["excluded_count"], failed_count=value["failed_count"],
            aggregate_metrics=value["aggregate_metrics"], evaluation_digest=value["evaluation_digest"],
            lineage=value["lineage"], status=value.get("status", "PASS"), metadata=value.get("metadata", {}),
        )


def _truth_result_map(truth: TruthArtifact) -> dict[str, Any]:
    result = {}
    for item in truth.query_results:
        if item.query_id in result:
            raise ValueError(f"duplicate truth query ID: {item.query_id}")
        result[item.query_id] = item
    return result


def _estimate_result_map(estimate: EstimateArtifact) -> dict[str, QueryEstimate]:
    result = {}
    for item in estimate.query_estimates:
        if item.query_id in result:
            raise ValueError(f"duplicate estimate query ID: {item.query_id}")
        result[item.query_id] = item
    return result


class ArtifactEvaluator:
    """Pure evaluator for exactly one TruthArtifact and EstimateArtifact."""

    def evaluate(
        self,
        truth: TruthArtifact,
        estimate: EstimateArtifact,
        *,
        truth_artifact_id: str = "truth",
        truth_digest_value: str | None = None,
        artifact_id: str | None = None,
    ) -> EvaluationArtifact:
        if not isinstance(truth, TruthArtifact):
            raise TypeError("truth must be a TruthArtifact")
        if not isinstance(estimate, EstimateArtifact):
            raise TypeError("estimate must be an EstimateArtifact")
        if truth.benchmark_id != estimate.benchmark_id:
            raise ValueError("benchmark_id mismatch")
        if truth.workload_id != estimate.workload_id:
            raise ValueError("workload_id mismatch")
        truth_workload_digest = truth.workload_digest
        if not isinstance(truth_workload_digest, str) or not _DIGEST.fullmatch(truth_workload_digest):
            raise ValueError("truth artifact must declare workload_digest")
        if truth_workload_digest != estimate.workload_digest:
            raise ValueError("workload_digest mismatch")
        if estimate.compute_estimate_digest() != estimate.estimate_digest:
            raise ValueError("estimate_digest does not match canonical estimate content")
        truth_results = _truth_result_map(truth)
        estimate_results = _estimate_result_map(estimate)
        if set(truth_results) != set(estimate_results):
            missing = sorted(set(truth_results) - set(estimate_results))
            extra = sorted(set(estimate_results) - set(truth_results))
            raise ValueError(f"query ID universe mismatch: missing={missing}, extra={extra}")

        evaluations: list[QueryEvaluation] = []
        for query_id in sorted(truth_results):
            truth_result = truth_results[query_id]
            estimate_result = estimate_results[query_id]
            truth_cardinality = truth_result.cardinality
            estimated_rows = estimate_result.estimated_rows
            if estimate_result.status == "ERROR" or (truth_result.status not in {"PASS", "UNSUPPORTED"}):
                evaluations.append(QueryEvaluation(
                    query_id, "ERROR", truth_cardinality, estimated_rows,
                    message="truth or estimate has ERROR status",
                ))
            elif estimate_result.status == "UNSUPPORTED" or truth_result.status == "UNSUPPORTED":
                evaluations.append(QueryEvaluation(
                    query_id, "EXCLUDED", truth_cardinality, estimated_rows,
                    message="truth or estimate is explicitly unsupported",
                ))
            elif truth_result.status != "PASS" or truth_cardinality is None:
                evaluations.append(QueryEvaluation(
                    query_id, "ERROR", truth_cardinality, estimated_rows,
                    message="PASS truth result lacks a valid cardinality",
                ))
            else:
                try:
                    value = q_error(float(estimated_rows), truth_cardinality)
                except (TypeError, ValueError) as exc:
                    evaluations.append(QueryEvaluation(
                        query_id, "ERROR", truth_cardinality, estimated_rows,
                        message=str(exc),
                    ))
                else:
                    evaluations.append(QueryEvaluation(
                        query_id, "PASS", truth_cardinality, float(estimated_rows), value,
                    ))

        semantic_truth_digest = truth_digest(truth)
        artifact = EvaluationArtifact.create(
            artifact_id=artifact_id or (truth_artifact_id if truth_artifact_id.startswith("evaluation-") else f"evaluation-{truth_artifact_id}-{estimate.artifact_id}"),
            benchmark_id=estimate.benchmark_id,
            workload_id=estimate.workload_id,
            workload_digest=estimate.workload_digest,
            truth_artifact_id=truth_artifact_id,
            truth_digest=truth_digest_value or semantic_truth_digest,
            estimate_artifact_id=estimate.artifact_id,
            estimate_digest=estimate.estimate_digest,
            repository_artifact_id=estimate.repository_artifact_id,
            repository_digest=estimate.repository_digest,
            configuration_id=estimate.configuration_id,
            configuration_digest=estimate.configuration_digest,
            query_evaluations=tuple(evaluations),
            lineage={
                "truth_artifact_id": truth_artifact_id,
                "estimate_artifact_id": estimate.artifact_id,
                "repository_artifact_id": estimate.repository_artifact_id,
                "configuration_id": estimate.configuration_id,
            },
            metadata={"evaluator": self.__class__.__name__, "q_error_convention": "advisor-positive-truth-estimate-floor-1", "percentile_convention": "nearest-rank"},
        )
        return artifact


CardinalityEvaluationProvider = ArtifactEvaluator


def evaluate(
    truth: TruthArtifact,
    estimate: EstimateArtifact,
    **kwargs: Any,
) -> EvaluationArtifact:
    """Convenience wrapper around :class:`ArtifactEvaluator`."""

    return ArtifactEvaluator().evaluate(truth, estimate, **kwargs)


evaluate_artifacts = evaluate


__all__ = [
    "ArtifactEvaluator", "CardinalityEvaluationProvider", "EvaluationArtifact",
    "QueryEvaluation", "aggregate_q_errors", "nearest_rank", "q_error", "truth_digest",
    "evaluate", "evaluate_artifacts",
]
