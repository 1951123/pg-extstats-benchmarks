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
- `executor.py` coordinates manifest, adapter, loader, and validator contracts.
  It does not invoke shells, databases, or cleanup operations.
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
```

The core models—`Artifact`, `Lineage`, `ExecutionRecord`, `LoadedInstance`,
and `ValidationReport`—do not import the CLI, adapters, loaders, or any DBMS.
`SampleArtifact` is also a core metadata model: it contains no SQL or binary
parser; the PostgreSQL provider remains the only component that asks a server
to decode its payload.
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
