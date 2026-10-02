# Fixed ANALYZE sample artifacts

`SampleArtifact` freezes one PostgreSQL `ANALYZE` sampling realization. It is
not a random seed, `pg_statistic` payload, extended-statistics payload,
planner estimate, query truth result, or statistics configuration.

The research-state chain is:

```text
prepared DataArtifact
        -> managed LoadedInstance
        -> SampleArtifact
        -> (future) StatisticsRepositoryArtifact
```

The sample payload is PostgreSQL's opaque `PGEXTSC1` format, version 1.
Python records its path and SHA256 only; PostgreSQL validates its magic,
version, server build, relation identity, tuple descriptor, and CRC during
replay.

Payloads and manifests are stored outside Git below the absolute, non-root
`$PGEXTADV_BENCHMARK_DATA` directory:

```text
$PGEXTADV_BENCHMARK_DATA/
  census/
    artifacts/
      census-sample-v1/
        sample.bin
        manifest.json
```

The manifest records benchmark and logical relation identities, the parent
prepared artifact, loaded instance, relative payload path, digest, tuple and
estimated row counts, schema fingerprint, acquisition mechanism, lineage, and
the authoritative PostgreSQL source repository/commit, upstream base, 16.14
version, and optional binary digest. Relation OIDs are diagnostic only; the
stable identity is the qualified logical relation name.

`pgextbench sample-capture census` validates the managed instance and patched
server capability, sets the documented export GUC, runs `ANALYZE`, hashes the
new payload, writes a manifest without overwriting an existing artifact, and
resets both sample GUCs to their documented empty disabled value.
`pgextbench sample-replay census ID` verifies the manifest and digest, checks
source provenance, sets only the import GUC, runs `ANALYZE`, and resets session
state. A vanilla PostgreSQL 16.14 server is rejected rather than silently
sampling again.

This freezes sampling randomness only. It does not guarantee results across
incompatible server builds, schemas, or relation contents, and does not freeze
later candidate statistics or planner behavior.
