from pathlib import Path
import hashlib
import json
import pytest
from pgextstats_benchmarks.registry import load_registry, load_manifest, verify_benchmark
from pgextstats_benchmarks.cli import main

REPO = Path(__file__).resolve().parents[1]


def _artifact_verify_fixture(tmp_path: Path, *, raw=True, prepared=True, workload=True):
    repo = tmp_path / "repo"
    benchmark = repo / "benchmarks" / "fixture"
    (repo / "registry").mkdir(parents=True)
    (benchmark / "sources").mkdir(parents=True)
    data = b"raw fixture"
    query = b"SELECT 1;\n"
    data_sha = hashlib.sha256(data).hexdigest()
    workload_sha = hashlib.sha256(query).hexdigest()
    (repo / "registry/benchmarks.yaml").write_text(
        "benchmarks:\n  fixture:\n    path: benchmarks/fixture\n    status: ready\n    version: v1\n"
    )
    (benchmark / "benchmark.yaml").write_text(
        "benchmark_id: fixture\nversion: v1\ndescription: Fixture\n"
        "sources:\n  data: {manifest: sources/data.yaml}\n"
        "  workload: {manifest: sources/workload.yaml}\n"
        "pipeline: {}\n"
        "artifacts:\n  raw: raw-v1\n  prepared: prepared-v1\n  workload: workload-v1\n"
        "provenance: {}\n"
    )
    (benchmark / "sources/data.yaml").write_text(
        f"source_url: fixture://data\nsha256: {data_sha}\n"
    )
    (benchmark / "sources/workload.yaml").write_text(
        f"raw_url: fixture://workload\nsha256: {workload_sha}\n"
    )
    root = tmp_path / "external"
    artifacts = root / "fixture" / "artifacts"
    if raw:
        path = artifacts / "raw-v1"
        path.mkdir(parents=True)
        (path / "source.zip").write_bytes(data)
        (path / "manifest.json").write_text(json.dumps({
            "artifact_id": "raw-v1", "type": "raw_dataset", "sha256": data_sha,
        }))
    if prepared:
        path = artifacts / "prepared-v1"
        path.mkdir(parents=True)
        (path / "data.csv").write_text("id\n1\n")
        (path / "manifest.json").write_text(json.dumps({
            "artifact_id": "prepared-v1", "type": "prepared_dataset", "data_path": "data.csv",
        }))
    if workload:
        path = artifacts / "workload-v1"
        path.mkdir(parents=True)
        (path / "query.sql").write_bytes(query)
        (path / "manifest.json").write_text(json.dumps({
            "artifact_id": "workload-v1", "type": "workload", "sha256": workload_sha,
        }))
    return repo, root


def test_registry_and_manifests():
    registry = load_registry(REPO)
    assert set(registry) == {"dmv", "census", "example", "arecel-census13"}
    for name, benchmark in registry.items():
        expected_status = "declared" if name == "arecel-census13" else "planned"
        assert benchmark.status == expected_status
        assert benchmark.version == "v1"
        manifest = load_manifest(benchmark)
        assert manifest["benchmark_id"] == name
        assert manifest["version"] == "v1"
        if name != "arecel-census13":
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
    assert main(["--repo", str(REPO), "verify", "dmv"]) == 1
    output = capsys.readouterr().out
    assert "Manifest: PASS" in output
    assert "Source declaration: PASS" in output
    assert "Raw artifact: CONFIGURATION MISSING" in output
    assert "Prepared artifact: CONFIGURATION MISSING" in output
    assert "Workload artifact: CONFIGURATION MISSING" in output
    assert "Status: CONFIGURATION MISSING" in output
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


def test_artifact_aware_verify_reports_all_artifacts_valid(tmp_path, monkeypatch, capsys):
    repo, root = _artifact_verify_fixture(tmp_path)
    monkeypatch.setenv("PGEXTADV_BENCHMARK_DATA", str(root))
    result = verify_benchmark(repo, "fixture")
    assert result.status == "COMPLETE"
    assert result.source_declaration_status == "PRESENT/VALID"
    assert result.artifact_statuses == {
        "raw": "PRESENT/VALID",
        "prepared": "PRESENT/VALID",
        "workload": "PRESENT/VALID",
    }
    assert main(["--repo", str(repo), "verify", "fixture"]) == 0
    output = capsys.readouterr().out
    assert "Raw artifact: PRESENT/VALID" in output
    assert "Prepared artifact: PRESENT/VALID" in output
    assert "Workload artifact: PRESENT/VALID" in output
    assert "Status: COMPLETE" in output


@pytest.mark.parametrize(
    ("missing", "field"),
    [("raw", "raw"), ("prepared", "prepared"), ("workload", "workload")],
)
def test_artifact_aware_verify_reports_missing_artifact(tmp_path, monkeypatch, missing, field):
    repo, root = _artifact_verify_fixture(tmp_path, **{missing: False})
    monkeypatch.setenv("PGEXTADV_BENCHMARK_DATA", str(root))
    result = verify_benchmark(repo, "fixture")
    assert result.status == "INCOMPLETE"
    assert result.artifact_statuses[field] == "MISSING"


def test_artifact_aware_verify_requires_external_data_root(tmp_path, monkeypatch):
    repo, _ = _artifact_verify_fixture(tmp_path)
    monkeypatch.delenv("PGEXTADV_BENCHMARK_DATA", raising=False)
    result = verify_benchmark(repo, "fixture")
    assert result.configuration_missing is True
    assert result.source_declaration_status == "PRESENT/VALID"
    assert result.raw_artifact_status == "CONFIGURATION MISSING"
    assert result.status == "CONFIGURATION MISSING"


def test_source_declaration_is_validated_independently(tmp_path, monkeypatch):
    repo, root = _artifact_verify_fixture(tmp_path)
    (repo / "benchmarks/fixture/sources/data.yaml").write_text(
        "source_url: fixture://data\nsha256: invalid\n"
    )
    monkeypatch.setenv("PGEXTADV_BENCHMARK_DATA", str(root))
    result = verify_benchmark(repo, "fixture")
    assert result.source_declaration_status == "PRESENT/INVALID"
    assert result.artifact_statuses["raw"] == "PRESENT/INVALID"
    assert result.status == "INCOMPLETE"
