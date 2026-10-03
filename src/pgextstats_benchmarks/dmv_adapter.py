"""DMV benchmark acquisition, preparation, and workload lifecycle.

The DMV archive is manually acquired because its historical Dropbox sharing URL
is not a stable unattended download endpoint.  This adapter consumes the
immutable local ``data.tar.gz`` and only downloads the small, stable BayesCard
workload source when it is not already cached.  All generated artifacts live
under ``PGEXTADV_BENCHMARK_DATA``.
"""
from __future__ import annotations

from datetime import datetime, timezone
import csv
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import tarfile
from typing import Any, Callable, Mapping
from urllib.request import urlopen

from .adapter import BenchmarkAdapter
from .adapters import register_adapter
from .artifacts import Artifact
from .paths import benchmark_data_root, confined_path
from .registry import load_manifest, load_registry, read_mapping
from .truth import TruthArtifact
from .estimate import workload_digest
from .workload_executor import Query, Workload, load_workload_artifact

DMV_COLUMNS = (
    "record_type", "registration_class", "state", "county", "body_type",
    "fuel_type", "reg_valid_date", "color", "scofflaw_indicator",
    "suspension_indicator", "revocation_indicator",
)
DMV_ARCHIVE_MEMBER = "data/dmv11/original.csv"
DMV_RAW_FILENAME = "data.tar.gz"

_IN_LIST = re.compile(r"\bIN\s*\[([^\]]*)\]", re.IGNORECASE)
_FROM_DMV = re.compile(r"\bFROM\s+DMV\b", re.IGNORECASE)
_EQUALITY_TOKEN = re.compile(
    r"(\b[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?![\'\"])(.*?)(?=\s+(?:AND|OR)\s+|$)",
    re.IGNORECASE,
)


