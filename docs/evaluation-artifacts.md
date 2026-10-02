# EvaluationArtifact contract

`EvaluationArtifact` is the final artifact-level comparison in the current
benchmark chain:

```text
DataArtifact
  -> LoadedInstance
  -> SampleArtifact
  -> CandidateCatalog
  -> StatisticsRepositoryArtifact
  -> StatisticsConfiguration
  -> EstimateArtifact
       + TruthArtifact
       -> EvaluationArtifact
```

The evaluator is an offline, DBMS-independent transformation. It does not
connect to PostgreSQL, execute SQL, run `EXPLAIN`, activate statistics, search
candidate configurations, rank configurations, or make recommendations.

## Identity and lineage

Each evaluation records the benchmark and workload identity, workload digest,
truth and estimate artifact IDs and digests, repository and configuration
identity, ordered per-query evaluations, descriptive aggregate metrics, and a
canonical `evaluation_digest`. The lineage identifies the truth artifact,
estimate artifact, repository artifact, and configuration that produced the
comparison.

Evaluation digests cover semantic content only:

- workload, truth, estimate, repository, and configuration digests;
- query rows canonically ordered by `query_id`;
- aggregate metrics.

Timestamps, paths, execution-session details, and generated directory names are
excluded. The payload is stored outside Git below
`$PGEXTADV_BENCHMARK_DATA/<benchmark>/artifacts/<evaluation-id>/` as
`manifest.json` and `evaluation.json`. Existing paths are never overwritten.

## Query states and q-error

Every query in the aligned truth/estimate universe appears exactly once:

- `PASS` contains valid truth and estimate values and a computed q-error;
- `EXCLUDED` represents an explicit `UNSUPPORTED` input and has no q-error;
- `ERROR` represents malformed or failed input and has no q-error.

The q-error convention is the frozen advisor rule:

```text
truth must be > 0
effective_estimate = max(estimate, 1.0)
q_error = max(effective_estimate / truth, truth / effective_estimate)
```

Thus truth cardinality zero has no q-error under the established contract and
is recorded as `ERROR` rather than assigned an invented value. Negative,
non-finite, or missing values also produce `ERROR`.

Queries align strictly by `query_id`; duplicate, missing, or extra IDs are
rejected. Benchmark ID, workload ID, and workload digest must match exactly.

Aggregate metrics are observations over `PASS` rows only: count, arithmetic
mean, median, p90, p95, and maximum q-error. Percentiles use deterministic
nearest-rank semantics: for sorted values of length `n`, percentile `p` uses
one-based rank `ceil(p*n)`, clamped to one. Empty PASS sets have count zero and
null metric values.

## Reproducibility boundary

Given fixed `TruthArtifact`, `EstimateArtifact`, and evaluator implementation,
the resulting `EvaluationArtifact` is deterministic. This does not claim that
workload execution, PostgreSQL, or upstream sampling is universally
deterministic; those properties belong to their own artifact contracts.

The evaluator computes descriptive metrics only. Configuration comparison,
leaderboards, ranking, search, recommendations, and optimization objectives
remain outside this repository phase.

The CLI form is:

```sh
pgextbench evaluate census census-truth-v1 census-estimate-v1
```

It loads the two existing artifacts, validates the result, writes the small
evaluation artifact externally, and records an `evaluation_compute`
`ExecutionRecord`.
