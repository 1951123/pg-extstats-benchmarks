"""Confined external storage for ComparisonReport manifests."""
from __future__ import annotations

import json
from pathlib import Path

from .comparison import ComparisonReport
from .sample_storage import _reject_symlink_components, _safe_root


def comparison_report_dir(benchmark_id: str, report_id: str, root: Path | None = None) -> Path:
    base = _safe_root(root)
    for value, label in ((benchmark_id, "benchmark_id"), (report_id, "report_id")):
        if not isinstance(value, str) or not value or Path(value).name != value or "/" in value or "\\" in value or value in {".", ".."}:
            raise ValueError(f"{label} must be a safe path component")
    path = (base / benchmark_id / "artifacts" / report_id).resolve()
    if not path.is_relative_to(base):
        raise ValueError("comparison report path escapes benchmark data root")
    return path


def allocate_comparison_report_dir(benchmark_id: str, report_id: str, root: Path | None = None) -> Path:
    path = comparison_report_dir(benchmark_id, report_id, root)
    if path.exists():
        raise FileExistsError(f"comparison report already exists: {path}")
    base = _safe_root(root)
    _reject_symlink_components(base, path.parent)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink() or not path.parent.resolve().is_relative_to(base):
        raise ValueError("comparison report path escapes benchmark data root")
    path.mkdir()
    return path


def write_comparison_report(report: ComparisonReport, benchmark_id: str, root: Path | None = None) -> Path:
    directory = comparison_report_dir(benchmark_id, report.report_id, root)
    if not directory.is_dir() or directory.is_symlink():
        raise FileNotFoundError(f"comparison report directory is missing: {directory}")
    manifest = directory / "manifest.json"
    comparison = directory / "comparison.json"
    if manifest.exists() or comparison.exists():
        raise FileExistsError(f"comparison report already has metadata: {directory}")
    with manifest.open("x", encoding="utf-8") as stream:
        stream.write(report.to_json())
    with comparison.open("x", encoding="utf-8") as stream:
        json.dump(report.canonical_dict(), stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    return manifest


write_comparison_report_for_benchmark = write_comparison_report


def load_comparison_report(benchmark_id: str, report_id: str, root: Path | None = None) -> ComparisonReport:
    directory = comparison_report_dir(benchmark_id, report_id, root)
    manifest = directory / "manifest.json"
    if not manifest.is_file() or manifest.is_symlink():
        raise FileNotFoundError(f"comparison report manifest is missing: {manifest}")
    report = ComparisonReport.from_dict(json.loads(manifest.read_text(encoding="utf-8")))
    if report.report_id != report_id:
        raise ValueError("comparison report identity does not match requested report")
    return report


__all__ = [
    "allocate_comparison_report_dir", "comparison_report_dir", "load_comparison_report",
    "write_comparison_report", "write_comparison_report_for_benchmark",
]
