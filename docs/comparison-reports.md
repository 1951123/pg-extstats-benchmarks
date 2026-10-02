# ComparisonReport contract

`ComparisonReport` is a deterministic descriptive report over one
`ExperimentRunArtifact`:

```text
ExperimentRunArtifact -> ComparisonReport
```

It reports each configuration's existing q-error metrics and compares every
non-baseline configuration with the explicitly nominated baseline. It does not
rank configurations, select one, recommend deployment, or compute an
optimization score.

For a query where both evaluations are `PASS`:

```text
q_error_delta = target_q_error - baseline_q_error
q_error_ratio_to_baseline = target_q_error / baseline_q_error
```

Negative delta or ratio below one is numerically lower q-error; zero or one is
equal; positive delta or ratio above one is numerically higher. These values
remain observations and are not converted into a score.

Exact comparisons define the per-query counts:

- target q-error `<` baseline: `improved`;
- equal: `unchanged`;
- target q-error `>` baseline: `worsened`.

Status mismatches remain visible. If the baseline is unavailable, the row is
`BASELINE_UNAVAILABLE`; if the baseline is `PASS` and the target is not, it is
`TARGET_UNAVAILABLE`. No q-error delta or ratio is fabricated. The baseline
summary uses explicit `SELF` status, with its PASS rows counted as unchanged.

The report stores q-error metrics, comparable/improved/unchanged/worsened
counts, excluded/error/unavailable counts, deterministic delta percentiles, and
per-query rows. Delta percentiles use the same nearest-rank convention as the
evaluation layer. Canonical report order is configuration ID/digest followed by
query ID; report digests exclude paths, timestamps, and formatting.

Reports are stored outside Git:

```text
$PGEXTADV_BENCHMARK_DATA/<benchmark>/artifacts/<report-id>/
    manifest.json
    comparison.json
```

Use:

```sh
pgextbench comparison-report census census-experiment-census-evaluation-empty
```

Future multi-sample studies may aggregate multiple experiment runs, but that
`StudyArtifact` layer is intentionally not implemented here.
