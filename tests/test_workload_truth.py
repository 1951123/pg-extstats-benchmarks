from __future__ import annotations

import json
from pathlib import Path

import pytest

from pgextstats_benchmarks.census_adapter import CensusAdapter
from pgextstats_benchmarks.census_validator import CensusTruthValidator
from pgextstats_benchmarks.postgres.instance import PostgresInstance
from pgextstats_benchmarks.postgres.query_runner import PostgreSQLQueryRunner
from pgextstats_benchmarks.query_runner import QueryExecutionResult
from pgextstats_benchmarks.truth import TruthArtifact
from pgextstats_benchmarks.workload_executor import Query, Workload, normalize_workload
from pgextstats_benchmarks.cli import main


def test_workload_normalization_preserves_query_text_and_stable_ids():
    source = b"SELECT 1||10\r\nSELECT  COUNT(*) FROM census||2\r\n"
    first = normalize_workload(source, workload_id="census-workload-v1")
    second = normalize_workload(source, workload_id="census-workload-v1")
    assert first == second
    assert [query.query_id for query in first.queries] == ["q001", "q002"]
    assert first.queries[0].sql == "SELECT 1"
    assert first.queries[1].sql == "SELECT  COUNT(*) FROM census"
    assert first.metadata["query_count"] == 2
    assert first.metadata["source_checksum"]


def test_workload_and_truth_serialization():
    workload = Workload("w1", (Query("q001", "SELECT 1"),))
    truth = TruthArtifact(
        benchmark_id="census",
        workload_id="w1",
        query_results=(
            QueryExecutionResult("q001", "PASS", {"cardinality": 1}),
        ),
    )
    assert Workload.from_dict(json.loads(workload.to_json())) == workload
    assert TruthArtifact.from_dict(json.loads(truth.to_json())) == truth


def test_truth_validator_checks_coverage_and_cardinality():
    workload = Workload(
        "w1",
        (Query("q001", "SELECT 1"), Query("q002", "SELECT 2")),
    )
    passing = TruthArtifact(
        "census",
        "w1",
        (
            QueryExecutionResult("q001", "PASS", {"cardinality": 1}),
            QueryExecutionResult("q002", "PASS", {"cardinality": 1}),
        ),
    )
    assert CensusTruthValidator().validate_truth(workload, passing).status == "PASS"
    failing = TruthArtifact(
        "census",
        "w1",
        (QueryExecutionResult("q001", "FAIL", {"error": "failed"}),),
    )
    report = CensusTruthValidator().validate_truth(workload, failing)
    assert report.status == "FAIL"
    assert {check.name for check in report.checks} == {
        "query_count",
        "query_ids",
        "cardinality_values",
    }


def test_census_adapter_collect_truth_with_recorded_runner(tmp_path):
    from tests.test_census import make_adapter

    adapter, _, _ = make_adapter(tmp_path)
    adapter.fetch()
    adapter.normalize_workload()

    class RecordedRunner:
        def execute_workload(self, workload, instance):
            return tuple(
                QueryExecutionResult(query.query_id, "PASS", {"cardinality": index + 1})
                for index, query in enumerate(workload.queries)
            )

    instance = PostgresInstance("pgextbench_test", "pgextbench_test", "READY")
    result = adapter.collect_truth(instance, RecordedRunner())
    assert result["status"] == "PASS"
    truth = result["truth"]
    assert truth.query_count == 2
    assert result["output_artifacts"][0].id == "census-truth-v1"
    assert (result["output_artifacts"][0].path / "truth.json").is_file()


def _integration_loader():
    from pgextstats_benchmarks.postgres.loader import PostgreSQLLoader

    try:
        loader = PostgreSQLLoader()
        loader.connection.connect()
    except Exception as exc:  # pragma: no cover - depends on external service
        pytest.skip(f"PostgreSQL integration unavailable: {exc}")
    loader.connection.close()
    return loader


def test_postgresql_query_runner_exact_cardinality_integration(tmp_path):
    from tests.test_census import make_loader_adapter

    adapter, _ = make_loader_adapter(tmp_path)
    adapter.fetch()
    prepared = adapter.prepare()["output_artifacts"][0]
    loader = _integration_loader()
    instance = loader.create_instance("census")
    try:
        loaded = loader.load_artifact(instance, prepared)
        workload = Workload(
            "small-workload",
            (
                Query("q001", "SELECT COUNT(*) FROM census"),
                Query("q002", "SELECT caseid FROM census"),
            ),
        )
        results = PostgreSQLQueryRunner().execute_workload(workload, loaded)
        assert [result.cardinality for result in results] == [1, 1]
        assert all(result.status == "PASS" for result in results)
    finally:
        assert loader.destroy_instance(instance)["status"] == "PASS"
        loader.close()


def test_collect_census_truth_cli_with_small_fixture(tmp_path, monkeypatch, capsys):
    from tests.test_census import make_loader_adapter

    adapter, _ = make_loader_adapter(tmp_path)
    adapter.fetch()
    prepared_result = adapter.prepare()
    workload_result = adapter.normalize_workload()
    monkeypatch.setenv("PGEXTADV_BENCHMARK_DATA", str(tmp_path / "external"))
    monkeypatch.setattr(CensusAdapter, "prepare", lambda self: prepared_result)
    monkeypatch.setattr(CensusAdapter, "normalize_workload", lambda self: workload_result)
    loader = _integration_loader()
    loader.close()
    assert main(["collect-census-truth"]) == 0
    output = capsys.readouterr().out
    assert "Benchmark: census" in output
    assert "Workload: census-workload-v1" in output
    assert "Runner: PostgreSQLQueryRunner" in output
    assert "Queries: 1" in output
    assert "Truth: PASS" in output
    assert "Successful queries: 1" in output
