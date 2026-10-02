"""Fetch and prepare the Census benchmark without DBMS or query execution."""
from __future__ import annotations

from datetime import datetime, timezone
import csv
import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping
from urllib.request import urlopen
import zipfile

from .adapter import BenchmarkAdapter
from .artifacts import Artifact
from .paths import benchmark_data_root, confined_path
from .registry import load_manifest, load_registry, read_mapping
from .adapters import register_adapter
from .workload_executor import load_workload_artifact, normalize_workload
from .truth import TruthArtifact


class CensusAdapter(BenchmarkAdapter):
    """Materialize Census source files into an external, controlled data root.

    The source URL and expected checksums are read from the Census source YAML
    declarations.  ``data_root`` and ``downloader`` are injectable so tests can
    use small recorded fixtures without contacting the network.
    """

    def __init__(
        self,
        *,
        repo_root: Path | None = None,
        data_root: Path | None = None,
        downloader: Callable[[str], bytes] | None = None,
        source_declarations: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> None:
        self.repo_root = Path(repo_root or Path(__file__).resolve().parents[2]).resolve()
        root = Path(data_root).expanduser().resolve() if data_root is not None else benchmark_data_root()
        if root == self.repo_root or root.is_relative_to(self.repo_root):
            raise ValueError("Census data root must be outside the benchmark repository")
        self.data_root = root
        self._downloader = downloader
        self._provided_sources = source_declarations

    @property
    def census_root(self) -> Path:
        return self.data_root / "census"

    @property
    def artifacts_root(self) -> Path:
        return self.census_root / "artifacts"

    @property
    def source_cache(self) -> Path:
        return self.census_root / "source-cache"

    @property
    def relation_identity(self) -> str:
        """Stable logical relation name used by the sample lifecycle."""
        return "public.census"

    def prepared_artifact(self) -> Artifact:
        """Load the existing prepared artifact without fetching or executing it."""
        return self._artifact_from_manifest(self.artifacts_root / "census-prepared-v1")

    def _source_declarations(self) -> dict[str, dict[str, Any]]:
        if self._provided_sources is not None:
            return {key: dict(value) for key, value in self._provided_sources.items()}
        benchmarks = load_registry(self.repo_root)
        definition = benchmarks["census"]
        manifest = load_manifest(definition)
        result: dict[str, dict[str, Any]] = {}
        for name, entry in manifest["sources"].items():
            source_path = confined_path(definition.path, entry["manifest"])
            result[name] = read_mapping(source_path)
        return result

    def _source(self, name: str) -> tuple[str, str]:
        try:
            declaration = self._source_declarations()[name]
            url = declaration.get("source_url") or declaration.get("raw_url") or declaration.get("url")
            digest = declaration["sha256"]
        except (KeyError, TypeError) as exc:
            raise ValueError(f"Census source declaration is incomplete: {name}") from exc
        if not isinstance(url, str) or not url.strip():
            raise ValueError(f"Census source URL is missing: {name}")
        if not isinstance(digest, str) or len(digest) != 64:
            raise ValueError(f"Census source SHA256 is invalid: {name}")
        return url, digest.lower()

    def _download(self, url: str) -> bytes:
        if self._downloader is not None:
            return self._downloader(url)
        with urlopen(url, timeout=60) as response:
            return response.read()

    @staticmethod
    def _digest(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _write_json(path: Path, value: Mapping[str, Any]) -> None:
        path.write_text(json.dumps(dict(value), sort_keys=True, indent=2) + "\n", encoding="utf-8")

    def _artifact_manifest(self, artifact_dir: Path) -> Path:
        return artifact_dir / "manifest.json"

    def _artifact_from_manifest(self, artifact_dir: Path) -> Artifact:
        manifest_path = self._artifact_manifest(artifact_dir)
        if not manifest_path.is_file():
            raise FileNotFoundError(f"Census artifact manifest is missing: {manifest_path}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        return Artifact(
            id=manifest["artifact_id"],
            type=manifest["type"],
            path=artifact_dir,
            digest=manifest.get("sha256"),
            metadata=manifest,
            created_at=manifest.get("timestamp"),
            created_by="CensusAdapter",
            parent_artifacts=tuple(manifest.get("parent_artifacts", ())),
        )

    def _write_source(self, path: Path, data: bytes, expected: str, label: str) -> None:
        actual = self._digest(data)
        if actual != expected:
            raise ValueError(f"Census {label} checksum mismatch: expected {expected}, got {actual}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    @staticmethod
    def _data_member(prepared_dir: Path, members: list[dict[str, Any]]) -> tuple[str, list[str], int]:
        """Identify the transformed Census CSV and inspect its header/row count."""
        names = [member["name"] for member in members if not member["directory"]]
        preferred = next(
            (name for name in names if Path(name).name == "USCensus1990.data.txt"),
            None,
        )
        candidate = preferred or next(
            (name for name in names if Path(name).suffix.lower() == ".csv"),
            None,
        )
        if candidate is None:
            for name in names:
                path = prepared_dir / name
                with path.open("r", encoding="utf-8", newline="") as stream:
                    first = stream.readline()
                if "," in first and not first.lstrip().startswith(("<", "<!")):
                    candidate = name
                    break
        if candidate is None:
            raise ValueError("Census archive has no detectable delimited data file")
        data_path = prepared_dir / candidate
        with data_path.open("r", encoding="utf-8", newline="") as stream:
            header = next(csv.reader([stream.readline()]), [])
        if not header or any(not isinstance(column, str) or not column for column in header):
            raise ValueError(f"Census data header is invalid: {candidate}")
        with data_path.open("rb") as stream:
            rows = sum(chunk.count(b"\n") for chunk in iter(lambda: stream.read(1024 * 1024), b""))
        if rows < 1:
            raise ValueError(f"Census data file has no header: {candidate}")
        return candidate, header, rows - 1

    def fetch(self) -> dict[str, Any]:
        """Download the declared archive and workload, verifying both digests."""
        dataset_url, dataset_sha = self._source("data")
        workload_url, workload_sha = self._source("workload")
        dataset = self._download(dataset_url)
        workload = self._download(workload_url)

        raw_dir = self.artifacts_root / "census-raw-v1"
        self._write_source(raw_dir / "source.zip", dataset, dataset_sha, "dataset")
        self._write_source(self.source_cache / "query.sql", workload, workload_sha, "workload")

        timestamp = self._timestamp()
        self._write_json(
            self._artifact_manifest(raw_dir),
            {
                "artifact_id": "census-raw-v1",
                "type": "raw_dataset",
                "parent_artifacts": [],
                "source_url": dataset_url,
                "sha256": dataset_sha,
                "size": len(dataset),
                "timestamp": timestamp,
                "workload_source_url": workload_url,
                "workload_sha256": workload_sha,
            },
        )
        artifact = self._artifact_from_manifest(raw_dir)
        return {
            "status": "PASS",
            "message": "census fetch completed",
            "output_artifacts": (artifact,),
            "metadata": {"workload_cached": str(self.source_cache / "query.sql")},
        }

    def prepare(self) -> dict[str, Any]:
        """Extract every archive member into a confined prepared artifact."""
        raw_dir = self.artifacts_root / "census-raw-v1"
        raw_manifest_path = self._artifact_manifest(raw_dir)
        if not raw_manifest_path.is_file():
            raise FileNotFoundError("Run Census fetch before prepare")
        raw_manifest = json.loads(raw_manifest_path.read_text(encoding="utf-8"))
        archive_path = raw_dir / "source.zip"
        if self._digest(archive_path.read_bytes()) != raw_manifest["sha256"]:
            raise ValueError("Census raw archive checksum mismatch")

        prepared_dir = self.artifacts_root / "census-prepared-v1"
        prepared_dir.mkdir(parents=True, exist_ok=True)
        members: list[dict[str, Any]] = []
        with zipfile.ZipFile(archive_path) as archive:
            bad_member = archive.testzip()
            if bad_member is not None:
                raise ValueError(f"Census archive CRC check failed: {bad_member}")
            for info in archive.infolist():
                member = PurePosixPath(info.filename)
                if member.is_absolute() or ".." in member.parts:
                    raise ValueError(f"Unsafe Census archive member: {info.filename}")
                target = (prepared_dir / Path(*member.parts)).resolve()
                if target != prepared_dir and not target.is_relative_to(prepared_dir.resolve()):
                    raise ValueError(f"Unsafe Census archive member: {info.filename}")
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(archive.read(info))
                members.append(
                    {
                        "name": info.filename,
                        "size": info.file_size,
                        "compressed_size": info.compress_size,
                        "directory": info.is_dir(),
                    }
                )

        data_path, columns, expected_rows = self._data_member(prepared_dir, members)
        schema_source = self.repo_root / "benchmarks" / "census" / "schema" / "schema.sql"
        if not schema_source.is_file():
            raise FileNotFoundError(f"Census schema artifact is missing: {schema_source}")
        (prepared_dir / "schema.sql").write_bytes(schema_source.read_bytes())
        timestamp = self._timestamp()
        self._write_json(
            self._artifact_manifest(prepared_dir),
            {
                "artifact_id": "census-prepared-v1",
                "type": "prepared_dataset",
                "parent_artifacts": ["census-raw-v1"],
                "source_url": raw_manifest["source_url"],
                "sha256": raw_manifest["sha256"],
                "size": raw_manifest["size"],
                "timestamp": timestamp,
                "archive_members": members,
                "schema_artifact_id": "census-schema-v1",
                "schema_path": "schema.sql",
                "data_path": data_path,
                "table": "census",
                "columns": columns,
                "database_columns": [column.lower() for column in columns],
                "expected_rows": expected_rows,
                "format": "csv",
                "delimiter": ",",
                "header": True,
                "encoding": "utf-8",
            },
        )
        artifact = self._artifact_from_manifest(prepared_dir)
        return {
            "status": "PASS",
            "message": "census prepare completed",
            "input_artifacts": (self._artifact_from_manifest(raw_dir),),
            "output_artifacts": (artifact,),
            "metadata": {"archive_members": members},
        }

    def normalize_workload(self) -> dict[str, Any]:
        """Copy the verified source SQL byte-for-byte into a workload artifact."""
        workload_url, workload_sha = self._source("workload")
        source_path = self.source_cache / "query.sql"
        if not source_path.is_file():
            raise FileNotFoundError("Run Census fetch before normalize_workload")
        workload = source_path.read_bytes()
        workload_model = normalize_workload(
            workload,
            workload_id="census-workload-v1",
            source_checksum=workload_sha,
        )
        workload_dir = self.artifacts_root / "census-workload-v1"
        self._write_source(workload_dir / "query.sql", workload, workload_sha, "workload")
        timestamp = self._timestamp()
        self._write_json(
            self._artifact_manifest(workload_dir),
            {
                "artifact_id": "census-workload-v1",
                "type": "workload",
                "parent_artifacts": [],
                "source_url": workload_url,
                "sha256": workload_sha,
                "size": len(workload),
                "timestamp": timestamp,
                "source_checksum": workload_model.metadata["source_checksum"],
                "query_count": workload_model.query_count,
                "source_line_count": workload_model.metadata["source_line_count"],
                "normalization": workload_model.metadata["normalization"],
                "query_id_format": workload_model.metadata["query_id_format"],
            },
        )
        artifact = self._artifact_from_manifest(workload_dir)
        return {
            "status": "PASS",
            "message": "census normalize_workload completed",
            "output_artifacts": (artifact,),
        }

    def collect_truth(self, instance: Any = None, runner: Any = None) -> dict[str, Any]:
        """Execute a normalized workload through an injected DBMS runner."""
        if instance is None:
            return {
                "status": "INCOMPLETE",
                "message": "collect_truth requires a loaded PostgreSQL instance",
            }
        workload_dir = self.artifacts_root / "census-workload-v1"
        workload_artifact = self._artifact_from_manifest(workload_dir)
        workload = load_workload_artifact(workload_dir)
        if runner is None:
            from .postgres.query_runner import PostgreSQLQueryRunner

            runner = PostgreSQLQueryRunner()
        results = runner.execute_workload(workload, instance)
        truth = TruthArtifact(
            benchmark_id="census",
            workload_id=workload.workload_id,
            query_results=results,
            metadata={
                "runner": runner.__class__.__name__,
                "query_count": workload.query_count,
                "successful_queries": sum(result.status == "PASS" for result in results),
            },
        )
        truth_dir = self.artifacts_root / "census-truth-v1"
        truth_dir.mkdir(parents=True, exist_ok=True)
        truth_bytes = truth.to_json().encode("utf-8")
        truth_path = truth_dir / "truth.json"
        truth_path.write_bytes(truth_bytes)
        truth_digest = self._digest(truth_bytes)
        timestamp = self._timestamp()
        self._write_json(
            self._artifact_manifest(truth_dir),
            {
                "artifact_id": "census-truth-v1",
                "type": "truth",
                "parent_artifacts": [workload_artifact.id],
                "source_url": workload_artifact.metadata.get("source_url"),
                "sha256": truth_digest,
                "size": len(truth_bytes),
                "timestamp": timestamp,
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
            "message": "census truth collection completed" if status == "PASS" else "census truth collection had failures",
            "input_artifacts": (workload_artifact,),
            "output_artifacts": (artifact,),
            "truth": truth,
            "workload": workload,
        }

    def load(self) -> dict[str, Any]:
        return {"status": "NOT_IMPLEMENTED", "message": "census load is not implemented"}

    def validate(self) -> dict[str, Any]:
        return {"status": "NOT_IMPLEMENTED", "message": "census validate is not implemented"}



register_adapter("census", CensusAdapter)
