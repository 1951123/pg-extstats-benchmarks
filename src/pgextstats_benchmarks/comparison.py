"""Deterministic descriptive comparison of one controlled experiment run."""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import math
import re
from typing import Any, Mapping, Sequence

from .evaluation import EvaluationArtifact, nearest_rank
from .experiment import ExperimentRunArtifact


_DIGEST = re.compile(r"[0-9a-f]{64}")


def _digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def _delta_metrics(deltas: list[float]) -> dict[str, float | None]:
    return {
        "median_delta": nearest_rank(deltas, 0.5),
        "p90_delta": nearest_rank(deltas, 0.90),
        "p95_delta": nearest_rank(deltas, 0.95),
    }


@dataclass(frozen=True)
class QueryComparison:
    query_id: str
    configuration_id: str
    status: str
    baseline_q_error: float | None = None
    configuration_q_error: float | None = None
    delta: float | None = None
    ratio: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.query_id, str) or not self.query_id.strip():
            raise ValueError("query_id must be nonempty")
        if not isinstance(self.configuration_id, str) or not self.configuration_id.strip():
            raise ValueError("configuration_id must be nonempty")
        if self.status not in {"SELF", "COMPARABLE", "BASELINE_UNAVAILABLE", "TARGET_UNAVAILABLE"}:
            raise ValueError("invalid query comparison status")
        for name in ("baseline_q_error", "configuration_q_error", "delta", "ratio"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, (int, float)) or not math.isfinite(float(value))):
                raise ValueError(f"{name} must be finite or None")
        if self.status == "COMPARABLE":
            if None in (self.baseline_q_error, self.configuration_q_error, self.delta, self.ratio):
                raise ValueError("COMPARABLE row requires q-errors, delta, and ratio")
        elif self.delta is not None or self.ratio is not None:
            raise ValueError("unavailable comparison cannot contain delta or ratio")

    def to_dict(self) -> dict[str, Any]:
        return {
            "query_id": self.query_id,
            "configuration_id": self.configuration_id,
            "status": self.status,
            "baseline_q_error": self.baseline_q_error,
            "configuration_q_error": self.configuration_q_error,
            "delta": self.delta,
            "ratio": self.ratio,
        }

    def canonical_dict(self) -> dict[str, Any]:
        return self.to_dict()

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "QueryComparison":
        return cls(
            query_id=value["query_id"], configuration_id=value["configuration_id"], status=value["status"],
            baseline_q_error=value.get("baseline_q_error"), configuration_q_error=value.get("configuration_q_error"),
            delta=value.get("delta"), ratio=value.get("ratio"),
        )


