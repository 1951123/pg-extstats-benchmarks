"""Explicit external data and confined definition paths."""
import os
from pathlib import Path


def benchmark_data_root() -> Path:
    value = os.environ.get("PGEXTADV_BENCHMARK_DATA")
    if value is None or not value.strip():
        raise ValueError("Set PGEXTADV_BENCHMARK_DATA to an absolute external data directory")
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError("PGEXTADV_BENCHMARK_DATA must be absolute")
    path = path.resolve()
    if path == Path(path.anchor):
        raise ValueError("The filesystem root cannot be the benchmark data directory")
    if path.exists() and not path.is_dir():
        raise ValueError("PGEXTADV_BENCHMARK_DATA must name a directory")
    return path


def confined_path(root: Path, value: str) -> Path:
    if not isinstance(value, str) or not value.strip() or Path(value).is_absolute():
        raise ValueError("Definition path must be a nonempty relative path")
    root = root.resolve()
    path = (root / value).resolve()
    if path == root or not path.is_relative_to(root):
        raise ValueError("Definition path escapes its root or names the root itself")
    return path
