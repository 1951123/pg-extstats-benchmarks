from pathlib import Path
import pytest
from pgextstats_benchmarks.registry import load_registry, load_manifest
from pgextstats_benchmarks.cli import main

REPO = Path(__file__).resolve().parents[1]


def test_registry_and_manifests():
    registry = load_registry(REPO)
    assert set(registry) == {"dmv", "census", "example"}
    for name, benchmark in registry.items():
        assert benchmark.status == "planned"
        assert benchmark.version == "v1"
        manifest = load_manifest(benchmark)
        assert manifest["benchmark_id"] == name
        assert manifest["version"] == "v1"
        assert manifest["pipeline"]["load"] is None


def test_extension_and_manifest_parsing(tmp_path):
    (tmp_path / "registry").mkdir()
    (tmp_path / "extra").mkdir()
    (tmp_path / "registry/benchmarks.yaml").write_text(
        "benchmarks: {extra: {path: extra, status: planned, version: v1}}")
    (tmp_path / "extra/benchmark.yaml").write_text(
        "benchmark_id: extra\nversion: v1\ndescription: Extra\n"
        "sources: {}\npipeline: {}\nartifacts: {}\nprovenance: {}\n")
    registry = load_registry(tmp_path)
    assert load_manifest(registry["extra"])["benchmark_id"] == "extra"
    (tmp_path / "extra/benchmark.yaml").write_text("[]")
    with pytest.raises(ValueError, match="mapping"):
        load_manifest(registry["extra"])


def test_cli(capsys, monkeypatch, tmp_path):
    assert main(["--repo", str(REPO), "list"]) == 0
    assert "dmv\tv1\tplanned" in capsys.readouterr().out
    assert main(["--repo", str(REPO), "verify", "dmv"]) == 0
    output = capsys.readouterr().out
    assert "Manifest: PASS" in output
    assert "Source declaration: PASS" in output
    assert "Raw data: NOT PRESENT" in output
    assert "Status: INCOMPLETE" in output
    assert main(["--repo", str(REPO), "verify", "unknown"]) == 1
    monkeypatch.delenv("PGEXTADV_BENCHMARK_DATA", raising=False)
    assert main(["status"]) == 1
    monkeypatch.setenv("PGEXTADV_BENCHMARK_DATA", str(tmp_path))
    assert main(["status"]) == 0


def test_missing_manifest(tmp_path):
    (tmp_path / "registry").mkdir()
    (tmp_path / "registry/benchmarks.yaml").write_text(
        "benchmarks: {extra: {path: extra, status: planned, version: v1}}")
    assert main(["--repo", str(tmp_path), "verify", "extra"]) == 1


def test_missing_registry_version_is_configuration_error(tmp_path):
    (tmp_path / "registry").mkdir()
    (tmp_path / "registry/benchmarks.yaml").write_text(
        "benchmarks: {extra: {path: extra, status: planned}}")
    with pytest.raises(ValueError, match="version"):
        load_registry(tmp_path)


def test_missing_source_declaration_is_configuration_error(tmp_path, capsys):
    (tmp_path / "registry").mkdir()
    (tmp_path / "extra").mkdir()
    (tmp_path / "registry/benchmarks.yaml").write_text(
        "benchmarks: {extra: {path: extra, status: planned, version: v1}}")
    (tmp_path / "extra/benchmark.yaml").write_text(
        "benchmark_id: extra\nversion: v1\ndescription: Extra\n"
        "sources: {data: {manifest: sources/data.yaml}, workload: "
        "{manifest: sources/workload.yaml}}\npipeline: {}\nartifacts: {}\n"
        "provenance: {}\n")
    assert main(["--repo", str(tmp_path), "verify", "extra"]) == 1
    assert "Status: CONFIGURATION MISSING" in capsys.readouterr().out
