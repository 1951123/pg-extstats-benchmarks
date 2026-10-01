# pg-extstats-benchmarks

Reusable infrastructure for external benchmark ingestion and provenance.
The planned lifecycle is fetch → immutable raw data → deterministic preparation
→ loading → validation → workload normalization → truth collection.
Only metadata and registry inspection are implemented today. DMV and Census
are placeholders; no URLs, transformations, loaders, or cleanup are supplied.
The stable metadata contract is documented in
[`docs/benchmark-manifest-v1.md`](docs/benchmark-manifest-v1.md), and concrete
benchmark implementations will conform to the six-stage
`BenchmarkAdapter` lifecycle in `src/pgextstats_benchmarks/adapter.py`.

## Development

Python 3.12 or newer. From this repository:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
export PGEXTADV_BENCHMARK_DATA="$HOME/benchmark-data"
.venv/bin/pgextbench status
.venv/bin/pgextbench list
.venv/bin/pgextbench verify dmv
.venv/bin/python -m pytest
```

Registry commands default to this checkout when installed in editable mode.
Use `pgextbench --repo PATH list` for a separate definition checkout.
`verify` reports the definition directory, manifest, source declarations, and
raw-data presence. It distinguishes incomplete data from missing configuration
and never connects to a database. Missing/invalid configuration produces a
nonzero exit status.

## Definitions and external data

Add a directory under `benchmarks/` and an entry in `registry/benchmarks.yaml`
without changing core code. Registry and source manifest paths must remain
inside their definition roots, including after symlink resolution.
`PGEXTADV_BENCHMARK_DATA` must be an explicit absolute directory path other
than the filesystem root. It may name a directory that does not exist yet;
inspection commands never create it. Relative paths and blank values fail.

Keep raw data immutable and outside Git. Large CSVs, database dumps, generated
samples, prepared artifacts, and experiment outputs do not belong in this
repository. No default data directory is guessed. Future pipeline stages must
record source and derived artifact metadata using `ArtifactProvenance`.
No deletion or database dropping API is implemented; destructive operations
require a separate safety design.
