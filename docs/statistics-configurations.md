# Statistics configurations

`StatisticsConfiguration` is an explicit experiment input. It selects a
deterministically ordered subset of `PRESENT` candidates from one
`StatisticsRepositoryArtifact`; it does not generate, rank, search, or
recommend candidates.

The JSON contract is:

```json
{
  "configuration_id": "example-config-1",
  "repository_artifact_id": "example-statistics-repository-v1",
  "repository_digest": "...",
  "selected_candidate_ids": ["c001", "c003"],
  "relation_identity": "public.example_table",
  "effective_statistics_target": 100
}
```

Candidate IDs are sorted by stable ID. The empty list is the ordinary
statistics-only baseline. Selecting every `PRESENT` candidate is a full
available configuration; it has no optimality meaning. `ABSENT_NATIVE`
candidates are rejected because they have no usable native payload.

The configuration digest covers only the semantic fields above: repository
identity and digest, relation, target, and ordered selected IDs. Metadata,
timestamps, filesystem paths, OIDs, and generated object names are excluded.

The PostgreSQL configuration provider registers a repository once per backend
session, resets the active set, activates exactly the requested OID subset,
and verifies the backend active set. Estimate collection does not run
`CREATE STATISTICS`, `ANALYZE`, or `DROP STATISTICS`.

Candidate generation and selection remain outside this repository, in the
advisor or another explicit input producer.
