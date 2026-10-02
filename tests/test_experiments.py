from __future__ import annotations

import hashlib

import pytest

from pgextstats_benchmarks.comparison import ComparisonReport
from pgextstats_benchmarks.comparison_storage import (
    allocate_comparison_report_dir,
    load_comparison_report,
    write_comparison_report,
)
from pgextstats_benchmarks.comparison_validator import ComparisonReportValidator
from pgextstats_benchmarks.evaluation import ArtifactEvaluator, truth_digest
from pgextstats_benchmarks.experiment import ExperimentRunArtifact
from pgextstats_benchmarks.experiment_storage import (
    allocate_experiment_artifact_dir,
    load_experiment_artifact,
    write_experiment_artifact,
)
from pgextstats_benchmarks.experiment_validator import ExperimentRunArtifactValidator
from pgextstats_benchmarks.query_runner import QueryExecutionResult
from pgextstats_benchmarks.statistics_repository import StatisticsRepositoryArtifact
from pgextstats_benchmarks.truth import TruthArtifact
from pgextstats_benchmarks.workload_executor import Query, Workload
from pgextstats_benchmarks.estimate import EstimateArtifact, QueryEstimate, workload_digest


SOURCE = {
    "repository": "https://github.com/1951123/postgresql-pgextadv",
    "source_commit": "7e992ab6438fef2f8eb98c7a9ed30c9f1c816ce7",
    "upstream_base_commit": "0d1c00c624fa7367d4a895f44381887757289682",
    "server_version": "PostgreSQL 16.14",
    "binary_sha256": "4" * 64,
}


def make_fixture():
    workload = Workload(
        "w1", (Query("q001", "SELECT 1"), Query("q002", "SELECT 2"), Query("q003", "SELECT 3"))
    )
    wd = workload_digest(workload)
    truth = TruthArtifact(
        "example", "w1",
        (
            QueryExecutionResult("q001", "PASS", {"cardinality": 10}),
            QueryExecutionResult("q002", "PASS", {"cardinality": 20}),
            QueryExecutionResult("q003", "PASS", {"cardinality": 30}),
        ),
        {"workload_digest": wd},
    )
    repo = StatisticsRepositoryArtifact.create(
        artifact_id="repo-v1", benchmark_id="example", relation_identity="public.fixture",
        sample_artifact_id="sample-v1", sample_payload_sha256="a" * 64,
        candidate_catalog={"catalog_id": "catalog-v1", "catalog_sha256": "b" * 64, "candidate_count": 0},
        postgres_source=SOURCE, statistics_target={"requested": 100, "effective": 100},
        ordinary_statistics_fingerprint="c" * 64, candidate_states=(), repository_digest="0" * 64,
        lineage={"sample_artifact_id": "sample-v1"},
    )
    evaluations = []
    estimates = {"empty": (20, 20, 60), "a": (10, 20, 60), "b": (40, 20, 30)}
    for config, values in estimates.items():
        estimate = EstimateArtifact.create(
            artifact_id=f"estimate-{config}", benchmark_id="example", workload_id="w1", workload_digest=wd,
            repository_artifact_id=repo.artifact_id, repository_digest=repo.repository_digest,
            configuration_id=f"config-{config}", configuration_digest=hashlib.sha256(config.encode()).hexdigest(),
            relation_identity=repo.relation_identity, postgres_source=SOURCE,
            query_estimates=tuple(QueryEstimate(f"q{i:03d}", "PASS", value) for i, value in enumerate(values, 1)),
            query_count=3, successful_count=3, failed_count=0, estimate_digest="0" * 64,
            lineage={"repository_artifact_id": repo.artifact_id},
        )
        evaluations.append(ArtifactEvaluator().evaluate(
            truth, estimate, truth_artifact_id="truth-v1", truth_digest_value=truth_digest(truth),
            artifact_id=f"evaluation-{config}",
        ))
    repositories = {repo.artifact_id: repo}
    return truth, repo, tuple(evaluations), repositories


def make_experiment(evaluations, repositories, order=None, baseline_label="evaluation-empty"):
    values = tuple(evaluations if order is None else [evaluations[index] for index in order])
    labels = {item.artifact_id: item.artifact_id for item in values}
    return ExperimentRunArtifact.from_evaluations(
        experiment_id="experiment-v1", evaluations=values, repositories=repositories,
        baseline_label=baseline_label, labels=labels,
    )


def make_status_evaluation(truth, repo, status):
    rows = tuple(QueryEstimate(f"q{i:03d}", status) for i in range(1, 4))
    estimate = EstimateArtifact.create(
        artifact_id=f"estimate-{status.lower()}", benchmark_id="example", workload_id="w1",
        workload_digest=truth.workload_digest, repository_artifact_id=repo.artifact_id,
        repository_digest=repo.repository_digest, configuration_id=f"config-{status.lower()}",
        configuration_digest=hashlib.sha256(status.encode()).hexdigest(), relation_identity=repo.relation_identity,
        postgres_source=SOURCE, query_estimates=rows, query_count=3,
        successful_count=0, failed_count=3 if status == "ERROR" else 0,
        estimate_digest="0" * 64, lineage={"repository_artifact_id": repo.artifact_id},
    )
    return ArtifactEvaluator().evaluate(
        truth, estimate, truth_artifact_id="truth-v1", truth_digest_value=truth_digest(truth),
        artifact_id=f"evaluation-{status.lower()}",
    )


