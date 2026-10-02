"""Controlled multi-configuration experiment-run artifacts.

This module only records comparability and explicit membership.  It never
chooses, ranks, or recommends a configuration.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import re
from typing import Any, Mapping, Sequence

from .evaluation import EvaluationArtifact
from .statistics_repository import StatisticsRepositoryArtifact


_DIGEST = re.compile(r"[0-9a-f]{64}")


def _digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def _source(value: Mapping[str, Any]) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise TypeError("postgres_source must be a mapping")
    result = dict(value)
    version = result.get("server_version", result.get("version"))
    required = {
        "repository": result.get("repository"),
        "source_commit": result.get("source_commit"),
        "upstream_base_commit": result.get("upstream_base_commit"),
        "server_version": version,
        "binary_sha256": result.get("binary_sha256"),
    }
    for key, item in required.items():
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"postgres_source.{key} is required")
    if not _DIGEST.fullmatch(required["binary_sha256"]):
        raise ValueError("postgres_source.binary_sha256 must be a SHA256 digest")
    return required


@dataclass(frozen=True)
class ExperimentEvaluationEntry:
    """One explicitly named evaluation in an experiment run."""

    label: str
    configuration_id: str
    configuration_digest: str
    estimate_artifact_id: str
    estimate_digest: str
    evaluation_artifact_id: str
    evaluation_digest: str

    @classmethod
    def from_evaluation(cls, evaluation: EvaluationArtifact, label: str | None = None) -> "ExperimentEvaluationEntry":
        if not isinstance(evaluation, EvaluationArtifact):
            raise TypeError("evaluation must be an EvaluationArtifact")
        return cls(
            label=label or evaluation.configuration_id,
            configuration_id=evaluation.configuration_id,
            configuration_digest=evaluation.configuration_digest,
            estimate_artifact_id=evaluation.estimate_artifact_id,
            estimate_digest=evaluation.estimate_digest,
            evaluation_artifact_id=evaluation.artifact_id,
            evaluation_digest=evaluation.evaluation_digest,
        )

    def __post_init__(self) -> None:
        for name in (
            "label", "configuration_id", "estimate_artifact_id", "evaluation_artifact_id",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be nonempty")
        for name in ("configuration_digest", "estimate_digest", "evaluation_digest"):
            value = getattr(self, name)
            if not isinstance(value, str) or not _DIGEST.fullmatch(value):
                raise ValueError(f"{name} must be a lowercase SHA256 digest")

    def to_dict(self) -> dict[str, str]:
        return {
            "label": self.label,
            "configuration_id": self.configuration_id,
            "configuration_digest": self.configuration_digest,
            "estimate_artifact_id": self.estimate_artifact_id,
            "estimate_digest": self.estimate_digest,
            "evaluation_artifact_id": self.evaluation_artifact_id,
            "evaluation_digest": self.evaluation_digest,
        }

    def canonical_dict(self) -> dict[str, str]:
        """Semantic entry content; labels are presentation metadata."""
        return {
            "configuration_id": self.configuration_id,
            "configuration_digest": self.configuration_digest,
            "estimate_artifact_id": self.estimate_artifact_id,
            "estimate_digest": self.estimate_digest,
            "evaluation_artifact_id": self.evaluation_artifact_id,
            "evaluation_digest": self.evaluation_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ExperimentEvaluationEntry":
        return cls(
            label=value["label"], configuration_id=value["configuration_id"],
            configuration_digest=value["configuration_digest"], estimate_artifact_id=value["estimate_artifact_id"],
            estimate_digest=value["estimate_digest"], evaluation_artifact_id=value["evaluation_artifact_id"],
            evaluation_digest=value["evaluation_digest"],
        )


ExperimentEntry = ExperimentEvaluationEntry


@dataclass(frozen=True)
class ExperimentRunArtifact:
    """One controlled set of explicitly supplied comparable evaluations."""

    experiment_id: str
    benchmark_id: str
    workload_id: str
    workload_digest: str
    truth_artifact_id: str
    truth_digest: str
    sample_artifact_id: str
    sample_payload_sha256: str
    statistics_repository_artifact_id: str
    statistics_repository_digest: str
    postgres_source: Mapping[str, Any]
    effective_statistics_target: int
    evaluations: tuple[ExperimentEvaluationEntry, ...]
    baseline_label: str
    metadata: Mapping[str, Any]
    experiment_digest: str
    lineage: Mapping[str, Any]

    @classmethod
    def create(
        cls,
        *,
        experiment_id: str,
        evaluations: Sequence[EvaluationArtifact | ExperimentEvaluationEntry],
        baseline_label: str,
        sample_artifact_id: str,
        sample_payload_sha256: str,
        postgres_source: Mapping[str, Any],
        effective_statistics_target: int,
        labels: Mapping[str, str] | None = None,
        metadata: Mapping[str, Any] | None = None,
        lineage: Mapping[str, Any] | None = None,
    ) -> "ExperimentRunArtifact":
        if not evaluations:
            raise ValueError("experiment requires at least one evaluation")
        labels = dict(labels or {})
        entries = tuple(
            item if isinstance(item, ExperimentEvaluationEntry)
            else ExperimentEvaluationEntry.from_evaluation(item, labels.get(item.artifact_id))
            for item in evaluations
        )
        first = evaluations[0]
        if isinstance(first, ExperimentEvaluationEntry):
            raise ValueError("at least one EvaluationArtifact is required to derive experiment identity")
        if not all(isinstance(item, EvaluationArtifact) for item in evaluations):
            raise TypeError("evaluations must contain EvaluationArtifact objects")
        baseline = next((entry for entry in entries if entry.label == baseline_label), None)
        if baseline is None:
            raise ValueError("baseline_label is not present in evaluations")
        cls._validate_evaluation_identity(evaluations, sample_artifact_id, sample_payload_sha256, postgres_source, effective_statistics_target)
        kwargs: dict[str, Any] = {
            "experiment_id": experiment_id,
            "benchmark_id": first.benchmark_id,
            "workload_id": first.workload_id,
            "workload_digest": first.workload_digest,
            "truth_artifact_id": first.truth_artifact_id,
            "truth_digest": first.truth_digest,
            "sample_artifact_id": sample_artifact_id,
            "sample_payload_sha256": sample_payload_sha256,
            "statistics_repository_artifact_id": first.repository_artifact_id,
            "statistics_repository_digest": first.repository_digest,
            "postgres_source": _source(postgres_source),
            "effective_statistics_target": effective_statistics_target,
            "evaluations": entries,
            "baseline_label": baseline_label,
            "metadata": dict(metadata or {}),
            "lineage": dict(lineage or {
                "truth_artifact_id": first.truth_artifact_id,
                "sample_artifact_id": sample_artifact_id,
                "statistics_repository_artifact_id": first.repository_artifact_id,
                "evaluation_artifact_ids": [entry.evaluation_artifact_id for entry in entries],
            }),
            "experiment_digest": "0" * 64,
        }
        provisional = object.__new__(cls)
        for key, value in kwargs.items():
            object.__setattr__(provisional, key, value)
        kwargs["experiment_digest"] = provisional.compute_experiment_digest()
        return cls(**kwargs)

    @classmethod
    def from_evaluations(
        cls,
        *,
        experiment_id: str,
        evaluations: Sequence[EvaluationArtifact],
        repositories: Mapping[str, StatisticsRepositoryArtifact],
        baseline_label: str,
        labels: Mapping[str, str] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "ExperimentRunArtifact":
        if not evaluations:
            raise ValueError("experiment requires at least one evaluation")
        first_repository = repositories.get(evaluations[0].repository_artifact_id)
        if not isinstance(first_repository, StatisticsRepositoryArtifact):
            raise ValueError("repository provenance is required for every evaluation")
        for evaluation in evaluations:
            repository = repositories.get(evaluation.repository_artifact_id)
            if not isinstance(repository, StatisticsRepositoryArtifact):
                raise ValueError(f"missing repository provenance for {evaluation.artifact_id}")
            if repository.artifact_id != evaluation.repository_artifact_id:
                raise ValueError(f"repository identity mismatch for {evaluation.artifact_id}")
            if repository.benchmark_id != evaluation.benchmark_id or repository.repository_digest != evaluation.repository_digest:
                raise ValueError(f"repository provenance mismatch for {evaluation.artifact_id}")
            if repository.sample_artifact_id != first_repository.sample_artifact_id or repository.sample_payload_sha256 != first_repository.sample_payload_sha256:
                raise ValueError("incompatible sample provenance")
            if repository.postgres_source.get("source_commit") != first_repository.postgres_source.get("source_commit"):
                raise ValueError("incompatible PostgreSQL source provenance")
            if repository.statistics_target.get("effective") != first_repository.statistics_target.get("effective"):
                raise ValueError("incompatible statistics target")
        return cls.create(
            experiment_id=experiment_id,
            evaluations=evaluations,
            baseline_label=baseline_label,
            sample_artifact_id=first_repository.sample_artifact_id,
            sample_payload_sha256=first_repository.sample_payload_sha256,
            postgres_source=first_repository.postgres_source,
            effective_statistics_target=int(first_repository.statistics_target["effective"]),
            labels=labels,
            metadata=metadata,
        )

    @staticmethod
    def _validate_evaluation_identity(
        evaluations: Sequence[EvaluationArtifact],
        sample_artifact_id: str,
        sample_payload_sha256: str,
        postgres_source: Mapping[str, Any],
        effective_statistics_target: int,
    ) -> None:
        first = evaluations[0]
        ids = [item.configuration_id for item in evaluations]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate configuration ID in experiment")
        evaluation_ids = [item.artifact_id for item in evaluations]
        if len(evaluation_ids) != len(set(evaluation_ids)):
            raise ValueError("duplicate evaluation artifact ID in experiment")
        if not isinstance(sample_artifact_id, str) or not sample_artifact_id.strip():
            raise ValueError("sample_artifact_id is required")
        if not isinstance(sample_payload_sha256, str) or not _DIGEST.fullmatch(sample_payload_sha256):
            raise ValueError("sample_payload_sha256 must be a SHA256 digest")
        _source(postgres_source)
        if not isinstance(effective_statistics_target, int) or effective_statistics_target <= 0:
            raise ValueError("effective_statistics_target must be a positive integer")
        for item in evaluations:
            if item.compute_evaluation_digest() != item.evaluation_digest:
                raise ValueError(f"evaluation_digest does not match canonical content: {item.artifact_id}")
            for name in ("benchmark_id", "workload_id", "workload_digest", "truth_artifact_id", "truth_digest", "repository_artifact_id", "repository_digest"):
                if getattr(item, name) != getattr(first, name):
                    raise ValueError(f"incompatible evaluation {name}")
            metadata = item.metadata
            if metadata.get("sample_artifact_id") is not None and metadata.get("sample_artifact_id") != sample_artifact_id:
                raise ValueError("incompatible evaluation sample_artifact_id")
            if metadata.get("sample_payload_sha256") is not None and metadata.get("sample_payload_sha256") != sample_payload_sha256:
                raise ValueError("incompatible evaluation sample_payload_sha256")
            source = metadata.get("postgres_source")
            if source is not None and _source(source) != _source(postgres_source):
                raise ValueError("incompatible evaluation PostgreSQL source")
        # Estimate/evaluation digest coherence is checked by the evaluation validator;
        # this layer still requires each identity to be present and distinct.

    def __post_init__(self) -> None:
        for name in ("experiment_id", "benchmark_id", "workload_id", "truth_artifact_id", "sample_artifact_id", "statistics_repository_artifact_id", "baseline_label"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be nonempty")
        for name in ("workload_digest", "truth_digest", "sample_payload_sha256", "statistics_repository_digest", "experiment_digest"):
            value = getattr(self, name)
            if not isinstance(value, str) or not _DIGEST.fullmatch(value):
                raise ValueError(f"{name} must be a lowercase SHA256 digest")
        _source(self.postgres_source)
        if not isinstance(self.effective_statistics_target, int) or self.effective_statistics_target <= 0:
            raise ValueError("effective_statistics_target must be a positive integer")
        if not isinstance(self.evaluations, (tuple, list)) or not self.evaluations:
            raise ValueError("experiment evaluations must be nonempty")
        if not all(isinstance(item, ExperimentEvaluationEntry) for item in self.evaluations):
            raise TypeError("evaluations must contain ExperimentEvaluationEntry objects")
        if isinstance(self.evaluations, list):
            object.__setattr__(self, "evaluations", tuple(self.evaluations))
        labels = [item.label for item in self.evaluations]
        configs = [item.configuration_id for item in self.evaluations]
        evaluation_ids = [item.evaluation_artifact_id for item in self.evaluations]
        if len(labels) != len(set(labels)):
            raise ValueError("duplicate evaluation label")
        if len(configs) != len(set(configs)):
            raise ValueError("duplicate configuration ID")
        if len(evaluation_ids) != len(set(evaluation_ids)):
            raise ValueError("duplicate evaluation artifact ID")
        if self.baseline_label not in set(labels):
            raise ValueError("baseline_label is not present in evaluations")
        if not isinstance(self.metadata, Mapping) or not isinstance(self.lineage, Mapping):
            raise TypeError("experiment metadata and lineage must be mappings")
        json.dumps(dict(self.metadata), sort_keys=True, allow_nan=False)
        json.dumps(dict(self.lineage), sort_keys=True, allow_nan=False)
        if self.compute_experiment_digest() != self.experiment_digest:
            raise ValueError("experiment_digest does not match canonical content")

    @property
    def baseline_entry(self) -> ExperimentEvaluationEntry:
        return next(item for item in self.evaluations if item.label == self.baseline_label)

    @property
    def baseline_configuration_id(self) -> str:
        return self.baseline_entry.configuration_id

    def canonical_dict(self) -> dict[str, Any]:
        baseline = self.baseline_entry
        return {
            "format": "experiment-run-v1",
            "benchmark_id": self.benchmark_id,
            "workload_id": self.workload_id,
            "workload_digest": self.workload_digest,
            "truth_digest": self.truth_digest,
            "sample_artifact_id": self.sample_artifact_id,
            "sample_payload_sha256": self.sample_payload_sha256,
            "statistics_repository_artifact_id": self.statistics_repository_artifact_id,
            "statistics_repository_digest": self.statistics_repository_digest,
            "postgres_source": dict(_source(self.postgres_source)),
            "effective_statistics_target": self.effective_statistics_target,
            "baseline_identity": {
                "configuration_id": baseline.configuration_id,
                "configuration_digest": baseline.configuration_digest,
                "evaluation_artifact_id": baseline.evaluation_artifact_id,
                "evaluation_digest": baseline.evaluation_digest,
            },
            "evaluations": [item.canonical_dict() for item in sorted(self.evaluations, key=lambda value: (value.configuration_id, value.configuration_digest))],
        }

    def compute_experiment_digest(self) -> str:
        return _digest(self.canonical_dict())

    def to_dict(self) -> dict[str, Any]:
        value = {
            "experiment_id": self.experiment_id,
            "benchmark_id": self.benchmark_id,
            "workload_id": self.workload_id,
            "workload_digest": self.workload_digest,
            "truth_artifact_id": self.truth_artifact_id,
            "truth_digest": self.truth_digest,
            "sample_artifact_id": self.sample_artifact_id,
            "sample_payload_sha256": self.sample_payload_sha256,
            "statistics_repository_artifact_id": self.statistics_repository_artifact_id,
            "statistics_repository_digest": self.statistics_repository_digest,
            "postgres_source": dict(self.postgres_source),
            "effective_statistics_target": self.effective_statistics_target,
            "evaluations": [item.to_dict() for item in self.evaluations],
            "baseline_label": self.baseline_label,
            "metadata": dict(self.metadata),
            "experiment_digest": self.experiment_digest,
            "lineage": dict(self.lineage),
        }
        json.dumps(value, sort_keys=True, allow_nan=False)
        return value

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, indent=2, allow_nan=False) + "\n"

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ExperimentRunArtifact":
        return cls(
            experiment_id=value["experiment_id"], benchmark_id=value["benchmark_id"],
            workload_id=value["workload_id"], workload_digest=value["workload_digest"],
            truth_artifact_id=value["truth_artifact_id"], truth_digest=value["truth_digest"],
            sample_artifact_id=value["sample_artifact_id"], sample_payload_sha256=value["sample_payload_sha256"],
            statistics_repository_artifact_id=value["statistics_repository_artifact_id"],
            statistics_repository_digest=value["statistics_repository_digest"], postgres_source=value["postgres_source"],
            effective_statistics_target=value["effective_statistics_target"],
            evaluations=tuple(ExperimentEvaluationEntry.from_dict(item) for item in value.get("evaluations", ())),
            baseline_label=value["baseline_label"], metadata=value.get("metadata", {}),
            experiment_digest=value["experiment_digest"], lineage=value.get("lineage", {}),
        )


__all__ = ["ExperimentEntry", "ExperimentEvaluationEntry", "ExperimentRunArtifact"]
