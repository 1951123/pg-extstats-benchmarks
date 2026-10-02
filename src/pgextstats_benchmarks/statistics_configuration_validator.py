"""Validation reports for explicit statistics configurations."""
from __future__ import annotations

from .statistics_configuration import StatisticsConfiguration
from .statistics_repository import StatisticsRepositoryArtifact
from .validation import ValidationCheck, ValidationReport


class StatisticsConfigurationValidator:
    def validate(
        self,
        configuration: StatisticsConfiguration,
        repository: StatisticsRepositoryArtifact,
    ) -> ValidationReport:
        if not isinstance(configuration, StatisticsConfiguration):
            raise TypeError("configuration must be a StatisticsConfiguration")
        checks: list[ValidationCheck] = []
        digest = configuration.compute_configuration_digest()
        digest_ok = digest == configuration.configuration_digest
        checks.append(ValidationCheck("configuration_digest", "PASS" if digest_ok else "FAIL", configuration.configuration_digest, digest))
        failed = not digest_ok
        checks.append(ValidationCheck("repository_reference", "PASS" if configuration.repository_artifact_id == repository.artifact_id and configuration.repository_digest == repository.repository_digest else "FAIL", repository.artifact_id, configuration.repository_artifact_id))
        try:
            configuration.validate_against(repository)
            checks.extend([
                ValidationCheck("candidate_membership", "PASS", repository.candidate_catalog["candidate_count"], configuration.selected_candidate_count),
                ValidationCheck("target", "PASS", repository.statistics_target["effective"], configuration.effective_statistics_target),
                ValidationCheck("absent_native", "PASS", "no ABSENT_NATIVE selected", "none selected"),
            ])
        except (TypeError, ValueError) as exc:
            failed = True
            checks.append(ValidationCheck("configuration_contract", "FAIL", "compatible repository subset", str(exc), str(exc)))
        return ValidationReport(
            benchmark_id=repository.benchmark_id,
            instance_id=configuration.configuration_id,
            status="FAIL" if failed else "PASS",
            checks=tuple(checks),
            metadata={"selected_candidate_count": configuration.selected_candidate_count},
        )


__all__ = ["StatisticsConfigurationValidator"]
