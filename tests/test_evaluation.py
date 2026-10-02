from __future__ import annotations

import json

import pytest

from pgextstats_benchmarks.estimate import EstimateArtifact, QueryEstimate, workload_digest
from pgextstats_benchmarks.evaluation import (
    ArtifactEvaluator,
    EvaluationArtifact,
    QueryEvaluation,
    q_error,
    truth_digest,
)
from pgextstats_benchmarks.evaluation_storage import (
    allocate_evaluation_artifact_dir,
    load_evaluation_artifact,
    write_evaluation_artifact,
)
from pgextstats_benchmarks.evaluation_validator import EvaluationArtifactValidator
from pgextstats_benchmarks.query_runner import QueryExecutionResult
from pgextstats_benchmarks.truth import TruthArtifact
from pgextstats_benchmarks.workload_executor import Query, Workload


SOURCE = {
    "repository": "https://github.com/1951123/postgresql-pgextadv",
    "source_commit": "7e992ab6438fef2f8eb98c7a9ed30c9f1c816ce7",
    "upstream_base_commit": "0d1c00c624fa7367d4a895f44381887757289682",
    "server_version": "PostgreSQL 16.14",
    "binary_sha256": "4" * 64,
}


def make_inputs(order=("q001", "q002", "q003")):
    workload = Workload(
        "workload-v1",
        tuple(Query(query_id, f"SELECT {int(query_id[1:])}") for query_id in ("q001", "q002", "q003")),
    )
    digest = workload_digest(workload)
    truth_values = {"q001": 10, "q002": 0, "q003": 5}
    estimate_values = {"q001": 20, "q002": 0, "q003": 0}
    truth = TruthArtifact(
        "example", "workload-v1",
        tuple(QueryExecutionResult(query_id, "PASS", {"cardinality": truth_values[query_id]}) for query_id in reversed(order)),
        metadata={"workload_digest": digest},
    )
    estimates = tuple(
        QueryEstimate(query_id, "PASS", estimated_rows=estimate_values[query_id])
        for query_id in reversed(order)
    )
    estimate = EstimateArtifact.create(
        artifact_id="estimate-v1", benchmark_id="example", workload_id="workload-v1",
        workload_digest=digest, repository_artifact_id="repo-v1", repository_digest="2" * 64,
        configuration_id="config-v1", configuration_digest="3" * 64,
        relation_identity="public.fixture", postgres_source=SOURCE,
        query_estimates=estimates, query_count=len(estimates), successful_count=len(estimates),
        failed_count=0, estimate_digest="0" * 64, lineage={"configuration_id": "config-v1"},
    )
    return truth, estimate


def test_q_error_matches_frozen_advisor_rule():
    assert q_error(20, 10) == 2.0
    assert q_error(0, 10) == 10.0
    with pytest.raises(ValueError, match="positive truth"):
        q_error(0, 0)


def test_evaluation_is_deterministic_and_query_order_independent():
    truth, estimate = make_inputs()
    first = ArtifactEvaluator().evaluate(truth, estimate, truth_artifact_id="truth-v1")
    second = ArtifactEvaluator().evaluate(truth, estimate, truth_artifact_id="truth-v1")
    assert first == second
    reordered_truth, reordered_estimate = make_inputs(("q003", "q001", "q002"))
    reordered = ArtifactEvaluator().evaluate(reordered_truth, reordered_estimate, truth_artifact_id="truth-v1")
    assert first.evaluation_digest == reordered.evaluation_digest
    assert [row.query_id for row in first.query_evaluations] == ["q001", "q002", "q003"]


def test_zero_truth_is_explicit_error_and_unsupported_is_excluded():
    truth, estimate = make_inputs()
    artifact = ArtifactEvaluator().evaluate(truth, estimate)
    assert artifact.failed_count == 1
    assert artifact.query_evaluations[1].status == "ERROR"
    unsupported = EstimateArtifact.create(
        artifact_id="estimate-unsupported", benchmark_id=estimate.benchmark_id,
        workload_id=estimate.workload_id, workload_digest=estimate.workload_digest,
        repository_artifact_id=estimate.repository_artifact_id, repository_digest=estimate.repository_digest,
        configuration_id=estimate.configuration_id, configuration_digest=estimate.configuration_digest,
        relation_identity=estimate.relation_identity, postgres_source=SOURCE,
        query_estimates=tuple(QueryEstimate(item.query_id, "UNSUPPORTED") for item in estimate.query_estimates),
        query_count=estimate.query_count, successful_count=0, failed_count=0,
        estimate_digest="0" * 64, lineage=estimate.lineage,
    )
    excluded = ArtifactEvaluator().evaluate(truth, unsupported)
    assert excluded.excluded_count == 3
    assert all(item.q_error is None for item in excluded.query_evaluations)


def test_input_compatibility_is_strict():
    truth, estimate = make_inputs()
    bad = TruthArtifact(truth.benchmark_id, "other-workload", truth.query_results, truth.metadata)
    with pytest.raises(ValueError, match="workload_id"):
        ArtifactEvaluator().evaluate(bad, estimate)
    extra = EstimateArtifact.create(
        artifact_id="estimate-extra", benchmark_id=estimate.benchmark_id,
        workload_id=estimate.workload_id, workload_digest=estimate.workload_digest,
        repository_artifact_id=estimate.repository_artifact_id, repository_digest=estimate.repository_digest,
        configuration_id=estimate.configuration_id, configuration_digest=estimate.configuration_digest,
        relation_identity=estimate.relation_identity, postgres_source=SOURCE,
        query_estimates=estimate.query_estimates + (QueryEstimate("q999", "PASS", 1),),
        query_count=4, successful_count=4, failed_count=0,
        estimate_digest="0" * 64, lineage=estimate.lineage,
    )
    with pytest.raises(ValueError, match="query ID universe"):
        ArtifactEvaluator().evaluate(truth, extra)


def test_serialization_storage_and_validator(tmp_path):
    truth, estimate = make_inputs()
    artifact = ArtifactEvaluator().evaluate(truth, estimate, truth_artifact_id="truth-v1")
    directory = allocate_evaluation_artifact_dir("example", artifact.artifact_id, tmp_path)
    write_evaluation_artifact(artifact, tmp_path)
    loaded = load_evaluation_artifact("example", artifact.artifact_id, tmp_path)
    assert loaded == artifact
    assert json.loads((directory / "evaluation.json").read_text())['aggregate_metrics'] == dict(artifact.aggregate_metrics)
    assert EvaluationArtifactValidator().validate(loaded, truth=truth, estimate=estimate).status == "PASS"


def test_validator_recomputes_corrupted_digest():
    truth, estimate = make_inputs()
    artifact = ArtifactEvaluator().evaluate(truth, estimate)
    object.__setattr__(artifact, "evaluation_digest", "f" * 64)
    assert EvaluationArtifactValidator().validate(artifact, truth=truth, estimate=estimate).status == "FAIL"
