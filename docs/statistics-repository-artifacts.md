# Fixed-sample statistics repository artifacts

This layer accepts an explicit candidate catalog and records the native
statistics payloads PostgreSQL realizes under one previously captured
`SampleArtifact`.

```text
DataArtifact
    -> LoadedInstance
    -> SampleArtifact
    -> CandidateCatalog
    -> StatisticsRepositoryArtifact
    -> (future) StatisticsConfiguration
    -> (future) EstimateArtifact
```

Candidate generation, ranking, selection, search, hypothetical activation,
recommendations, and estimate collection belong to `pg-extstats-advisor` or
later layers. This repository only validates and materializes the catalog it
is given.

The catalog records a stable `catalog_id`, exact input-file SHA256, relation,
fixed target 100, and ordered candidate definitions. Candidate IDs are sorted
by stable ID for repository identity; column order is preserved because it is
part of the PostgreSQL definition semantics.

Each repository manifest records the SampleArtifact ID and payload digest, the
catalog ID/digest/count, authoritative PostgreSQL source identity, requested
and effective target, ordinary-statistics fingerprint, lineage, and one state
for every candidate. Native states are exactly:

- `PRESENT`: PostgreSQL produced a nonempty native payload; its SHA256 and
  opaque payload file are recorded.
- `ABSENT_NATIVE`: PostgreSQL created the candidate and ran under the fixed
  sample, but the native payload column was null. No fake payload or null
  fingerprint is written.

Acquisition failures are reported separately as errors and are never converted
to `ABSENT_NATIVE`.

Acquisition sets the import GUC once, creates all managed statistics objects,
runs exactly one relation-grouped `ANALYZE`, reads ordinary and extended
statistics, then drops only the exact `pgextbench_stat_*` objects it created.
The canonical repository digest includes benchmark/relation identity, sample
identity and digest, catalog identity and digest, PostgreSQL source metadata,
target, ordinary-statistics fingerprint, and candidate IDs/kinds/columns,
states, and payload fingerprints. Generated object OIDs, names, timestamps,
and filesystem paths do not participate.

Artifacts are external to Git:

```text
$PGEXTADV_BENCHMARK_DATA/<benchmark>/artifacts/<repository-id>/
  manifest.json
  repository.json
  payloads/<candidate-id>.<kind>.bin
```

Run the generic command with a supplied catalog:

```text
pgextbench statistics-acquire census SAMPLE_ID catalog.json
```

The command does not generate candidates, run the Census workload, collect
truth, execute `EXPLAIN`, or perform planner evaluation.
