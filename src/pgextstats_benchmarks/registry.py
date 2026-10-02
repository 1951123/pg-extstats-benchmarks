"""Extensible YAML definitions and generic artifact-aware verification."""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping
import yaml
from .paths import benchmark_data_root, confined_path


_ARTIFACT_KEYS = ("raw", "prepared", "workload")
_ARTIFACT_TYPES = {
    "raw": "raw_dataset",
    "prepared": "prepared_dataset",
    "workload": "workload",
}
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")


@dataclass(frozen=True)
class Benchmark:
    id: str
    path: Path
    status: str
    version: str


@dataclass(frozen=True)
class VerifyResult:
    """Read-only completeness report for one registered benchmark."""

    benchmark: Benchmark
    directory_exists: bool
    manifest_exists: bool
    source_manifest_exists: bool
    raw_data_present: bool
    configuration_missing: bool
    source_declaration_valid: bool = False
    source_declaration_status: str = "PRESENT/INVALID"
    raw_artifact_status: str = "NOT DECLARED"
    prepared_artifact_status: str = "NOT DECLARED"
    workload_artifact_status: str = "NOT DECLARED"

    @property
    def artifact_statuses(self) -> dict[str, str]:
        return {
            "raw": self.raw_artifact_status,
            "prepared": self.prepared_artifact_status,
            "workload": self.workload_artifact_status,
        }

    @property
    def artifact_declarations_present(self) -> bool:
        return any(status != "NOT DECLARED" for status in self.artifact_statuses.values())

    @property
    def all_declared_artifacts_valid(self) -> bool:
        declared = [status for status in self.artifact_statuses.values() if status != "NOT DECLARED"]
        return bool(declared) and all(status == "PRESENT/VALID" for status in declared)

    @property
    def status(self) -> str:
        if self.configuration_missing:
            return "CONFIGURATION MISSING"
        if self.artifact_declarations_present:
            if not self.source_declaration_valid or not self.all_declared_artifacts_valid:
                return "INCOMPLETE"
            return "COMPLETE"
        if not self.raw_data_present:
            return "INCOMPLETE"
        return "COMPLETE"


def read_mapping(path: Path) -> dict:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected YAML mapping: {path}")
    return value


def load_registry(repo: Path) -> dict[str, Benchmark]:
    value = read_mapping(repo / "registry" / "benchmarks.yaml").get("benchmarks")
    if not isinstance(value, dict):
        raise ValueError("Registry must contain a benchmarks mapping")
    result = {}
    for name, entry in value.items():
        if not isinstance(name, str) or not name or not isinstance(entry, dict):
            raise ValueError("Invalid benchmark registry entry")
        status = entry.get("status")
        if not isinstance(status, str) or not status:
            raise ValueError(f"Missing benchmark status: {name}")
        version = entry.get("version")
        if not isinstance(version, str) or not version:
            raise ValueError(f"Missing benchmark version: {name}")
        result[name] = Benchmark(
            name, confined_path(repo, entry.get("path")), status, version
        )
    return result


