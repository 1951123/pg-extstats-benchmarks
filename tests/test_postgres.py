import json
from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from pgextstats_benchmarks.cli import main
from pgextstats_benchmarks.example_adapter import ExampleAdapter
from pgextstats_benchmarks.executor import load_artifact
from pgextstats_benchmarks.loader_registry import get_loader, list_loaders
from pgextstats_benchmarks.postgres.connection import PostgresConnection
from pgextstats_benchmarks.postgres.instance import PostgresInstance
from pgextstats_benchmarks.postgres.loader import (
    PostgreSQLLoader,
    is_managed_database_name,
    validate_managed_database_name,
)


def test_connection_defaults_and_environment(monkeypatch):
    monkeypatch.setenv("PGHOST", "db.example")
    monkeypatch.setenv("PGPORT", "55438")
    monkeypatch.setenv("PGUSER", "alice")
    connection = PostgresConnection.from_environment()
    assert (connection.host, connection.port, connection.user, connection.database) == (
        "db.example", 55438, "alice", "postgres"
    )


def test_database_name_safety():
    assert is_managed_database_name("pgextbench_test_12345678")
    assert validate_managed_database_name("pgextbench_test") == "pgextbench_test"
    for name in ("postgres", "template0", "template1", "postgres_bad", "pgextbench_bad-name"):
        with pytest.raises(ValueError):
            validate_managed_database_name(name)
    with pytest.raises(ValueError):
        PostgreSQLLoader.database_name_for("bad-name")


def test_managed_database_guard_without_connection():
    class FakeConnection:
        def drop_database(self, name):
            raise AssertionError(f"must not drop {name}")

    loader = PostgreSQLLoader(connection=FakeConnection())
    instance = PostgresInstance("unsafe", "postgres", "READY")
    with pytest.raises(ValueError, match="pgextbench"):
        loader.destroy_instance(instance)


def test_postgres_instance_serialization():
    instance = PostgresInstance(
        "pgextbench_test_12345678",
        "pgextbench_test_12345678",
        "READY",
        {"postgres_version": "PostgreSQL 16.14", "host": "localhost", "port": 55437},
    )
    assert PostgresInstance.from_dict(json.loads(instance.to_json())) == instance


def test_loader_registration():
    assert "postgres" in list_loaders()
    assert get_loader("postgres") is PostgreSQLLoader


def test_example_prepared_artifact_structure():
    root = Path(__file__).parents[1] / "benchmarks/example/artifacts/example-prepared-v1"
    assert (root / "schema.sql").read_text(encoding="utf-8").startswith("CREATE TABLE example_table")
    assert (root / "data.csv").read_text(encoding="utf-8") == "id,value\n1,hello\n2,world\n"
    manifest = yaml.safe_load((root / "manifest.yaml").read_text(encoding="utf-8"))
    assert manifest["artifact_id"] == "example-prepared-v1"
    assert manifest["expected_rows"] == 2


def test_example_adapter_declares_prepared_artifact():
    artifact = ExampleAdapter().prepare()["output_artifacts"][0]
    assert artifact.id == "example-prepared-v1"
    assert Path(artifact.path, "schema.sql").is_file()
    assert artifact.metadata["expected_rows"] == 2


def _integration_loader():
    try:
        loader = PostgreSQLLoader()
        loader.connection.connect()
    except Exception as exc:  # pragma: no cover - depends on external service
        pytest.skip(f"PostgreSQL integration unavailable: {exc}")
    loader.connection.close()
    return loader


def test_postgres_lifecycle_integration():
    loader = _integration_loader()
    instance = loader.create_instance("test")
    try:
        assert instance.database_name.startswith("pgextbench_test_")
        report = loader.validate_instance(instance)
        assert report["status"] == "PASS"
        assert {check["name"] for check in report["checks"]} == {
            "connection_works", "database_exists", "version_query"
        }
    finally:
        assert loader.destroy_instance(instance)["status"] == "PASS"
        loader.close()


def test_postgres_artifact_loading_and_row_validation():
    loader = _integration_loader()
    instance = loader.create_instance("example")
    artifact = ExampleAdapter().prepare()["output_artifacts"][0]
    try:
        loaded = loader.load_artifact(instance, artifact)
        assert loaded.status == "LOADED"
        assert loaded.metadata["tables"] == ["example_table"]
        assert loaded.metadata["rows_loaded"] == 2
        report = loader.validate_instance(loaded)
        assert report["status"] == "PASS"
        assert {check["name"] for check in report["checks"]} >= {
            "table_exists", "row_count"
        }
        wrong_counts = dict(loaded.metadata)
        wrong_counts["expected_tables"] = {"example_table": 3}
        failed = loader.validate_instance(replace(loaded, metadata=wrong_counts))
        assert failed["status"] == "FAIL"
        assert next(check for check in failed["checks"] if check["name"] == "row_count")["status"] == "FAIL"
    finally:
        assert loader.destroy_instance(instance)["status"] == "PASS"
        loader.close()


def test_postgres_artifact_execution_provenance():
    loader = _integration_loader()
    loader.close()
    result = load_artifact("example", "postgres", destroy=True, record=True)
    assert result["status"] == "PASS"
    assert result["provenance"]["artifact_id"] == "example-prepared-v1"
    assert result["provenance"]["loader_type"] == "PostgreSQLLoader"
    assert result["provenance"]["instance_metadata"]["rows_loaded"] == 2
    assert result["execution"]["metadata"]["artifact_id"] == "example-prepared-v1"


def test_postgres_check_cli(capsys):
    loader = _integration_loader()
    loader.close()
    assert main(["postgres-check"]) == 0
    output = capsys.readouterr().out
    assert "PostgreSQL: 16.14" in output
    assert "Create: PASS" in output
    assert "Validate: PASS" in output
    assert "Destroy: PASS" in output
