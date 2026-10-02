from __future__ import annotations

from io import BytesIO
import hashlib
import json
from pathlib import Path
import zipfile

import pytest

from pgextstats_benchmarks.artifacts import Artifact
from pgextstats_benchmarks.census_adapter import CensusAdapter
from pgextstats_benchmarks.census_validator import CensusValidator
from pgextstats_benchmarks.instances import LoadedInstance
from pgextstats_benchmarks.registry import load_manifest, load_registry
from pgextstats_benchmarks.validator_registry import get_validator, list_validators
from pgextstats_benchmarks.adapters import get_adapter, list_adapters
from pgextstats_benchmarks.executor import run_stage
from pgextstats_benchmarks.cli import main


REPO = Path(__file__).resolve().parents[1]


def fixture_sources() -> tuple[bytes, bytes, dict[str, dict[str, str]]]:
    stream = BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("README.txt", "fixture\n")
        archive.writestr("nested/data.csv", "1,hello\n2,world\n")
    dataset = stream.getvalue()
    workload = b"select 1;\nselect 2;\n"
    digest = lambda data: hashlib.sha256(data).hexdigest()
    sources = {
        "data": {"source_url": "fixture://census.zip", "sha256": digest(dataset)},
        "workload": {"raw_url": "fixture://query.sql", "sha256": digest(workload)},
    }
    return dataset, workload, sources


def make_adapter(tmp_path: Path) -> tuple[CensusAdapter, bytes, bytes]:
    dataset, workload, sources = fixture_sources()

    def download(url: str) -> bytes:
        return dataset if url.endswith("census.zip") else workload

    adapter = CensusAdapter(
        repo_root=REPO,
        data_root=tmp_path / "external",
        downloader=download,
        source_declarations=sources,
    )
    return adapter, dataset, workload


def test_census_manifest_and_registration():
    definition = load_registry(REPO)["census"]
    manifest = load_manifest(definition)
    assert manifest["benchmark_id"] == "census"
    assert manifest["version"] == "v1"
    assert manifest["sources"]["data"]["manifest"] == "sources/data.yaml"
    assert get_adapter("census") is CensusAdapter
    assert "census" in list_adapters()
    assert get_validator("census-validator") is CensusValidator
    assert "census-validator" in list_validators()


def test_cli_benchmarks_lists_census(capsys):
    assert main(["benchmarks"]) == 0
    assert "census" in capsys.readouterr().out


def test_fetch_prepare_and_normalize_create_external_artifacts(tmp_path):
    adapter, dataset, workload = make_adapter(tmp_path)
    fetched = adapter.fetch()
    raw = fetched["output_artifacts"][0]
    assert fetched["status"] == "PASS"
    assert raw.id == "census-raw-v1"
    assert raw.path is not None
    assert (raw.path / "source.zip").read_bytes() == dataset
    assert raw.path.parent.parent == (tmp_path / "external" / "census").resolve()

    prepared = adapter.prepare()["output_artifacts"][0]
    assert prepared.id == "census-prepared-v1"
    assert (prepared.path / "README.txt").read_text() == "fixture\n"
    assert (prepared.path / "nested/data.csv").read_text() == "1,hello\n2,world\n"
    prepared_manifest = json.loads((prepared.path / "manifest.json").read_text())
    assert [member["name"] for member in prepared_manifest["archive_members"]] == [
        "README.txt",
        "nested/data.csv",
    ]

    workload_artifact = adapter.normalize_workload()["output_artifacts"][0]
    assert workload_artifact.id == "census-workload-v1"
    assert (workload_artifact.path / "query.sql").read_bytes() == workload
    assert json.loads((workload_artifact.path / "manifest.json").read_text())["size"] == len(workload)


def test_fetch_rejects_checksum_mismatch(tmp_path):
    adapter, _, _ = make_adapter(tmp_path)
    adapter._downloader = lambda url: b"wrong"
    with pytest.raises(ValueError, match="checksum mismatch"):
        adapter.fetch()


def test_census_validator_checks_artifacts(tmp_path):
    adapter, _, _ = make_adapter(tmp_path)
    raw = adapter.fetch()["output_artifacts"][0]
    prepared = adapter.prepare()["output_artifacts"][0]
    workload = adapter.normalize_workload()["output_artifacts"][0]
    report = CensusValidator(source_declarations=adapter._provided_sources).validate_artifacts(
        raw_artifact=raw,
        prepared_artifact=prepared,
        workload_artifact=workload,
    )
    assert report.status == "PASS"
    assert {check.name for check in report.checks} == {
        "raw_artifact_checksum",
        "prepared_artifact_extraction",
        "workload_artifact_checksum",
    }

    instance = LoadedInstance(
        instance_id="census-artifacts-v1",
        benchmark_id="census",
        loader_type="artifact-only",
        status="READY",
        metadata={
            "raw_artifact": raw.to_dict(),
            "prepared_artifact": prepared.to_dict(),
            "workload_artifact": workload.to_dict(),
        },
    )
    assert CensusValidator(source_declarations=adapter._provided_sources).validate_instance(instance).status == "PASS"


def test_cli_census_run_with_recorded_fixture(tmp_path, monkeypatch, capsys):
    adapter, dataset, workload = make_adapter(tmp_path)
    monkeypatch.setenv("PGEXTADV_BENCHMARK_DATA", str(tmp_path / "external"))
    monkeypatch.setattr(CensusAdapter, "_source_declarations", lambda self: adapter._provided_sources)
    monkeypatch.setattr(CensusAdapter, "_download", lambda self, url: dataset if url.endswith("census.zip") else workload)
    assert main(["run", "census", "--stage", "fetch"]) == 0
    output = capsys.readouterr().out
    assert "Benchmark: census" in output
    assert "Adapter: CensusAdapter" in output
    assert "Status: PASS" in output
