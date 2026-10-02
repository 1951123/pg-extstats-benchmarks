"""Small PostgreSQL connection boundary used by the PostgreSQL loader.

The optional ``psycopg`` driver is imported only when a connection is opened.
All SQL used by the PostgreSQL lifecycle lives in this module; loaders call
the named helpers rather than embedding SQL statements.
"""

from dataclasses import dataclass, field
import getpass
import os
import re
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_DATABASE_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*$")
_MANAGED_PREFIX = "pgextbench_"
_MANAGED_STATISTICS_PREFIX = "pgextbench_stat_"
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
    if len(name) > 63 or not _DATABASE_IDENTIFIER.fullmatch(name):
        raise ValueError(f"unsafe database identifier: {name!r}")
    if managed:
        if not name.startswith(_MANAGED_PREFIX):
            raise ValueError("database name is not a managed pgextbench database")
        suffix = name[len(_MANAGED_PREFIX):]
        if not suffix or not _DATABASE_IDENTIFIER.fullmatch(suffix):
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
    _notices: list[str] = field(default_factory=list, init=False, repr=False, compare=False)

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
        add_notice_handler = getattr(self._connection, "add_notice_handler", None)
        if callable(add_notice_handler):
            add_notice_handler(self._collect_notice)
        return self._connection

    def _collect_notice(self, diagnostic: Any) -> None:
        message = getattr(diagnostic, "message_primary", None)
        self._notices.append(str(message or diagnostic))

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

    def set_config(self, name: str, value: str) -> None:
        """Set a session GUC through a parameterized server-side call."""

        if not isinstance(name, str) or not name.strip():
            raise ValueError("GUC name must be nonempty")
        if not isinstance(value, str):
            raise TypeError("GUC value must be a string")
        self.execute("SELECT set_config(%s, %s, false)", (name, value))

    def quote_relation(self, relation_identity: str) -> Any:
        """Return a safely quoted two-part relation identifier."""

        if not isinstance(relation_identity, str):
            raise TypeError("relation identity must be a string")
        parts = relation_identity.split(".")
        if len(parts) != 2 or any(not _IDENTIFIER.fullmatch(part) for part in parts):
            raise ValueError("relation identity must be schema.relation with safe identifiers")
        psycopg = _driver()
        return psycopg.sql.SQL("{}.{}").format(
            psycopg.sql.Identifier(parts[0]), psycopg.sql.Identifier(parts[1])
        )

    def analyze(self, relation_identity: str) -> None:
        """Run ANALYZE for one safely quoted relation."""

        psycopg = _driver()
        self.execute(psycopg.sql.SQL("ANALYZE {};").format(self.quote_relation(relation_identity)))

    def set_default_statistics_target(self, target: int) -> None:
        if not isinstance(target, int) or target <= 0:
            raise ValueError("statistics target must be positive")
        self.set_config("default_statistics_target", str(target))

    def create_statistics(
        self, schema: str, name: str, kind: str, columns: Sequence[str], relation_identity: str
    ) -> None:
        schema = _validate_identifier(schema, "statistics schema")
        name = _validate_identifier(name, "statistics name")
        if not name.startswith(_MANAGED_STATISTICS_PREFIX):
            raise ValueError("statistics name is not experiment-managed")
        if kind not in {"mcv", "fd"}:
            raise ValueError("statistics kind must be mcv or fd")
        columns = tuple(_validate_identifier(column, "statistics column") for column in columns)
        if len(columns) < 2:
            raise ValueError("statistics requires at least two columns")
        relation = self.quote_relation(relation_identity)
        psycopg = _driver()
        postgres_kind = "dependencies" if kind == "fd" else kind
        statement = psycopg.sql.SQL("CREATE STATISTICS {}.{} ({}) ON {} FROM {}").format(
            psycopg.sql.Identifier(schema), psycopg.sql.Identifier(name), psycopg.sql.SQL(postgres_kind),
            psycopg.sql.SQL(", ").join(psycopg.sql.Identifier(column) for column in columns), relation,
        )
        self.execute(statement)

    def statistics_object(self, schema: str, name: str) -> tuple[Any, ...] | None:
        schema = _validate_identifier(schema, "statistics schema")
        name = _validate_identifier(name, "statistics name")
        rows = self.execute(
            "SELECT e.oid, e.stxrelid, e.stxkind, e.stxname FROM pg_catalog.pg_statistic_ext e "
            "JOIN pg_catalog.pg_namespace n ON n.oid=e.stxnamespace "
            "WHERE n.nspname=%s AND e.stxname=%s", (schema, name)
        )
        return rows[0] if rows else None

    def set_statistics_target(self, schema: str, name: str, target: int) -> None:
        schema = _validate_identifier(schema, "statistics schema")
        name = _validate_identifier(name, "statistics name")
        if not name.startswith(_MANAGED_STATISTICS_PREFIX):
            raise ValueError("statistics name is not experiment-managed")
        if not isinstance(target, int) or target <= 0:
            raise ValueError("statistics target must be positive")
        psycopg = _driver()
        self.execute(
            psycopg.sql.SQL("ALTER STATISTICS {}.{} SET STATISTICS {}").format(
                psycopg.sql.Identifier(schema), psycopg.sql.Identifier(name), psycopg.sql.Literal(target)
            )
        )

    def native_statistics_payload(self, schema: str, name: str, kind: str) -> tuple[Any, ...] | None:
        schema = _validate_identifier(schema, "statistics schema")
        name = _validate_identifier(name, "statistics name")
        if kind not in {"mcv", "fd"}:
            raise ValueError("statistics kind must be mcv or fd")
        expression = "pg_mcv_list_send(d.stxdmcv)" if kind == "mcv" else "pg_dependencies_send(d.stxddependencies)"
        rows = self.execute(
            f"SELECT {expression}, e.oid, e.stxrelid, e.stxkind FROM pg_catalog.pg_statistic_ext e "
            "JOIN pg_catalog.pg_namespace n ON n.oid=e.stxnamespace "
            "LEFT JOIN pg_catalog.pg_statistic_ext_data d ON d.stxoid=e.oid "
            "WHERE n.nspname=%s AND e.stxname=%s", (schema, name)
        )
        return rows[0] if rows else None

    def ordinary_statistics(self, relation_identity: str) -> list[tuple[Any, ...]]:
        parts = relation_identity.split(".") if isinstance(relation_identity, str) else []
        if len(parts) != 2 or any(not _IDENTIFIER.fullmatch(part) for part in parts):
            raise ValueError("relation identity must be schema.relation")
        return self.execute(
            "SELECT attname, null_frac, avg_width, n_distinct, most_common_vals::text, "
            "most_common_freqs::text, histogram_bounds::text, correlation "
            "FROM pg_catalog.pg_stats WHERE schemaname=%s AND tablename=%s ORDER BY attname",
            (parts[0], parts[1]),
        )

    def drop_statistics(self, schema: str, name: str) -> None:
        schema = _validate_identifier(schema, "statistics schema")
        name = _validate_identifier(name, "statistics name")
        if not name.startswith(_MANAGED_STATISTICS_PREFIX):
            raise ValueError("refusing to drop non-managed statistics")
        psycopg = _driver()
        self.execute(
            psycopg.sql.SQL("DROP STATISTICS IF EXISTS {}.{}").format(
                psycopg.sql.Identifier(schema), psycopg.sql.Identifier(name)
            )
        )

    def relation_metadata(self, relation_identity: str) -> list[tuple[Any, ...]]:
        """Read stable relation/column metadata for a provenance fingerprint."""

        parts = relation_identity.split(".") if isinstance(relation_identity, str) else []
        if len(parts) != 2 or any(not _IDENTIFIER.fullmatch(part) for part in parts):
            raise ValueError("relation identity must be schema.relation with safe identifiers")
        return self.execute(
            "SELECT c.oid, n.nspname, c.relname, a.attnum, a.attname, "
            "a.atttypid, a.atttypmod, a.attcollation, a.attisdropped "
            "FROM pg_catalog.pg_class AS c "
            "JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace "
            "JOIN pg_catalog.pg_attribute AS a ON a.attrelid = c.oid "
            "WHERE n.nspname = %s AND c.relname = %s AND a.attnum > 0 "
            "ORDER BY a.attnum",
            (parts[0], parts[1]),
        )

    def relation_oid(self, relation_identity: str) -> int:
        parts = relation_identity.split(".") if isinstance(relation_identity, str) else []
        if len(parts) != 2 or any(not _IDENTIFIER.fullmatch(part) for part in parts):
            raise ValueError("relation identity must be schema.relation")
        rows = self.execute(
            "SELECT c.oid FROM pg_catalog.pg_class AS c "
            "JOIN pg_catalog.pg_namespace AS n ON n.oid=c.relnamespace "
            "WHERE n.nspname=%s AND c.relname=%s AND c.relkind IN ('r','p')",
            (parts[0], parts[1]),
        )
        if not rows:
            raise ValueError(f"relation does not exist: {relation_identity}")
        return int(rows[0][0])

    def hypothetical_reset(self) -> None:
        """Clear the backend-local hypothetical repository and active design."""

        self.execute("SELECT pg_hypothetical_extstats_reset()")

    def hypothetical_register(self, statistics_oid: int, relation_oid: int, kind_code: str, payload: bytes) -> None:
        if not isinstance(statistics_oid, int) or statistics_oid <= 0:
            raise ValueError("statistics_oid must be positive")
        if not isinstance(relation_oid, int) or relation_oid <= 0:
            raise ValueError("relation_oid must be positive")
        if kind_code not in {"m", "f"}:
            raise ValueError("hypothetical statistics kind must be m or f")
        if not isinstance(payload, (bytes, bytearray)) or not payload:
            raise ValueError("hypothetical payload must be nonempty bytes")
        self.execute(
            'SELECT pg_hypothetical_extstats_register(%s::oid,%s::oid,%s::"char",%s::bytea)',
            (statistics_oid, relation_oid, kind_code, bytes(payload)),
        )

    def hypothetical_register_absent(self, statistics_oid: int, relation_oid: int, kind_code: str) -> None:
        if not isinstance(statistics_oid, int) or statistics_oid <= 0:
            raise ValueError("statistics_oid must be positive")
        if not isinstance(relation_oid, int) or relation_oid <= 0:
            raise ValueError("relation_oid must be positive")
        if kind_code not in {"m", "f"}:
            raise ValueError("hypothetical statistics kind must be m or f")
        self.execute(
            'SELECT pg_hypothetical_extstats_register_absent(%s::oid,%s::oid,%s::"char")',
            (statistics_oid, relation_oid, kind_code),
        )

    def hypothetical_register_definition(
        self, candidate_id: str, relation_oid: int, kind_code: str,
        attribute_keys: Sequence[int], payload: bytes,
    ) -> int:
        """Register a catalogless native hypothetical definition."""

        if not isinstance(candidate_id, str) or not candidate_id:
            raise ValueError("candidate_id must be nonempty")
        if not isinstance(attribute_keys, (list, tuple)) or len(attribute_keys) < 2:
            raise ValueError("attribute_keys must contain at least two entries")
        rows = self.execute(
            'SELECT pg_hypothetical_extstats_register_definition(%s,%s::oid,%s::"char",%s::smallint[],%s::bytea)',
            (candidate_id, relation_oid, kind_code, list(attribute_keys), bytes(payload)),
        )
        if not rows or not rows[0]:
            raise RuntimeError("catalogless hypothetical registration returned no identity")
        return int(rows[0][0])

    def hypothetical_register_definition_absent(
        self, candidate_id: str, relation_oid: int, kind_code: str,
        attribute_keys: Sequence[int],
    ) -> int:
        """Register an absent-native catalogless hypothetical definition."""

        if not isinstance(candidate_id, str) or not candidate_id:
            raise ValueError("candidate_id must be nonempty")
        if not isinstance(attribute_keys, (list, tuple)) or len(attribute_keys) < 2:
            raise ValueError("attribute_keys must contain at least two entries")
        rows = self.execute(
            'SELECT pg_hypothetical_extstats_register_definition_absent(%s,%s::oid,%s::"char",%s::smallint[])',
            (candidate_id, relation_oid, kind_code, list(attribute_keys)),
        )
        if not rows or not rows[0]:
            raise RuntimeError("catalogless hypothetical registration returned no identity")
        return int(rows[0][0])

    def hypothetical_activate(self, statistics_oids: Sequence[int]) -> list[int]:
        values = [int(value) for value in statistics_oids]
        if any(value <= 0 for value in values) or len(set(values)) != len(values):
            raise ValueError("hypothetical activation OIDs must be unique and positive")
        self.execute("SELECT pg_hypothetical_extstats_activate(%s::oid[])", (values,))
        rows = self.execute("SELECT pg_hypothetical_extstats_active()")
        if not rows:
            raise RuntimeError("hypothetical active-state probe returned no row")
        active = rows[0][0]
        if active is None:
            return []
        return [int(value) for value in active]

    def hypothetical_active(self) -> list[int]:
        rows = self.execute("SELECT pg_hypothetical_extstats_active()")
        if not rows:
            raise RuntimeError("hypothetical capability probe returned no row")
        active = rows[0][0]
        return [] if active is None else [int(value) for value in active]

    def explain_json(self, query: str) -> Any:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be nonempty SQL")
        rows = self.execute(f"EXPLAIN (FORMAT JSON) {query}")
        if not rows:
            raise RuntimeError("EXPLAIN returned no row")
        return rows[0][0]

    def notices(self) -> list[str]:
        """Return server notices when the installed psycopg exposes them."""

        connection = self.connect()
        notices = getattr(connection, "notices", ())
        if notices:
            return [str(value) for value in notices]
        return list(self._notices)

    def clear_notices(self) -> None:
        self._notices.clear()

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

    def copy_file(
        self,
        table: str,
        columns: Sequence[str],
        path: str | Path,
        *,
        delimiter: str = ",",
        header: bool = True,
    ) -> None:
        """Bulk-load a delimited file with PostgreSQL COPY FROM STDIN."""

        table = _validate_identifier(table, "table name")
        columns = tuple(_validate_identifier(column, "column name") for column in columns)
        if not columns:
            raise ValueError("at least one column is required")
        if not isinstance(delimiter, str) or len(delimiter) != 1:
            raise ValueError("COPY delimiter must be one character")
        source = Path(path)
        if not source.is_file():
            raise ValueError(f"COPY source is missing: {source}")
        psycopg = _driver()
        statement = psycopg.sql.SQL(
            "COPY public.{} ({}) FROM STDIN WITH (FORMAT csv, HEADER {}, DELIMITER {})"
        ).format(
            psycopg.sql.Identifier(table),
            psycopg.sql.SQL(", ").join(
                psycopg.sql.Identifier(column) for column in columns
            ),
            psycopg.sql.SQL("TRUE" if header else "FALSE"),
            psycopg.sql.Literal(delimiter),
        )
        connection = self.connect()
        try:
            with connection.cursor() as cursor:
                with cursor.copy(statement) as copy:
                    with source.open("rb") as stream:
                        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                            copy.write(chunk)
        except Exception as exc:
            raise RuntimeError(f"PostgreSQL COPY failed: {exc}") from exc

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

    def table_columns(self, table: str) -> list[str]:
        table = _validate_identifier(table, "table name")
        rows = self.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = %s "
            "ORDER BY ordinal_position",
            (table,),
        )
        return [str(row[0]) for row in rows]

    def for_database(self, database: str) -> "PostgresConnection":
        return type(self)(host=self.host, port=self.port, user=self.user, database=database)

    def close(self) -> None:
        """Close the connection if one is open; this is idempotent."""

        if self._connection is not None:
            self._connection.close()
            self._connection = None
