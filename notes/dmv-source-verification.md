# DMV source verification

The DMV source is manually acquired from the AreCELearnedYet benchmark
repository. Its historical Dropbox sharing URL is recorded as provenance but
is not used as an unattended downloader.

- Source identity: <https://github.com/sfu-db/AreCELearnedYet>
- Local input: `$PGEXTADV_BENCHMARK_DATA/dmv/incoming/data.tar.gz`
- SHA256: `5cd33cba7f3d7182ef497e60e7346fb2a7546941590a90a4444913a944958f79`
- Archive: gzip-compressed tar
- Required member: `data/dmv11/original.csv`
- Source columns: 11 text columns
- Source data rows: 11,591,877

The DMV workload is BayesCard's raw query file:

- URL: <https://raw.githubusercontent.com/wuziniu/BayesCard/master/Benchmark/DMV/query.sql>
- SHA256: `eeacc0b3d25cac16ea108987ae2c54e45a88f9482689b07070a7afc0b2c06168`
- Query count: 1,965

The adapter preserves the original workload and creates a deterministic
normalized SQL artifact by translating the source `IN [...]` and `==` syntax,
qualifying `DMV` as `public.dmv`, and trimming whitespace in prepared CSV
fields. Raw, prepared, workload, and truth artifacts remain below the external
benchmark data root and outside Git.
