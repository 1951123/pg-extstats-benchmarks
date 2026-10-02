# ExperimentRunArtifact contract

An `ExperimentRunArtifact` organizes one controlled set of explicit
`EvaluationArtifact` objects:

```text
DataArtifact -> LoadedInstance -> SampleArtifact -> CandidateCatalog
  -> StatisticsRepositoryArtifact -> StatisticsConfiguration
  -> EstimateArtifact + TruthArtifact -> EvaluationArtifact
  -> ExperimentRunArtifact
```

It proves that the evaluations share benchmark/workload identity, truth,
sample, repository, PostgreSQL source, and effective statistics target. A
configuration may differ; that is the purpose of the run. Missing provenance
is an incompatibility and is rejected. Sample identity is supplied from the
repository artifact, never reconstructed from a filename.

The baseline is explicit. The caller names a baseline label (normally the
evaluation for the empty StatisticsConfiguration); the framework never infers
it from q-error or any other metric. Labels are presentation metadata and are
excluded from the experiment digest. The digest includes the resolved baseline
configuration/evaluation identity, so changing the baseline changes semantic
content even if a label is renamed.

Entries are canonically ordered by `configuration_id`, then
`configuration_digest`. Input order and performance metrics do not determine
semantic ordering.

Experiment artifacts are stored outside Git:

```text
$PGEXTADV_BENCHMARK_DATA/<benchmark>/artifacts/<experiment-id>/
    manifest.json
    experiment.json
```

The artifact records the exact PostgreSQL source repository, source commit,
upstream base, server version, binary digest, sample artifact and payload
digest, repository digest, workload/truth digests, baseline, and evaluation
entries.

The generic command is:

```sh
pgextbench experiment-create census \
  --baseline census-evaluation-empty \
  census-evaluation-empty census-evaluation-a census-evaluation-b
```

The command reads repository provenance from the external artifacts and fails
closed if the evaluations cannot be proven comparable.

One run represents one controlled state. Robustness over multiple samples or
PostgreSQL versions belongs to a future `StudyArtifact` layer.
