# Architecture checkpoint

This package keeps its core models DBMS-independent while allowing explicit
provider plugins at the execution boundary. It defines how a benchmark
declaration is resolved, how an adapter produces metadata artifacts, how a
loader describes a loaded instance, and how a validator returns a serializable
report. PostgreSQL sample capture/replay is isolated under the PostgreSQL
plugin; no PostgreSQL details enter the core models.

## Components

- `registry.py` resolves benchmark definitions and manifests.
- `adapter.py` defines the six benchmark lifecycle stages; `adapters.py` holds
  the explicit benchmark-to-adapter registry.
- `artifacts.py` is the canonical `Artifact` model. `lineage.py` provides the
  `Lineage` graph and validates parent references. `ArtifactLineage` remains a
  compatibility name for the same implementation.
- `loaders.py` defines the DBMS-independent materialization contract;
  `loader_registry.py` maps explicit loader IDs to implementations.
- `instances.py` contains `LoadedInstance`, metadata for a managed benchmark
  instance without a connection or process handle.
- `validation.py` contains `ValidationCheck` and `ValidationReport`;
  `validators.py` defines the benchmark-specific validator contract and
  `validator_registry.py` provides explicit registration.
- `execution.py` records stage provenance and writes JSON only below the
  repository-local `runs/` directory.
- `sample_artifacts.py` defines the immutable `SampleArtifact` metadata model;
  `sample_storage.py` confines its opaque payload and manifest below the
  external benchmark data root.
- `postgres/sample_provider.py` owns PostgreSQL GUC interaction, relation
  quoting, capability detection, ANALYZE orchestration, and source provenance.
- `candidate_catalog.py` validates an explicit catalog input; it never creates
  candidates. `statistics_repository.py` and `statistics_repository_validator.py`
  model and validate native payload states. `postgres/statistics_provider.py`
  creates managed definitions, imports a sample once, runs one ANALYZE, and
  records opaque native payloads.
- `statistics_configuration.py` validates an explicit candidate subset.
  `postgres/configuration_provider.py` registers the native repository once per
  backend session through the catalogless PostgreSQL overlay when available;
  it never requires a physical `pg_statistic_ext` shell during evaluation, and
  switches exact active subsets. `estimate.py` and
  `postgres/estimate_provider.py` record `EXPLAIN (FORMAT JSON)` Plan Rows
  without physical statistics changes.
- `evaluation.py` is a pure offline evaluator for one `TruthArtifact` and one
  `EstimateArtifact`; `evaluation_validator.py` recomputes row coverage,
  descriptive q-error metrics, lineage, and the canonical digest.
- `evaluation_storage.py` writes only small JSON artifacts below the external
  benchmark data root. It never starts a database or runs a workload.
- `experiment.py` proves comparability for an explicit set of evaluation
  artifacts; `comparison.py` derives descriptive baseline-relative deltas.
  Their validators recompute digests and report content. Neither module ranks,
  selects, or recommends configurations.
- `executor.py` coordinates manifest, adapter, loader, and validator contracts.
  It does not invoke shells, databases, or cleanup operations.
- `dmv_adapter.py` is the benchmark-specific manual-source extension: it
  validates the immutable external tar archive, extracts every member, emits
  deterministic trimmed DMV data and normalized workload artifacts, and keeps
  PostgreSQL materialization in the generic loader. `dmv_validator.py` checks
  source, prepared, loaded-instance, and truth-artifact contracts.
- `cli.py` is the user-facing inspection and demonstration layer. `fetch.py`,
  `prepare.py`, `load.py`, `validate.py`, `workload.py`, and `truth.py` remain
  reserved extension modules.

## Dependency direction

The intended direction is:

```text
CLI
 |
 v
Executor ------------------------------+
 |             |              |        |
 v             v              v        v
Adapters     Loaders       Validators Registry/manifest
 |             |              |
 v             v              v
Artifacts    Instances      Validation reports
    |
    v
    SampleArtifact (opaque PGEXTSC1 payload)
        ->
    CandidateCatalog -> StatisticsRepositoryArtifact
        ->
    StatisticsConfiguration -> EstimateArtifact
        + TruthArtifact
        -> EvaluationArtifact
        -> ExperimentRunArtifact
        -> ComparisonReport
```

The core models—`Artifact`, `Lineage`, `ExecutionRecord`, `LoadedInstance`,
and `ValidationReport`—do not import the CLI, adapters, loaders, or any DBMS.
`SampleArtifact` is also a core metadata model: it contains no SQL or binary
parser; the PostgreSQL provider remains the only component that asks a server
to decode its payload.
Repository acquisition may create temporary physical statistics definitions
solely to obtain native payloads. Evaluation consumes the persisted repository
through backend-local catalogless definitions, so the target relation can have
zero `pg_statistic_ext` and `pg_statistic_ext_data` rows; reset restores the
ordinary planner state and unrelated physical statistics remain visible.
`EvaluationArtifact` and `ArtifactEvaluator` are core/offline models: they
consume already-produced truth and estimate artifacts and never depend on
PostgreSQL or the advisor repository. Evaluation metrics are descriptive and
cannot select or rank configurations.
`ExperimentRunArtifact` is the single controlled comparability boundary. It
requires explicit sample/repository/PostgreSQL provenance and an explicit
baseline. `ComparisonReport` compares q-error rows to that baseline using
exact delta/ratio semantics; its output is descriptive and has no ranking or
recommendation meaning. Future robustness across multiple runs belongs to a
separate `StudyArtifact` layer.
The executor is the orchestration boundary: it resolves a manifest, selects an
explicit implementation, and passes model objects between contracts.

The package initializer imports the three toy implementations solely to make
their explicit registrations available to the CLI. There is no dynamic module
discovery. The built-in examples must remain replaceable by future adapters,
loaders, and validators without changing the core models.

## Extension points

To add a benchmark, add its manifest and source declarations, implement a
`BenchmarkAdapter`, and register it explicitly with `register_adapter`.
Benchmark code should emit `Artifact` objects and keep source-specific details
out of the core models.

To add a loader, implement `DatabaseLoader`, register an ID with
`register_loader`, and return `LoadedInstance` metadata. The loader owns any
future DBMS-specific materialization; the current framework performs none.

To add validation, implement `BenchmarkValidator`, register an ID with
`register_validator`, and return a `ValidationReport` containing named
`ValidationCheck` objects. Validators receive loaded instance metadata and do
not require the executor or CLI.

Every extension remains responsible for preserving provenance and for keeping
destructive operations outside these contracts. The core models perform no
cleanup, shell execution, SQL, or database connection. PostgreSQL sample
capture and replay are explicit provider operations and never fall back to
random sampling when capability detection fails.
