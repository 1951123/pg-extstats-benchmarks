"""Validation for EstimateArtifact lineage and query coverage."""
from __future__ import annotations

from .estimate import EstimateArtifact, workload_digest
from .statistics_configuration import StatisticsConfiguration
from .statistics_repository import StatisticsRepositoryArtifact
from .validation import ValidationCheck, ValidationReport
from .workload_executor import Workload


class EstimateArtifactValidator:
    def validate(
        self,
        artifact: EstimateArtifact,
        *,
        workload: Workload | None = None,
        repository: StatisticsRepositoryArtifact | None = None,
        configuration: StatisticsConfiguration | None = None,
    ) -> ValidationReport:
        if not isinstance(artifact, EstimateArtifact):
            raise TypeError("artifact must be an EstimateArtifact")
        checks: list[ValidationCheck] = []
        digest = artifact.compute_estimate_digest()
        digest_ok = digest == artifact.estimate_digest
        checks.append(ValidationCheck("estimate_digest", "PASS" if digest_ok else "FAIL", artifact.estimate_digest, digest))
        failed = not digest_ok
        if workload is not None:
            expected = workload_digest(workload)
            ok = artifact.workload_id == workload.workload_id and artifact.workload_digest == expected and {item.query_id for item in artifact.query_estimates} == {item.query_id for item in workload.queries}
            checks.append(ValidationCheck("workload_coverage", "PASS" if ok else "FAIL", workload.query_count, artifact.query_count))
            failed |= not ok
        if repository is not None:
            ok = artifact.repository_artifact_id == repository.artifact_id and artifact.repository_digest == repository.repository_digest
            checks.append(ValidationCheck("repository_lineage", "PASS" if ok else "FAIL", repository.artifact_id, artifact.repository_artifact_id))
            failed |= not ok
        if configuration is not None:
            ok = artifact.configuration_id == configuration.configuration_id and artifact.configuration_digest == configuration.configuration_digest
            checks.append(ValidationCheck("configuration_lineage", "PASS" if ok else "FAIL", configuration.configuration_id, artifact.configuration_id))
            failed |= not ok
        return ValidationReport(
            benchmark_id=artifact.benchmark_id,
            instance_id=artifact.artifact_id,
            status="FAIL" if failed else "PASS",
            checks=tuple(checks),
            metadata={"query_count": artifact.query_count, "successful_count": artifact.successful_count, "failed_count": artifact.failed_count, "status": artifact.status},
        )


__all__ = ["EstimateArtifactValidator"]
