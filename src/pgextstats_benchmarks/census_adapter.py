"""Fetch and prepare the Census benchmark without DBMS or query execution."""
from __future__ import annotations

from datetime import datetime, timezone
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
            },
        )
        artifact = self._artifact_from_manifest(workload_dir)
        return {
            "status": "PASS",
            "message": "census normalize_workload completed",
            "output_artifacts": (artifact,),
        }

    def load(self) -> dict[str, Any]:
        return {"status": "NOT_IMPLEMENTED", "message": "census load is not implemented"}

    def validate(self) -> dict[str, Any]:
        return {"status": "NOT_IMPLEMENTED", "message": "census validate is not implemented"}

    def collect_truth(self) -> dict[str, Any]:
        return {"status": "NOT_IMPLEMENTED", "message": "census collect_truth is not implemented"}


register_adapter("census", CensusAdapter)
