"""Extensible YAML definitions; no benchmark-specific assumptions."""
from dataclasses import dataclass
from pathlib import Path
import yaml
from .paths import confined_path


@dataclass(frozen=True)
class Benchmark:
    id: str
    path: Path
    status: str


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
        result[name] = Benchmark(name, confined_path(repo, entry.get("path")), status)
    return result


def load_manifest(benchmark: Benchmark) -> dict:
    value = read_mapping(benchmark.path / "benchmark.yaml")
    if value.get("id") != benchmark.id:
        raise ValueError("Manifest ID does not match registry")
    if not isinstance(value.get("version"), str):
        raise ValueError("Manifest version must be a string")
    sources = value.get("sources")
    if not isinstance(sources, dict):
        raise ValueError("Manifest sources must be a mapping")
    for source in sources.values():
        if not isinstance(source, dict):
            raise ValueError("Invalid source manifest entry")
        confined_path(benchmark.path, source.get("manifest"))
    if not isinstance(value.get("pipeline"), dict):
        raise ValueError("Manifest pipeline must be a mapping")
    return value