def test_experiment_and_comparison_are_input_order_independent():
    _, _, evaluations, repositories = make_fixture()
    first = make_experiment(evaluations, repositories)
    second = make_experiment(evaluations, repositories, (2, 0, 1))
    assert first.experiment_digest == second.experiment_digest
    report_a = ComparisonReport.create(report_id="report-v1", experiment=first, evaluations=evaluations)
    report_b = ComparisonReport.create(report_id="report-v1", experiment=second, evaluations=tuple(reversed(evaluations)))
    assert report_a.report_digest == report_b.report_digest


def test_comparison_counts_and_exact_delta_semantics():
    _, _, evaluations, repositories = make_fixture()
    experiment = make_experiment(evaluations, repositories)
    report = ComparisonReport.create(report_id="report-v1", experiment=experiment, evaluations=evaluations)
    summary = next(item for item in report.configuration_summaries if item.configuration_id == "config-a")
    comparison = summary.baseline_comparison
    assert comparison["comparable_query_count"] == 3
    assert comparison["improved_query_count"] == 1
    assert comparison["unchanged_query_count"] == 2
    assert comparison["worsened_query_count"] == 0
    rows = [item for item in report.per_query_comparisons if item.configuration_id == "config-a"]
    assert [item.query_id for item in rows] == ["q001", "q002", "q003"]
    assert rows[0].status == "COMPARABLE" and rows[0].delta < 0 and rows[0].ratio < 1
    assert rows[1].delta == 0 and rows[1].ratio == 1
    assert rows[2].delta == 0 and rows[2].ratio == 1
    baseline = next(item for item in report.configuration_summaries if item.configuration_id == "config-empty")
    assert baseline.baseline_comparison["status"] == "SELF"


def test_experiment_and_report_validators_recompute_content(tmp_path):
    _, _, evaluations, repositories = make_fixture()
    experiment = make_experiment(evaluations, repositories)
    report = ComparisonReport.create(report_id="report-v1", experiment=experiment, evaluations=evaluations)
    assert ExperimentRunArtifactValidator().validate(experiment, evaluations=evaluations, repositories=repositories).status == "PASS"
    assert ComparisonReportValidator().validate(report, experiment=experiment, evaluations=evaluations).status == "PASS"
    allocate_experiment_artifact_dir("example", experiment.experiment_id, tmp_path)
    write_experiment_artifact(experiment, tmp_path)
    assert load_experiment_artifact("example", experiment.experiment_id, tmp_path) == experiment
    allocate_comparison_report_dir("example", report.report_id, tmp_path)
    write_comparison_report(report, "example", tmp_path)
    assert load_comparison_report("example", report.report_id, tmp_path) == report


def test_experiment_rejects_missing_baseline_and_incompatible_workload():
    _, _, evaluations, repositories = make_fixture()
    with pytest.raises(ValueError, match="baseline_label"):
        ExperimentRunArtifact.from_evaluations(
            experiment_id="experiment-v1", evaluations=evaluations, repositories=repositories,
            baseline_label="missing", labels={item.artifact_id: item.artifact_id for item in evaluations},
        )
    altered = list(evaluations)
    object.__setattr__(altered[1], "workload_digest", "f" * 64)
    with pytest.raises(ValueError, match="evaluation_digest"):
        make_experiment(tuple(altered), repositories)


def test_comparison_rejects_evaluation_coverage_mismatch():
    _, _, evaluations, repositories = make_fixture()
    experiment = make_experiment(evaluations, repositories)
    with pytest.raises(ValueError, match="evaluation set mismatch"):
        ComparisonReport.create(report_id="report-v1", experiment=experiment, evaluations=evaluations[:2])


def test_status_mismatches_remain_explicit_without_fabricated_deltas():
    truth, repo, evaluations, repositories = make_fixture()
    unsupported = make_status_evaluation(truth, repo, "UNSUPPORTED")
    experiment = make_experiment(evaluations + (unsupported,), repositories)
    report = ComparisonReport.create(report_id="report-v1", experiment=experiment, evaluations=evaluations + (unsupported,))
    summary = next(item for item in report.configuration_summaries if item.configuration_id == "config-unsupported")
    assert summary.baseline_comparison["comparable_query_count"] == 0
    assert summary.baseline_comparison["excluded_query_count"] == 3
    assert all(item.status == "TARGET_UNAVAILABLE" for item in report.per_query_comparisons if item.configuration_id == "config-unsupported")
    baseline_first = make_experiment((unsupported,) + evaluations, repositories, (0, 1, 2, 3), baseline_label="evaluation-unsupported")
    baseline_report = ComparisonReport.create(report_id="report-v2", experiment=baseline_first, evaluations=(unsupported,) + evaluations)
    baseline_summary = next(item for item in baseline_report.configuration_summaries if item.configuration_id == "config-unsupported")
    assert baseline_summary.baseline_comparison["status"] == "SELF"
    assert baseline_summary.baseline_comparison["excluded_query_count"] == 3
