import json

import pytest

from pgextstats_benchmarks.cli import main
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


def test_postgres_check_cli(capsys):
    loader = _integration_loader()
    loader.close()
    assert main(["postgres-check"]) == 0
    output = capsys.readouterr().out
    assert "PostgreSQL: 16.14" in output
    assert "Create: PASS" in output
    assert "Validate: PASS" in output
    assert "Destroy: PASS" in output
