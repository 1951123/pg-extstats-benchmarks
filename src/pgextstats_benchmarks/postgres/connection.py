"""Small PostgreSQL connection boundary used by the PostgreSQL loader.

The optional ``psycopg`` driver is imported only when a connection is opened.
All SQL used by the PostgreSQL lifecycle lives in this module; loaders call
the named helpers rather than embedding SQL statements.
"""

from dataclasses import dataclass, field
import getpass
import os
import re
from typing import Any, Iterable, Mapping, Sequence


_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*$")
_MANAGED_PREFIX = "pgextbench_"
_RESERVED_DATABASES = frozenset({"postgres", "template0", "template1"})


def _validate_identifier(name: str, label: str = "identifier") -> str:
    if not isinstance(name, str) or not _IDENTIFIER.fullmatch(name):
        raise ValueError(f"unsafe {label}: {name!r}")
    return name


def _driver() -> Any:
    try:
        import psycopg
    except ImportError as exc:  # pragma: no cover - exercised without optional install
        raise RuntimeError(
            "PostgreSQL support requires psycopg[binary]>=3,<4; install project dependencies"
        ) from exc
    return psycopg


def _validate_database_name(name: str, *, managed: bool = True) -> str:
    if not isinstance(name, str) or not name:
        raise ValueError("database name must be a nonempty string")
    if name in _RESERVED_DATABASES:
        raise ValueError(f"refusing reserved database name: {name}")
    if len(name) > 63 or not _IDENTIFIER.fullmatch(name):
        raise ValueError(f"unsafe database identifier: {name!r}")
    if managed:
        if not name.startswith(_MANAGED_PREFIX):
            raise ValueError("database name is not a managed pgextbench database")
        suffix = name[len(_MANAGED_PREFIX):]
        if not suffix or not _IDENTIFIER.fullmatch(suffix):
            raise ValueError(f"unsafe managed database identifier: {name!r}")
    return name


