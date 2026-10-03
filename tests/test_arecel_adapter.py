from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path

from pgextstats_benchmarks.arecel_adapter import AreCELearnedYetAdapter, DATASET_SPECS
from pgextstats_benchmarks.adapters import get_adapter


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(tmp_path: Path) -> AreCELearnedYetAdapter:
    raw_root = tmp_path / "raw" / "data"
    audit_root = tmp_path / "audit"
    source = raw_root / "census13" / "workload"
    source.mkdir(parents=True)
    columns = list(DATASET_SPECS["census13"]["columns"])
    csv_path = source.parent / "original.csv"
    csv_path.write_text(
        ",".join(columns) + "\n" + ",".join(["1", "Private", "Bachelors", "13", "Never-married", "Tech", "Not-in-family", "White", "Male", "0", "0", "40", "United-States"]) + "\n",
        encoding="utf-8",
    )
    for name in ("base.pkl", "base-original-label.pkl"):
        (source / name).write_bytes(name.encode())
    canonical = audit_root / "census13.canonical.jsonl.gz"
    canonical.parent.mkdir(parents=True)
    records = []
    for split, index in (("valid", 0), ("test", 1)):
        records.append({
            "dataset": "census13", "split": split, "index": index,
            "query_id": f"arecel:census13:{split}:{index:06d}",
            "sql": 'SELECT COUNT(*) FROM public."census13" WHERE "age" >= 1;',
            "source_query": {"dataset": "census13", "predicates": [{"column": "age", "operator": ">=", "value": 1}]},
            "source_label": {"cardinality": 1, "selectivity": 1 / 1},
        })
    with gzip.open(canonical, "wt", encoding="utf-8") as stream:
        for record in records:
            stream.write(json.dumps(record) + "\n")
    audit = {
        "archive": {"sha256": "5cd33cba7f3d7182ef497e60e7346fb2a7546941590a90a4444913a944958f79"},
        "upstream": {"AreCELearnedYet": {"commit": "aa52da7768023270bad884232972e0b77ec6534a"}},
        "datasets": {"census13": {
            "csv": {"sha256": _sha(csv_path), "rows": 1},
            "pickles": {name: {"sha256": _sha(source / name)} for name in ("base.pkl", "base-original-label.pkl")},
        }},
    }
    audit_root.mkdir(exist_ok=True)
    (audit_root / "audit.json").write_text(json.dumps(audit), encoding="utf-8")
    return AreCELearnedYetAdapter(data_root=tmp_path / "external", raw_root=raw_root, audit_root=audit_root)


def test_arecel_adapter_is_registered_and_promotes_split_artifacts(tmp_path):
    assert get_adapter("arecel-census13") is AreCELearnedYetAdapter
    adapter = _fixture(tmp_path)
    raw = adapter.fetch()["output_artifacts"][0]
    prepared = adapter.prepare()["output_artifacts"][0]
    workload = adapter.normalize_workload()["output_artifacts"][0]
    assert raw.metadata["archive_sha256"].startswith("5cd33cba")
    assert prepared.metadata["relation_identity"] == "public.census13"
    assert '"workclass" text' in (prepared.path / "schema.sql").read_text()
    manifest = json.loads((workload.path / "manifest.json").read_text())
    assert set(manifest["split_identity"]) == {"valid", "test"}
    assert all(item["query_count"] == 1 for item in manifest["split_artifacts"].values())


def test_arecel_adapter_preserves_stable_sql_and_source_fields(tmp_path):
    adapter = _fixture(tmp_path)
    adapter.fetch(); adapter.prepare(); artifact = adapter.normalize_workload()["output_artifacts"][0]
    with gzip.open(artifact.path / "valid.jsonl.gz", "rt", encoding="utf-8") as stream:
        row = json.loads(stream.readline())
    assert row["query_id"] == "arecel:census13:valid:000000"
    assert row["source_workload"] == "base"
    assert row["source_split"] == "valid"
    assert row["predicate_columns"] == ["age"]
    assert 'public."census13"' in row["sql"]
