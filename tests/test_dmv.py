from __future__ import annotations

from pathlib import Path
import hashlib
import io
import json
import tarfile

import pytest

from pgextstats_benchmarks.cli import main
from pgextstats_benchmarks.dmv_adapter import DMVAdapter, DMV_COLUMNS
from pgextstats_benchmarks.dmv_validator import DMVTruthValidator, DMVValidator
from pgextstats_benchmarks.query_runner import QueryExecutionResult
from pgextstats_benchmarks.truth import TruthArtifact
from pgextstats_benchmarks.workload_executor import load_workload_artifact

REPO = Path(__file__).resolve().parents[1]


def _archive_bytes() -> bytes:
    csv = (
        "Record_Type,Registration_Class,State,County,Body_Type,Fuel_Type,Reg_Valid_Date,Color,"
        "Scofflaw_Indicator,Suspension_Indicator,Revocation_Indicator\n"
        "VEH ,PAS,NY,NEW YORK   ,SUBN,GAS     ,20170626,WH   ,N,N,N\n"
        "VEH ,COM,NJ,HUDSON      ,TRLR,DIESEL,20180723,GY   ,N,N,N\n"
    ).encode()
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:gz") as archive:
        info = tarfile.TarInfo("data/dmv11/original.csv")
        info.size = len(csv)
        archive.addfile(info, io.BytesIO(csv))
        note = b"fixture\n"
        info = tarfile.TarInfo("README.txt")
        info.size = len(note)
        archive.addfile(info, io.BytesIO(note))
    return stream.getvalue()


def _fixture(tmp_path: Path) -> tuple[DMVAdapter, dict[str, dict[str, str]], bytes, bytes]:
    root = tmp_path / "external"
    archive = _archive_bytes()
    workload = b"SELECT COUNT(*) FROM DMV WHERE State IN [NY, NJ] AND Scofflaw_Indicator == N||2\n"
    incoming = root / "dmv" / "incoming"
    incoming.mkdir(parents=True)
    (incoming / "data.tar.gz").write_bytes(archive)
    sources = {
        "data": {"source_url": "fixture://dmv", "sha256": hashlib.sha256(archive).hexdigest()},
        "workload": {"source_url": "fixture://dmv-query", "sha256": hashlib.sha256(workload).hexdigest()},
    }
    adapter = DMVAdapter(
        repo_root=REPO,
        data_root=root,
        downloader=lambda _url: workload,
        source_declarations=sources,
    )
    return adapter, sources, archive, workload


def test_dmv_manifest_and_registration():
    from pgextstats_benchmarks.adapters import get_adapter
    from pgextstats_benchmarks.registry import load_manifest, load_registry
    from pgextstats_benchmarks.validator_registry import get_validator

    definition = load_registry(REPO)["dmv"]
    manifest = load_manifest(definition)
    assert manifest["artifacts"]["raw"] == "dmv-raw-v1"
    assert manifest["artifacts"]["prepared"] == "dmv-prepared-v1"
    assert get_adapter("dmv") is DMVAdapter
    assert get_validator("dmv-validator") is DMVValidator


def test_missing_manual_archive_is_explicit(tmp_path):
    adapter = DMVAdapter(repo_root=REPO, data_root=tmp_path / "external", source_declarations={
        "data": {"source_url": "fixture://dmv", "sha256": "0" * 64},
        "workload": {"source_url": "fixture://query", "sha256": "1" * 64},
    })
    with pytest.raises(FileNotFoundError, match="manual acquisition required"):
        adapter.fetch()


def test_dmv_fetch_prepare_and_normalize_are_deterministic(tmp_path):
    adapter, sources, archive, _workload = _fixture(tmp_path)
    raw_result = adapter.fetch()
    prepared_result = adapter.prepare()
    workload_result = adapter.normalize_workload()
    raw = raw_result["output_artifacts"][0]
    prepared = prepared_result["output_artifacts"][0]
    workload = workload_result["output_artifacts"][0]
    assert raw.metadata["sha256"] == sources["data"]["sha256"]
    assert prepared.metadata["expected_rows"] == 2
    assert prepared.metadata["columns"] == list(DMV_COLUMNS)
    assert (prepared.path / "README.txt").read_text() == "fixture\n"
    assert (prepared.path / "dmv.csv").read_text().splitlines()[1].startswith("VEH,PAS,NY,NEW YORK,SUBN,GAS")
    assert workload.metadata["query_count"] == 1
    assert workload.metadata["source_checksum"] == sources["workload"]["sha256"]
    assert "IN ('NY', 'NJ')" in (workload.path / "query.sql").read_text()
    assert "= 'N'" in (workload.path / "query.sql").read_text()
    assert "source_query.sql" in workload.metadata["source_payload_path"]
    second = adapter.prepare()["output_artifacts"][0]
    assert second.metadata["sha256"] == prepared.metadata["sha256"]
    assert raw.path.joinpath("data.tar.gz").read_bytes() == archive


def test_dmv_validator_and_truth_contract(tmp_path):
    adapter, sources, _archive, _workload = _fixture(tmp_path)
    raw = adapter.fetch()["output_artifacts"][0]
    prepared = adapter.prepare()["output_artifacts"][0]
    workload_artifact = adapter.normalize_workload()["output_artifacts"][0]
    report = DMVValidator(source_declarations=sources).validate_artifacts(
        raw_artifact=raw, prepared_artifact=prepared, workload_artifact=workload_artifact,
    )
    assert report.status == "PASS"
    workload = load_workload_artifact(workload_artifact.path)
    truth = TruthArtifact(
        benchmark_id="dmv", workload_id=workload.workload_id,
        query_results=(QueryExecutionResult("q0001", "PASS", {"cardinality": 2}),),
    )
    assert DMVTruthValidator().validate_truth(workload, truth).status == "PASS"


def test_dmv_cli_run_prepare_with_fixture(tmp_path, monkeypatch, capsys):
    adapter, _sources, _archive, _workload = _fixture(tmp_path)
    adapter.fetch()
    monkeypatch.setenv("PGEXTADV_BENCHMARK_DATA", str(tmp_path / "external"))
    monkeypatch.setattr("pgextstats_benchmarks.dmv_adapter.DMVAdapter", lambda: adapter)
    # The explicit registry holds the class, so patch its methods instead of
    # replacing the registered type.
    assert main(["run", "dmv", "--stage", "prepare"]) == 0
    output = capsys.readouterr().out
    assert "Benchmark: dmv" in output
    assert "Status: PASS" in output
