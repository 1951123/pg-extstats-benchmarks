"""Fail-closed validation for ExperimentRunArtifact comparability."""
from __future__ import annotations

from typing import Mapping, Sequence

from .evaluation import EvaluationArtifact
from .experiment import ExperimentRunArtifact
from .statistics_repository import StatisticsRepositoryArtifact
from .validation import ValidationCheck, ValidationReport


class ExperimentRunArtifactValidator:
    def validate(
        self,
        artifact: ExperimentRunArtifact,
        *,
        evaluations: Sequence[EvaluationArtifact] | None = None,
        repositories: Mapping[str, StatisticsRepositoryArtifact] | None = None,
    ) -> ValidationReport:
        if not isinstance(artifact, ExperimentRunArtifact):
            raise TypeError("artifact must be an ExperimentRunArtifact")
        checks: list[ValidationCheck] = []
        try:
            digest = artifact.compute_experiment_digest()
            digest_ok = digest == artifact.experiment_digest
        except (TypeError, ValueError, KeyError):
            digest = None
            digest_ok = False
        checks.append(ValidationCheck("experiment_digest", "PASS" if digest_ok else "FAIL", artifact.experiment_digest, digest))

        labels = [item.label for item in artifact.evaluations]
        configurations = [item.configuration_id for item in artifact.evaluations]
        evaluation_ids = [item.evaluation_artifact_id for item in artifact.evaluations]
        baseline_ok = artifact.baseline_label in labels and len(labels) == len(set(labels))
        checks.append(ValidationCheck("baseline", "PASS" if baseline_ok else "FAIL", artifact.baseline_label, labels))
        identity_ok = len(configurations) == len(set(configurations)) and len(evaluation_ids) == len(set(evaluation_ids))
        checks.append(ValidationCheck("unique_entries", "PASS" if identity_ok else "FAIL", "unique configuration and evaluation IDs", {"configurations": configurations, "evaluations": evaluation_ids}))

        if evaluations is not None:
            by_id = {item.artifact_id: item for item in evaluations}
            set_ok = set(by_id) == set(evaluation_ids)
            checks.append(ValidationCheck("evaluation_coverage", "PASS" if set_ok else "FAIL", sorted(evaluation_ids), sorted(by_id)))
            all_ok = True
            reasons: list[str] = []
            for entry in artifact.evaluations:
                item = by_id.get(entry.evaluation_artifact_id)
                if item is None:
                    all_ok = False
                    continue
                if item.evaluation_digest != entry.evaluation_digest:
                    all_ok = False
                    reasons.append(f"{item.artifact_id}: evaluation digest")
                if item.configuration_id != entry.configuration_id or item.configuration_digest != entry.configuration_digest:
                    all_ok = False
                    reasons.append(f"{item.artifact_id}: configuration identity")
                for name in ("benchmark_id", "workload_id", "workload_digest", "truth_artifact_id", "truth_digest", "repository_artifact_id", "repository_digest"):
                    if getattr(item, name) != getattr(artifact, name if name not in {"repository_artifact_id", "repository_digest"} else ("statistics_repository_artifact_id" if name == "repository_artifact_id" else "statistics_repository_digest")):
                        all_ok = False
                        reasons.append(f"{item.artifact_id}: {name}")
            checks.append(ValidationCheck("evaluation_identity", "PASS" if all_ok else "FAIL", "all evaluations comparable", reasons or "comparable"))

        if repositories is not None:
            repository_ok = True
            reasons = []
            for entry in artifact.evaluations:
                item = None if evaluations is None else next((value for value in evaluations if value.artifact_id == entry.evaluation_artifact_id), None)
                repository = repositories.get(item.repository_artifact_id) if item is not None else repositories.get(artifact.statistics_repository_artifact_id)
                if not isinstance(repository, StatisticsRepositoryArtifact):
                    repository_ok = False
                    reasons.append(f"{entry.evaluation_artifact_id}: missing repository")
                    continue
                if repository.artifact_id != artifact.statistics_repository_artifact_id or repository.repository_digest != artifact.statistics_repository_digest:
                    repository_ok = False
                    reasons.append(f"{entry.evaluation_artifact_id}: repository identity")
                if repository.sample_artifact_id != artifact.sample_artifact_id or repository.sample_payload_sha256 != artifact.sample_payload_sha256:
                    repository_ok = False
                    reasons.append(f"{entry.evaluation_artifact_id}: sample identity")
                if repository.postgres_source.get("source_commit") != artifact.postgres_source.get("source_commit"):
                    repository_ok = False
                    reasons.append(f"{entry.evaluation_artifact_id}: PostgreSQL source")
                if repository.statistics_target.get("effective") != artifact.effective_statistics_target:
                    repository_ok = False
                    reasons.append(f"{entry.evaluation_artifact_id}: statistics target")
            checks.append(ValidationCheck("repository_provenance", "PASS" if repository_ok else "FAIL", artifact.statistics_repository_artifact_id, reasons or "comparable"))

        status = "PASS" if all(check.status == "PASS" for check in checks) else "FAIL"
        return ValidationReport(
            benchmark_id=artifact.benchmark_id,
            instance_id=artifact.experiment_id,
            status=status,
            checks=tuple(checks),
            metadata={"validator": self.__class__.__name__},
        )


__all__ = ["ExperimentRunArtifactValidator"]
