# Benchmark manifest contract v1

Each directory registered in `registry/benchmarks.yaml` contains a
`benchmark.yaml`. The manifest describes a benchmark definition; it does not
claim that source data has been downloaded or that a database instance exists.

The required top-level fields are:

```yaml
benchmark_id: dmv
version: v1
description: Human-readable description
sources:
  data:
    manifest: sources/data.yaml
  workload:
    manifest: sources/workload.yaml
pipeline:
  transform: null
  load: null
  validate: null
  truth: null
artifacts:
  raw: null
  prepared: null
  loaded: null
provenance:
  url: null
  sha256: null
  timestamp: null
  generator_commit: null
  transformation_version: null
```

`benchmark_id` must match the registry key. `version` identifies the manifest
contract or benchmark release and is a nonempty string. `sources.data` and
`sources.workload` point to source declaration files inside the benchmark
directory. The four `pipeline` entries name transformation or adapter stages;
`null` is valid for a placeholder.

The artifact fields identify the raw source, prepared representation, and
loaded benchmark instance when they exist. Provenance records the source URL,
download timestamp, source SHA256, generator commit, and transformation
version. Placeholder manifests may use `null` for all of these values. A
separate artifact lineage record connects derived artifacts to their parents.

The contract does not prescribe URLs, data formats, database schemas, loader
commands, or truth semantics. Those belong to a benchmark-specific adapter.
