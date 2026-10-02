# Estimate artifacts

An `EstimateArtifact` records PostgreSQL native planner observations for one
normalized `Workload`, one `StatisticsRepositoryArtifact`, and one explicit
`StatisticsConfiguration`:

```text
DataArtifact
    -> LoadedInstance
    -> SampleArtifact
    -> CandidateCatalog
    -> StatisticsRepositoryArtifact
    -> StatisticsConfiguration
    -> EstimateArtifact
```

Each query result has a stable query ID and one status:

- `PASS`: nonnegative native `Plan Rows` was extracted;
- `UNSUPPORTED`: the query is outside the single base-relation selection
  scope;
- `ERROR`: PostgreSQL or plan-shape processing failed.

The provider uses `EXPLAIN (FORMAT JSON)` and never uses `EXPLAIN ANALYZE`,
executes the query, imports a sample, or regenerates payloads. PostgreSQL is
the cardinality-estimation authority. Full plan JSON is not persisted; an
optional plan fingerprint is diagnostic only.

The estimate digest covers benchmark/workload identity, workload digest,
repository and configuration identity/digests, relation identity, and ordered
`query_id -> status/estimated_rows`. Timestamps, paths, sessions, OIDs, and
incidental plan fields are excluded. Truth and q-error are separate artifacts.

Estimate manifests are external to Git:

```text
$PGEXTADV_BENCHMARK_DATA/<benchmark>/artifacts/<estimate-id>/
  manifest.json
  estimates.json
```

The next layer may combine an `EstimateArtifact` with a `TruthArtifact` into an
evaluation artifact. This phase does not compute q-error, ranking, search, or
recommendations.
