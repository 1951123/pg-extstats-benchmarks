# pg-extstats-benchmarks

Reusable infrastructure for external benchmark ingestion and provenance.
The lifecycle is fetch → immutable raw data → deterministic preparation
→ loading → validation → workload normalization → truth collection → fixed
PostgreSQL ANALYZE sample capture/replay.
The framework includes local toy, Census, and DMV metadata adapters. Generated data
and sample payloads remain external to Git.
The stable metadata contract is documented in
[`docs/benchmark-manifest-v1.md`](docs/benchmark-manifest-v1.md), and concrete
benchmark implementations will conform to the six-stage
`BenchmarkAdapter` lifecycle in `src/pgextstats_benchmarks/adapter.py`.
The package dependency direction and extension points are documented in
[`docs/architecture.md`](docs/architecture.md).

## Current lifecycle

```text
benchmark manifest
        -> adapter
        -> artifact
        -> loader
        -> loaded instance
        -> validator
        -> validation report
        -> SampleArtifact (capture/replay)
        -> CandidateCatalog
        -> StatisticsRepositoryArtifact
        -> StatisticsConfiguration
        -> EstimateArtifact
        + TruthArtifact
        -> EvaluationArtifact
        -> ExperimentRunArtifact
        -> ComparisonReport
```

The framework currently demonstrates this lifecycle with the in-memory
`example` benchmark and the external `census` and `dmv` contracts. To add a
benchmark, implement and explicitly register a `BenchmarkAdapter`; to add
materialization behavior, register a `DatabaseLoader`; to add correctness
checks, register a `BenchmarkValidator`. Core models remain DBMS-independent.

DMV raw acquisition is manual because the historical source is distributed
through a Dropbox sharing URL rather than a stable download API. Place the
immutable archive at
`$PGEXTADV_BENCHMARK_DATA/dmv/incoming/data.tar.gz`. The adapter validates
its SHA256 against `benchmarks/dmv/sources/data.yaml`, extracts and trims the
source deterministically into external `dmv-*` artifacts, and never commits
raw or generated data to Git. The BayesCard DMV workload is cached from its
stable raw GitHub URL and normalized into PostgreSQL-compatible SQL while the
original query text remains in the workload artifact.

## Development

Python 3.12 or newer. From this repository:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
export PGEXTADV_BENCHMARK_DATA="$HOME/benchmark-data"
.venv/bin/pgextbench status
.venv/bin/pgextbench list
.venv/bin/pgextbench verify dmv
.venv/bin/pgextbench run example --stage prepare
.venv/bin/pgextbench run example --stage prepare --record
.venv/bin/pgextbench loaders
.venv/bin/pgextbench load-example
.venv/bin/pgextbench validators
.venv/bin/pgextbench validate-example
.venv/bin/pgextbench postgres-check
.venv/bin/pgextbench load-example-postgres
.venv/bin/pgextbench sample-capture census
.venv/bin/pgextbench sample-replay census census-sample-v1
.venv/bin/pgextbench configuration-validate example repository-id configuration.json
.venv/bin/pgextbench estimate-collect example workload-id repository-id configuration.json --database pgextbench_example
.venv/bin/pgextbench evaluate census census-truth-v1 census-estimate-v1
.venv/bin/pgextbench experiment-create census --baseline census-evaluation-empty census-evaluation-empty census-evaluation-a
.venv/bin/pgextbench comparison-report census census-experiment-census-evaluation-empty
.venv/bin/python -m pytest
```

Registry commands default to this checkout when installed in editable mode.
Use `pgextbench --repo PATH list` for a separate definition checkout.
`verify` reports the definition directory, manifest, source declarations, and
raw-data presence. It distinguishes incomplete data from missing configuration
and never connects to a database. Missing/invalid configuration produces a
nonzero exit status.

`run example --stage STAGE` executes the in-memory toy adapter. Valid stages
are `fetch`, `prepare`, `load`, `validate`, `normalize_workload`, and
`collect_truth`; the Census adapter additionally owns external source and
workload metadata stages. Adding
`--record` writes one JSON execution record under the repository-local `runs/`
directory, including artifact IDs and the repository commit.

`load-example` runs the DBMS-independent in-memory loader contract over the
example prepared artifact. It creates no database and performs no SQL or file
materialization.

`validate-example` passes the resulting loaded instance through
`ExampleValidator`, producing serializable checks and a validation report.

The PostgreSQL lifecycle plugin uses the standard `psycopg` 3 driver, declared
as the runtime dependency `psycopg[binary]>=3,<4`. `postgres-check` reads
`PGHOST`, `PGPORT`, and `PGUSER` (defaulting to `localhost`, `55437`, and the
current OS user), creates and validates a temporary `pgextbench_*` database,
then drops only that managed database. Passwords are never stored by the
framework.

The checked-in example prepared artifact is under
`benchmarks/example/artifacts/example-prepared-v1/`. It contains a two-row CSV
and a schema for `example_table`. `load-example-postgres` creates a managed
database, loads that artifact, validates the table and row count, records
loader provenance, and drops the managed database.

`sample-capture census` loads the prepared Census relation into a managed
database and asks the patched PostgreSQL provider to export one opaque
`PGEXTSC1` sample into `$PGEXTADV_BENCHMARK_DATA`. `sample-replay census ID`
loads the relation again and runs `ANALYZE` with that sample. Both commands
validate the patched capability first and drop only their managed database.
See [`docs/sample-artifacts.md`](docs/sample-artifacts.md) for the contract.
The fixed-sample native statistics repository contract is documented in
[`docs/statistics-repository-artifacts.md`](docs/statistics-repository-artifacts.md).
Configuration and native planner observations are documented in
[`docs/statistics-configurations.md`](docs/statistics-configurations.md) and
[`docs/estimate-artifacts.md`](docs/estimate-artifacts.md).
`estimate-collect` consumes a persisted repository through the patched
PostgreSQL catalogless overlay. Repository acquisition may have used temporary
physical definitions to produce native payloads, but evaluation itself only
registers opaque payloads and definition metadata in the backend session,
activates the requested subset, runs `EXPLAIN (FORMAT JSON)`, and resets the
subset. The target relation therefore needs no physical `pg_statistic_ext` or
`pg_statistic_ext_data` rows during evaluation.

`evaluate` is a pure offline comparison of one existing truth artifact and one
existing estimate artifact. It reports descriptive q-error metrics and writes
an `EvaluationArtifact` below the external benchmark data root; it does not
connect to PostgreSQL, execute queries, activate statistics, rank
configurations, or make recommendations. See
[`docs/evaluation-artifacts.md`](docs/evaluation-artifacts.md) for the exact
status, q-error, percentile, digest, and reproducibility contracts.

`experiment-create` groups explicitly supplied EvaluationArtifacts after
checking their workload, truth, sample, repository, PostgreSQL source, and
statistics-target provenance. The baseline is supplied explicitly. It never
infers a baseline or chooses a configuration. `comparison-report` computes
descriptive per-configuration and baseline-relative observations, preserving
status mismatches and never ranking or recommending configurations. See
[`docs/experiment-runs.md`](docs/experiment-runs.md) and
[`docs/comparison-reports.md`](docs/comparison-reports.md).

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
Database dropping is limited to the PostgreSQL loader's explicitly managed
`pgextbench_*` databases; no filesystem cleanup is provided.