def load_manifest(benchmark: Benchmark) -> dict:
    value = read_mapping(benchmark.path / "benchmark.yaml")
    if value.get("benchmark_id") != benchmark.id:
        raise ValueError("Manifest benchmark_id does not match registry")
    if not isinstance(value.get("version"), str) or not value["version"]:
        raise ValueError("Manifest version must be a nonempty string")
    if value["version"] != benchmark.version:
        raise ValueError("Manifest version does not match registry")
    if not isinstance(value.get("description"), str) or not value["description"].strip():
        raise ValueError("Manifest description must be a nonempty string")
    sources = value.get("sources")
    if not isinstance(sources, dict):
        raise ValueError("Manifest sources must be a mapping")
    for source in sources.values():
        if not isinstance(source, dict):
            raise ValueError("Invalid source manifest entry")
        confined_path(benchmark.path, source.get("manifest"))
    if not isinstance(value.get("pipeline"), dict):
        raise ValueError("Manifest pipeline must be a mapping")
    for field in ("artifacts", "provenance"):
        if not isinstance(value.get(field), dict):
            raise ValueError(f"Manifest {field} must be a mapping")
    return value


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_declaration_status(
    source_paths: Mapping[str, Path],
) -> tuple[bool, str, dict[str, dict[str, Any]]]:
    """Validate source declarations independently of materialized artifacts."""
    declarations: dict[str, dict[str, Any]] = {}
    complete = True
    structurally_valid = True
    for name, path in source_paths.items():
        try:
            value = read_mapping(path)
        except (OSError, TypeError, ValueError, yaml.YAMLError):
            structurally_valid = False
            continue
        declarations[name] = value
        url = value.get("source_url") or value.get("raw_url") or value.get("url")
        sha256 = value.get("sha256")
        # Placeholder benchmarks may deliberately declare a source without
        # bytes yet.  Preserve that as declared configuration rather than
        # treating it as an invalid source declaration.
        if url is None and sha256 is None:
            continue
        if not isinstance(url, str) or not url.strip() or not isinstance(sha256, str) or not _SHA256.fullmatch(sha256):
            structurally_valid = False
        else:
            complete = complete and True
    if not structurally_valid:
        return False, "PRESENT/INVALID", declarations
    if not complete or any(
        not ((value.get("source_url") or value.get("raw_url") or value.get("url")) and value.get("sha256"))
        for value in declarations.values()
    ):
        return True, "PRESENT/DECLARED", declarations
    return True, "PRESENT/VALID", declarations


def _artifact_manifest(artifact_dir: Path) -> tuple[Path, dict[str, Any]] | None:
    for name in ("manifest.json", "manifest.yaml", "manifest.yml"):
        path = artifact_dir / name
        if not path.is_file():
            continue
        try:
            return path, read_mapping(path)
        except (OSError, TypeError, ValueError, yaml.YAMLError, json.JSONDecodeError):
            return path, {}
    return None


def _artifact_location(benchmark: Benchmark, reference: str, data_root: Path | None) -> tuple[Path, Path] | None:
    """Resolve repository-local declarations or external artifact IDs safely."""
    if not isinstance(reference, str) or not reference.strip():
        return None
    # Existing toy benchmarks can point at a repository-local manifest.
    if reference.startswith("artifacts/"):
        manifest_path = confined_path(benchmark.path, reference)
        return manifest_path.parent, manifest_path
    if data_root is None:
        return None
    artifact_dir = confined_path(data_root, f"{benchmark.id}/artifacts/{reference}")
    return artifact_dir, artifact_dir / "manifest.json"


def _verify_artifact(
    benchmark: Benchmark,
    key: str,
    reference: Any,
    declarations: Mapping[str, Mapping[str, Any]],
    data_root: Path | None,
) -> str:
    if reference is None:
        return "NOT DECLARED"
    if not isinstance(reference, str) or not reference.strip():
        return "PRESENT/INVALID"
    try:
        location = _artifact_location(benchmark, reference, data_root)
    except (ValueError, OSError):
        return "PRESENT/INVALID"
    if location is None:
        return "CONFIGURATION MISSING"
    artifact_dir, manifest_path = location
    if not artifact_dir.is_dir() or not manifest_path.is_file():
        return "MISSING"
    loaded = _artifact_manifest(artifact_dir)
    if loaded is None:
        return "PRESENT/INVALID"
    _, manifest = loaded
    artifact_id = manifest.get("artifact_id")
    if not isinstance(artifact_id, str) or not artifact_id.strip():
        return "PRESENT/INVALID"
    if not reference.startswith("artifacts/") and artifact_id != reference:
        return "PRESENT/INVALID"
    expected_type = _ARTIFACT_TYPES[key]
    if manifest.get("type") != expected_type:
        return "PRESENT/INVALID"

    if key == "raw":
        payload = artifact_dir / "source.zip"
        source = declarations.get("data", {})
        expected = source.get("sha256")
        if not payload.is_file() or not isinstance(expected, str):
            return "PRESENT/INVALID"
        actual = _digest(payload)
        return "PRESENT/VALID" if actual == expected == manifest.get("sha256") else "PRESENT/INVALID"

    if key == "workload":
        payload = artifact_dir / "query.sql"
        source = declarations.get("workload", {})
        expected = source.get("sha256")
        if not payload.is_file() or not isinstance(expected, str):
            return "PRESENT/INVALID"
        actual = _digest(payload)
        return "PRESENT/VALID" if actual == expected == manifest.get("sha256") else "PRESENT/INVALID"

    # Prepared artifacts are validated from their manifest and confined member
    # paths.  Their large data payload is not re-hashed by the registry check.
    members = manifest.get("archive_members")
    if isinstance(members, list):
        for member in members:
            if not isinstance(member, Mapping) or not isinstance(member.get("name"), str):
                return "PRESENT/INVALID"
            try:
                member_path = confined_path(artifact_dir, member["name"])
            except ValueError:
                return "PRESENT/INVALID"
            if not member_path.exists():
                return "PRESENT/INVALID"
    data_path = manifest.get("data_path")
    if not isinstance(data_path, str):
        return "PRESENT/INVALID"
    try:
        if not confined_path(artifact_dir, data_path).is_file():
            return "PRESENT/INVALID"
    except ValueError:
        return "PRESENT/INVALID"
    return "PRESENT/VALID"


