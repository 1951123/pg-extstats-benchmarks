from __future__ import annotations

import pytest

from pgextstats_benchmarks.postgres import connection as connection_module
from pgextstats_benchmarks.postgres.connection import PostgresConnection
from pgextstats_benchmarks.postgres.statistics_provider import (
    _fingerprint_rows,
    verify_ordinary_statistics_fingerprint,
)


ROWS = [("a", 0.0, 4, -1.0, None, None, None, 1.0)]


class FakeStatisticsConnection:
    def ordinary_statistics(self, relation):
        assert relation == "public.fixture"
        return ROWS


def test_ordinary_statistics_guard_passes_and_fails_closed():
    expected = _fingerprint_rows(ROWS)
    result = verify_ordinary_statistics_fingerprint(
        FakeStatisticsConnection(), "public.fixture", expected, "after_sample_replay"
    )
    assert result["match"] is True
    with pytest.raises(RuntimeError, match="fingerprint drifted"):
        verify_ordinary_statistics_fingerprint(
            FakeStatisticsConnection(), "public.fixture", "0" * 64, "before_search"
        )


class FakeComposable:
    def __init__(self, text):
        self.text = text

    def format(self, *values):
        text = self.text
        for value in values:
            text = text.replace("{}", str(value), 1)
        return FakeComposable(text)

    def __str__(self):
        return self.text


class FakeSQL:
    @staticmethod
    def SQL(text):
        return FakeComposable(text)

    @staticmethod
    def Identifier(value):
        return FakeComposable(f'"{value}"')


class FakeDriver:
    sql = FakeSQL


def test_disable_automatic_statistics_maintenance_is_relation_local(monkeypatch):
    monkeypatch.setattr(connection_module, "_driver", lambda: FakeDriver)
    connection = PostgresConnection(database="pgextbench_fixture")
    calls = []

    def execute(query, params=None):
        calls.append((str(query), params))
        if str(query).startswith("SELECT c.reloptions"):
            return [(["autovacuum_enabled=false"],)]
        return []

    connection.execute = execute
    result = connection.disable_automatic_statistics_maintenance("public.fixture")
    assert result["relation_autovacuum_enabled"] is False
    assert result["reloptions"] == ["autovacuum_enabled=false"]
    assert calls[0][0].startswith('ALTER TABLE "public"."fixture" SET')
    assert all("ALTER SYSTEM" not in query for query, _ in calls)


def test_disable_automatic_statistics_maintenance_rejects_unverified_option(monkeypatch):
    monkeypatch.setattr(connection_module, "_driver", lambda: FakeDriver)
    connection = PostgresConnection(database="pgextbench_fixture")

    def execute(query, params=None):
        if str(query).startswith("SELECT c.reloptions"):
            return [(["fillfactor=90"],)]
        return []

    connection.execute = execute
    with pytest.raises(RuntimeError, match="was not verified"):
        connection.disable_automatic_statistics_maintenance("public.fixture")
