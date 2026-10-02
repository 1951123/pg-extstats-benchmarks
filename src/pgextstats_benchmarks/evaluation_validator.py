"""Validation for deterministic EvaluationArtifact content and lineage."""
from __future__ import annotations

from typing import Any

from .estimate import EstimateArtifact
from .evaluation import EvaluationArtifact, aggregate_q_errors, q_error, truth_digest
from .truth import TruthArtifact
from .validation import ValidationCheck, ValidationReport


class EvaluationArtifactValidator:
    """Recompute evaluation counts, metrics, provenance, and digest."""

    def validate(
        self,
        artifact: EvaluationArtifact,
        *,
        truth: TruthArtifact | None = None,
        estimate: EstimateArtifact | None = None,
    ) -> ValidationReport:
        if not isinstance(artifact, EvaluationArtifact):
            raise TypeError("artifact must be an EvaluationArtifact")
        checks: list[ValidationCheck] = []

        ids = [item.query_id for item in artifact.query_evaluations]
        unique = len(ids) == len(set(ids))
        checks.append(ValidationCheck("unique_query_ids", "PASS" if unique else "FAIL", len(ids), len(set(ids))))
        valid_statuses = all(item.status in {"PASS", "EXCLUDED", "ERROR"} for item in artifact.query_evaluations)
        checks.append(ValidationCheck("status_validity", "PASS" if valid_statuses else "FAIL", ["PASS", "EXCLUDED", "ERROR"], sorted({item.status for item in artifact.query_evaluations})))

        expected_counts = {
            "query_count": len(artifact.query_evaluations),
            "successful_count": sum(item.status == "PASS" for item in artifact.query_evaluations),
            "excluded_count": sum(item.status == "EXCLUDED" for item in artifact.query_evaluations),
            "failed_count": sum(item.status == "ERROR" for item in artifact.query_evaluations),
        }
        counts_ok = all(getattr(artifact, key) == value for key, value in expected_counts.items())
        checks.append(ValidationCheck("aggregate_counts", "PASS" if counts_ok else "FAIL", expected_counts, {key: getattr(artifact, key) for key in expected_counts}))

        rows_ok = True
        row_messages: list[str] = []
        for row in artifact.query_evaluations:
            if row.status == "PASS" and (row.truth_cardinality is None or row.estimated_rows is None or row.q_error is None):
                rows_ok = False
                row_messages.append(f"{row.query_id}: PASS requires truth, estimate, q_error")
            if row.status != "PASS" and row.q_error is not None:
                rows_ok = False
                row_messages.append(f"{row.query_id}: non-PASS row has q_error")
        checks.append(ValidationCheck("query_row_contract", "PASS" if rows_ok else "FAIL", "valid status fields", row_messages or "valid"))

        qerror_ok = True
        qerror_messages: list[str] = []
        for row in artifact.query_evaluations:
            if row.status != "PASS":
                continue
            try:
                expected_qerror = q_error(float(row.estimated_rows), row.truth_cardinality)
            except (TypeError, ValueError) as exc:
                qerror_ok = False
                qerror_messages.append(f"{row.query_id}: {exc}")
            else:
                if float(row.q_error) != expected_qerror:
                    qerror_ok = False
                    qerror_messages.append(f"{row.query_id}: q_error differs from frozen formula")
        checks.append(ValidationCheck("q_error_values", "PASS" if qerror_ok else "FAIL", "frozen q-error formula", qerror_messages or "valid"))

        try:
            expected_metrics = aggregate_q_errors([float(item.q_error) for item in artifact.query_evaluations if item.status == "PASS" and item.q_error is not None])
            metrics_ok = dict(artifact.aggregate_metrics) == expected_metrics
        except (TypeError, ValueError, KeyError):
            expected_metrics = None
            metrics_ok = False
        checks.append(ValidationCheck("aggregate_metrics", "PASS" if metrics_ok else "FAIL", expected_metrics, dict(artifact.aggregate_metrics)))

        try:
            digest = artifact.compute_evaluation_digest()
            digest_ok = digest == artifact.evaluation_digest
        except (TypeError, ValueError, KeyError):
            digest = None
            digest_ok = False
        checks.append(ValidationCheck("evaluation_digest", "PASS" if digest_ok else "FAIL", artifact.evaluation_digest, digest))

        if truth is not None:
            truth_ok = (
                truth.benchmark_id == artifact.benchmark_id
                and truth.workload_id == artifact.workload_id
                and truth_digest(truth) == artifact.truth_digest
                and truth.workload_digest == artifact.workload_digest
                and {item.query_id for item in truth.query_results} == {item.query_id for item in artifact.query_evaluations}
            )
            checks.append(ValidationCheck("truth_lineage", "PASS" if truth_ok else "FAIL", truth_digest(truth), artifact.truth_digest))
        if estimate is not None:
            try:
                estimate_digest = estimate.compute_estimate_digest()
                estimate_ok = (
                    estimate.benchmark_id == artifact.benchmark_id
                    and estimate.workload_id == artifact.workload_id
                    and estimate.workload_digest == artifact.workload_digest
                    and estimate.artifact_id == artifact.estimate_artifact_id
                    and estimate_digest == artifact.estimate_digest
                    and estimate.repository_artifact_id == artifact.repository_artifact_id
                    and estimate.repository_digest == artifact.repository_digest
                    and estimate.configuration_id == artifact.configuration_id
                    and estimate.configuration_digest == artifact.configuration_digest
                    and {item.query_id for item in estimate.query_estimates} == {item.query_id for item in artifact.query_evaluations}
                )
            except (TypeError, ValueError, KeyError):
                estimate_digest = None
                estimate_ok = False
            checks.append(ValidationCheck("estimate_lineage", "PASS" if estimate_ok else "FAIL", estimate_digest, artifact.estimate_digest))

        status_ok = artifact.status == ("PASS" if artifact.failed_count == 0 else "FAIL")
        checks.append(ValidationCheck("status_consistency", "PASS" if status_ok else "FAIL", "PASS or FAIL derived from ERROR rows", artifact.status))
        status = "PASS" if all(check.status == "PASS" for check in checks) else "FAIL"
        return ValidationReport(
            benchmark_id=artifact.benchmark_id,
            instance_id=artifact.artifact_id,
            status=status,
            checks=tuple(checks),
            metadata={"validator": self.__class__.__name__},
        )


__all__ = ["EvaluationArtifactValidator"]