class DMVAdapter(BenchmarkAdapter):
    """Materialize the DMV benchmark from a manually acquired archive."""

    def __init__(
        self,
        *,
        repo_root: Path | None = None,
        data_root: Path | None = None,
        downloader: Callable[[str], bytes] | None = None,
        source_declarations: Mapping[str, Mapping[str, Any]] | None = None,
        raw_archive: Path | None = None,
    ) -> None:
        self.repo_root = Path(repo_root or Path(__file__).resolve().parents[2]).resolve()
        root = Path(data_root).expanduser().resolve() if data_root is not None else benchmark_data_root()
        if root == self.repo_root or root.is_relative_to(self.repo_root):
            raise ValueError("DMV data root must be outside the benchmark repository")
        self.data_root = root
        self._downloader = downloader
        self._provided_sources = source_declarations
        self._raw_archive_override = Path(raw_archive).expanduser().resolve() if raw_archive is not None else None

    @property
    def dmv_root(self) -> Path:
        return self.data_root / "dmv"

    @property
    def artifacts_root(self) -> Path:
        return self.dmv_root / "artifacts"

    @property
    def source_cache(self) -> Path:
        return self.dmv_root / "source-cache"

    @property
    def relation_identity(self) -> str:
        return "public.dmv"

    def _source_declarations(self) -> dict[str, dict[str, Any]]:
        if self._provided_sources is not None:
            return {key: dict(value) for key, value in self._provided_sources.items()}
        definition = load_registry(self.repo_root)["dmv"]
        manifest = load_manifest(definition)
        return {
            name: read_mapping(confined_path(definition.path, entry["manifest"]))
            for name, entry in manifest["sources"].items()
        }

    def _source(self, name: str) -> tuple[str, str]:
        try:
            declaration = self._source_declarations()[name]
            url = declaration.get("source_url") or declaration.get("raw_url") or declaration.get("url")
            digest = declaration["sha256"]
        except (KeyError, TypeError) as exc:
            raise ValueError(f"DMV source declaration is incomplete: {name}") from exc
        if not isinstance(url, str) or not url.strip():
            raise ValueError(f"DMV source URL is missing: {name}")
        if not isinstance(digest, str) or len(digest) != 64:
            raise ValueError(f"DMV source SHA256 is invalid: {name}")
        return url, digest.lower()

    @staticmethod
    def _digest(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _bytes_digest(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _write_json(path: Path, value: Mapping[str, Any]) -> None:
        path.write_text(json.dumps(dict(value), sort_keys=True, indent=2) + "\n", encoding="utf-8")

    @staticmethod
    def _manifest_path(directory: Path) -> Path:
        return directory / "manifest.json"

    def _artifact_from_manifest(self, directory: Path) -> Artifact:
        manifest_path = self._manifest_path(directory)
        if not manifest_path.is_file():
            raise FileNotFoundError(f"DMV artifact manifest is missing: {manifest_path}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        return Artifact(
            id=manifest["artifact_id"],
            type=manifest["type"],
            path=directory,
            digest=manifest.get("sha256"),
            metadata=manifest,
            created_at=manifest.get("timestamp"),
            created_by="DMVAdapter",
            parent_artifacts=tuple(manifest.get("parent_artifacts", ())),
        )

    def prepared_artifact(self) -> Artifact:
        return self._artifact_from_manifest(self.artifacts_root / "dmv-prepared-v1")

    def _raw_filename(self) -> str:
        value = self._source_declarations().get("data", {}).get("raw_filename", DMV_RAW_FILENAME)
        if not isinstance(value, str) or not value or Path(value).name != value:
            raise ValueError("DMV source raw_filename must be one safe filename")
        return value

    def _raw_archive_path(self) -> Path:
        if self._raw_archive_override is not None:
            return self._raw_archive_override
        return self.dmv_root / "incoming" / self._raw_filename()

    def _download(self, url: str) -> bytes:
        if self._downloader is not None:
            return self._downloader(url)
        with urlopen(url, timeout=60) as response:
            return response.read()

    def _ensure_workload_cache(self, expected: str) -> Path:
        path = self.source_cache / "query.sql"
        if path.is_file():
            actual = self._digest(path)
            if actual != expected:
                raise ValueError(f"DMV workload checksum mismatch: expected {expected}, got {actual}")
            return path
        if path.exists():
            raise FileExistsError(f"DMV workload cache is not a regular file: {path}")
        url, _ = self._source("workload")
        data = self._download(url)
        actual = self._bytes_digest(data)
        if actual != expected:
            raise ValueError(f"DMV workload checksum mismatch: expected {expected}, got {actual}")
        self.source_cache.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(data)
        return path

    def fetch(self) -> dict[str, Any]:
        """Validate manual input and materialize immutable raw/workload sources."""
        dataset_url, expected_dataset = self._source("data")
        workload_url, expected_workload = self._source("workload")
        raw_filename = self._raw_filename()
        archive = self._raw_archive_path()
        if not archive.is_file():
            raise FileNotFoundError(
                "DMV raw archive is missing; manual acquisition required: "
                f"place {raw_filename} at {archive}"
            )
        actual = self._digest(archive)
        if actual != expected_dataset:
            raise ValueError(f"DMV raw archive checksum mismatch: expected {expected_dataset}, got {actual}")

        raw_dir = self.artifacts_root / "dmv-raw-v1"
        raw_dir.mkdir(parents=True, exist_ok=True)
        payload = raw_dir / raw_filename
        if payload.exists():
            if not payload.is_file() or self._digest(payload) != expected_dataset:
                raise FileExistsError(f"DMV raw artifact already exists with different content: {payload}")
        else:
            shutil.copyfile(archive, payload)
        workload_cache = self._ensure_workload_cache(expected_workload)
        manifest_path = self._manifest_path(raw_dir)
        if not manifest_path.exists():
            self._write_json(
                manifest_path,
                {
                    "artifact_id": "dmv-raw-v1",
                    "type": "raw_dataset",
                    "parent_artifacts": [],
                    "source_url": dataset_url,
                    "acquisition_url": self._source_declarations()["data"].get("acquisition_url"),
                    "sha256": expected_dataset,
                    "size": payload.stat().st_size,
                    "timestamp": self._timestamp(),
                    "payload_path": raw_filename,
                    "raw_filename": raw_filename,
                    "archive_type": "tar.gz",
                    "manual_acquisition": True,
                    "workload_source_url": workload_url,
                    "workload_sha256": expected_workload,
                },
            )
        raw = self._artifact_from_manifest(raw_dir)
        return {
            "status": "PASS",
            "message": "dmv fetch completed (manual archive verified)",
            "output_artifacts": (raw,),
            "metadata": {"workload_cached": str(workload_cache), "manual_acquisition": True},
        }

    @staticmethod
    def _safe_member(name: str, root: Path) -> Path:
        member = PurePosixPath(name)
        if member.is_absolute() or ".." in member.parts or not name:
            raise ValueError(f"Unsafe DMV archive member: {name}")
        target = (root / Path(*member.parts)).resolve()
        if target == root or not target.is_relative_to(root.resolve()):
            raise ValueError(f"Unsafe DMV archive member: {name}")
        return target

    def _normalize_data(self, source: Path, target: Path) -> tuple[int, str, list[str]]:
        target.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        rows = 0
        with source.open("r", encoding="utf-8", newline="") as input_stream, target.open("w", encoding="utf-8", newline="") as output_stream:
            reader = csv.reader(input_stream)
            writer = csv.writer(output_stream, lineterminator="\n")
            try:
                header = next(reader)
            except StopIteration as exc:
                raise ValueError("DMV source CSV is empty") from exc
            if len(header) != len(DMV_COLUMNS):
                raise ValueError(f"DMV source CSV has {len(header)} columns, expected {len(DMV_COLUMNS)}")
            normalized_header = [value.strip().lower() for value in header]
            if normalized_header != list(DMV_COLUMNS):
                raise ValueError(f"unexpected DMV source header: {header!r}")
            writer.writerow(normalized_header)
            for row_number, row in enumerate(reader, start=2):
                if len(row) != len(DMV_COLUMNS):
                    raise ValueError(f"DMV source row {row_number} has {len(row)} fields")
                writer.writerow([value.strip() for value in row])
                rows += 1
        with target.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return rows, digest.hexdigest(), normalized_header

    def prepare(self) -> dict[str, Any]:
        """Extract the complete archive and create deterministic trimmed CSV data."""
        raw = self._artifact_from_manifest(self.artifacts_root / "dmv-raw-v1")
        raw_manifest = dict(raw.metadata)
        payload = Path(raw.path) / raw_manifest.get("payload_path", DMV_RAW_FILENAME)
        if not payload.is_file():
            raise FileNotFoundError(f"DMV raw payload is missing: {payload}")
        expected = raw_manifest.get("sha256")
        if self._digest(payload) != expected:
            raise ValueError("DMV raw archive checksum mismatch")
        prepared_dir = self.artifacts_root / "dmv-prepared-v1"
        existing = self._manifest_path(prepared_dir)
        if existing.is_file():
            return {
                "status": "PASS",
                "message": "dmv prepare completed (existing deterministic artifact)",
                "input_artifacts": (raw,),
                "output_artifacts": (self._artifact_from_manifest(prepared_dir),),
            }
        if prepared_dir.exists():
            raise FileExistsError(f"DMV prepared artifact directory exists without manifest: {prepared_dir}")
        prepared_dir.mkdir(parents=True)
        members: list[dict[str, Any]] = []
        with tarfile.open(payload, "r:gz") as archive:
            for info in archive.getmembers():
                target = self._safe_member(info.name, prepared_dir)
                if info.issym() or info.islnk() or not (info.isdir() or info.isreg()):
                    raise ValueError(f"unsupported DMV archive member type: {info.name}")
                if info.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    source = archive.extractfile(info)
                    if source is None:
                        raise ValueError(f"DMV archive member cannot be read: {info.name}")
                    with target.open("xb") as output:
                        shutil.copyfileobj(source, output, length=1024 * 1024)
                members.append({
                    "name": info.name,
                    "size": info.size,
                    "mode": info.mode,
                    "directory": info.isdir(),
                })
        source_csv = prepared_dir / DMV_ARCHIVE_MEMBER
        if not source_csv.is_file():
            raise ValueError(f"DMV archive has no required member: {DMV_ARCHIVE_MEMBER}")
        normalized_csv = prepared_dir / "dmv.csv"
        expected_rows, prepared_sha, columns = self._normalize_data(source_csv, normalized_csv)
        schema_source = self.repo_root / "benchmarks" / "dmv" / "schema" / "schema.sql"
        if not schema_source.is_file():
            raise FileNotFoundError(f"DMV schema artifact is missing: {schema_source}")
        (prepared_dir / "schema.sql").write_bytes(schema_source.read_bytes())
        timestamp = raw_manifest.get("timestamp") or self._timestamp()
        self._write_json(
            self._manifest_path(prepared_dir),
            {
                "artifact_id": "dmv-prepared-v1",
                "type": "prepared_dataset",
                "parent_artifacts": ["dmv-raw-v1"],
                "source_url": raw_manifest.get("source_url"),
                "sha256": prepared_sha,
                "size": normalized_csv.stat().st_size,
                "timestamp": timestamp,
                "archive_members": members,
                "source_data_path": DMV_ARCHIVE_MEMBER,
                "source_data_sha256": self._digest(source_csv),
                "schema_artifact_id": "dmv-schema-v1",
                "schema_path": "schema.sql",
                "data_path": "dmv.csv",
                "table": "dmv",
                "columns": columns,
                "database_columns": list(DMV_COLUMNS),
                "expected_rows": expected_rows,
                "format": "csv",
                "delimiter": ",",
                "header": True,
                "encoding": "utf-8",
                "transformation_version": "dmv-trim-v1",
                "transformation": "trim surrounding whitespace in every CSV field; preserve row order",
                "raw_archive_sha256": raw_manifest.get("sha256"),
            },
        )
        artifact = self._artifact_from_manifest(prepared_dir)
        return {
            "status": "PASS",
            "message": "dmv prepare completed",
            "input_artifacts": (raw,),
            "output_artifacts": (artifact,),
            "metadata": {"archive_members": members, "rows": expected_rows},
        }

    @staticmethod
    def _sql_literal(value: str) -> str:
        return "'" + value.replace("'", "''") + "'"

    @classmethod
    def _normalize_query(cls, sql: str) -> str:
        def replace_list(match: re.Match[str]) -> str:
            values = [item.strip() for item in match.group(1).split(",")]
            return "IN (" + ", ".join(cls._sql_literal(item) for item in values) + ")"
        sql = _IN_LIST.sub(replace_list, sql)
        sql = sql.replace("==", "=")
        sql = _EQUALITY_TOKEN.sub(lambda match: f"{match.group(1)} = {cls._sql_literal(match.group(2))}", sql)
        sql = _FROM_DMV.sub("FROM public.dmv", sql)
        return sql.strip()

    @classmethod
    def _normalize_workload_bytes(cls, source: bytes, expected: str) -> tuple[Workload, bytes]:
        actual = hashlib.sha256(source).hexdigest()
        if actual != expected:
            raise ValueError(f"DMV workload checksum mismatch: expected {expected}, got {actual}")
        queries: list[Query] = []
        source_line_count = 0
        normalized_lines: list[str] = []
        for source_line_count, line in enumerate(source.decode("utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            sql, separator, _truth = line.partition("||")
            if not separator:
                raise ValueError(f"DMV workload line {source_line_count} has no || truth suffix")
            normalized = cls._normalize_query(sql)
            if not normalized.upper().startswith("SELECT"):
                raise ValueError(f"DMV workload line {source_line_count} is not a SELECT query")
            normalized_lines.append(normalized)
            queries.append(Query(query_id=f"q{len(queries) + 1:04d}", sql=normalized))
        normalized_bytes = ("\n".join(normalized_lines) + "\n").encode("utf-8")
        workload = Workload(
            workload_id="dmv-workload-v1",
            queries=tuple(queries),
            metadata={
                "source_checksum": actual,
                "source_bytes": len(source),
                "source_line_count": source_line_count,
                "query_count": len(queries),
                "normalization": "convert BayesCard IN [...], bare scalar literals, and == syntax to PostgreSQL IN (...), quoted literals, and =; qualify DMV as public.dmv",
                "query_id_format": "qNNNN",
            },
        )
        return workload, normalized_bytes

    def normalize_workload(self) -> dict[str, Any]:
        """Preserve source SQL and create deterministic PostgreSQL workload SQL."""
        _url, expected = self._source("workload")
        source_path = self.source_cache / "query.sql"
        if not source_path.is_file():
            raise FileNotFoundError("Run DMV fetch before normalize_workload")
        source = source_path.read_bytes()
        workload, normalized_bytes = self._normalize_workload_bytes(source, expected)
        workload_dir = self.artifacts_root / "dmv-workload-v1"
        workload_dir.mkdir(parents=True, exist_ok=True)
        query_path = workload_dir / "query.sql"
        source_query_path = workload_dir / "source_query.sql"
        if query_path.exists() and query_path.read_bytes() != normalized_bytes:
            raise FileExistsError(f"DMV workload artifact already exists with different content: {query_path}")
        if source_query_path.exists() and source_query_path.read_bytes() != source:
            raise FileExistsError(f"DMV source workload already exists with different content: {source_query_path}")
        if not query_path.exists():
            query_path.write_bytes(normalized_bytes)
        if not source_query_path.exists():
            source_query_path.write_bytes(source)
        manifest_path = self._manifest_path(workload_dir)
        normalized_sha = self._bytes_digest(normalized_bytes)
        if not manifest_path.exists():
            self._write_json(
                manifest_path,
                {
                    "artifact_id": "dmv-workload-v1",
                    "type": "workload",
                    "parent_artifacts": [],
                    "source_url": self._source("workload")[0],
                    "sha256": normalized_sha,
                    "source_checksum": expected,
                    "source_payload_path": "source_query.sql",
                    "normalized_payload_path": "query.sql",
                    "size": len(normalized_bytes),
                    "source_size": len(source),
                    "timestamp": self._timestamp(),
                    "query_count": workload.query_count,
                    "source_line_count": workload.metadata["source_line_count"],
                    "normalization": workload.metadata["normalization"],
                    "query_id_format": workload.metadata["query_id_format"],
                },
            )
        artifact = self._artifact_from_manifest(workload_dir)
        return {
            "status": "PASS",
            "message": "dmv normalize_workload completed",
            "output_artifacts": (artifact,),
            "workload": workload,
        }

    def collect_truth(self, instance: Any = None, runner: Any = None) -> dict[str, Any]:
        if instance is None:
            return {"status": "INCOMPLETE", "message": "collect_truth requires a loaded PostgreSQL instance"}
        workload_dir = self.artifacts_root / "dmv-workload-v1"
        workload_artifact = self._artifact_from_manifest(workload_dir)
        workload = load_workload_artifact(workload_dir)
        if runner is None:
            from .postgres.query_runner import PostgreSQLQueryRunner
            runner = PostgreSQLQueryRunner()
        results = runner.execute_workload(workload, instance)
        truth = TruthArtifact(
            benchmark_id="dmv",
            workload_id=workload.workload_id,
            query_results=results,
            metadata={
                "runner": runner.__class__.__name__,
                "query_count": workload.query_count,
                "successful_queries": sum(result.status == "PASS" for result in results),
                "workload_digest": workload_digest(workload),
            },
        )
        truth_dir = self.artifacts_root / "dmv-truth-v1"
        truth_dir.mkdir(parents=True, exist_ok=True)
        truth_bytes = truth.to_json().encode("utf-8")
        truth_path = truth_dir / "truth.json"
        manifest_path = self._manifest_path(truth_dir)
        replace_incomplete = False
        if truth_path.exists() and truth_path.read_bytes() != truth_bytes:
            if not manifest_path.exists():
                raise FileExistsError(f"DMV truth artifact already exists with different content: {truth_path}")
            existing_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            replace_incomplete = (
                existing_manifest.get("successful_queries")
                != existing_manifest.get("query_count")
            )
            if not replace_incomplete:
                raise FileExistsError(f"DMV truth artifact already exists with different content: {truth_path}")
        if not truth_path.exists() or replace_incomplete:
            truth_path.write_bytes(truth_bytes)
        truth_digest = self._bytes_digest(truth_bytes)
        if not manifest_path.exists() or replace_incomplete:
            self._write_json(
                manifest_path,
                {
                    "artifact_id": "dmv-truth-v1",
                    "type": "truth",
                    "parent_artifacts": [workload_artifact.id],
                    "sha256": truth_digest,
                    "size": len(truth_bytes),
                    "timestamp": self._timestamp(),
                    "workload_id": workload.workload_id,
                    "query_count": workload.query_count,
                    "successful_queries": truth.successful_queries,
                    "runner": runner.__class__.__name__,
                },
            )
        artifact = self._artifact_from_manifest(truth_dir)
        status = "PASS" if truth.successful_queries == truth.query_count else "FAIL"
        return {
            "status": status,
            "message": "dmv truth collection completed" if status == "PASS" else "dmv truth collection had failures",
            "input_artifacts": (workload_artifact,),
            "output_artifacts": (artifact,),
            "truth": truth,
            "workload": workload,
        }

    def load(self) -> dict[str, Any]:
        return {"status": "INCOMPLETE", "message": "DMV load requires a managed PostgreSQL instance; use load-dmv-postgres"}

    def validate(self) -> dict[str, Any]:
        return {"status": "INCOMPLETE", "message": "DMV validation requires a loaded instance; use load-dmv-postgres"}


register_adapter("dmv", DMVAdapter)

__all__ = ["DMVAdapter", "DMV_COLUMNS"]
