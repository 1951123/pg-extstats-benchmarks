"""PostgreSQL implementation of the workload query runner."""
from __future__ import annotations

from typing import Any

from ..query_runner import QueryExecutionResult, QueryRunner
from ..workload_executor import Workload
from .connection import PostgresConnection
from .instance import PostgresInstance
from .loader import validate_managed_database_name


class PostgreSQLQueryRunner(QueryRunner):
    """Execute SELECT workloads and collect exact result cardinalities only."""

    def __init__(self, connection: PostgresConnection | None = None) -> None:
        self.connection = connection or PostgresConnection.from_environment()

    @staticmethod
    def _cardinality(rows: list[tuple[Any, ...]]) -> int:
        # Census queries are SELECT COUNT(*) and return one scalar. For a
        # general SELECT, the exact cardinality is the number of returned rows.
        if len(rows) == 1 and len(rows[0]) == 1 and isinstance(rows[0][0], int):
            return int(rows[0][0])
        return len(rows)

    def execute_workload(
        self, workload: Workload, instance: PostgresInstance
    ) -> tuple[QueryExecutionResult, ...]:
        if not isinstance(workload, Workload):
            raise TypeError("workload must be a Workload")
        if not isinstance(instance, PostgresInstance):
            raise TypeError("PostgreSQLQueryRunner requires a PostgresInstance")
        validate_managed_database_name(instance.database_name)
        target = self.connection.for_database(instance.database_name)
        results: list[QueryExecutionResult] = []
        try:
            target.connect()
            for query in workload.queries:
                if not query.sql.lstrip().upper().startswith("SELECT"):
                    results.append(
                        QueryExecutionResult(
                            query_id=query.query_id,
                            status="FAIL",
                            execution_metadata={"error": "workload query is not a SELECT"},
                        )
                    )
                    continue
                try:
                    rows = target.execute(query.sql)
                    results.append(
                        QueryExecutionResult(
                            query_id=query.query_id,
                            status="PASS",
                            execution_metadata={"cardinality": self._cardinality(rows)},
                        )
                    )
                except Exception as exc:
                    results.append(
                        QueryExecutionResult(
                            query_id=query.query_id,
                            status="FAIL",
                            execution_metadata={"error": str(exc)},
                        )
                    )
        finally:
            target.close()
        return tuple(results)

    def close(self) -> None:
        self.connection.close()
