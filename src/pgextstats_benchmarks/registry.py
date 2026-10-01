"""Extensible YAML definitions; no benchmark-specific assumptions."""
from dataclasses import dataclass
from pathlib import Path
import yaml
from .paths import benchmark_data_root, confined_path


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

    @property
    def status(self) -> str:
        if self.configuration_missing:
            return "CONFIGURATION MISSING"
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


def verify_benchmark(repo: Path, benchmark_id: str) -> VerifyResult:
    """Inspect definitions and declared raw data without creating or loading anything."""
    registry = load_registry(repo)
    if benchmark_id not in registry:
        raise ValueError(f"Unknown benchmark: {benchmark_id}")
    benchmark = registry[benchmark_id]
    directory_exists = benchmark.path.is_dir()
    manifest_path = benchmark.path / "benchmark.yaml"
    manifest_exists = manifest_path.is_file()
    if not directory_exists or not manifest_exists:
        return VerifyResult(
            benchmark, directory_exists, manifest_exists, False, False, True
        )

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

    raw_data_present = False
    try:
        data_source = read_mapping(source_paths["data"])
        raw_artifact = data_source.get("raw_artifact")
        if raw_artifact is not None:
            raw_data_present = confined_path(
                benchmark_data_root(), raw_artifact
            ).is_file()
    except (KeyError, TypeError, ValueError, OSError, yaml.YAMLError):
        return VerifyResult(benchmark, True, True, True, False, True)
    return VerifyResult(benchmark, True, True, True, raw_data_present, False)
