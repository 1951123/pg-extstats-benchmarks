from pathlib import Path
import pytest
from pgextstats_benchmarks.registry import load_registry, load_manifest
from pgextstats_benchmarks.cli import main

REPO = Path(__file__).resolve().parents[1]


def test_registry_and_manifests():
    registry = load_registry(REPO)
    assert set(registry) == {"dmv", "census"}
    for name, benchmark in registry.items():
        assert benchmark.status == "placeholder"
        manifest = load_manifest(benchmark)
        assert manifest["id"] == name
        assert manifest["pipeline"]["load"] is None


def test_extension_and_manifest_parsing(tmp_path):
    (tmp_path / "registry").mkdir()
    (tmp_path / "extra").mkdir()
    (tmp_path / "registry/benchmarks.yaml").write_text(
        "benchmarks: {extra: {path: extra, status: placeholder}}")
    (tmp_path / "extra/benchmark.yaml").write_text(
        "id: extra\nversion: placeholder\nsources: {}\npipeline: {}\n")
    registry = load_registry(tmp_path)
    assert load_manifest(registry["extra"])["id"] == "extra"
    (tmp_path / "extra/benchmark.yaml").write_text("[]")
    with pytest.raises(ValueError, match="mapping"):
        load_manifest(registry["extra"])


def test_cli(capsys, monkeypatch, tmp_path):
    assert main(["--repo", str(REPO), "list"]) == 0
    assert "dmv" in capsys.readouterr().out
    assert main(["--repo", str(REPO), "verify", "dmv"]) == 0
    assert "existence check only" in capsys.readouterr().out
    assert main(["--repo", str(REPO), "verify", "unknown"]) == 1
    monkeypatch.delenv("PGEXTADV_BENCHMARK_DATA", raising=False)
    assert main(["status"]) == 1
    monkeypatch.setenv("PGEXTADV_BENCHMARK_DATA", str(tmp_path))
    assert main(["status"]) == 0


def test_missing_manifest(tmp_path):
    (tmp_path / "registry").mkdir()
    (tmp_path / "registry/benchmarks.yaml").write_text(
        "benchmarks: {extra: {path: extra, status: placeholder}}")
    assert main(["--repo", str(tmp_path), "verify", "extra"]) == 1
