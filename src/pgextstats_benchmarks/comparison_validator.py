"""Validator that recomputes a ComparisonReport from its experiment inputs."""
from __future__ import annotations

from typing import Sequence

from .comparison import ComparisonReport
from .evaluation import EvaluationArtifact
from .experiment import ExperimentRunArtifact
from .validation import ValidationCheck, ValidationReport


class ComparisonReportValidator:
    def validate(
        self,
        report: ComparisonReport,
        *,
        experiment: ExperimentRunArtifact,
        evaluations: Sequence[EvaluationArtifact],
    ) -> ValidationReport:
        if not isinstance(report, ComparisonReport):
            raise TypeError("report must be a ComparisonReport")
        checks: list[ValidationCheck] = []
        reference_ok = report.experiment_id == experiment.experiment_id and report.experiment_digest == experiment.experiment_digest and report.baseline_configuration_id == experiment.baseline_configuration_id
        checks.append(ValidationCheck("experiment_reference", "PASS" if reference_ok else "FAIL", experiment.experiment_id, report.experiment_id))
        try:
            recomputed = ComparisonReport.create(
                report_id=report.report_id, experiment=experiment, evaluations=evaluations,
            )
            digest_ok = recomputed.report_digest == report.report_digest
            content_ok = recomputed.canonical_dict() == report.canonical_dict()
        except (TypeError, ValueError, KeyError) as exc:
            recomputed = None
            digest_ok = False
            content_ok = False
            error = str(exc)
        else:
            error = ""
        checks.append(ValidationCheck("report_recomputation", "PASS" if content_ok else "FAIL", "recomputed report matches", error or ("match" if content_ok else "content differs")))
        checks.append(ValidationCheck("report_digest", "PASS" if digest_ok else "FAIL", report.report_digest, recomputed.report_digest if recomputed else None))
        status = "PASS" if all(check.status == "PASS" for check in checks) else "FAIL"
        return ValidationReport(
            benchmark_id=experiment.benchmark_id,
            instance_id=report.report_id,
            status=status,
            checks=tuple(checks),
            metadata={"validator": self.__class__.__name__},
        )


__all__ = ["ComparisonReportValidator"]