@dataclass
class PostgresConnection:
    """Connection settings and one lazily opened psycopg connection.

    Passwords are deliberately not represented or persisted.  psycopg may
    obtain credentials through its normal environment or ``.pgpass`` rules.
    """

    host: str = "localhost"
    port: int = 55437
    user: str | None = None
    database: str = "postgres"
    _connection: Any = field(default=None, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.host, str) or not self.host.strip():
            raise ValueError("host must be a nonempty string")
        if not isinstance(self.port, int) or not 1 <= self.port <= 65535:
            raise ValueError("port must be an integer between 1 and 65535")
        if self.user is not None and (not isinstance(self.user, str) or not self.user.strip()):
            raise ValueError("user must be a nonempty string when provided")
        if not isinstance(self.database, str) or not self.database.strip():
            raise ValueError("database must be a nonempty string")

    @classmethod
    def from_environment(cls, database: str = "postgres") -> "PostgresConnection":
        """Build settings from PGHOST, PGPORT, and PGUSER.

        The defaults target the isolated patched PostgreSQL instance used by
        this project and do not include a password.
        """

        raw_port = os.environ.get("PGPORT", "55437")
        try:
            port = int(raw_port)
        except ValueError as exc:
            raise ValueError("PGPORT must be an integer") from exc
        return cls(
            host=os.environ.get("PGHOST", "localhost"),
            port=port,
            user=os.environ.get("PGUSER") or getpass.getuser(),
            database=database,
        )

    def connect(self) -> Any:
        """Open and return the psycopg connection, reusing an open one."""

        if self._connection is not None and not self._connection.closed:
            return self._connection
        psycopg = _driver()
        kwargs: dict[str, Any] = {
            "host": self.host,
            "port": self.port,
            "dbname": self.database,
            "autocommit": True,
        }
        if self.user is not None:
            kwargs["user"] = self.user
        try:
            self._connection = psycopg.connect(**kwargs)
        except Exception as exc:
            raise RuntimeError(
                f"could not connect to PostgreSQL at {self.host}:{self.port}/{self.database}: {exc}"
            ) from exc
        return self._connection

    def execute(self, query: Any, params: Mapping[str, Any] | tuple[Any, ...] | None = None) -> list[tuple[Any, ...]]:
        """Execute one query and return rows, if the query produces rows."""

        connection = self.connect()
        try:
            with connection.cursor() as cursor:
                if params is None:
                    cursor.execute(query)
                else:
                    cursor.execute(query, params)
                if cursor.description is None:
                    return []
                return list(cursor.fetchall())
        except Exception as exc:
            raise RuntimeError(f"PostgreSQL query failed: {exc}") from exc

    def database_exists(self, database_name: str) -> bool:
        _validate_database_name(database_name)
        return bool(self.execute(
            "SELECT 1 FROM pg_catalog.pg_database WHERE datname = %s",
            (database_name,),
        ))

    def create_database(self, database_name: str) -> None:
        database_name = _validate_database_name(database_name)
        psycopg = _driver()
        statement = psycopg.sql.SQL("CREATE DATABASE {}").format(
            psycopg.sql.Identifier(database_name)
        )
        self.execute(statement)

    def drop_database(self, database_name: str) -> None:
        database_name = _validate_database_name(database_name)
        psycopg = _driver()
        statement = psycopg.sql.SQL("DROP DATABASE {}").format(
            psycopg.sql.Identifier(database_name)
        )
        self.execute(statement)

    def server_version(self) -> str:
        rows = self.execute("SELECT version()")
        if not rows or not rows[0] or not isinstance(rows[0][0], str):
            raise RuntimeError("PostgreSQL version query returned no value")
        return rows[0][0]

    def execute_script(self, script: str) -> None:
        """Execute a schema script supplied by a prepared artifact."""

        if not isinstance(script, str) or not script.strip():
            raise ValueError("schema script must be nonempty")
        self.execute(script)

    def insert_rows(
        self,
        table: str,
        columns: Sequence[str],
        rows: Iterable[Sequence[Any]],
    ) -> int:
        """Insert prepared rows using quoted identifiers and parameters."""

        table = _validate_identifier(table, "table name")
        columns = tuple(_validate_identifier(column, "column name") for column in columns)
        if not columns:
            raise ValueError("at least one column is required")
        values = [tuple(row) for row in rows]
        if not values:
            return 0
        if any(len(row) != len(columns) for row in values):
            raise ValueError("row width does not match the declared columns")
        psycopg = _driver()
        statement = psycopg.sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
            psycopg.sql.Identifier(table),
            psycopg.sql.SQL(", ").join(psycopg.sql.Identifier(column) for column in columns),
            psycopg.sql.SQL(", ").join(psycopg.sql.Placeholder() for _ in columns),
        )
        connection = self.connect()
        try:
            with connection.cursor() as cursor:
                cursor.executemany(statement, values)
        except Exception as exc:
            raise RuntimeError(f"PostgreSQL row load failed: {exc}") from exc
        return len(values)

    def table_exists(self, table: str) -> bool:
        table = _validate_identifier(table, "table name")
        return bool(self.execute(
            "SELECT 1 FROM pg_catalog.pg_class AS c "
            "JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND c.relname = %s "
            "AND c.relkind IN ('r', 'p')",
            (table,),
        ))

    def row_count(self, table: str) -> int:
        table = _validate_identifier(table, "table name")
        psycopg = _driver()
        statement = psycopg.sql.SQL("SELECT count(*) FROM public.{}").format(
            psycopg.sql.Identifier(table)
        )
        rows = self.execute(statement)
        if not rows or not rows[0]:
            raise RuntimeError("row count query returned no value")
        return int(rows[0][0])

    def for_database(self, database: str) -> "PostgresConnection":
        return type(self)(host=self.host, port=self.port, user=self.user, database=database)

    def close(self) -> None:
        """Close the connection if one is open; this is idempotent."""

        if self._connection is not None:
            self._connection.close()
            self._connection = None
