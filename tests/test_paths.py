from pathlib import Path
import pytest
from pgextstats_benchmarks.paths import benchmark_data_root, confined_path


def test_missing_environment(monkeypatch):
    monkeypatch.delenv("PGEXTADV_BENCHMARK_DATA", raising=False)
    with pytest.raises(ValueError, match="Set PGEXTADV"):
        benchmark_data_root()


@pytest.mark.parametrize("value", ["", "   ", ".", "relative", "/", "/tmp/.."])
def test_unsafe_data_roots(monkeypatch, value):
    monkeypatch.setenv("PGEXTADV_BENCHMARK_DATA", value)
    with pytest.raises(ValueError):
        benchmark_data_root()


def test_explicit_root_does_not_create(monkeypatch, tmp_path):
    target = tmp_path / "external"
    monkeypatch.setenv("PGEXTADV_BENCHMARK_DATA", str(target))
    assert benchmark_data_root() == target
    assert not target.exists()


def test_file_root_refused(monkeypatch, tmp_path):
    target = tmp_path / "file"
    target.write_text("preserve")
    monkeypatch.setenv("PGEXTADV_BENCHMARK_DATA", str(target))
    with pytest.raises(ValueError):
        benchmark_data_root()
    assert target.read_text() == "preserve"


@pytest.mark.parametrize("value", ["", ".", "..", "../outside", "/", None])
def test_definition_escape(tmp_path, value):
    with pytest.raises(ValueError):
        confined_path(tmp_path, value)


def test_symlink_escape(tmp_path):
    root = tmp_path / "definitions"
    root.mkdir()
    (root / "link").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError):
        confined_path(root, "link/elsewhere")
