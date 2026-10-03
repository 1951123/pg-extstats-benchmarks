"""Promotion adapter for audited AreCELearnedYet dataset/workload artifacts.

The adapter consumes an already audited external extraction.  It never
downloads or regenerates the source pickles; the audit's canonical split files
are promoted byte-for-byte into production benchmark artifacts.
"""
from __future__ import annotations

from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
from typing import Any

from .adapter import BenchmarkAdapter
from .adapters import register_adapter
from .artifacts import Artifact
from .paths import benchmark_data_root


ARCHIVE_SHA256 = "5cd33cba7f3d7182ef497e60e7346fb2a7546941590a90a4444913a944958f79"
UPSTREAM_COMMIT = "aa52da7768023270bad884232972e0b77ec6534a"

DATASET_SPECS: dict[str, dict[str, Any]] = {
    "census13": {
        "relation": "public.census13",
        "columns": (
            "age", "workclass", "education", "education_num", "marital_status",
            "occupation", "relationship", "race", "sex", "capital_gain",
            "capital_loss", "hours_per_week", "native_country",
        ),
        "numeric": {"age", "education_num", "capital_gain", "capital_loss", "hours_per_week"},
    },
    "dmv11": {
        "relation": "public.dmv11",
        "columns": (
            "Record_Type", "Registration_Class", "State", "County", "Body_Type",
            "Fuel_Type", "Reg_Valid_Date", "Color", "Scofflaw_Indicator",
            "Suspension_Indicator", "Revocation_Indicator",
        ),
        "numeric": {"Reg_Valid_Date"},
    },
    "forest10": {
        "relation": "public.forest10",
        "columns": (
            "Elevation", "Aspect", "Slope", "Horizontal_Distance_To_Hydrology",
            "Vertical_Distance_To_Hydrology", "Horizontal_Distance_To_Roadways",
            "Hillshade_9am", "Hillshade_Noon", "Hillshade_3pm",
            "Horizontal_Distance_To_Fire_Points",
        ),
        "numeric": set((
            "Elevation", "Aspect", "Slope", "Horizontal_Distance_To_Hydrology",
            "Vertical_Distance_To_Hydrology", "Horizontal_Distance_To_Roadways",
            "Hillshade_9am", "Hillshade_Noon", "Hillshade_3pm",
            "Horizontal_Distance_To_Fire_Points",
        )),
    },
    "power7": {
        "relation": "public.power7",
        "columns": (
            "Global_active_power", "Global_reactive_power", "Voltage",
            "Global_intensity", "Sub_metering_1", "Sub_metering_2", "Sub_metering_3",
        ),
        "numeric": set((
            "Global_active_power", "Global_reactive_power", "Voltage",
            "Global_intensity", "Sub_metering_1", "Sub_metering_2", "Sub_metering_3",
        )),
    },
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _artifact(path: Path) -> Artifact:
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    return Artifact(
        id=manifest["artifact_id"], type=manifest["type"], path=path,
        digest=manifest.get("sha256"), metadata=manifest,
        created_at=manifest.get("timestamp"), created_by="AreCELearnedYetAdapter",
        parent_artifacts=tuple(manifest.get("parent_artifacts", ())),
    )


class AreCELearnedYetAdapter(BenchmarkAdapter):
    """Generic adapter for one audited AreCELearnedYet dataset identity."""

    def __init__(
        self,
        *,
        dataset: str = "census13",
        data_root: Path | None = None,
        raw_root: Path | None = None,
        audit_root: Path | None = None,
    ) -> None:
        if dataset not in DATASET_SPECS:
            raise ValueError(f"unsupported AreCELearnedYet dataset: {dataset}")
        self.dataset = dataset
        self.spec = DATASET_SPECS[dataset]
        self.data_root = (Path(data_root) if data_root is not None else benchmark_data_root()).expanduser().resolve()
        self.raw_root = (Path(raw_root) if raw_root is not None else Path(os.environ.get("PGEXTADV_ARECEL_RAW_ROOT", "/home/wqts/benchmark-data/arecel/raw/data"))).expanduser().resolve()
        self.audit_root = (Path(audit_root) if audit_root is not None else Path(os.environ.get("PGEXTADV_ARECEL_AUDIT_ROOT", "/home/wqts/benchmark-data/arecel/audit-v1"))).expanduser().resolve()

    @property
    def arecel_root(self) -> Path:
        return self.data_root / "arecel" / self.dataset

    @property
    def artifacts_root(self) -> Path:
        return self.arecel_root / "artifacts"

    @property
    def relation_identity(self) -> str:
        return str(self.spec["relation"])

    def prepared_artifact(self) -> Artifact:
        return _artifact(self.artifacts_root / f"arecel-{self.dataset}-prepared-v1")

    def workload_artifact(self) -> Artifact:
        return _artifact(self.artifacts_root / f"arecel-{self.dataset}-workload-v1")

    def _source_dir(self) -> Path:
        path = self.raw_root / self.dataset
        if not path.is_dir():
            raise FileNotFoundError(f"audited AreCELearnedYet source directory is missing: {path}")
        return path

    def _audit(self) -> dict[str, Any]:
        path = self.audit_root / "audit.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        if value["archive"]["sha256"] != ARCHIVE_SHA256:
            raise ValueError("audited archive SHA256 does not match the frozen contract")
        upstream = value.get("upstream", {}).get("AreCELearnedYet", {})
        if upstream.get("commit") != UPSTREAM_COMMIT:
            raise ValueError("audited AreCELearnedYet commit does not match the frozen contract")
        return value

    def fetch(self) -> dict[str, Any]:
        audit = self._audit()
        source = self._source_dir()
        csv_path = source / "original.csv"
        if not csv_path.is_file():
            raise FileNotFoundError(csv_path)
        source_meta = audit["datasets"][self.dataset]
        if _sha256(csv_path) != source_meta["csv"]["sha256"]:
            raise ValueError("audited original.csv checksum mismatch")
        for name, record in source_meta["pickles"].items():
            path = source / "workload" / name
            if not path.is_file() or _sha256(path) != record["sha256"]:
                raise ValueError(f"audited workload checksum mismatch: {path}")
        raw_dir = self.artifacts_root / f"arecel-{self.dataset}-raw-v1"
        raw_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(csv_path, raw_dir / "original.csv")
        (raw_dir / "workload").mkdir(exist_ok=True)
        for name in source_meta["pickles"]:
            shutil.copyfile(source / "workload" / name, raw_dir / "workload" / name)
        manifest = {
            "artifact_id": f"arecel-{self.dataset}-raw-v1",
            "type": "raw_dataset",
            "dataset": self.dataset,
            "relation_identity": self.relation_identity,
            "archive_sha256": ARCHIVE_SHA256,
            "upstream_commit": UPSTREAM_COMMIT,
            "audit_root": str(self.audit_root),
            "source_root": str(source),
            "source_csv_sha256": source_meta["csv"]["sha256"],
            "workload_sha256": {name: record["sha256"] for name, record in source_meta["pickles"].items()},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        _write_json(raw_dir / "manifest.json", manifest)
        return {"status": "PASS", "output_artifacts": (_artifact(raw_dir),), "message": "audited AreCELearnedYet source verified"}

    def prepare(self) -> dict[str, Any]:
        raw = _artifact(self.artifacts_root / f"arecel-{self.dataset}-raw-v1")
        prepared_dir = self.artifacts_root / f"arecel-{self.dataset}-prepared-v1"
        prepared_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(Path(raw.path) / "original.csv", prepared_dir / "original.csv")
        lines = [f"CREATE TABLE public.{self.dataset} ("]
        definitions = []
        for column in self.spec["columns"]:
            sql_type = "double precision" if column in self.spec["numeric"] else "text"
            definitions.append(f'    "{column.replace(chr(34), chr(34) * 2)}" {sql_type}')
        lines.append(",\n".join(definitions))
        lines.append(");\n")
        (prepared_dir / "schema.sql").write_text("\n".join(lines), encoding="utf-8")
        raw_manifest = dict(raw.metadata)
        manifest = {
            "artifact_id": f"arecel-{self.dataset}-prepared-v1",
            "type": "prepared_dataset",
            "parent_artifacts": [raw.id],
            "dataset": self.dataset,
            "relation_identity": self.relation_identity,
            "schema_path": "schema.sql",
            "data_path": "original.csv",
            "table": self.dataset,
            "columns": list(self.spec["columns"]),
            "database_columns": list(self.spec["columns"]),
            "format": "csv",
            "delimiter": ",",
            "header": True,
            "encoding": "utf-8",
            "expected_rows": int(self._audit()["datasets"][self.dataset]["csv"]["rows"]),
            "source_csv_sha256": raw_manifest["source_csv_sha256"],
            "archive_sha256": ARCHIVE_SHA256,
            "upstream_commit": UPSTREAM_COMMIT,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        manifest["sha256"] = _sha256(prepared_dir / "original.csv")
        _write_json(prepared_dir / "manifest.json", manifest)
        return {"status": "PASS", "input_artifacts": (raw,), "output_artifacts": (_artifact(prepared_dir),), "message": "AreCELearnedYet prepared artifact created"}

    def normalize_workload(self) -> dict[str, Any]:
        raw = _artifact(self.artifacts_root / f"arecel-{self.dataset}-raw-v1")
        workload_dir = self.artifacts_root / f"arecel-{self.dataset}-workload-v1"
        workload_dir.mkdir(parents=True, exist_ok=True)
        source_files = {}
        for split in ("valid", "test"):
            source = self.audit_root / f"{self.dataset}.canonical.jsonl.gz"
            target = workload_dir / f"{split}.jsonl.gz"
            with gzip.open(source, "rt", encoding="utf-8") as input_stream, gzip.open(target, "wt", encoding="utf-8") as output_stream:
                count = 0
                for line in input_stream:
                    record = json.loads(line)
                    if record["split"] == split:
                        output_stream.write(json.dumps({
                            "query_id": record["query_id"], "source_dataset": self.dataset,
                            "source_workload": "base", "source_split": split,
                            "source_index": record["index"], "source_query": record["source_query"],
                            "sql": record["sql"], "source_label": record["source_label"],
                            "predicate_columns": [p["column"] for p in record["source_query"]["predicates"]],
                        }, sort_keys=True) + "\n")
                        count += 1
            source_files[split] = {"path": str(target), "sha256": _sha256(target), "query_count": count}
        manifest = {
            "artifact_id": f"arecel-{self.dataset}-workload-v1",
            "type": "workload",
            "parent_artifacts": [raw.id],
            "dataset": self.dataset,
            "source_workload": "base",
            "source_archive_sha256": ARCHIVE_SHA256,
            "upstream_commit": UPSTREAM_COMMIT,
            "split_artifacts": source_files,
            "split_identity": {split: source_files[split]["sha256"] for split in source_files},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        manifest["sha256"] = hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        _write_json(workload_dir / "manifest.json", manifest)
        return {"status": "PASS", "input_artifacts": (raw,), "output_artifacts": (_artifact(workload_dir),), "message": "AreCELearnedYet valid/test workload artifacts promoted"}

    def load(self) -> dict[str, Any]:
        return {"status": "INCOMPLETE", "message": "Use PostgreSQLLoader.load_artifact with prepared_artifact() for managed loading"}

    def validate(self) -> dict[str, Any]:
        prepared = self.artifacts_root / f"arecel-{self.dataset}-prepared-v1"
        workload = self.artifacts_root / f"arecel-{self.dataset}-workload-v1"
        status = "PASS" if (prepared / "manifest.json").is_file() and (workload / "manifest.json").is_file() else "FAIL"
        return {"status": status, "dataset": self.dataset, "relation_identity": self.relation_identity}

    def collect_truth(self) -> dict[str, Any]:
        return {"status": "INCOMPLETE", "message": "Truth collection is experiment-scoped and requires an explicit split/managed instance"}


register_adapter("arecel-census13", AreCELearnedYetAdapter)


__all__ = ["ARCHIVE_SHA256", "UPSTREAM_COMMIT", "DATASET_SPECS", "AreCELearnedYetAdapter"]