def verify_benchmark(repo: Path, benchmark_id: str) -> VerifyResult:
    """Verify declarations and materialized artifacts without side effects."""
    registry = load_registry(repo)
    if benchmark_id not in registry:
        raise ValueError(f"Unknown benchmark: {benchmark_id}")
    benchmark = registry[benchmark_id]
    directory_exists = benchmark.path.is_dir()
    manifest_path = benchmark.path / "benchmark.yaml"
    manifest_exists = manifest_path.is_file()
    if not directory_exists or not manifest_exists:
        return VerifyResult(benchmark, directory_exists, manifest_exists, False, False, True)

    try:
        manifest = load_manifest(benchmark)
        source_entries = manifest["sources"]
        source_paths = {
            name: confined_path(benchmark.path, entry["manifest"])
            for name, entry in source_entries.items()
        }
    except (KeyError, TypeError, ValueError, OSError, yaml.YAMLError):
        return VerifyResult(benchmark, True, True, False, False, True)

    source_manifest_exists = all(path.is_file() for path in source_paths.values())
    if not source_manifest_exists:
        return VerifyResult(benchmark, True, True, False, False, True)

    try:
        source_valid, source_status, declarations = _source_declaration_status(source_paths)
        artifact_refs = manifest.get("artifacts", {})
        if not isinstance(artifact_refs, Mapping):
            return VerifyResult(benchmark, True, True, True, False, True)

        needs_external_root = any(
            isinstance(artifact_refs.get(key), str)
            and bool(artifact_refs.get(key))
            and not str(artifact_refs[key]).startswith("artifacts/")
            for key in _ARTIFACT_KEYS
        )
        if needs_external_root:
            try:
                data_root = benchmark_data_root()
            except ValueError:
                statuses = {
                    key: (
                        "CONFIGURATION MISSING"
                        if isinstance(artifact_refs.get(key), str)
                        and bool(artifact_refs.get(key))
                        else "NOT DECLARED"
                    )
                    for key in _ARTIFACT_KEYS
                }
                return VerifyResult(
                    benchmark, True, True, True, False, True,
                    source_valid, source_status,
                    statuses["raw"], statuses["prepared"], statuses["workload"],
                )
        else:
            data_root = None
        statuses = {
            key: _verify_artifact(
                benchmark, key, artifact_refs.get(key), declarations, data_root
            )
            for key in _ARTIFACT_KEYS
        }
        if any(value == "CONFIGURATION MISSING" for value in statuses.values()):
            return VerifyResult(
                benchmark, True, True, True, False, True,
                source_valid, source_status,
                statuses["raw"], statuses["prepared"], statuses["workload"],
            )
        raw_present = statuses["raw"] == "PRESENT/VALID"
        return VerifyResult(
            benchmark, True, True, True, raw_present, False,
            source_valid, source_status,
            statuses["raw"], statuses["prepared"], statuses["workload"],
        )
    except (KeyError, TypeError, ValueError, OSError, yaml.YAMLError):
        return VerifyResult(benchmark, True, True, True, False, True)