@dataclass(frozen=True)
class ConfigurationSummary:
    configuration_id: str
    configuration_digest: str
    evaluation_artifact_id: str
    evaluation_digest: str
    qerror_metrics: Mapping[str, Any]
    baseline_comparison: Mapping[str, Any]

    def __post_init__(self) -> None:
        for name in ("configuration_id", "evaluation_artifact_id"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise ValueError(f"{name} must be nonempty")
        for name in ("configuration_digest", "evaluation_digest"):
            value = getattr(self, name)
            if not isinstance(value, str) or not _DIGEST.fullmatch(value):
                raise ValueError(f"{name} must be a SHA256 digest")
        if not isinstance(self.qerror_metrics, Mapping) or not isinstance(self.baseline_comparison, Mapping):
            raise TypeError("summary metrics must be mappings")
        json.dumps(dict(self.qerror_metrics), sort_keys=True, allow_nan=False)
        json.dumps(dict(self.baseline_comparison), sort_keys=True, allow_nan=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "configuration_id": self.configuration_id,
            "configuration_digest": self.configuration_digest,
            "evaluation_artifact_id": self.evaluation_artifact_id,
            "evaluation_digest": self.evaluation_digest,
            "qerror_metrics": dict(self.qerror_metrics),
            "baseline_comparison": dict(self.baseline_comparison),
        }

    def canonical_dict(self) -> dict[str, Any]:
        return self.to_dict()

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ConfigurationSummary":
        return cls(
            configuration_id=value["configuration_id"], configuration_digest=value["configuration_digest"],
            evaluation_artifact_id=value["evaluation_artifact_id"], evaluation_digest=value["evaluation_digest"],
            qerror_metrics=value["qerror_metrics"], baseline_comparison=value["baseline_comparison"],
        )


@dataclass(frozen=True)
class ComparisonReport:
    report_id: str
    experiment_id: str
    experiment_digest: str
    baseline_configuration_id: str
    configuration_summaries: tuple[ConfigurationSummary, ...]
    per_query_comparisons: tuple[QueryComparison, ...]
    report_digest: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        *,
        report_id: str,
        experiment: ExperimentRunArtifact,
        evaluations: Sequence[EvaluationArtifact],
        metadata: Mapping[str, Any] | None = None,
    ) -> "ComparisonReport":
        if not isinstance(experiment, ExperimentRunArtifact):
            raise TypeError("experiment must be an ExperimentRunArtifact")
        expected_ids = {entry.evaluation_artifact_id for entry in experiment.evaluations}
        actual_ids = {item.artifact_id for item in evaluations}
        if expected_ids != actual_ids:
            raise ValueError(f"evaluation set mismatch: missing={sorted(expected_ids - actual_ids)}, extra={sorted(actual_ids - expected_ids)}")
        by_id = {item.artifact_id: item for item in evaluations}
        for entry in experiment.evaluations:
            evaluation = by_id[entry.evaluation_artifact_id]
            if evaluation.compute_evaluation_digest() != evaluation.evaluation_digest:
                raise ValueError(f"evaluation content digest mismatch for {evaluation.artifact_id}")
            if evaluation.evaluation_digest != entry.evaluation_digest:
                raise ValueError(f"evaluation digest mismatch for {evaluation.artifact_id}")
            if evaluation.configuration_id != entry.configuration_id or evaluation.configuration_digest != entry.configuration_digest:
                raise ValueError(f"configuration identity mismatch for {evaluation.artifact_id}")
            if evaluation.benchmark_id != experiment.benchmark_id or evaluation.workload_id != experiment.workload_id or evaluation.workload_digest != experiment.workload_digest:
                raise ValueError(f"workload identity mismatch for {evaluation.artifact_id}")
            if evaluation.truth_artifact_id != experiment.truth_artifact_id or evaluation.truth_digest != experiment.truth_digest:
                raise ValueError(f"truth identity mismatch for {evaluation.artifact_id}")
            if evaluation.repository_artifact_id != experiment.statistics_repository_artifact_id or evaluation.repository_digest != experiment.statistics_repository_digest:
                raise ValueError(f"repository identity mismatch for {evaluation.artifact_id}")
        baseline_entry = experiment.baseline_entry
        baseline = by_id[baseline_entry.evaluation_artifact_id]
        baseline_rows = {row.query_id: row for row in baseline.query_evaluations}
        if len(baseline_rows) != len(baseline.query_evaluations):
            raise ValueError("baseline evaluation has duplicate query IDs")
        summaries: list[ConfigurationSummary] = []
        rows: list[QueryComparison] = []
        for entry in sorted(experiment.evaluations, key=lambda item: (item.configuration_id, item.configuration_digest)):
            target = by_id[entry.evaluation_artifact_id]
            target_rows = {row.query_id: row for row in target.query_evaluations}
            if set(target_rows) != set(baseline_rows):
                raise ValueError(f"query universe mismatch for {target.artifact_id}")
            if entry.evaluation_artifact_id == baseline_entry.evaluation_artifact_id:
                comparison = {
                    "status": "SELF",
                    "comparable_query_count": target.successful_count,
                    "improved_query_count": 0,
                    "unchanged_query_count": target.successful_count,
                    "worsened_query_count": 0,
                    "baseline_unavailable_query_count": 0,
                    "excluded_query_count": target.excluded_count,
                    "error_query_count": target.failed_count,
                    "median_delta": 0.0,
                    "p90_delta": 0.0,
                    "p95_delta": 0.0,
                    "median_ratio_to_baseline": 1.0,
                }
                for query_id in sorted(baseline_rows):
                    base_row = baseline_rows[query_id]
                    rows.append(QueryComparison(query_id, entry.configuration_id, "SELF", base_row.q_error, base_row.q_error))
            else:
                deltas: list[float] = []
                ratios: list[float] = []
                improved = unchanged = worsened = excluded = errors = baseline_unavailable = 0
                for query_id in sorted(baseline_rows):
                    base_row = baseline_rows[query_id]
                    target_row = target_rows[query_id]
                    if base_row.status != "PASS":
                        baseline_unavailable += 1
                        rows.append(QueryComparison(query_id, entry.configuration_id, "BASELINE_UNAVAILABLE", base_row.q_error, target_row.q_error))
                    elif target_row.status != "PASS":
                        if target_row.status == "EXCLUDED":
                            excluded += 1
                        else:
                            errors += 1
                        rows.append(QueryComparison(query_id, entry.configuration_id, "TARGET_UNAVAILABLE", base_row.q_error, target_row.q_error))
                    else:
                        delta = float(target_row.q_error) - float(base_row.q_error)
                        ratio = float(target_row.q_error) / float(base_row.q_error)
                        deltas.append(delta)
                        ratios.append(ratio)
                        if target_row.q_error < base_row.q_error:
                            improved += 1
                        elif target_row.q_error == base_row.q_error:
                            unchanged += 1
                        else:
                            worsened += 1
                        rows.append(QueryComparison(query_id, entry.configuration_id, "COMPARABLE", base_row.q_error, target_row.q_error, delta, ratio))
                comparison = {
                    "status": "COMPARISON",
                    "comparable_query_count": len(deltas),
                    "improved_query_count": improved,
                    "unchanged_query_count": unchanged,
                    "worsened_query_count": worsened,
                    "baseline_unavailable_query_count": baseline_unavailable,
                    "excluded_query_count": excluded,
                    "error_query_count": errors,
                    **_delta_metrics(deltas),
                    "median_ratio_to_baseline": nearest_rank(ratios, 0.5),
                }
            summaries.append(ConfigurationSummary(
                entry.configuration_id, entry.configuration_digest, entry.evaluation_artifact_id,
                entry.evaluation_digest, dict(target.aggregate_metrics), comparison,
            ))
        provisional = {
            "report_id": report_id,
            "experiment_id": experiment.experiment_id,
            "experiment_digest": experiment.experiment_digest,
            "baseline_configuration_id": experiment.baseline_configuration_id,
            "configuration_summaries": tuple(summaries),
            "per_query_comparisons": tuple(sorted(rows, key=lambda item: (item.configuration_id, item.query_id))),
            "metadata": dict(metadata or {}),
        }
        temp = object.__new__(cls)
        for key, value in provisional.items():
            object.__setattr__(temp, key, value)
        provisional["report_digest"] = temp.compute_report_digest()
        return cls(**provisional)

    def __post_init__(self) -> None:
        for name in ("report_id", "experiment_id", "baseline_configuration_id"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise ValueError(f"{name} must be nonempty")
        for name in ("experiment_digest", "report_digest"):
            value = getattr(self, name)
            if not isinstance(value, str) or not _DIGEST.fullmatch(value):
                raise ValueError(f"{name} must be a SHA256 digest")
        if not self.configuration_summaries:
            raise ValueError("comparison report requires summaries")
        if not all(isinstance(item, ConfigurationSummary) for item in self.configuration_summaries):
            raise TypeError("configuration_summaries must contain ConfigurationSummary objects")
        if not all(isinstance(item, QueryComparison) for item in self.per_query_comparisons):
            raise TypeError("per_query_comparisons must contain QueryComparison objects")
        if not isinstance(self.metadata, Mapping):
            raise TypeError("comparison metadata must be a mapping")
        if self.compute_report_digest() != self.report_digest:
            raise ValueError("report_digest does not match canonical content")

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "format": "comparison-report-v1",
            "experiment_digest": self.experiment_digest,
            "baseline_configuration_id": self.baseline_configuration_id,
            "configuration_summaries": [item.canonical_dict() for item in sorted(self.configuration_summaries, key=lambda value: (value.configuration_id, value.configuration_digest))],
            "per_query_comparisons": [item.canonical_dict() for item in sorted(self.per_query_comparisons, key=lambda value: (value.configuration_id, value.query_id))],
        }

    def compute_report_digest(self) -> str:
        return _digest(self.canonical_dict())

    def to_dict(self) -> dict[str, Any]:
        value = {
            "report_id": self.report_id,
            "experiment_id": self.experiment_id,
            "experiment_digest": self.experiment_digest,
            "baseline_configuration_id": self.baseline_configuration_id,
            "configuration_summaries": [item.to_dict() for item in self.configuration_summaries],
            "per_query_comparisons": [item.to_dict() for item in self.per_query_comparisons],
            "report_digest": self.report_digest,
            "metadata": dict(self.metadata),
        }
        json.dumps(value, sort_keys=True, allow_nan=False)
        return value

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, indent=2, allow_nan=False) + "\n"

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ComparisonReport":
        return cls(
            report_id=value["report_id"], experiment_id=value["experiment_id"],
            experiment_digest=value["experiment_digest"], baseline_configuration_id=value["baseline_configuration_id"],
            configuration_summaries=tuple(ConfigurationSummary.from_dict(item) for item in value["configuration_summaries"]),
            per_query_comparisons=tuple(QueryComparison.from_dict(item) for item in value["per_query_comparisons"]),
            report_digest=value["report_digest"], metadata=value.get("metadata", {}),
        )


__all__ = ["ComparisonReport", "ConfigurationSummary", "QueryComparison"]
